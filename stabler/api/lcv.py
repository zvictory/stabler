import json
import frappe
from frappe import _
from frappe.utils import flt, cint

from stabler.api.imports import _assert_cost_visible, _latest_exchange_rate
from stabler.api._common import _assert_can_read, _assert_can_write

def _company_of(doctype: str, name: str) -> str:
	return frappe.get_cached_value(doctype, name, "company")

@frappe.whitelist()
def get_landed_cost_review(document_type: str, document_name: str, rate=None):
	"""Unified whitelisted endpoint for LCV review.

	Supports both:
	- document_type="GRN Checklist" (Imports Flow)
	- document_type="Purchase Receipt" (Tender/General Purchasing Flow)
	"""
	if not document_type or not document_name:
		frappe.throw(_("Missing document type or name"))

	if document_type == "GRN Checklist":
		from stabler.api.imports import get_landed_cost_review as imports_review
		return imports_review(document_name, rate)

	elif document_type == "Purchase Receipt":
		if not frappe.db.exists("Purchase Receipt", document_name):
			frappe.throw(_("Unknown Purchase Receipt: {0}").format(document_name))

		_assert_can_read("Purchase Receipt", document_name)
		_assert_cost_visible()

		pr = frappe.get_doc("Purchase Receipt", document_name)
		company_currency = frappe.get_cached_value("Company", pr.company, "default_currency") or "UZS"

		# Get distinct linked Purchase Orders
		po_names = list(set([
			d.purchase_order for d in pr.items
			if d.purchase_order and frappe.db.exists("Purchase Order", d.purchase_order)
		]))

		# Read customized setting includes from the PR
		custom_settings = {}
		if pr.get("custom_landed_cost_settings"):
			try:
				custom_settings = json.loads(pr.custom_landed_cost_settings)
			except Exception:
				pass
		includes = custom_settings.get("includes", {})

		# Find existing LCVs referencing this Purchase Receipt to mark consumed/vouchered components
		lcvs = frappe.db.sql("""
			SELECT parent
			FROM `tabLanded Cost Purchase Receipt`
			WHERE receipt_document = %s
		""", (document_name,), as_dict=True)

		consumed_descriptions = set()
		existing_lcvs = []
		for item in lcvs:
			lcv_name = item.parent
			lcv_doc = frappe.get_doc("Landed Cost Voucher", lcv_name)

			existing_lcvs.append({
				"lcv": lcv_name,
				"note": lcv_doc.get("note") or "",
				"posted_on": str(lcv_doc.creation) if lcv_doc.creation else None,
				"docstatus": cint(lcv_doc.docstatus),
				"total": flt(lcv_doc.total_taxes_and_charges),
				"posting_date": str(lcv_doc.posting_date) if lcv_doc.posting_date else None,
			})

			if lcv_doc.docstatus == 1:
				for tax in lcv_doc.taxes or []:
					consumed_descriptions.add(tax.description)

		from stabler.api.tender import _parse_landed
		raw_lines = []
		idx = 1
		for po_name in po_names:
			po_charges_raw = frappe.db.get_value("Purchase Order", po_name, "custom_landed_charges")
			po_charges = _parse_landed(po_charges_raw)
			for charge in po_charges:
				label = charge.get("label") or charge.get("type") or "Other"
				amount = charge.get("amount") or 0.0

				consumed = label in consumed_descriptions

				# Check custom setting first, default to True
				include_in_landed_cost = 1
				if label in includes:
					include_in_landed_cost = 1 if includes[label] else 0

				raw_lines.append({
					"row_name": label, # Use label as the identifier
					"cost_component": label,
					"description": f"PO: {po_name} - {label}",
					"currency": company_currency,
					"amount": amount,
					"amount_uzs": amount,
					"include_in_landed_cost": include_in_landed_cost,
					"lcv_ref": "vouchered" if consumed else "",
					"consumed": consumed,
				})
				idx += 1

		# Rate preview conversions
		usd_rate = 1.0
		rate_as_of = None
		rate_overridden = False
		if rate not in (None, ""):
			try:
				usd_rate = flt(rate)
				rate_overridden = True
			except Exception:
				pass

		from stabler.stabler.imports_module import lcv_math
		components = lcv_math.aggregate_components(raw_lines, usd_rate, company_currency)
		preview_components = [{"component": k, "amount": round(v, 2)} for k, v in sorted(components.items())]
		preview_total = round(sum(components.values()), 2)

		warnings = []
		if pr.docstatus != 1:
			warnings.append(_("Purchase Receipt must be Submitted to create a Landed Cost Voucher."))
		if not preview_components:
			warnings.append(_("No unconsumed landed-cost lines to voucher."))

		containers = []
		if raw_lines:
			containers.append({
				"container": "po_charges",
				"container_number": _("Purchase Order Landed Charges"),
				"cost_lines": raw_lines
			})

		return {
			"grn": {
				"name": pr.name,
				"company": pr.company,
				"company_currency": company_currency,
				"commercial_invoice": pr.get("custom_commercial_invoice") or "",
				"supplier": pr.supplier,
				"warehouse": pr.items[0].warehouse if pr.items else "",
				"docstatus": cint(pr.docstatus),
				"receipt_status": "Completed" if pr.docstatus == 1 else "Draft",
				"completion_date": str(pr.posting_date) if pr.posting_date else None,
				"received_total_kg": sum(flt(d.qty) for d in pr.items),
				"received_total_boxes": 0,
			},
			"purchase_receipts": [
				{
					"name": pr.name,
					"supplier": pr.supplier,
					"posting_date": str(pr.posting_date) if pr.posting_date else None,
					"grand_total": flt(pr.grand_total),
					"currency": pr.currency,
					"docstatus": cint(pr.docstatus),
				}
			] if pr.docstatus == 1 else [],
			"existing_lcvs": existing_lcvs,
			"containers": containers,
			"gtd": None,
			"preview": {
				"exchange_rate": usd_rate,
				"rate_as_of": str(rate_as_of) if rate_as_of else None,
				"rate_overridden": rate_overridden,
				"components": preview_components,
				"total": preview_total,
				"warnings": warnings,
				"can_create": bool(preview_components and pr.docstatus == 1),
			}
		}

@frappe.whitelist()
def toggle_cost_line_include(document_type: str, document_name: str, container: str, row_name: str, include: int = 1):
	if not document_type or not document_name:
		frappe.throw(_("Missing document type or name"))

	if document_type == "GRN Checklist":
		from stabler.api.imports import toggle_cost_line_include as imports_toggle
		return imports_toggle(container, row_name, include)

	elif document_type == "Purchase Receipt":
		_assert_can_write("Purchase Receipt", document_name)
		_assert_cost_visible()

		pr = frappe.get_doc("Purchase Receipt", document_name)
		custom_settings = {}
		if pr.get("custom_landed_cost_settings"):
			try:
				custom_settings = json.loads(pr.custom_landed_cost_settings)
			except Exception:
				pass
		includes = custom_settings.get("includes", {})

		# Here row_name is the charge label/component name
		includes[row_name] = bool(int(include))
		custom_settings["includes"] = includes

		pr.db_set("custom_landed_cost_settings", json.dumps(custom_settings))
		return {"status": "ok"}

@frappe.whitelist()
def create_additional_lcv(document_type: str, document_name: str):
	if not document_type or not document_name:
		frappe.throw(_("Missing document type or name"))

	if document_type == "GRN Checklist":
		from stabler.api.imports import create_additional_lcv as imports_create
		return imports_create(document_name)

	elif document_type == "Purchase Receipt":
		_assert_can_write("Purchase Receipt", document_name)
		_assert_cost_visible()

		review = get_landed_cost_review(document_type, document_name)
		preview = review.get("preview") or {}
		components_list = preview.get("components") or []

		if not components_list:
			frappe.throw(_("No unconsumed landed-cost lines to voucher."))

		# Promoted Stabler Settings field
		expense_account = frappe.db.get_single_value("Stabler Settings", "landed_cost_expense_account")
		if not expense_account:
			expense_account = frappe.db.get_single_value("Stabler Settings", "imports_lcv_expense_account")
		if not expense_account:
			frappe.throw(_("Please configure the Landed Cost Expense Account in Stabler Settings."))

		components = {c["component"]: c["amount"] for c in components_list}

		from stabler.stabler.imports_module import lcv_math
		lcv_dict = lcv_math.build_lcv_payload(
			company=review["grn"]["company"],
			purchase_receipts=[document_name],
			components=components,
			expense_account=expense_account,
			distribute_based_on="Qty",
		)

		if not lcv_dict:
			frappe.throw(_("Failed to build Landed Cost Voucher payload."))

		lcv = frappe.get_doc(lcv_dict)
		lcv.insert()

		frappe.db.set_value("Purchase Receipt", document_name, "custom_landed_cost_vouchered", 1)

		return {"status": "ok", "lcv": lcv.name}
