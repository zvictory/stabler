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

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, today

from stabler.api.tender import _require_tender, _require_tender_view
from stabler.api.tender_master import require_selected_company

#: The tag patch v68 puts on Request for Quotation, mirroring v30 on Supplier
#: Quotation. Named once so a rename cannot drift between read and write.
_RFQ_DEAL_FIELD = "custom_crm_deal"

#: The same tag on the answer side, installed by v30. Named separately from
#: `_RFQ_DEAL_FIELD` even though the string matches: they are two custom fields
#: on two doctypes, and one being renamed must not silently rename the other.
_SQ_DEAL_FIELD = "custom_crm_deal"

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


def _line_basics(entry) -> tuple[str, float]:
	"""The two facts every line — asked or answered — must carry."""
	item_code = str((entry or {}).get("item_code") or "").strip()
	qty = flt((entry or {}).get("qty"))
	if not item_code:
		frappe.throw(_("Every line needs an item."), frappe.ValidationError)
	if qty <= 0:
		frappe.throw(
			_("Quantity must be greater than zero for {0}.").format(item_code),
			frappe.ValidationError,
		)
	return item_code, qty


def _clean_items(raw) -> list[dict]:
	"""Normalize the requested lines. A request for nothing is not a request —
	and it would still satisfy a naive "an RFQ exists" policy count."""
	lines: list[dict] = []
	for entry in raw or []:
		item_code, qty = _line_basics(entry)
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


def _clean_quotation_items(raw) -> list[dict]:
	"""Normalize the answered lines: the asked facts, plus a price.

	Zero is a legitimate quote — an included line, a sample, freight the vendor
	absorbs. Negative is data-entry damage, and it is not harmless: the vendor
	comparison ranks on the total, so one negative line drags a bid below every
	honest one and wins the award.
	"""
	lines: list[dict] = []
	for entry in raw or []:
		item_code, qty = _line_basics(entry)
		rate = flt((entry or {}).get("rate"))
		if rate < 0:
			frappe.throw(_("Rate cannot be negative for {0}.").format(item_code), frappe.ValidationError)
		lines.append(
			{
				"item_code": item_code,
				"qty": qty,
				"rate": rate,
				"uom": str((entry or {}).get("uom") or "").strip() or None,
				"description": str((entry or {}).get("description") or "").strip() or None,
			}
		)
	if not lines:
		frappe.throw(_("A quotation needs at least one line."), frappe.ValidationError)
	return lines


def _sq_link_ready() -> bool:
	"""v30 put `custom_crm_deal` on Supplier Quotation; same tag, other end."""
	return bool(frappe.db.has_column("Supplier Quotation", _SQ_DEAL_FIELD))


def _quotation_for_edit(name: str, deal: str, selected_company: str):
	"""Resolve an existing quotation for in-place edit, in this strict order.

	Company first, then lot, then draft state — the order is the answer to three
	different questions and swapping them changes what an attacker learns. A
	foreign-company quotation must read as "not permitted" and never as "wrong
	lot", which would confirm the record exists.
	"""
	doc = frappe.get_doc("Supplier Quotation", name)
	if doc.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("Supplier Quotation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if (doc.get(_SQ_DEAL_FIELD) or "") != deal:
		# Retagging is not an edit. Allowing it would move a rival's bid onto
		# your own lot by passing its name.
		frappe.throw(_("This quotation belongs to another tender lot."), frappe.ValidationError)
	if int(doc.docstatus or 0) != 0:
		frappe.throw(_("A submitted quotation cannot be edited. Amend it instead."), frappe.ValidationError)
	return doc


@frappe.whitelist()
def get_supplier_quotation(name, company=None):
	"""Read one Supplier Quotation with its lines for display or editing in the SPA."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	doc = frappe.get_doc("Supplier Quotation", name)
	if doc.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("Supplier Quotation", ptype="read", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	supplier_name = frappe.db.get_value("Supplier", doc.supplier, "supplier_name") or doc.supplier
	return {
		"name": doc.name,
		"deal": doc.get(_SQ_DEAL_FIELD) or "",
		"supplier": doc.supplier,
		"supplier_name": supplier_name,
		"currency": doc.currency,
		"valid_till": doc.valid_till or None,
		"docstatus": int(doc.docstatus or 0),
		"items": [
			{
				"item_code": d.get("item_code"),
				"item_name": d.get("item_name") or d.get("item_code"),
				"qty": flt(d.get("qty")),
				"rate": flt(d.get("rate")),
				"uom": d.get("uom") or "",
				"description": d.get("description") or "",
			}
			for d in (doc.get("items") or [])
		],
	}


@frappe.whitelist()
def save_supplier_quotation(deal, supplier, currency, items, valid_till=None, name=None, company=None):
	"""Create or update a DRAFT Supplier Quotation tagged to one tender lot.

	Submitting is a separate call on purpose. The sourcing policy counts drafts
	and submitted quotations differently; a save that also submitted would make
	"5 quotations collected" unfalsifiable, because every half-typed draft would
	count as a firm offer.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_deal_scope(deal, selected_company, "write")
	if not _sq_link_ready():
		frappe.throw(_("Run migrate to enable tender quotations."))

	supplier_name = str(supplier or "").strip()
	currency_code = str(currency or "").strip()
	if not currency_code:
		# The comparison is done in company currency through `base_grand_total`;
		# a quotation with no currency of its own has no honest conversion.
		frappe.throw(_("Pick the currency the supplier quoted in."), frappe.ValidationError)
	_assert_suppliers_permitted([supplier_name])
	lines = _clean_quotation_items(frappe.parse_json(items))

	if name:
		doc = _quotation_for_edit(name, deal, selected_company)
		doc.set("items", [])
	else:
		if not frappe.has_permission("Supplier Quotation", "create"):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		doc = frappe.new_doc("Supplier Quotation")
		doc.transaction_date = today()

	doc.company = selected_company
	doc.supplier = supplier_name
	doc.currency = currency_code
	doc.valid_till = valid_till or None
	setattr(doc, _SQ_DEAL_FIELD, deal)
	for line in lines:
		doc.append("items", line)

	if name:
		doc.save()
	else:
		doc.insert()
	return {
		"name": doc.name,
		"deal": deal,
		"supplier": supplier_name,
		"currency": currency_code,
		"docstatus": int(doc.docstatus or 0),
		"line_count": len(lines),
	}


@frappe.whitelist()
def submit_supplier_quotation(name, company=None):
	"""Freeze one draft quotation into the record the award is decided from."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	doc = frappe.get_doc("Supplier Quotation", name)
	if doc.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)
	deal = doc.get(_SQ_DEAL_FIELD) or ""
	if not deal:
		# This endpoint is module-gated. Submitting an untagged quotation through
		# it would turn it into a general-purpose purchase submit button handed
		# to every tender role.
		frappe.throw(_("This quotation is not attached to a tender lot."), frappe.ValidationError)
	_deal_scope(deal, selected_company, "write")
	if int(doc.docstatus or 0) != 0:
		frappe.throw(_("This quotation is not a draft."), frappe.ValidationError)
	# Submit is its own right in Frappe, not implied by write: a buyer who may
	# draft a quotation is not automatically allowed to freeze one.
	if not frappe.has_permission("Supplier Quotation", ptype="submit", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	doc.submit()
	return {"name": name, "deal": deal, "docstatus": int(doc.docstatus or 0)}


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


# --- The award -------------------------------------------------------------
#
# "Cheapest" and "selected" are two different facts. The comparison screen knew
# the first and nothing recorded the second, so an award existed only as a
# highlighted row on a page that recomputes itself on every load.
#
# The numbers are taken HERE, never from the caller. A payload that carries its
# own comparison is a payload that can carry a flattering one, and the snapshot
# is the whole point of the record: it is what the decision was made against,
# not what the totals happen to be today.

_DECISION = "Tender Sourcing Decision"

_DECISION_FIELDS = (
	"name",
	"company",
	"deal",
	"status",
	"selected_quotation",
	"cheapest_quotation",
	"selection_reason",
	"technical_result",
	"quotation_count",
	"country_count",
	"policy_exception",
	"exception_reason",
	"approved_by",
	"approved_at",
)


def _comparison(deal: str) -> dict:
	"""The vendor comparison as the server sees it right now.

	Imported inside the call, not at module import: `purchasing` reaches back
	into the tender module for its gates, and a top-level import here would close
	that circle at load time.
	"""
	from stabler.api.purchasing import tender_quotations

	return tender_quotations(deal)


def _snapshot_rows(rows: list) -> list:
	"""Only the columns a later reader needs to re-check the decision. Freezing
	the whole payload would preserve fields that mean nothing outside today's UI."""
	return [
		{
			"quotation": r.get("name"),
			"supplier": r.get("supplier"),
			"supplier_name": r.get("supplier_name"),
			"country": r.get("country"),
			"currency": r.get("currency"),
			"grand_total": flt(r.get("grand_total")),
			"base_total": flt(r.get("base_total")),
			"cheapest": bool(r.get("cheapest")),
		}
		for r in rows
	]


def _open_decision(deal: str, company: str):
	rows = frappe.get_list(
		_DECISION,
		filters={"deal": deal, "company": company, "status": "Draft"},
		fields=list(_DECISION_FIELDS),
		limit_page_length=0,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def get_sourcing_decision(deal, company=None):
	"""The open award for a lot, plus the comparison it would be made against."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_deal_scope(deal, selected_company)
	return {"decision": _open_decision(deal, selected_company), "comparison": _comparison(deal)}


@frappe.whitelist()
def save_sourcing_decision(
	deal,
	selected_quotation,
	selection_reason,
	technical_result="Compliant",
	policy_exception=0,
	exception_reason="",
	name=None,
	company=None,
):
	"""Record (or amend) the DRAFT award for a lot.

	Sourcing writes it; a director approves it. Separating the two is the point
	of the record — an award nobody but its author ever saw is a note.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_tender_view("sourcing", selected_company)
	_deal_scope(deal, selected_company, "write")

	reason = str(selection_reason or "").strip()
	if not reason:
		frappe.throw(_("Say why this quotation was selected."), frappe.ValidationError)

	comparison = _comparison(deal)
	rows = comparison.get("rows") or []
	by_name = {r.get("name") for r in rows}
	if selected_quotation not in by_name:
		# Either it belongs to another lot or it is not tagged at all. Both mean
		# the same thing here: it is not one of the bids this decision compares.
		frappe.throw(
			_("That quotation is not among the bids collected for this lot."),
			frappe.ValidationError,
		)
	cheapest = next((r.get("name") for r in rows if r.get("cheapest")), "")

	if name:
		doc = frappe.get_doc(_DECISION, name)
		if doc.company != selected_company:
			frappe.throw(_("Decision does not belong to the selected company."), frappe.PermissionError)
		if not frappe.has_permission(_DECISION, ptype="write", doc=doc):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		if doc.deal != deal:
			frappe.throw(_("This decision belongs to another tender lot."), frappe.ValidationError)
	else:
		if _open_decision(deal, selected_company):
			# One open award per lot. Two drafts mean two answers to "who won",
			# and nothing in the record says which one the buyer acted on.
			frappe.throw(_("This lot already has an open sourcing decision."), frappe.ValidationError)
		if not frappe.has_permission(_DECISION, "create"):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		doc = frappe.new_doc(_DECISION)
		doc.company = selected_company
		doc.deal = deal
		doc.status = "Draft"

	doc.selected_quotation = selected_quotation
	# A snapshot, not a link that follows today's cheapest: the interesting case
	# is the award where the two differ, and it stops being visible the moment a
	# new quotation arrives and moves the cheapest link with it.
	doc.cheapest_quotation = cheapest
	doc.selection_reason = reason
	doc.technical_result = technical_result or "Compliant"
	doc.quotation_count = int(comparison.get("count") or 0)
	doc.country_count = int(comparison.get("countries") or 0)
	doc.policy_exception = 1 if int(policy_exception or 0) else 0
	doc.exception_reason = str(exception_reason or "").strip()
	doc.comparison_snapshot = json.dumps(
		{
			"taken_at": now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
			"base_currency": comparison.get("base_currency"),
			"rows": _snapshot_rows(rows),
		},
		ensure_ascii=False,
	)

	if name:
		doc.save()
	else:
		doc.insert()
	return {
		"name": doc.name,
		"deal": deal,
		"status": doc.status,
		"selected_quotation": selected_quotation,
		"cheapest_quotation": cheapest,
		"policy_exception": doc.policy_exception,
	}


@frappe.whitelist()
def approve_sourcing_decision(name, company=None):
	"""Approve one award. Director only, and the stamp is written here.

	The controller refuses a payload that carries its own `approved_by`, so this
	is the only place a name and a time can enter the record — which is exactly
	what makes them worth reading later.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_tender_view("director", selected_company)

	doc = frappe.get_doc(_DECISION, name)
	if doc.company != selected_company:
		frappe.throw(_("Decision does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission(_DECISION, ptype="write", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if (doc.status or "Draft") != "Draft":
		frappe.throw(_("This decision is not a draft."), frappe.ValidationError)
	_deal_scope(doc.deal, selected_company)

	doc.flags.stabler_approving = True
	doc.status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_at = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
	doc.save()
	return {
		"name": name,
		"deal": doc.deal,
		"status": doc.status,
		"approved_by": doc.approved_by,
		"approved_at": doc.approved_at,
	}


@frappe.whitelist()
def get_quotation_landed(quotation, company=None):
	"""Read quotation landed charges breakdown and calculated landed total."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	doc = frappe.get_doc("Supplier Quotation", quotation)
	if doc.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("Supplier Quotation", ptype="read", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	from stabler.api._landed import parse_landed_charges

	raw_charges = doc.get("custom_landed_charges")
	total_landed, clean_charges, has_estimate = parse_landed_charges(raw_charges)

	base_grand_total = flt(doc.base_grand_total) or flt(doc.grand_total)

	return {
		"quotation": doc.name,
		"supplier": doc.supplier,
		"currency": doc.currency,
		"grand_total": flt(doc.grand_total),
		"base_grand_total": base_grand_total,
		"landed_charges_total": total_landed,
		"base_landed_total": flt(base_grand_total + total_landed),
		"has_landed_estimate": has_estimate,
		"charges": clean_charges,
	}


@frappe.whitelist()
def update_quotation_landed(quotation, charges, company=None):
	"""Save quotation landed charges breakdown on a Supplier Quotation."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	doc = frappe.get_doc("Supplier Quotation", quotation)
	if doc.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)
	_require_tender_view("sourcing", selected_company)
	if not frappe.has_permission("Supplier Quotation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if isinstance(charges, str):
		parsed = frappe.parse_json(charges)
	else:
		parsed = charges

	if not isinstance(parsed, list):
		frappe.throw(_("Charges must be a list of landed charges."), frappe.ValidationError)

	from stabler.api._landed import parse_landed_charges

	_, clean_charges, has_est = parse_landed_charges(parsed)
	json_str = json.dumps(clean_charges, ensure_ascii=False) if (has_est and clean_charges) else None

	frappe.db.set_value("Supplier Quotation", quotation, "custom_landed_charges", json_str)

	return get_quotation_landed(quotation, company=selected_company)

