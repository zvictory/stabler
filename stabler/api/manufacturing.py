"""Manufacturing module — BOMs, Work Orders, Production Plan basics."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, getdate, today


from stabler.api._common import _require_company


# ----- BOMs ----------------------------------------------------------------


@frappe.whitelist()
def list_boms(company: str, search: str = "", item: str | None = None, limit: int = 100):
	_require_company(company)
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if search:
		conds.append("(name LIKE %(s)s OR item LIKE %(s)s OR item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	if item:
		conds.append("item = %(item)s")
		params["item"] = item
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, item, item_name, quantity, uom, is_active, is_default,
		       total_cost, currency, docstatus, modified
		FROM `tabBOM`
		WHERE {where}
		ORDER BY is_default DESC, modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def bom_detail(name: str):
	if not name or not frappe.db.exists("BOM", name):
		frappe.throw(f"Unknown BOM: {name}")
	doc = frappe.get_doc("BOM", name)
	items = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"qty": flt(r.qty),
			"uom": r.uom or r.stock_uom,
			"stock_qty": flt(r.stock_qty),
			"rate": flt(r.rate),
			"amount": flt(r.amount),
			"bom_no": r.bom_no,
		}
		for r in (doc.items or [])
	]
	return {
		"name": doc.name,
		"item": doc.item,
		"item_name": doc.item_name,
		"quantity": flt(doc.quantity),
		"uom": doc.uom,
		"company": doc.company,
		"currency": doc.currency,
		"is_active": doc.is_active,
		"is_default": doc.is_default,
		"with_operations": doc.with_operations,
		"total_cost": flt(doc.total_cost),
		"raw_material_cost": flt(doc.raw_material_cost),
		"operating_cost": flt(doc.operating_cost),
		"docstatus": doc.docstatus,
		"items": items,
	}


@frappe.whitelist()
def create_bom(
	company: str,
	item: str,
	quantity: float,
	items: list | str,
	uom: str | None = None,
	is_default: int = 0,
	submit: int = 0,
):
	"""Create a Bill of Materials. `items` is a list of
	{item_code, qty, uom?, rate?, bom_no?}."""
	_require_company(company)
	if not item or not frappe.db.exists("Item", item):
		frappe.throw(f"Unknown FG item: {item}")
	if flt(quantity) <= 0:
		frappe.throw("Quantity must be positive.")

	if isinstance(items, str):
		items = json.loads(items or "[]")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one raw material line is required.")

	for it in items:
		if not (it or {}).get("item_code"):
			frappe.throw("Each line needs an item_code.")
		if flt((it or {}).get("qty")) <= 0:
			frappe.throw("Each line needs a positive qty.")

	doc = frappe.new_doc("BOM")
	doc.company = company
	doc.item = item
	doc.quantity = flt(quantity)
	if uom:
		doc.uom = uom
	doc.is_active = 1
	doc.is_default = 1 if int(is_default or 0) else 0

	for it in items:
		row = doc.append("items", {})
		row.item_code = it["item_code"]
		row.qty = flt(it.get("qty"))
		if it.get("uom"):
			row.uom = it["uom"]
		if it.get("rate") not in (None, ""):
			row.rate = flt(it["rate"])
		if it.get("bom_no"):
			row.bom_no = it["bom_no"]

	doc.set_missing_values()
	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def submit_bom(name: str):
	doc = frappe.get_doc("BOM", name)
	if doc.docstatus != 0:
		frappe.throw("BOM is not in draft.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def cancel_bom(name: str):
	doc = frappe.get_doc("BOM", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted BOMs can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus}


# ----- Work Orders ---------------------------------------------------------


_WO_STATUSES = ("Draft", "Not Started", "In Process", "Completed", "Stopped", "Closed", "Cancelled")


@frappe.whitelist()
def list_work_orders(
	company: str,
	status: str | None = None,
	search: str = "",
	limit: int = 100,
):
	_require_company(company)
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if status and status in _WO_STATUSES:
		conds.append("status = %(status)s")
		params["status"] = status
	if search:
		conds.append("(name LIKE %(s)s OR production_item LIKE %(s)s OR item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, production_item, item_name, bom_no, qty, produced_qty,
		       material_transferred_for_manufacturing AS transferred_qty,
		       status, planned_start_date, planned_end_date, fg_warehouse,
		       wip_warehouse, docstatus, modified
		FROM `tabWork Order`
		WHERE {where}
		ORDER BY modified DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def work_order_detail(name: str):
	if not name or not frappe.db.exists("Work Order", name):
		frappe.throw(f"Unknown Work Order: {name}")
	doc = frappe.get_doc("Work Order", name)
	required = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"required_qty": flt(r.required_qty),
			"transferred_qty": flt(r.transferred_qty),
			"consumed_qty": flt(r.consumed_qty),
			"source_warehouse": r.source_warehouse,
			"rate": flt(r.rate),
			"amount": flt(r.amount),
		}
		for r in (doc.required_items or [])
	]
	return {
		"name": doc.name,
		"production_item": doc.production_item,
		"item_name": doc.item_name,
		"bom_no": doc.bom_no,
		"qty": flt(doc.qty),
		"produced_qty": flt(doc.produced_qty),
		"transferred_qty": flt(doc.material_transferred_for_manufacturing),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"planned_start_date": str(doc.planned_start_date) if doc.planned_start_date else None,
		"planned_end_date": str(doc.planned_end_date) if doc.planned_end_date else None,
		"fg_warehouse": doc.fg_warehouse,
		"wip_warehouse": doc.wip_warehouse,
		"source_warehouse": doc.source_warehouse,
		"company": doc.company,
		"required_items": required,
	}


@frappe.whitelist()
def create_work_order(
	company: str,
	production_item: str,
	qty: float,
	bom_no: str | None = None,
	planned_start_date: str | None = None,
	fg_warehouse: str | None = None,
	wip_warehouse: str | None = None,
	source_warehouse: str | None = None,
	submit: int = 0,
):
	_require_company(company)
	if not production_item or not frappe.db.exists("Item", production_item):
		frappe.throw(f"Unknown item: {production_item}")
	if flt(qty) <= 0:
		frappe.throw("Quantity must be positive.")

	if not bom_no:
		bom_no = frappe.db.get_value(
			"BOM",
			{"item": production_item, "is_default": 1, "is_active": 1, "docstatus": 1},
			"name",
		)
		if not bom_no:
			frappe.throw(f"No default active BOM exists for {production_item}.")

	doc = frappe.new_doc("Work Order")
	doc.company = company
	doc.production_item = production_item
	doc.bom_no = bom_no
	doc.qty = flt(qty)
	if planned_start_date:
		doc.planned_start_date = planned_start_date
	if fg_warehouse:
		doc.fg_warehouse = fg_warehouse
	if wip_warehouse:
		doc.wip_warehouse = wip_warehouse
	if source_warehouse:
		doc.source_warehouse = source_warehouse

	doc.set_work_order_operations()
	doc.get_items_and_operations_from_bom()
	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def submit_work_order(name: str):
	doc = frappe.get_doc("Work Order", name)
	if doc.docstatus != 0:
		frappe.throw("Work Order is not in draft.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def stop_work_order(name: str, reason: str = "Production Stopped"):
	from erpnext.manufacturing.doctype.work_order.work_order import stop_unstop

	stop_unstop(name, "Stopped")
	return {"name": name, "status": frappe.db.get_value("Work Order", name, "status")}


@frappe.whitelist()
def close_work_order(name: str):
	doc = frappe.get_doc("Work Order", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted Work Orders can be closed.")
	doc.status = "Closed"
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def make_work_order_stock_entry(work_order: str, purpose: str, qty: float | None = None):
	"""Generate a Stock Entry document for material transfer or manufacture.

	Returns the unsaved Stock Entry as a dict the UI can pre-fill, mirroring
	what the ERPNext Work Order desk action does."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	if purpose not in ("Material Transfer for Manufacture", "Manufacture"):
		frappe.throw(f"Unsupported purpose: {purpose}")
	doc = make_stock_entry(work_order, purpose, qty=flt(qty) if qty else None)
	if isinstance(doc, dict):
		stub = doc
	else:
		stub = doc.as_dict()
	# Insert + submit immediately — match the "produce now" flow used by the
	# Tabler UI button. If we ever want to allow drafts, expose a separate API.
	se = frappe.get_doc(stub)
	se.insert(ignore_permissions=False)
	se.submit()
	return {"name": se.name, "purpose": purpose, "docstatus": se.docstatus}


@frappe.whitelist()
def manufacturable_items(company: str, search: str = "", limit: int = 50):
	"""Items that have at least one submitted, active BOM in this company."""
	_require_company(company)
	conds = ["b.company = %(company)s", "b.is_active = 1", "b.docstatus = 1"]
	params: dict = {"company": company, "limit": int(limit)}
	if search:
		conds.append("(i.item_code LIKE %(s)s OR i.item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT DISTINCT i.name AS item_code, i.item_name, i.stock_uom
		FROM `tabItem` i
		JOIN `tabBOM` b ON b.item = i.name
		WHERE {where} AND i.disabled = 0
		ORDER BY i.item_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
