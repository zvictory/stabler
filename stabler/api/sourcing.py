"""Tender sourcing — the request side of the quotation conversation.

Until this module the SPA could only read Supplier Quotations that someone had
tagged to a deal somewhere else. That left the two questions a sourcing officer
is actually asked unanswerable: *whom did we ask*, and *what did we ask for*.
`Request for Quotation` is ERPNext's own record for both, so nothing new is
invented here — the RFQ is tagged to the lot with `custom_crm_deal` (patch v68),
exactly the way v30 tags the answers.

Three gates, in this order, on every endpoint:

  1. `_require_tender(company)` — the module switch. Six of the seven tenants
     carry CRM Deal for ordinary sales; without this they could write purchase
     documents through a tender endpoint they never enabled.
  2. `require_selected_company(company)` — the company must be passed and
     permitted, never inferred from a user default. A deal name alone must not
     be able to select the scope.
  3. `frappe.has_permission(...)` per record — company scope is not record
     permission. `LOT-DENIED` lives in the right company and is still not
     readable by everyone in it.

Sending the RFQ to the supplier stays a human act: this slice creates the draft
and stops. No `sendmail`, no portal push.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, today
from stabler.api.tender import _require_tender
from stabler.api.tender_master import require_selected_company

#: The tag patch v68 puts on Request for Quotation, mirroring v30 on Supplier
#: Quotation. Named once so a rename cannot drift between read and write.
_RFQ_DEAL_FIELD = "custom_crm_deal"

#: Columns the sourcing workspace lists. `docstatus` travels with the rows so
#: the UI can tell a draft request from a sent one without a second call.
_RFQ_LIST_FIELDS = (
	"name",
	"status",
	"transaction_date",
	"schedule_date",
	"docstatus",
)


def _rfq_link_ready() -> bool:
	return bool(frappe.db.has_column("Request for Quotation", _RFQ_DEAL_FIELD))


def _assert_company_scope(company: str | None) -> str:
	"""Canonical company-scope wrapper — the same one every Tender Master
	endpoint uses. Called by name INSIDE each endpoint, not only through
	`_deal_scope`: `test_company_scope_guard` parses each whitelisted function's
	own source and cannot see a guard that hides one call deeper. That is not a
	quirk to work around — an endpoint whose tenant check is invisible at its
	own top is one a reviewer reads as unscoped."""
	return require_selected_company(company)


def _deal_scope(deal: str, company=None, ptype: str = "read"):
	"""Resolve + authorize one CRM Deal lot against the SELECTED company."""
	selected_company = _assert_company_scope(company)
	doc = frappe.get_doc("CRM Deal", deal)
	if doc.company != selected_company:
		frappe.throw(_("Deal does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("CRM Deal", ptype=ptype, doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return doc, selected_company


def _clean_suppliers(raw) -> list[str]:
	"""Normalize the supplier list, preserving the order the user picked."""
	names: list[str] = []
	for entry in raw or []:
		name = (entry.get("supplier") if isinstance(entry, dict) else entry) or ""
		name = str(name).strip()
		if name and name not in names:
			names.append(name)
	if not names:
		frappe.throw(_("Pick at least one supplier to ask."), frappe.ValidationError)
	return names


def _clean_items(raw) -> list[dict]:
	"""Normalize the requested lines. A request for nothing is not a request —
	and it would still satisfy a naive "an RFQ exists" policy count."""
	lines: list[dict] = []
	for entry in raw or []:
		item_code = str((entry or {}).get("item_code") or "").strip()
		qty = flt((entry or {}).get("qty"))
		if not item_code:
			frappe.throw(_("Every requested line needs an item."), frappe.ValidationError)
		if qty <= 0:
			frappe.throw(
				_("Quantity must be greater than zero for {0}.").format(item_code),
				frappe.ValidationError,
			)
		lines.append(
			{
				"item_code": item_code,
				"qty": qty,
				"uom": str((entry or {}).get("uom") or "").strip() or None,
				"warehouse": str((entry or {}).get("warehouse") or "").strip() or None,
				"schedule_date": (entry or {}).get("schedule_date") or None,
				"description": str((entry or {}).get("description") or "").strip() or None,
			}
		)
	if not lines:
		frappe.throw(_("Add at least one line to request."), frappe.ValidationError)
	return lines


def _assert_suppliers_permitted(names: list[str]) -> None:
	"""Every named supplier must come back through the PERMISSION-filtered read.

	`frappe.db.exists` would answer "yes" for a supplier this user may not see,
	which is how a restricted buyer ends up mailed a price request. `get_list`
	applies role AND user permissions inside the query — that is exactly what
	separates it from `get_all`, so the check belongs there.
	"""
	permitted = {
		row["name"]
		for row in frappe.get_list(
			"Supplier",
			filters={"name": ["in", names]},
			fields=["name"],
			limit_page_length=0,
		)
	}
	missing = [name for name in names if name not in permitted]
	if missing:
		frappe.throw(_("Not permitted for supplier {0}.").format(", ".join(missing)), frappe.PermissionError)


@frappe.whitelist()
def list_rfqs(deal, company=None):
	"""Open requests for quotation raised for one tender lot."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_deal_scope(deal, selected_company)
	# An unmigrated site reports "no RFQs" rather than 500-ing the workspace —
	# the same tolerance `purchasing.tender_quotations` shows for v30.
	if not _rfq_link_ready():
		return {"rows": [], "count": 0}
	rows = frappe.get_list(
		"Request for Quotation",
		# A cancelled RFQ is not an open request. Counting it would inflate the
		# "we asked N suppliers" story the sourcing policy badge tells.
		filters={_RFQ_DEAL_FIELD: deal, "docstatus": ["<", 2]},
		fields=list(_RFQ_LIST_FIELDS),
		order_by="transaction_date desc",
		limit_page_length=0,
	)
	return {"rows": rows, "count": len(rows)}


@frappe.whitelist()
def create_rfq(deal, suppliers, items, schedule_date=None, company=None):
	"""Raise ONE draft Request for Quotation for a lot, tagged to that lot.

	Writing is deliberately stricter than reading about the migration state: an
	untagged RFQ is worse than no RFQ, because no screen will ever find it again.
	"""
	_require_tender(company)
	_assert_company_scope(company)
	# NOT `_, selected_company = ...`: that rebinds gettext's `_` to the CRM Deal
	# for the rest of the function, and the next `_("…")` call raises
	# "'_Doc' object is not callable" INSTEAD of the permission error it was
	# meant to raise — a guard that fails open-looking. Caught by
	# test_create_permission_on_the_rfq_doctype_is_demanded.
	_lot, selected_company = _deal_scope(deal, company, "write")
	if not _rfq_link_ready():
		frappe.throw(_("Run migrate to enable tender RFQs."))
	if not frappe.has_permission("Request for Quotation", "create"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	supplier_names = _clean_suppliers(frappe.parse_json(suppliers))
	lines = _clean_items(frappe.parse_json(items))
	_assert_suppliers_permitted(supplier_names)

	doc = frappe.new_doc("Request for Quotation")
	doc.company = selected_company
	doc.transaction_date = today()
	doc.schedule_date = schedule_date or None
	setattr(doc, _RFQ_DEAL_FIELD, deal)
	for supplier in supplier_names:
		doc.append("suppliers", {"supplier": supplier})
	for line in lines:
		doc.append("items", {**line, "schedule_date": line["schedule_date"] or schedule_date})
	doc.insert()
	return {
		"name": doc.name,
		"deal": deal,
		"company": selected_company,
		"supplier_count": len(supplier_names),
		"item_count": len(lines),
	}
