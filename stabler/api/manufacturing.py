"""Manufacturing module — BOMs, Work Orders, Production Plan basics."""

from __future__ import annotations

import json

import frappe
from stabler.api.approvals import _assert_company_scope
from frappe import _
from frappe.utils import flt, getdate, today


from stabler.api._common import _require_company, _assert_can_read, _assert_can_write
from stabler.api.organization import _can_access_module


# ----- Role helpers ---------------------------------------------------------

_ADMIN_ROLES = {"System Manager", "Stabler Admin"}


def _is_mfg_manager(user: str | None = None) -> bool:
	roles = set(frappe.get_roles(user or frappe.session.user))
	return bool(roles & ({"Manufacturing Manager"} | _ADMIN_ROLES))


def _is_warehouse_role(user: str | None = None) -> bool:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	has_role = bool(roles & ({"Stock User", "Stock Manager"} | _ADMIN_ROLES))
	return has_role or _can_access_module(user, "inventory")


def _require_mfg_manager() -> None:
	if not _is_mfg_manager():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_mfg() -> None:
	"""Any user with the manufacturing module (operator OR manager)."""
	if not _can_access_module(frappe.session.user, "manufacturing"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_own_work_order(name: str) -> None:
	"""Assert current user is the assigned operator on this WO (non-managers only)."""
	operator = frappe.db.get_value("Work Order", name, "operator")
	if operator != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# ----- BOMs ----------------------------------------------------------------


@frappe.whitelist()
def list_boms(company: str, search: str = "", item: str | None = None, limit: int = 100):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
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
	_assert_can_read("BOM", name)
	_require_mfg_manager()
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
def bom_materials(company: str, bom_no: str, qty: float = 1, exploded: int = 0):
	"""BOM raw-material lines scaled to a target finished-goods qty.

	Unlike bom_detail (manager-only, BOM-native quantity), this is available to
	operators too and returns the components already multiplied out for the WO
	qty they're about to start — so the create/start modal can preview exactly
	what will be transferred before anything is posted.

	`exploded=1` returns the fully-exploded LEAF raw materials (BOM Explosion
	Items) instead of the top-level components — so a mix/sub-assembly like
	'Smes' resolves down to the real ingredients (sut, qogoz, korobka…). That's
	what a shop-floor operator actually transfers."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg()
	if not bom_no or not frappe.db.exists("BOM", bom_no):
		frappe.throw(f"Unknown BOM: {bom_no}")
	doc = frappe.get_doc("BOM", bom_no)
	if doc.company != company:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	base = flt(doc.quantity) or 1
	factor = flt(qty) / base if flt(qty) > 0 else 1
	src = (doc.get("exploded_items") or []) if int(exploded or 0) else (doc.items or [])
	items = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"qty": flt(r.stock_qty or getattr(r, "qty", 0)) * factor,
			"uom": getattr(r, "stock_uom", None) or getattr(r, "uom", None),
			"rate": flt(r.rate),
			"amount": flt(r.amount) * factor,
			"bom_no": getattr(r, "bom_no", None),
		}
		for r in src
	]
	return {
		"bom_no": doc.name,
		"item": doc.item,
		"item_name": doc.item_name,
		"base_qty": base,
		"target_qty": flt(qty),
		"uom": doc.uom,
		"currency": doc.currency,
		"total_cost": flt(doc.total_cost) * factor,
		"items": items,
	}


@frappe.whitelist()
def wo_transfer_preview(work_order: str):
	"""The exact Material-Transfer-for-Manufacture rows ERPNext itself would build
	for this Work Order — item, qty, uom, source + target warehouse. The operator
	kiosk seeds its transfer list from this so it matches ERPNext 1:1 (the WO's
	required materials with the right quantities and warehouses), regardless of BOM
	nesting. Operators are not handed required_items by the API, so this computes
	them the same way ERPNext does. Operator (own WO) or manager."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	try:
		se = make_stock_entry(work_order, "Material Transfer for Manufacture")
	except Exception as e:  # noqa: BLE001 — preview must never hard-fail the kiosk
		frappe.log_error(title="Kassa/mfg: wo_transfer_preview failed", message=f"wo={work_order} err={e}")
		return {"items": [], "from_warehouse": None, "to_warehouse": None}
	stub = se if isinstance(se, dict) else se.as_dict()
	from_wh = to_wh = None
	items = []
	for r in (stub.get("items") or []):
		s_wh, t_wh = r.get("s_warehouse"), r.get("t_warehouse")
		from_wh = from_wh or s_wh
		to_wh = to_wh or t_wh
		items.append({
			"item_code": r.get("item_code"),
			"item_name": r.get("item_name") or frappe.db.get_value("Item", r.get("item_code"), "item_name"),
			"qty": flt(r.get("qty")),
			"uom": r.get("uom") or r.get("stock_uom"),
			"s_warehouse": s_wh,
			"t_warehouse": t_wh,
		})
	return {"items": items, "from_warehouse": from_wh, "to_warehouse": to_wh}


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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
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
	_assert_can_write("BOM", name, "submit")
	_require_mfg_manager()
	doc = frappe.get_doc("BOM", name)
	if doc.docstatus != 0:
		frappe.throw("BOM is not in draft.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def cancel_bom(name: str):
	_assert_can_write("BOM", name, "cancel")
	_require_mfg_manager()
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg()
	conds = ["company = %(company)s"]
	params: dict = {"company": company, "limit": int(limit)}
	if status and status in _WO_STATUSES:
		conds.append("status = %(status)s")
		params["status"] = status
	if search:
		conds.append("(name LIKE %(s)s OR production_item LIKE %(s)s OR item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	# Operators see only WOs assigned to themselves; managers see all.
	if not _is_mfg_manager():
		conds.append("operator = %(user)s")
		params["user"] = frappe.session.user
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, production_item, item_name, bom_no, qty, produced_qty,
		       material_transferred_for_manufacturing AS transferred_qty,
		       status, planned_start_date, planned_end_date, fg_warehouse,
		       wip_warehouse, operator, docstatus, modified
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
	_assert_can_read("Work Order", name)
	_require_mfg()
	if not name or not frappe.db.exists("Work Order", name):
		frappe.throw(f"Unknown Work Order: {name}")
	doc = frappe.get_doc("Work Order", name)
	is_manager = _is_mfg_manager()
	is_warehouse = _is_warehouse_role()

	# IDOR guard: operators may only view their own WOs, but managers and warehouse staff can view any WO.
	if not (is_manager or is_warehouse) and doc.get("operator") != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	required = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"required_qty": flt(r.required_qty),
			"transferred_qty": flt(r.transferred_qty),
			"consumed_qty": flt(r.consumed_qty),
			"source_warehouse": r.source_warehouse,
			# Rates reveal BOM cost data — only managers see them.
			**({"rate": flt(r.rate), "amount": flt(r.amount)} if is_manager else {}),
		}
		for r in (doc.required_items or [])
	]
	payload: dict = {
		"name": doc.name,
		"production_item": doc.production_item,
		"item_name": doc.item_name,
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
		"operator": doc.get("operator") or None,
		"batch_no": doc.get("custom_batch_no") or None,
		"batch_mfg_date": str(doc.custom_batch_mfg_date) if doc.get("custom_batch_mfg_date") else None,
		"batch_expiry": str(doc.custom_batch_expiry) if doc.get("custom_batch_expiry") else None,
	}
	# bom_no reveals BOM structure — managers only.
	if is_manager:
		payload["bom_no"] = doc.bom_no
		payload["timeline"] = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Order", "reference_name": name},
			fields=["name", "content", "owner", "creation", "comment_by"],
			order_by="creation desc"
		)
	# required_items visible to managers and warehouse users (for staging transfers).
	if is_manager or is_warehouse:
		payload["required_items"] = required
	return payload


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
	operator: str | None = None,
	submit: int = 0,
):
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
	if not production_item or not frappe.db.exists("Item", production_item):
		frappe.throw(f"Unknown item: {production_item}")
	if flt(qty) <= 0:
		frappe.throw("Quantity must be positive.")
	if operator and not frappe.db.exists("User", operator):
		frappe.throw(_("Unknown user: {0}").format(operator))

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
	if operator:
		doc.operator = operator

	doc.set_work_order_operations()
	doc.get_items_and_operations_from_bom()
	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def submit_work_order(name: str):
	"""Release a Work Order from Draft → Not Started. Manager-only action."""
	_assert_can_write("Work Order", name, "submit")
	_require_mfg_manager()
	doc = frappe.get_doc("Work Order", name)
	if doc.docstatus != 0:
		frappe.throw("Work Order is not in draft.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def stop_work_order(name: str, reason: str = "Production Stopped"):
	_assert_can_write("Work Order", name, "write")
	from erpnext.manufacturing.doctype.work_order.work_order import stop_unstop

	_require_mfg()
	if not _is_mfg_manager():
		_require_own_work_order(name)
	stop_unstop(name, "Stopped")
	_log_wo_event(name, f"Work Order paused: {reason}")
	return {"name": name, "status": frappe.db.get_value("Work Order", name, "status")}


@frappe.whitelist()
def resume_work_order(name: str):
	"""Resume a previously stopped Work Order."""
	_assert_can_write("Work Order", name, "write")
	from erpnext.manufacturing.doctype.work_order.work_order import stop_unstop

	_require_mfg()
	if not _is_mfg_manager():
		_require_own_work_order(name)
	stop_unstop(name, "Resumed")
	_log_wo_event(name, "Work Order resumed")
	return {"name": name, "status": frappe.db.get_value("Work Order", name, "status")}


@frappe.whitelist()
def close_work_order(name: str):
	"""Finalize a completed Work Order. Manager-only."""
	_assert_can_write("Work Order", name, "write")
	_require_mfg_manager()
	doc = frappe.get_doc("Work Order", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted Work Orders can be closed.")
	doc.status = "Closed"
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def make_work_order_stock_entry(
	work_order: str,
	purpose: str,
	qty: float | None = None,
	scrap_qty: float | None = None,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	items: str | None = None,
	batch_no: str | None = None,
	mfg_date: str | None = None,
	expiry_date: str | None = None,
):
	"""Generate and submit a Stock Entry for material transfer or manufacture.

	`scrap_qty` is accepted for the Manufacture purpose and recorded as
	process loss (operator-reported rejects). On Manufacture, an optional
	`batch_no` (+ mfg/expiry) is stamped on the Work Order for lot traceability
	(Faz 4a) — informational only, does not touch the stock batch engine."""
	import json
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry
	from erpnext.stock.get_item_details import get_conversion_factor

	_require_mfg()
	if purpose not in ("Material Transfer for Manufacture", "Manufacture"):
		frappe.throw(f"Unsupported purpose: {purpose}")
	if not _is_mfg_manager():
		_require_own_work_order(work_order)

	doc = make_stock_entry(work_order, purpose, qty=flt(qty) if qty else None)
	stub = doc if isinstance(doc, dict) else doc.as_dict()
	se = frappe.get_doc(stub)

	if purpose == "Manufacture" and scrap_qty and flt(scrap_qty) > 0:
		se.process_loss_qty = flt(scrap_qty)

	if items:
		try:
			item_list = json.loads(items)
		except Exception:
			frappe.throw("Invalid items format.")

		if from_warehouse:
			se.from_warehouse = from_warehouse
		if to_warehouse:
			se.to_warehouse = to_warehouse

		se.set("items", [])
		for it in item_list:
			row = se.append("items", {})
			row.item_code = it["item_code"]
			row.qty = flt(it["qty"])
			row.s_warehouse = it.get("s_warehouse") or from_warehouse or se.from_warehouse
			row.t_warehouse = it.get("t_warehouse") or to_warehouse or se.to_warehouse
			uom = it.get("uom")
			if uom:
				row.uom = uom
			# set_missing_values() does NOT populate conversion_factor, only validates it.
			row.conversion_factor = get_conversion_factor(it["item_code"], uom or None).get("conversion_factor") or 1.0
			row.allow_zero_valuation_rate = 1
		se.set_missing_values()
	else:
		if from_warehouse:
			se.from_warehouse = from_warehouse
		if to_warehouse:
			se.to_warehouse = to_warehouse
		for item in se.items:
			if from_warehouse and purpose in ("Material Transfer for Manufacture", "Material Issue"):
				item.s_warehouse = from_warehouse
			if to_warehouse and purpose in ("Material Transfer for Manufacture", "Material Receipt"):
				item.t_warehouse = to_warehouse
			item.allow_zero_valuation_rate = 1

	se.insert(ignore_permissions=False)
	se.submit()

	if purpose == "Material Transfer for Manufacture":
		_log_wo_event(work_order, "Work Order started (materials transferred)")
	elif purpose == "Manufacture":
		if (batch_no or "").strip():
			_stamp_wo_batch(work_order, batch_no, mfg_date, expiry_date)
		batch_note = f", Batch: {batch_no}" if (batch_no or "").strip() else ""
		_log_wo_event(work_order, f"Work Order finished. Produced: {flt(qty)}, Rejects: {flt(scrap_qty)}{batch_note}")

	return {"name": se.name, "purpose": purpose, "docstatus": se.docstatus}


@frappe.whitelist()
def assign_work_order_operator(name: str, operator: str):
	"""Assign a shop-floor operator to this Work Order. Manager-only."""
	_assert_can_write("Work Order", name, "write")
	_require_mfg_manager()
	if not frappe.db.exists("Work Order", name):
		frappe.throw(f"Unknown Work Order: {name}")
	if operator and not frappe.db.exists("User", operator):
		frappe.throw(_("Unknown user: {0}").format(operator))
	frappe.db.set_value("Work Order", name, "operator", operator or None)
	return {"name": name, "operator": operator or None}


# ----- Batch / lot traceability (Faz 4a) -----------------------------------
#
# One Work Order == one production batch. We stamp the lot number + mfg/expiry
# on the WO (custom fields, patch v53) and derive genealogy from the WO's own
# submitted Stock Entries — no change to ERPNext's Batch/Bundle stock engine, so
# it's safe for every tenant and dormant until a WO is given a batch number.


def _suggest_batch_no(doc) -> str:
	"""'<ITEM>-<YYYYMMDD>' with a -N suffix when the day already has batches."""
	from frappe.utils import nowdate

	base = f"{doc.production_item}-{getdate(doc.planned_start_date or nowdate()).strftime('%Y%m%d')}"
	existing = frappe.db.count("Work Order", {"custom_batch_no": ["like", f"{base}%"]})
	return base if not existing else f"{base}-{existing + 1}"


@frappe.whitelist()
def suggest_wo_batch(work_order: str):
	"""A suggested batch id + default mfg/expiry for the finish dialog.

	Expiry defaults to mfg + Item.shelf_life_in_days when the item defines one."""
	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	doc = frappe.get_doc("Work Order", work_order)
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	mfg = today()
	shelf = frappe.db.get_value("Item", doc.production_item, "shelf_life_in_days")
	expiry = frappe.utils.add_days(mfg, int(shelf)) if shelf and int(shelf) > 0 else None
	return {
		"batch_no": doc.get("custom_batch_no") or _suggest_batch_no(doc),
		"mfg_date": doc.get("custom_batch_mfg_date") and str(doc.custom_batch_mfg_date) or mfg,
		"expiry_date": (doc.get("custom_batch_expiry") and str(doc.custom_batch_expiry)) or expiry,
	}


def _stamp_wo_batch(work_order, batch_no, mfg_date=None, expiry_date=None) -> None:
	"""Set the batch custom fields on a (possibly submitted) Work Order."""
	frappe.db.set_value(
		"Work Order",
		work_order,
		{
			"custom_batch_no": (batch_no or "").strip() or None,
			"custom_batch_mfg_date": mfg_date or None,
			"custom_batch_expiry": expiry_date or None,
		},
	)


@frappe.whitelist()
def set_wo_batch(work_order: str, batch_no: str, mfg_date: str | None = None, expiry_date: str | None = None):
	"""Record the production batch/lot for a Work Order. Operator (own WO) or manager."""
	_assert_can_write("Work Order", work_order, "write")
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	if not _is_mfg_manager():
		_require_own_work_order(work_order)
	if not (batch_no or "").strip():
		frappe.throw(_("Batch number is required."))
	_stamp_wo_batch(work_order, batch_no, mfg_date, expiry_date)
	return {"name": work_order, "batch_no": batch_no.strip()}


@frappe.whitelist()
def wo_genealogy(work_order: str):
	"""Backward traceability for a Work Order's batch: the raw materials
	(item, qty, source warehouse, voucher) that were transferred in, plus the
	produced batch header. Read from the WO's own submitted Stock Entries."""
	_assert_can_read("Work Order", work_order)
	_require_mfg()
	if not frappe.db.exists("Work Order", work_order):
		frappe.throw(f"Unknown Work Order: {work_order}")
	doc = frappe.get_doc("Work Order", work_order)
	if not (_is_mfg_manager() or _is_warehouse_role()) and doc.get("operator") != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	consumed = frappe.db.sql(
		"""
		SELECT sed.item_code, sed.item_name, sed.qty, sed.uom,
		       sed.s_warehouse AS warehouse, se.name AS stock_entry, se.posting_date
		FROM `tabStock Entry` se
		JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		WHERE se.work_order = %(wo)s AND se.docstatus = 1
		  AND se.purpose = 'Material Transfer for Manufacture'
		ORDER BY se.posting_date, sed.idx
		""",
		{"wo": work_order},
		as_dict=True,
	)
	for c in consumed:
		c["qty"] = flt(c["qty"])
	return {
		"work_order": doc.name,
		"produced": {
			"item_code": doc.production_item,
			"item_name": doc.item_name,
			"qty": flt(doc.produced_qty),
			"batch_no": doc.get("custom_batch_no") or None,
			"mfg_date": str(doc.custom_batch_mfg_date) if doc.get("custom_batch_mfg_date") else None,
			"expiry_date": str(doc.custom_batch_expiry) if doc.get("custom_batch_expiry") else None,
		},
		"consumed": consumed,
	}


@frappe.whitelist()
def list_operators(company: str):
	"""Users with Manufacturing User or Manager role. Manager-only."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_mfg_manager()
	_require_company(company)
	return frappe.db.sql(
		"""
		SELECT DISTINCT u.name, u.full_name, u.user_image
		FROM `tabUser` u
		JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
		WHERE hr.role IN ('Manufacturing User', 'Manufacturing Manager')
		  AND u.enabled = 1
		  AND u.name != 'Administrator'
		ORDER BY u.full_name ASC
		""",
		as_dict=True,
	)


@frappe.whitelist()
def manufacturable_items(company: str, search: str = "", limit: int = 50):
	"""Items that have at least one submitted, active BOM in this company."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	_require_mfg_manager()
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


def _log_wo_event(work_order: str, text: str):
	"""Log a timestamped event comment on the Work Order."""
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Comment",
		"reference_doctype": "Work Order",
		"reference_name": work_order,
		"content": text,
		"comment_email": frappe.session.user,
		"comment_by": frappe.session.user
	}).insert(ignore_permissions=True)


# ------------------ RFID & PIN Authentication ------------------

# Legacy salt — kept ONLY as a fallback so badge/PIN records hashed before the
# per-site secret was introduced keep matching. New deployments must set a random
# `stabler_rfid_salt` in site_config.json; see _kiosk_salt().
_LEGACY_RFID_SALT = "stabler_rfid_salt"


def _kiosk_salt() -> str:
	"""Per-site RFID/PIN salt from site_config, falling back to the legacy constant.

	The constant is public (it shipped in source), so it provides no secrecy — set
	`stabler_rfid_salt` in site_config.json to a random value per site."""
	return frappe.conf.get("stabler_rfid_salt") or _LEGACY_RFID_SALT


def _verify_kiosk_token() -> None:
	"""Gate the guest badge/PIN endpoints behind a device-level shared secret.

	badge_login/pin_login are `allow_guest=True` and mint a full session, so they
	MUST authenticate the calling kiosk before doing any work. The secret lives in
	site_config.json (`stabler_kiosk_token`) and is sent by the kiosk in the
	`X-Stabler-Kiosk-Token` header (header, not a body/query param, so it does not
	land in access logs). Fails closed if the secret is not configured."""
	import hmac

	expected = frappe.conf.get("stabler_kiosk_token")
	if not expected:
		# Misconfigured site → refuse rather than silently allowing open access.
		frappe.throw(_("Kiosk login is not configured on this site."), frappe.PermissionError)
	provided = ""
	try:
		provided = frappe.get_request_header("X-Stabler-Kiosk-Token") or ""
	except Exception:
		provided = ""
	if not provided or not hmac.compare_digest(str(provided), str(expected)):
		frappe.throw(_("Invalid kiosk credentials."), frappe.PermissionError)


def get_hashes(val: str) -> list[str]:
	"""Return plain value and its salted/unsalted SHA256 hashes."""
	import hashlib
	if not val:
		return []
	res = [val]
	# Unsalted SHA256
	res.append(hashlib.sha256(val.encode("utf-8")).hexdigest())
	# Salted SHA256 (per-site salt, legacy fallback for old records)
	res.append(hashlib.sha256((val + _kiosk_salt()).encode("utf-8")).hexdigest())
	return res


def match_employee_badge(uid: str):
	"""Find active employee by RFID badge UID."""
	if not uid:
		return None
	employees = frappe.get_all(
		"Employee",
		fields=["name", "user_id", "attendance_device_id"],
		filters={"status": "Active"}
	)
	uid_options = get_hashes(uid)
	for emp in employees:
		device_id = (emp.attendance_device_id or "").strip()
		if not device_id:
			continue
		# Check colon-separated e.g. "card_uid:pin"
		if ":" in device_id:
			card_part = device_id.split(":", 1)[0].strip()
		else:
			card_part = device_id

		if card_part in uid_options:
			return emp
		for h in get_hashes(card_part):
			if h in uid_options:
				return emp
	return None


def match_employee_pin(employee_id: str, pin: str):
	"""Find active employee by ID and match their PIN."""
	if not employee_id or not pin:
		return None
	if not frappe.db.exists("Employee", employee_id):
		return None
	emp = frappe.get_doc("Employee", employee_id)
	if emp.status != "Active":
		return None

	device_id = (emp.attendance_device_id or "").strip()
	if not device_id or ":" not in device_id:
		return None

	pin_part = device_id.split(":", 1)[1].strip()
	pin_options = get_hashes(pin)

	if pin_part in pin_options:
		return emp
	for h in get_hashes(pin_part):
		if h in pin_options:
			return emp
	return None


@frappe.whitelist(allow_guest=True)
def badge_login(uid: str):
	import hashlib
	_verify_kiosk_token()
	if not uid:
		frappe.throw(_("Badge UID is required."), frappe.ValidationError)

	ip = frappe.local.ip
	# Per-IP AND per-badge lockout: per-IP alone is defeated by rotating source IPs,
	# so also throttle attempts against a specific (low-entropy) card UID.
	uid_key = f"badge_login_fail:uid:{hashlib.sha256(uid.encode('utf-8')).hexdigest()}"
	fail_key = f"badge_login_fail:{ip}"
	fails = (frappe.cache().get_value(fail_key) or 0)
	uid_fails = (frappe.cache().get_value(uid_key) or 0)
	if fails >= 5 or uid_fails >= 5:
		frappe.throw(_("Too many failed attempts. Please try again in 5 minutes."), frappe.PermissionError)

	emp = match_employee_badge(uid)
	if not emp:
		frappe.cache().set_value(fail_key, fails + 1, expires_in_sec=300)
		frappe.cache().set_value(uid_key, uid_fails + 1, expires_in_sec=300)
		frappe.get_doc({
			"doctype": "Activity Log",
			"subject": "Failed Badge Login",
			"status": "Failure",
			"operation": "Badge Login",
			"remark": f"IP: {ip}, Scan UID: {uid[:4]}***"
		}).insert(ignore_permissions=True)
		frappe.throw(_("Card not recognized"), frappe.PermissionError)

	if not emp.user_id:
		frappe.throw(_("Employee has no linked user account."), frappe.PermissionError)

	frappe.cache().delete_key(fail_key)
	frappe.cache().delete_key(uid_key)

	from frappe.auth import LoginManager
	login_manager = LoginManager()
	login_manager.login_as(emp.user_id)

	frappe.get_doc({
		"doctype": "Activity Log",
		"subject": f"Successful Badge Login: {emp.user_id}",
		"status": "Success",
		"operation": "Badge Login",
		"user": emp.user_id
	}).insert(ignore_permissions=True)

	return {
		"message": "Logged in",
		"user": emp.user_id,
		"employee": emp.name,
		"full_name": frappe.db.get_value("User", emp.user_id, "full_name")
	}


@frappe.whitelist(allow_guest=True)
def pin_login(employee: str, pin: str):
	import hashlib
	_verify_kiosk_token()
	if not employee or not pin:
		frappe.throw(_("Employee ID and PIN are required."), frappe.ValidationError)

	ip = frappe.local.ip
	# Per-IP AND per-employee lockout: the employee id is enumerable and the PIN is
	# short, so a per-IP-only throttle is trivially bypassed by rotating IPs.
	emp_key = f"pin_login_fail:emp:{hashlib.sha256(employee.encode('utf-8')).hexdigest()}"
	fail_key = f"pin_login_fail:{ip}"
	fails = (frappe.cache().get_value(fail_key) or 0)
	emp_fails = (frappe.cache().get_value(emp_key) or 0)
	if fails >= 5 or emp_fails >= 5:
		frappe.throw(_("Too many failed attempts. Please try again in 5 minutes."), frappe.PermissionError)

	emp = match_employee_pin(employee, pin)
	if not emp:
		frappe.cache().set_value(fail_key, fails + 1, expires_in_sec=300)
		frappe.cache().set_value(emp_key, emp_fails + 1, expires_in_sec=300)
		frappe.get_doc({
			"doctype": "Activity Log",
			"subject": "Failed PIN Login",
			"status": "Failure",
			"operation": "PIN Login",
			"remark": f"IP: {ip}, Employee: {employee}"
		}).insert(ignore_permissions=True)
		frappe.throw(_("Card not recognized"), frappe.PermissionError)

	if not emp.user_id:
		frappe.throw(_("Employee has no linked user account."), frappe.PermissionError)

	frappe.cache().delete_key(fail_key)
	frappe.cache().delete_key(emp_key)

	from frappe.auth import LoginManager
	login_manager = LoginManager()
	login_manager.login_as(emp.user_id)

	frappe.get_doc({
		"doctype": "Activity Log",
		"subject": f"Successful PIN Login: {emp.user_id}",
		"status": "Success",
		"operation": "PIN Login",
		"user": emp.user_id
	}).insert(ignore_permissions=True)

	return {
		"message": "Logged in",
		"user": emp.user_id,
		"employee": emp.name,
		"full_name": frappe.db.get_value("User", emp.user_id, "full_name")
	}


@frappe.whitelist(allow_guest=True)
def badge_logout():
	from frappe.auth import LoginManager
	LoginManager().logout()
	return {"message": "Success"}


def create_material_request_for_tomorrow_wo(doc, method=None):
	"""Hook function triggered on Work Order submit (doc_events).
	If planned_start_date is tomorrow or later, creates a Material Request for any shortages in wip_warehouse.
	"""
	from frappe.utils import add_days, today, getdate

	if not doc.wip_warehouse:
		return

	tomorrow = getdate(add_days(today(), 1))
	if getdate(doc.planned_start_date) < tomorrow:
		return

	# Check if a Material Request already exists for this Work Order to avoid duplicate creation
	if frappe.db.exists("Material Request", {"work_order": doc.name, "docstatus": ["!=", 2]}):
		return

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Transfer"
	mr.transaction_date = today()
	mr.company = doc.company
	mr.schedule_date = doc.planned_start_date
	mr.work_order = doc.name

	for item in doc.required_items:
		actual = frappe.db.get_value("Bin", {"item_code": item.item_code, "warehouse": doc.wip_warehouse}, "actual_qty") or 0.0
		needed = flt(item.required_qty)
		if actual < needed:
			shortage = needed - actual
			mr.append("items", {
				"item_code": item.item_code,
				"qty": shortage,
				"warehouse": doc.wip_warehouse,
				"schedule_date": doc.planned_start_date
			})

	if mr.items:
		mr.insert(ignore_permissions=True)
		mr.submit()


@frappe.whitelist()
def update_work_order_materials(work_order: str, materials: str):
	"""Update required quantities of raw materials for a Work Order.
	`materials` is a JSON string containing a list of dicts: [{'item_code': '...', 'required_qty': 12.3}]

	Also triggers/re-runs Material Request creation for any updated shortages if the WO is scheduled for tomorrow/future.
	"""
	import json
	_require_mfg()

	doc = frappe.get_doc("Work Order", work_order)
	if not doc:
		frappe.throw(f"Unknown Work Order: {work_order}")

	# Operators can only edit their own assigned Work Orders
	if not _is_mfg_manager():
		_require_own_work_order(work_order)

	try:
		mat_list = json.loads(materials)
	except Exception:
		frappe.throw("Invalid materials format.")

	# Update the quantities in the child table directly
	for m in mat_list:
		item_code = m.get("item_code")
		new_qty = flt(m.get("required_qty"))

		# Update required_qty directly in db to bypass docstatus read-only restriction
		frappe.db.sql(
			"""
			UPDATE `tabWork Order Item`
			SET required_qty = %s
			WHERE parent = %s AND item_code = %s
			""",
			(new_qty, work_order, item_code)
		)

	# Log the event
	_log_wo_event(work_order, f"Raw materials manually adjusted by {frappe.session.user}")

	# Reload document to reflect database changes
	doc.reload()

	# If it's a tomorrow or future WO, create/update Material Request for any new shortages
	from frappe.utils import add_days, today, getdate
	tomorrow = getdate(add_days(today(), 1))
	if doc.wip_warehouse and getdate(doc.planned_start_date) >= tomorrow:
		# Cancel existing draft/submitted Material Request for this WO and create a fresh one with updated shortages
		existing_mrs = frappe.get_all("Material Request", filters={"work_order": doc.name, "docstatus": ["!=", 2]}, pluck="name")
		for mr_name in existing_mrs:
			try:
				mr_doc = frappe.get_doc("Material Request", mr_name)
				if mr_doc.docstatus == 1:
					mr_doc.cancel()
				elif mr_doc.docstatus == 0:
					frappe.delete_doc("Material Request", mr_name)
			except Exception:
				pass

		# Create fresh MR
		mr = frappe.new_doc("Material Request")
		mr.material_request_type = "Transfer"
		mr.transaction_date = today()
		mr.company = doc.company
		mr.schedule_date = doc.planned_start_date
		mr.work_order = doc.name

		for item in doc.required_items:
			actual = frappe.db.get_value("Bin", {"item_code": item.item_code, "warehouse": doc.wip_warehouse}, "actual_qty") or 0.0
			needed = flt(item.required_qty)
			if actual < needed:
				shortage = needed - actual
				mr.append("items", {
					"item_code": item.item_code,
					"qty": shortage,
					"warehouse": doc.wip_warehouse,
					"schedule_date": doc.planned_start_date
				})

		if mr.items:
			mr.insert(ignore_permissions=True)
			mr.submit()

	return {"ok": True}
