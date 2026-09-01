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
from frappe.utils import flt, getdate, now_datetime, today

from stabler.api._common import _company_default_warehouse
from stabler.api.tender import _require_tender, _require_tender_view
from stabler.api.tender_master import require_selected_company

#: The tag patch v68 puts on Request for Quotation, mirroring v30 on Supplier
#: Quotation. Named once so a rename cannot drift between read and write.
_RFQ_DEAL_FIELD = "custom_crm_deal"

#: The same tag on the answer side, installed by v30. Named separately from
#: `_RFQ_DEAL_FIELD` even though the string matches: they are two custom fields
#: on two doctypes, and one being renamed must not silently rename the other.
_SQ_DEAL_FIELD = "custom_crm_deal"

#: Tag patch v83 puts on Supplier Quotation linking it to Request for Quotation.
_SQ_RFQ_FIELD = "custom_rfq"

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


def _sq_rfq_link_ready() -> bool:
	return bool(frappe.db.has_column("Supplier Quotation", _SQ_RFQ_FIELD))


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
		"transaction_date": str(doc.transaction_date or ""),
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


def _resolve_warehouse(selected_company: str, warehouse: str | None, lines: list[dict]) -> str | None:
	"""Resolve warehouse for purchasing documents (Quotation / RFQ).
	Precedence:
	1. Explicitly passed `warehouse` argument (validated to belong to `selected_company`)
	2. `_company_default_warehouse(selected_company)`
	If unresolved and lines contain stock items, throws user-facing ValidationError.
	Assigns resolved warehouse to each dict in `lines`.
	"""
	target_wh = str(warehouse or "").strip() or _company_default_warehouse(selected_company)
	if (
		warehouse
		and target_wh
		and not frappe.db.exists("Warehouse", {"name": target_wh, "company": selected_company})
	):
		frappe.throw(
			_("Unknown warehouse: {0} for company {1}").format(target_wh, selected_company),
			frappe.ValidationError,
		)
	if not target_wh:
		has_stock = any(frappe.db.get_value("Item", line["item_code"], "is_stock_item") for line in lines)
		if has_stock:
			frappe.throw(
				_(
					"No default warehouse configured for {0}. Set a default warehouse in Company settings."
				).format(selected_company),
				frappe.ValidationError,
			)

	if target_wh:
		for line in lines:
			line["warehouse"] = target_wh

	return target_wh or None


def _apply_rfq_item_defaults(lines: list[dict], fallback_schedule_date) -> None:
	"""Fill the item defaults the Desk form fetches client-side.

	`Request for Quotation` is the one buying document whose controller does NOT
	call `super().validate()` — it cherry-picks four supers instead — so
	`AccountsController.validate` never runs and `set_missing_values` is never
	called for it. Supplier Quotation gets uom / stock_uom / conversion_factor
	filled for free; an RFQ built server-side gets nothing, and ERPNext then
	rejects the row for a field the user was never shown a box for.

	Verified against erpnext/buying/doctype/request_for_quotation/
	request_for_quotation.py::validate and controllers/accounts_controller.py:225.
	"""
	for line in lines:
		stock_uom = frappe.db.get_value("Item", line["item_code"], "stock_uom")
		# RFQ is deliberately ABSENT from get_item_details' purchase_uom branch
		# (erpnext/stock/get_item_details.py:479-486), so the Desk form lands on
		# stock_uom for this doctype too. Matching it keeps the unit we ask the
		# supplier in identical whether the RFQ was raised here or in Desk.
		uom = line.get("uom") or stock_uom
		line["stock_uom"] = stock_uom
		line["uom"] = uom
		if uom == stock_uom:
			line["conversion_factor"] = 1.0
		else:
			from erpnext.stock.get_item_details import get_conversion_factor

			line["conversion_factor"] = (
				get_conversion_factor(line["item_code"], uom).get("conversion_factor") or 1.0
			)
		# reqd on Request for Quotation Item, and frappe applies no doctype
		# default to a row created by `append` (base_document._init_child).
		line["schedule_date"] = line.get("schedule_date") or fallback_schedule_date or today()


@frappe.whitelist()
def save_supplier_quotation(
	deal,
	supplier,
	currency,
	items,
	valid_till=None,
	name=None,
	company=None,
	warehouse=None,
	rfq=None,
):
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
		frappe.throw(_("Run migrate to enable tender supplier quotations."))

	if rfq:
		if not frappe.db.exists("Request for Quotation", rfq):
			frappe.throw(_("RFQ not found: {0}").format(rfq), frappe.DoesNotExistError)
		rfq_doc = frappe.get_doc("Request for Quotation", rfq)
		if rfq_doc.company != selected_company or rfq_doc.get(_RFQ_DEAL_FIELD) != deal:
			frappe.throw(
				_("Cannot attach quotation to an RFQ from another lot or company."), frappe.ValidationError
			)
		if not frappe.has_permission("Request for Quotation", "read", doc=rfq_doc):
			frappe.throw(_("Not permitted."), frappe.PermissionError)

	supplier_name = str(supplier or "").strip()
	currency_code = str(currency or "").strip()
	if not supplier_name:
		frappe.throw(_("Pick the supplier who quoted."), frappe.ValidationError)
	if not currency_code:
		# The comparison is done in company currency through `base_grand_total`;
		# a quotation with no currency of its own has no honest conversion.
		frappe.throw(_("Pick the currency the supplier quoted in."), frappe.ValidationError)
	_assert_suppliers_permitted([supplier_name])
	lines = _clean_quotation_items(frappe.parse_json(items))

	_resolve_warehouse(selected_company, warehouse, lines)

	if name:
		doc = _quotation_for_edit(name, deal, selected_company)
		doc.set("items", [])
		effective_tx_date = str(doc.transaction_date or "") or today()
	else:
		if not frappe.has_permission("Supplier Quotation", "create"):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		doc = frappe.new_doc("Supplier Quotation")
		doc.transaction_date = today()
		effective_tx_date = str(doc.transaction_date)
		if rfq and _sq_rfq_link_ready():
			setattr(doc, _SQ_RFQ_FIELD, rfq)

	if valid_till and getdate(valid_till) < getdate(effective_tx_date):
		frappe.throw(
			_("Valid till date ({0}) cannot be before transaction date ({1}).").format(
				valid_till, effective_tx_date
			),
			frappe.ValidationError,
		)

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


def _invited_rows(rfq_names: list[str]) -> list[dict]:
	"""Who a lot's live RFQs asked, each with the country they answer from.

	The country lives on Supplier, so this joins out for it; `_rfq_supplier_counts`
	does not, because it answers a different question -- how big was THIS RFQ.
	That count is rows; this one is vendors, and the two must not be swapped.

	Parents are pulled rather than counted for the reason spelled out on
	`_rfq_supplier_counts`: Frappe v16 refuses a SQL function inside a string
	SELECT field, which passes every local check and then 500s the live list.

	De-duplication is left to `_sourcing_reach.reach_of` -- one place decides what
	a vendor is, so the badge and its test cannot drift apart.
	"""
	if not rfq_names:
		return []
	rows = frappe.get_all(
		_RFQ_SUPPLIER_TABLE,
		filters={"parent": ["in", rfq_names], "parenttype": "Request for Quotation"},
		fields=["supplier"],
		limit_page_length=0,
	)
	suppliers = sorted({r["supplier"] for r in rows if r.get("supplier")})
	if not suppliers:
		return []
	country_of = {
		s["name"]: s.get("country") or ""
		for s in frappe.get_all("Supplier", filters={"name": ["in", suppliers]}, fields=["name", "country"])
	}
	return [{"supplier": name, "country": country_of.get(name, "")} for name in suppliers]


@frappe.whitelist()
def list_rfqs(deal, company=None):
	"""Open requests for quotation raised for one tender lot, and their reach.

	`reach` is the send-side half of the procurement rule. The rule itself is
	checked on the way out, by `Tender Sourcing Decision.validate`; until this
	key existed nothing checked the way in, so a lot invited entirely inside one
	country read as healthy right up to the award that refused it.

	It reports what the invitation ALONE can reach. It is not a ceiling: an
	uninvited vendor's quotation can still be attached to the lot later
	(`attach_quotation_to_deal`), so anything shown from it must be worded as
	"this invitation", never as "impossible".
	"""
	from stabler.api._sourcing_reach import reach_of
	from stabler.stabler.doctype.tender_sourcing_decision.tender_sourcing_decision import (
		MIN_COUNTRIES,
		MIN_QUOTATIONS,
	)

	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_deal_scope(deal, selected_company)
	# An unmigrated site reports "no RFQs" rather than 500-ing the workspace —
	# the same tolerance `purchasing.tender_quotations` shows for v30. The reach
	# key is still present and zeroed: a badge reading `undefined.suppliers`
	# would break the workspace on exactly the sites that have not migrated.
	if not _rfq_link_ready():
		return {"rows": [], "count": 0, "reach": reach_of([], MIN_QUOTATIONS, MIN_COUNTRIES)}
	rows = frappe.get_list(
		"Request for Quotation",
		# A cancelled RFQ is not an open request. Counting it would inflate the
		# "we asked N suppliers" story the sourcing policy badge tells.
		filters={_RFQ_DEAL_FIELD: deal, "docstatus": ["<", 2]},
		fields=list(_RFQ_LIST_FIELDS),
		order_by="transaction_date desc",
		limit_page_length=0,
	)
	# Built from `rows`, so a cancelled RFQ is out of the reach for the same
	# reason it is out of the list — otherwise the badge tells the "we asked N
	# suppliers" story this filter exists to refuse.
	invited = _invited_rows([row["name"] for row in rows])
	return {
		"rows": rows,
		"count": len(rows),
		"reach": reach_of(invited, MIN_QUOTATIONS, MIN_COUNTRIES),
	}


def _read_deal_intake_items(doc) -> list[dict]:
	"""The tender's item lines, as sanitized at intake time.

	Read through the same pure module every intake reader uses, so an RFQ
	raised months after intake sees the same lines the drawer captured — not
	a JSON blob that drifted through edits by hand.
	"""
	from stabler.api._tender_intake_items import read_intake_items

	return read_intake_items(doc)


@frappe.whitelist()
def get_deal_rfq_defaults(deal, company=None):
	"""Return company-scoped default items and suppliers for a tender deal lot.

	The items are the tender scope as captured at intake: a deal that reached
	the sourcing lane was already specified line by line, and asking the officer
	to retype those lines is asking for a second, drifting copy of the same
	list. Suppliers stay a deliberate choice — the policy wants >=5 quotations
	from >=2 countries, not whatever a table happens to contain.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	doc, _ = _deal_scope(deal, selected_company, "read")

	items = [
		{
			"item_code": line["item_code"],
			"item_name": line["item_name"],
			"qty": line["qty"],
			"uom": line["uom"],
			"rate": line["rate"],
			"schedule_date": "",
			"warehouse": "",
		}
		for line in _read_deal_intake_items(doc)
	]

	# The form counts the reach of the vendors being picked, before anything is
	# saved, so it needs the same two numbers the award will be judged by. Sent
	# from here rather than spelled in the component: a threshold typed into Vue
	# is a copy that goes stale silently, and the screen that goes green on a set
	# the award refuses is worse than no badge at all.
	from stabler.stabler.doctype.tender_sourcing_decision.tender_sourcing_decision import (
		MIN_COUNTRIES,
		MIN_QUOTATIONS,
	)

	return {
		"deal": deal,
		"deal_label": doc.get("organization") or doc.get("lead_name") or deal,
		"currency": doc.get("currency") or "",
		"company": selected_company,
		"items": items,
		"suppliers": [],
		"policy": {"min_suppliers": MIN_QUOTATIONS, "min_countries": MIN_COUNTRIES},
	}


@frappe.whitelist()
def get_quotation_defaults(deal, rfq=None, company=None):
	"""Lines to quote against: the ask, not a blank form.

	A quotation answers a request. When a specific RFQ is given its lines are
	used; otherwise the lot's LATEST open RFQ's. Rates stay empty — the rate
	is the supplier's answer, never prefilled.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_deal_scope(deal, selected_company, "read")

	rfq_doc = None
	if rfq:
		if not frappe.db.exists("Request for Quotation", rfq):
			frappe.throw(_("RFQ not found: {0}").format(rfq), frappe.DoesNotExistError)
		candidate = frappe.get_doc("Request for Quotation", rfq)
		if candidate.company != selected_company or candidate.get(_RFQ_DEAL_FIELD) != deal:
			frappe.throw(_("RFQ does not belong to this deal."), frappe.PermissionError)
		if not frappe.has_permission("Request for Quotation", "read", doc=candidate):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		if candidate.docstatus < 2:
			rfq_doc = candidate
	else:
		if _rfq_link_ready():
			rfq_names = frappe.get_list(
				"Request for Quotation",
				filters={
					_RFQ_DEAL_FIELD: deal,
					"company": selected_company,
					"docstatus": ["<", 2],
				},
				fields=["name"],
				order_by="transaction_date desc, name desc",
				limit_page_length=1,
			)
			if rfq_names:
				candidate = frappe.get_doc("Request for Quotation", rfq_names[0]["name"])
				if frappe.has_permission("Request for Quotation", "read", doc=candidate):
					rfq_doc = candidate

	if not rfq_doc:
		return {"items": []}

	items = []
	for it in rfq_doc.get("items") or []:
		if isinstance(it, dict):
			item_code = it.get("item_code") or ""
			item_name = it.get("item_name") or item_code
			qty = flt(it.get("qty")) or 1.0
			uom = it.get("uom") or ""
		else:
			item_code = getattr(it, "item_code", "")
			item_name = getattr(it, "item_name", "") or item_code
			qty = flt(getattr(it, "qty", 1.0)) or 1.0
			uom = getattr(it, "uom", "") or ""
		items.append(
			{
				"item_code": item_code,
				"item_name": item_name,
				"qty": qty,
				"uom": uom,
			}
		)
	return {"items": items}


@frappe.whitelist()
def create_rfq(deal, suppliers, items, schedule_date=None, company=None, warehouse=None):
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
	_resolve_warehouse(selected_company, warehouse, lines)
	_apply_rfq_item_defaults(lines, schedule_date)

	doc = frappe.new_doc("Request for Quotation")
	doc.company = selected_company
	doc.transaction_date = today()
	doc.schedule_date = schedule_date or None
	# RFQ and Supplier Quotation do not have a set_warehouse field in header (unlike PO/PR/PI/SO); warehouse is set per line.
	setattr(doc, _RFQ_DEAL_FIELD, deal)
	for supplier in supplier_names:
		doc.append("suppliers", {"supplier": supplier})
	for line in lines:
		doc.append("items", dict(line))
	doc.insert()
	return {
		"name": doc.name,
		"deal": deal,
		"company": selected_company,
		"supplier_count": len(supplier_names),
		"item_count": len(lines),
	}


# --- The request, readable ---------------------------------------------------
#
# Until now an RFQ raised here existed only as a chip: a name, a date, a badge.
# The questions a chip cannot answer — whom exactly did we ask, and who has
# answered — are precisely the ones the sourcing policy (>=5 quotations from
# >=2 countries) is audited against, so the list and the detail carry them.

_RFQ_LIST_PAGE_FIELDS = (
	"name",
	"status",
	"transaction_date",
	"schedule_date",
	"docstatus",
	_RFQ_DEAL_FIELD,
)

_RFQ_SUPPLIER_TABLE = "Request for Quotation Supplier"

#: Channels a human can actually hand an RFQ over by, in the market this runs
#: in. WhatsApp is first-class on purpose: it is how suppliers answer here.
_SENT_CHANNELS = ("whatsapp", "email", "phone", "hand", "other")


def _rfq_doc_scope(name: str, selected_company: str, ptype: str = "read"):
	"""Resolve one RFQ inside the selected company, with record permission.

	Company first, record permission second — same order `_deal_scope` uses, so
	a foreign-company RFQ reads as "not permitted", never as "wrong lot".
	"""
	doc = frappe.get_doc("Request for Quotation", name)
	if doc.company != selected_company:
		frappe.throw(
			_("Request for quotation does not belong to the selected company."), frappe.PermissionError
		)
	if not frappe.has_permission("Request for Quotation", ptype=ptype, doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return doc


def _rfq_supplier_counts(names: list[str]) -> dict[str, int]:
	"""How many suppliers each RFQ asked, straight from the child table.

	Counted by pulling parents, not with `count(name)`: Frappe v16 refuses a
	SQL function inside a string SELECT field, which passes every local check
	and then 500s the list on the live site (same lesson as
	tender_master.list_tender_masters).
	"""
	counts = {name: 0 for name in names}
	if not names:
		return counts
	rows = frappe.get_all(
		_RFQ_SUPPLIER_TABLE,
		filters={"parent": ["in", names], "parenttype": "Request for Quotation"},
		fields=["parent"],
		limit_page_length=0,
	)
	for row in rows:
		counts[row["parent"]] = counts.get(row["parent"], 0) + 1
	return counts


def _deal_quotation_counts(deals: list[str]) -> dict[str, int]:
	"""Quotations received per lot (draft + submitted): the answer-side count."""
	counts = {deal: 0 for deal in deals}
	if not deals or not _sq_link_ready():
		return counts
	rows = frappe.get_list(
		"Supplier Quotation",
		filters={_SQ_DEAL_FIELD: ["in", deals], "docstatus": ["<", 2]},
		fields=["name", _SQ_DEAL_FIELD],
		limit_page_length=0,
	)
	for row in rows:
		deal_name = row.get(_SQ_DEAL_FIELD)
		if deal_name in counts:
			counts[deal_name] += 1
	return counts


def _deal_labels(deals: list[str]) -> dict[str, str]:
	"""Lot display labels, resolved in one query rather than one per row."""
	labels = {deal: deal for deal in deals}
	if not deals:
		return labels
	rows = frappe.get_list(
		"CRM Deal",
		filters={"name": ["in", deals]},
		fields=["name", "organization", "lead_name"],
		limit_page_length=0,
	)
	for row in rows:
		labels[row["name"]] = row.get("organization") or row.get("lead_name") or row["name"]
	return labels


@frappe.whitelist()
def list_all_rfqs(company=None, deal=None, search=None, limit=200):
	"""All requests for quotation across the selected company's tender lots."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	if not frappe.has_permission("Request for Quotation", "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	# Unmigrated site reports "no RFQs" instead of 500-ing the list page — the
	# tolerance `list_rfqs` shows for the same migration state.
	if not _rfq_link_ready():
		return {"rows": [], "count": 0}
	filters = {"company": selected_company, "docstatus": ["<", 2]}
	if deal:
		filters[_RFQ_DEAL_FIELD] = deal
	if search:
		filters["name"] = ["like", f"%{str(search).strip()}%"]
	rows = frappe.get_list(
		"Request for Quotation",
		filters=filters,
		fields=list(_RFQ_LIST_PAGE_FIELDS),
		order_by="transaction_date desc, modified desc",
		limit_page_length=max(1, min(int(flt(limit) or 200), 500)),
	)
	deals = sorted({row.get(_RFQ_DEAL_FIELD) for row in rows if row.get(_RFQ_DEAL_FIELD)})
	supplier_counts = _rfq_supplier_counts([row["name"] for row in rows])
	quotation_counts = _deal_quotation_counts(deals)
	labels = _deal_labels(deals)
	for row in rows:
		deal_name = row.get(_RFQ_DEAL_FIELD) or ""
		row["deal"] = deal_name
		row["deal_label"] = labels.get(deal_name, deal_name)
		row["supplier_count"] = supplier_counts.get(row["name"], 0)
		row["quotation_count"] = quotation_counts.get(deal_name, 0)
	return {"rows": rows, "count": len(rows)}


@frappe.whitelist()
def get_rfq(name, company=None):
	"""One RFQ with its suppliers, per-supplier response status, and lines.

	The target rate on each line is the intake estimate for that item — a buyer
	reference the RFQ doctype itself does not carry, joined back here by item
	code so the officer sees the tender's expectation next to what was asked.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	doc = _rfq_doc_scope(name, selected_company)

	deal = doc.get(_RFQ_DEAL_FIELD) or ""
	deal_label = deal
	intake_items = []
	if deal:
		deal_doc = frappe.get_doc("CRM Deal", deal)
		deal_label = deal_doc.get("organization") or deal_doc.get("lead_name") or deal
		intake_items = _read_deal_intake_items(deal_doc)
	target_rate = {line["item_code"]: line["rate"] for line in intake_items}

	quotations: dict[str, list[str]] = {}
	if deal and _sq_link_ready():
		sq_filters = {_SQ_DEAL_FIELD: deal, "docstatus": ["<", 2]}
		or_filters = None
		if _sq_rfq_link_ready():
			# v83 added `custom_rfq` for round tracking, but a custom field's
			# default only reaches NEW documents and `save_supplier_quotation`
			# stamps it on insert only — every quotation recorded before the
			# migrate keeps it empty. Matching on the RFQ alone would hide all
			# of those with no way to repair them from the UI (measured on
			# mikas 2026-08-15: 14 of 14 quotations), so an unstamped quotation
			# still answers every RFQ of its deal, as it did before v83.
			or_filters = [[_SQ_RFQ_FIELD, "=", name], [_SQ_RFQ_FIELD, "is", "not set"]]
		rows = frappe.get_list(
			"Supplier Quotation",
			filters=sq_filters,
			or_filters=or_filters,
			fields=["name", "supplier"],
			order_by="modified desc",
			limit_page_length=0,
		)
		for row in rows:
			quotations.setdefault(row["supplier"], []).append(row["name"])

	suppliers = []
	for row in doc.get("suppliers") or []:
		supplier = row.get("supplier") or ""
		if not supplier:
			continue
		suppliers.append(
			{
				"supplier": supplier,
				"supplier_name": row.get("supplier_name") or supplier,
				"contact": row.get("contact") or "",
				"email_id": row.get("email_id") or "",
				"quotations": quotations.get(supplier, []),
				"responded": bool(quotations.get(supplier)),
			}
		)

	return {
		"name": doc.name,
		"deal": deal,
		"deal_label": deal_label,
		"company": selected_company,
		"status": doc.status,
		"docstatus": int(doc.docstatus or 0),
		"transaction_date": str(doc.transaction_date or ""),
		"schedule_date": str(doc.schedule_date or ""),
		"suppliers": suppliers,
		"items": [
			{
				"item_code": d.get("item_code") or "",
				"item_name": d.get("item_name") or d.get("item_code") or "",
				"qty": flt(d.get("qty")),
				"uom": d.get("uom") or "",
				"warehouse": d.get("warehouse") or "",
				"schedule_date": str(d.get("schedule_date") or ""),
				"description": d.get("description") or "",
				"target_rate": target_rate.get(d.get("item_code"), 0.0),
			}
			for d in (doc.get("items") or [])
		],
	}


@frappe.whitelist()
def rfq_print(name, company=None):
	"""Print payload for one RFQ: the letter a supplier is handed."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_rfq_doc_scope(name, selected_company)
	base = get_rfq(name, company)
	# `get_rfq` joins the intake's estimate so the officer reading the RFQ sees
	# the tender's own expectation beside the ask. THIS payload is the letter the
	# supplier is handed — our ceiling is not part of what we hand the vendor we
	# are asking to come in under it.
	base["items"] = [
		{key: value for key, value in line.items() if key != "target_rate"}
		for line in (base.get("items") or [])
	]
	company_doc = frappe.get_doc("Company", selected_company)
	return {
		**base,
		"company_name": company_doc.company_name,
		"company_abbr": company_doc.abbr,
		"company_tax_id": getattr(company_doc, "tax_id", "") or "",
		"company_email": getattr(company_doc, "email", "") or "",
		"company_phone": getattr(company_doc, "phone_no", "") or "",
	}


@frappe.whitelist()
def mark_rfq_sent(name, company=None, channel=None, note=None):
	"""Record that the RFQ was handed to its suppliers — by whom, when, how.

	The draft-and-stop philosophy stays: Stabler does not email anything. But
	"we sent it" is a business fact the sourcing timeline needs, so the human
	act is logged as a Communication on the RFQ, the same record type the CRM
	email trail uses.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	doc = _rfq_doc_scope(name, selected_company, "write")
	if not frappe.has_permission("Communication", "create"):
		frappe.throw(_("Not permitted for Communication"), frappe.PermissionError)

	ch = str(channel or "").strip().lower() or "other"
	if ch not in _SENT_CHANNELS:
		frappe.throw(_("Unknown sending channel: {0}.").format(ch), frappe.ValidationError)
	note_text = str(note or "").strip()[:500]

	comm = frappe.new_doc("Communication")
	comm.communication_type = "Communication"
	comm.communication_medium = "Email" if ch == "email" else "Other"
	comm.sent_or_received = "Sent"
	comm.subject = _("Request for quotation {0} sent to {1} suppliers").format(
		doc.name, len(doc.get("suppliers") or [])
	)
	comm.content = note_text or _("RFQ shared with suppliers via {0}.").format(ch)
	comm.sender = frappe.session.user
	comm.reference_doctype = "Request for Quotation"
	comm.reference_name = doc.name
	comm.company = selected_company
	comm.insert()
	return {"communication": comm.name, "rfq": doc.name, "channel": ch}


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
			"base_landed_total": flt(r.get("base_landed_total")),
			"landed_charges_total": flt(r.get("landed_charges_total")),
			"has_landed_estimate": bool(r.get("has_landed_estimate")),
			"cheapest": bool(r.get("cheapest")),
			"is_cheapest_price": bool(r.get("is_cheapest_price")),
			"is_cheapest_landed": bool(r.get("is_cheapest_landed")),
			"landed_delta": flt(r.get("landed_delta")),
			"landed_pct": flt(r.get("landed_pct")),
		}
		for r in rows
	]


def _open_decision(deal: str, company: str):
	"""The one DRAFT award a lot may have open. Deliberately blind to approvals.

	`save_sourcing_decision` uses this as its "there is already an open draft"
	guard, so widening it to count approvals would refuse the re-award that
	follows a winner falling through — the case `purchasing._assert_awarded`
	orders by `approved_at desc` precisely to support.
	"""
	rows = frappe.get_list(
		_DECISION,
		filters={"deal": deal, "company": company, "status": "Draft"},
		fields=list(_DECISION_FIELDS),
		limit_page_length=0,
	)
	return rows[0] if rows else None


def _standing_award(deal: str, company: str):
	"""The approved award currently in force for a lot, if there is one.

	Same ordering as `purchasing._assert_awarded`: a lot can be awarded more
	than once, and only the LATEST approval opens the PO route. Reading it any
	other way would let the workspace name a superseded winner and offer a
	button the server then refuses, with nothing on screen explaining why.

	`get_list`, not `get_all`, matching `_open_decision` — this is a window onto
	the record for a screen, not the yes/no the PO gate asks.
	"""
	rows = frappe.get_list(
		_DECISION,
		filters={"deal": deal, "company": company, "status": "Approved"},
		fields=list(_DECISION_FIELDS),
		order_by="approved_at desc, modified desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def get_sourcing_decision(deal, company=None):
	"""The award state of a lot, plus the comparison it would be judged against.

	Two separate answers, because both can be true at once: `decision` is the
	open DRAFT (what save and approve act on) and `award` is the approval
	standing right now (what the PO gate honours). They were one field until
	2026-08-29, and because that field only ever carried drafts, an approved lot
	read back as "never awarded" the moment the page was reloaded — the
	read-only award panel and the Create-purchase-order button inside it existed
	only in the session that clicked approve.
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_deal_scope(deal, selected_company)
	return {
		"decision": _open_decision(deal, selected_company),
		"award": _standing_award(deal, selected_company),
		"comparison": _comparison(deal),
	}


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
	cheapest_price = comparison.get("cheapest_price_quote") or next(
		(r.get("name") for r in rows if r.get("is_cheapest_price")), ""
	)
	cheapest_landed = comparison.get("cheapest_landed_quote") or next(
		(r.get("name") for r in rows if r.get("is_cheapest_landed")), ""
	)
	estimate_complete = bool(comparison.get("estimate_complete"))

	cheapest = cheapest_landed if (estimate_complete and cheapest_landed) else cheapest_price
	if not cheapest:
		cheapest = next((r.get("name") for r in rows if r.get("cheapest")), "")

	if name:
		doc = frappe.get_doc(_DECISION, name)
		if doc.company != selected_company:
			frappe.throw(_("Decision does not belong to the selected company."), frappe.PermissionError)
		if not frappe.has_permission(_DECISION, ptype="write", doc=doc):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		if doc.deal != deal:
			frappe.throw(_("This decision belongs to another tender lot."), frappe.ValidationError)
		if (doc.status or "Draft") != "Draft":
			# Amending by name is how sourcing corrects its OWN draft. Pointed at
			# an approved decision it would rewrite the winner underneath the
			# director's stamp, and the record would keep reading as if the
			# approval had been given for the new supplier. Re-awarding a lot is
			# a NEW decision a director approves again, never an edit of the old.
			frappe.throw(
				_("This decision is already approved. Start a new one to re-award the lot."),
				frappe.ValidationError,
			)
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
			"estimate_complete": estimate_complete,
			"cheapest_price_quote": cheapest_price,
			"cheapest_landed_quote": cheapest_landed,
			"missing_estimates": comparison.get("missing_estimates") or [],
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

	_tot, clean_charges, has_est = parse_landed_charges(parsed)
	json_str = json.dumps(clean_charges, ensure_ascii=False) if (has_est and clean_charges) else None

	frappe.db.set_value("Supplier Quotation", quotation, "custom_landed_charges", json_str)

	return get_quotation_landed(quotation, company=selected_company)


@frappe.whitelist()
def list_unassigned_quotations(search=None, limit=20, company=None):
	"""List Supplier Quotations for company that are not tagged to any deal."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_tender_view("sourcing", selected_company)

	if not _sq_link_ready():
		return []

	filters = {"company": selected_company, "docstatus": ["<", 2]}
	rows = frappe.get_list(
		"Supplier Quotation",
		filters=filters,
		fields=[
			"name",
			"supplier",
			"currency",
			"grand_total",
			"base_grand_total",
			"transaction_date",
			"valid_till",
			"docstatus",
			_SQ_DEAL_FIELD,
		],
		order_by="transaction_date desc, name desc",
		limit_page_length=0 if not limit else int(limit) * 2,
	)

	unassigned = []
	search_q = str(search or "").strip().lower()
	for r in rows:
		deal = r.get(_SQ_DEAL_FIELD)
		if deal:
			continue
		if not frappe.has_permission("Supplier Quotation", "read", doc=r.get("name")):
			continue
		supplier = r.get("supplier") or ""
		supplier_name = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier
		country = frappe.db.get_value("Supplier", supplier, "country") or ""
		if search_q:
			name_match = search_q in r["name"].lower()
			sup_match = search_q in supplier.lower() or search_q in supplier_name.lower()
			if not (name_match or sup_match):
				continue
		unassigned.append(
			{
				"name": r["name"],
				"supplier": supplier,
				"supplier_name": supplier_name,
				"country": country,
				"currency": r.get("currency") or "",
				"grand_total": flt(r.get("grand_total")),
				"base_grand_total": flt(r.get("base_grand_total")) or flt(r.get("grand_total")),
				"transaction_date": str(r.get("transaction_date") or ""),
				"valid_till": str(r.get("valid_till") or "") if r.get("valid_till") else None,
				"docstatus": int(r.get("docstatus") or 0),
			}
		)
		if limit and len(unassigned) >= int(limit):
			break

	return unassigned


@frappe.whitelist()
def attach_quotation_to_deal(quotation, deal, company=None):
	"""Tag an unallocated Supplier Quotation to a tender lot."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_tender_view("sourcing", selected_company)
	_deal_scope(deal, selected_company, "write")

	doc = frappe.get_doc("Supplier Quotation", quotation)
	if doc.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("Supplier Quotation", "write", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if int(doc.docstatus or 0) >= 2:
		frappe.throw(_("Cannot attach a cancelled quotation."), frappe.ValidationError)

	frappe.db.set_value("Supplier Quotation", quotation, _SQ_DEAL_FIELD, deal)
	return {"quotation": quotation, "deal": deal}


@frappe.whitelist()
def detach_quotation_from_deal(quotation, company=None):
	"""Detach a Supplier Quotation from its tender lot if not part of an approved decision."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_tender_view("sourcing", selected_company)

	doc = frappe.get_doc("Supplier Quotation", quotation)
	if doc.company != selected_company:
		frappe.throw(_("Quotation does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("Supplier Quotation", "write", doc=doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	deal = doc.get(_SQ_DEAL_FIELD) or ""
	if deal:
		approved_decisions = frappe.get_all(
			_DECISION,
			filters={"deal": deal, "company": selected_company, "status": "Approved"},
			fields=["name", "selected_quotation", "cheapest_quotation"],
		)
		for dec in approved_decisions:
			if dec.get("selected_quotation") == quotation or dec.get("cheapest_quotation") == quotation:
				frappe.throw(
					_(
						"Cannot detach quotation '{0}': it is part of an approved sourcing decision for this tender."
					).format(quotation),
					frappe.ValidationError,
				)

	frappe.db.set_value("Supplier Quotation", quotation, _SQ_DEAL_FIELD, None)
	return {"quotation": quotation, "detached": True}
