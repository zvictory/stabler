"""CRM module API for Stabler — thin whitelisted wrappers over Frappe CRM doctypes."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from stabler.api._common import _assert_can_read, _assert_can_write, _require_company
from stabler.api.organization import (
	_ADMIN_ROLES,
	_can_access_module,
	_user_allowed_companies,
)
from stabler.api.tender_dimension import list_active_tenders, tender_enabled


def _require_crm():
	if not _can_access_module(frappe.session.user, "crm"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_crm_or_tender():
	"""Module gate for endpoints the TENDER flow shares with sales CRM.

	The tender intake drawer saves deals and both tender deal pickers search
	them through endpoints that used to sit behind the plain CRM gate; a
	tender-only tenant (enable_crm=0) would break its own intake. The gate
	accepts either module — company scoping below it is unchanged.
	"""
	if not (
		_can_access_module(frappe.session.user, "crm") or _can_access_module(frappe.session.user, "tender")
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_crm_company(company: str | None) -> str:
	"""Validate the caller's explicitly selected CRM company.

	CRM must never infer a company from user defaults or widen a query across a
	user's allowed companies.  The selected company is therefore both mandatory
	and checked against a non-admin user's explicit company allow-list.
	"""
	company = _require_company(company)
	if any(role in frappe.get_roles(frappe.session.user) for role in _ADMIN_ROLES):
		return company
	allowed = _user_allowed_companies(frappe.session.user)
	if allowed and company not in allowed:
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
	return company


def _assert_crm_record_company(doctype: str, name: str, company: str, ptype: str) -> None:
	"""Prevent named CRM reads/writes from crossing the selected company."""
	if not frappe.has_permission(doctype, ptype, name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if frappe.db.get_value(doctype, name, "company") != company:
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)


_LEAD_MUTABLE_FIELDS = frozenset(
	(
		"first_name",
		"last_name",
		"email",
		"mobile_no",
		"organization",
		"status",
		"lead_owner",
		"source",
		"job_title",
		"custom_manzil",
		"custom_sana",
		"custom_izoh",
	)
)

_DEAL_MUTABLE_FIELDS = frozenset(
	(
		"organization",
		"deal_owner",
		"deal_value",
		"currency",
		"probability",
		"expected_closure_date",
		"email",
		"mobile_no",
		"source",
		"outlet_type",
		"region",
		"expected_monthly_volume",
		"expected_cases_week",
		"price_tier",
		"needs_freezer",
		"credit_terms_days",
		"win_loss_reason",
		"tender_no",
		"tender_deadline",
		"bid_value",
		"tender_source",
		"deal_type",
		"next_action_type",
		"next_action_at",
		"next_action_owner",
		"forecast_category",
	)
)


def _mutable_payload(data: str | dict, fields: frozenset[str]) -> dict:
	"""Return only client-editable CRM fields; names, links, company and audit
	fields are always owned by the server."""
	payload = frappe.parse_json(data)
	return {field: payload[field] for field in fields if field in payload}


def _resolve_crm_organization(value: str | None) -> str:
	"""Resolve the SPA's free-text organization field to a CRM Organization link."""
	organization_name = str(value or "").strip()
	if not organization_name:
		return ""
	existing = frappe.db.exists("CRM Organization", {"organization_name": organization_name})
	if existing:
		return existing
	if not frappe.has_permission("CRM Organization", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	organization = frappe.new_doc("CRM Organization")
	organization.organization_name = organization_name
	organization.insert()
	return organization.name or organization_name


def _resolve_crm_source(value: str | None) -> str:
	"""Resolve the SPA's source field to a CRM Lead Source link, creating it if missing."""
	source_name = str(value or "").strip()
	if not source_name:
		return ""
	if frappe.db.exists("CRM Lead Source", source_name):
		return source_name
	if frappe.db.exists("DocType", "CRM Lead Source"):
		try:
			doc = frappe.new_doc("CRM Lead Source")
			doc.source_name = source_name
			doc.insert(ignore_permissions=True)
			return doc.name or source_name
		except Exception:
			pass
	return source_name


def _apply_tender_parent_link(updates: dict, company: str) -> None:
	"""Classify tender-form deals and bind an unambiguous matching master, creating one if missing."""
	deal_type = str(updates.get("deal_type") or "").strip()
	tender_no = str(updates.get("tender_no") or "").strip()
	if deal_type != "Tender" and not tender_no:
		return
	updates["deal_type"] = "Tender"
	if not tender_no:
		tender_no = f"TND-{now_datetime().year}-{frappe.generate_hash(length=6).upper()}"
		updates["tender_no"] = tender_no

	parents = frappe.get_list(
		"Tender Master",
		filters={"company": company, "tender_number": tender_no},
		fields=["name"],
		limit_page_length=2,
	)
	if len(parents) > 1:
		frappe.throw(_("Multiple Parent Tenders match tender number {0}.").format(tender_no), ValueError)
	if parents:
		updates["custom_parent_tender"] = parents[0]["name"]
	elif frappe.db.exists("DocType", "Tender Master"):
		master = frappe.new_doc("Tender Master")
		master.company = company
		master.tender_number = tender_no
		master.title = updates.get("title") or updates.get("organization") or tender_no
		master.buyer_name = updates.get("organization") or updates.get("buyer_name") or "Unknown Buyer"
		if updates.get("source"):
			master.source = updates["source"]
		master.insert(ignore_permissions=True)
		updates["custom_parent_tender"] = master.name
	else:
		updates["custom_parent_tender"] = ""


def _crm_list(
	doctype: str,
	*,
	company: str,
	fields: list[str],
	search: str,
	search_fields: list[str],
	status: str,
	owner: str,
	owner_field: str,
	page_length: int,
	start: int,
	extra_filters: dict | None = None,
) -> tuple[list, int]:
	"""Fetch one company through Frappe's permission-aware list API."""
	filters: dict = {"company": company}
	if status:
		filters["status"] = status
	if owner:
		filters[owner_field] = owner
	if extra_filters:
		filters.update(extra_filters)
	# ADR-609: "GENEL GİDER" is a ledger bucket wearing a CRM Deal, not a deal. On
	# the board it would sit in Qualification for ever and be counted in every
	# pipeline figure. Excluded unless the caller asked for a deal_type by name.
	# (v103 backfills NULL deal_type to Standard first — MariaDB's `!=` drops NULL
	# rows, so without it every pre-v60 deal would vanish from the board instead.)
	if doctype == "CRM Deal" and not filters.get("deal_type") and frappe.db.has_column(doctype, "deal_type"):
		filters["deal_type"] = ["!=", "Overhead"]
	or_filters = [[field, "like", f"%{search}%"] for field in search_fields] if search else None
	kwargs = {
		"filters": filters,
		"fields": fields,
		"order_by": "modified desc",
		"limit_page_length": min(max(int(page_length or 50), 1), 500),
		"start": max(int(start or 0), 0),
	}
	if or_filters:
		kwargs["or_filters"] = or_filters
	rows = frappe.get_list(doctype, **kwargs)
	# Counted by pulling names, not with `count(name) as total`: Frappe v16
	# rejects a SQL function in a string SELECT, so the aggregate form reads fine
	# locally and throws on the live site — it took the imports board down on msa
	# (0682569). Same filters as the page above, so the total stays truthful.
	count_kwargs: dict = {"filters": filters, "fields": ["name"], "limit_page_length": 0}
	if or_filters:
		count_kwargs["or_filters"] = or_filters
	total = len(frappe.get_list(doctype, **count_kwargs))
	return rows, total


_SI_AGGREGATORS = {
	"count": lambda rows, column: len(rows),
	"sum": lambda rows, column: sum(flt(r.get(column)) for r in rows),
	"min": lambda rows, column: min((r.get(column) for r in rows if r.get(column) is not None), default=None),
}


def _sales_invoice_aggregate_rows(
	company: str,
	customers: list[str],
	aggregates: list[tuple[str, str, str]],
	extra_filters: dict | None = None,
) -> list:
	"""Per-customer Sales Invoice aggregates, only over rows the caller may read.

	`aggregates` is a list of `(alias, op, column)` triples, not SQL strings:
	Frappe v16 rejects a SQL function inside a string SELECT, so
	`fields=["sum(outstanding_amount) as outstanding"]` reads fine locally and
	throws on the live site — that is what took the imports flow board down on msa
	(0682569). The columns are fetched plain and folded per customer here. Still
	ONE query for the whole cohort; never one per customer.
	"""
	if not customers:
		return []
	if not frappe.has_permission("Sales Invoice", "read"):
		return []
	filters = {"docstatus": 1, "company": company, "customer": ["in", customers]}
	if extra_filters:
		filters.update(extra_filters)
	columns = sorted({column for _alias, _op, column in aggregates})
	grouped: dict[str, list] = {}
	for row in frappe.get_list(
		"Sales Invoice",
		filters=filters,
		fields=["customer", *columns],
		limit_page_length=0,
	):
		grouped.setdefault(row["customer"], []).append(row)
	return [
		{
			"customer": customer,
			**{alias: _SI_AGGREGATORS[op](rows, column) for alias, op, column in aggregates},
		}
		for customer, rows in grouped.items()
	]


_CRM_MANAGER_ROLES = {"Sales Manager", "System Manager", "Stabler Admin"}


def _require_crm_manager():
	"""Pipeline config (create/edit/delete/reorder deal statuses) is manager-only."""
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & _CRM_MANAGER_ROLES):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_leads(company="", search="", status="", lead_owner="", page_length=50, start=0):
	_require_crm()
	company = _require_crm_company(company)
	if not frappe.has_permission("CRM Lead", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	rows, total = _crm_list(
		"CRM Lead",
		company=company,
		fields=[
			"name",
			"lead_name",
			"first_name",
			"last_name",
			"email",
			"mobile_no",
			"organization",
			"status",
			"lead_owner",
			"source",
			"modified",
		],
		search=search,
		search_fields=["lead_name", "email", "organization"],
		status=status,
		owner=lead_owner,
		owner_field="lead_owner",
		page_length=page_length,
		start=start,
	)
	return {"leads": rows, "total": total}


@frappe.whitelist()
def get_lead(name: str, company=""):
	_require_crm()
	company = _require_crm_company(company)
	_assert_crm_record_company("CRM Lead", name, company, "read")
	return frappe.get_doc("CRM Lead", name).as_dict()


@frappe.whitelist()
def save_lead(data: str | dict, company=""):
	_require_crm()
	company = _require_crm_company(company)
	payload = frappe.parse_json(data)
	if payload.get("name"):
		_assert_crm_record_company("CRM Lead", payload["name"], company, "write")
		doc = frappe.get_doc("CRM Lead", payload["name"])
	else:
		if not frappe.has_permission("CRM Lead", "create"):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		doc = frappe.new_doc("CRM Lead")
	updates = _mutable_payload(payload, _LEAD_MUTABLE_FIELDS)
	if updates.get("source"):
		updates["source"] = _resolve_crm_source(updates["source"])
	doc.update(updates)
	doc.company = company
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def delete_lead(name: str, company=""):
	_require_crm()
	company = _require_crm_company(company)
	_assert_crm_record_company("CRM Lead", name, company, "delete")
	frappe.delete_doc("CRM Lead", name)
	return "ok"


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------

#: The row shape every deal list returns. Named because the tender picker
#: (`active_tenders=1`) has to hand back the SAME shape from a different rule —
#: two field lists would let the two modes drift into two different rows.
_DEAL_LIST_FIELDS = [
	"name",
	"organization",
	"lead_name",
	"email",
	"mobile_no",
	"status",
	"deal_owner",
	"deal_value",
	"currency",
	"probability",
	"expected_closure_date",
	"modified",
	"outlet_type",
	"region",
	"expected_monthly_volume",
	"expected_cases_week",
	"price_tier",
	"needs_freezer",
	"credit_terms_days",
	"win_loss_reason",
	"linked_customer",
	"deal_type",
	"next_action_type",
	"next_action_at",
	"next_action_owner",
	"stage_entered_at",
	"won_at",
	"lost_at",
	"loss_reason",
	"forecast_category",
]


@frappe.whitelist()
def list_deals(
	company="",
	search="",
	status="",
	deal_owner="",
	deal_type="",
	page_length=50,
	start=0,
	active_tenders=0,
):
	"""The CRM board's deal list, and (with `active_tenders`) the tender picker's.

	`active_tenders=1` answers a different question from the board's: not "which
	deals exist" but "which values may a writer put on the ledger today" — the
	company's GENEL GİDER bucket first, then the tenders that can still receive
	cost. It therefore ignores `status`, `deal_type` and `deal_owner`, which are
	board filters, and it is gated on the tender MODULE as well as the CRM one.
	"""
	_require_crm_or_tender()
	company = _require_crm_company(company)
	if not frappe.has_permission("CRM Deal", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	# Imported here, not at module scope: the frappe-free suites stub `frappe.utils`
	# with only the names this module needs at IMPORT time, and a new top-level
	# import silently breaks every one of them (measured: 55 errors across two
	# modules). Same reason `crm.py` already imports its other utils in-function.
	from frappe.utils import cint

	if cint(active_tenders):
		if not tender_enabled(company):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		rows = list_active_tenders(company, _DEAL_LIST_FIELDS, search, page_length, start)
		return {"deals": rows, "total": len(rows)}
	extra_filters = {}
	if deal_type:
		extra_filters["deal_type"] = deal_type
	rows, total = _crm_list(
		"CRM Deal",
		company=company,
		fields=_DEAL_LIST_FIELDS,
		search=search,
		search_fields=["organization", "email", "lead_name"],
		status=status,
		owner=deal_owner,
		owner_field="deal_owner",
		page_length=page_length,
		start=start,
		extra_filters=extra_filters or None,
	)

	# Attach the linked customer's open AR so reps see exposure on the board.
	cust = list({r["linked_customer"] for r in rows if r.get("linked_customer")})
	ar: dict = {}
	if cust:
		for row in _sales_invoice_aggregate_rows(
			company,
			cust,
			[("outstanding", "sum", "outstanding_amount")],
			{"outstanding_amount": [">", 0]},
		):
			ar[row["customer"]] = flt(row.get("outstanding"))
	for r in rows:
		r["ar_outstanding"] = ar.get(r.get("linked_customer"), 0.0)

	return {"deals": rows, "total": total}


@frappe.whitelist()
def get_deal(name: str, company=""):
	# Same gate as `list_deals` and `save_deal` above and below it, for the reason
	# in `_require_crm_or_tender`'s docstring: a tender-only tenant (enable_crm=0)
	# that may list and overwrite a deal cannot coherently be denied reading one
	# back. `get_deal` was the odd one out, and on mikas — the only tenant with
	# tender on, crm off — it threw, leaving the PO form's tender picker showing a
	# raw deal id instead of a name. Company scoping below the gate is unchanged.
	_require_crm_or_tender()
	company = _require_crm_company(company)
	_assert_crm_record_company("CRM Deal", name, company, "read")
	return frappe.get_doc("CRM Deal", name).as_dict()


@frappe.whitelist()
def save_deal(data: str | dict, company=""):
	_require_crm_or_tender()
	company = _require_crm_company(company)
	payload = frappe.parse_json(data)
	requested_status = str(payload.get("status") or "").strip()
	is_existing = bool(payload.get("name"))
	updates = _mutable_payload(payload, _DEAL_MUTABLE_FIELDS)
	if "organization" in updates:
		updates["organization"] = _resolve_crm_organization(updates["organization"])
	if updates.get("source"):
		updates["source"] = _resolve_crm_source(updates["source"])
	_apply_tender_parent_link(updates, company)
	if is_existing and requested_status:
		return _transition_deal(
			payload["name"],
			requested_status,
			company,
			loss_reason=payload.get("loss_reason") or "",
			updates=updates,
		)
	if is_existing:
		_assert_crm_record_company("CRM Deal", payload["name"], company, "write")
		doc = frappe.get_doc("CRM Deal", payload["name"])
	else:
		if not frappe.has_permission("CRM Deal", "create"):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		doc = frappe.new_doc("CRM Deal")
	doc.update(updates)
	doc.company = company
	initial_transition_at = None
	initial_status_type = ""
	if not is_existing and requested_status:
		if not frappe.db.exists("CRM Deal Status", requested_status):
			frappe.throw(_("Please select a valid deal status."))
		initial_transition_at = now_datetime()
		initial_status_type = _deal_status_type(requested_status)
		_set_deal_outcome_fields(
			doc,
			requested_status,
			initial_status_type,
			initial_transition_at,
			payload.get("loss_reason") or "",
		)
	_assert_open_deal_hygiene(doc, requested_status or doc.get("status"))
	doc.save()
	if initial_transition_at:
		_insert_stage_event(
			doc.name,
			company,
			"",
			requested_status,
			initial_transition_at,
			loss_reason=(payload.get("loss_reason") or "") if initial_status_type == "lost" else "",
		)
	if requested_status and requested_status != doc.get("status"):
		return _transition_deal(
			doc.name,
			requested_status,
			company,
			loss_reason=payload.get("loss_reason") or "",
		)
	_maybe_convert_won_deal(doc, company)
	return doc.as_dict()


@frappe.whitelist()
def delete_deal(name: str, company=""):
	_require_crm_or_tender()
	company = _require_crm_company(company)
	_assert_crm_record_company("CRM Deal", name, company, "delete")
	frappe.delete_doc("CRM Deal", name)
	return "ok"


def clear_deal_stage_events(doc, method=None):
	"""Drop a deal's own stage history when the deal is trashed.

	`frappe.delete_doc` runs `on_trash` (delete_doc.py:165) BEFORE the link
	checks (delete_doc.py:172-173), so rows dropped here are never seen by
	`check_if_doc_is_linked`. Without this, any deal that was moved between
	lanes even once became undeletable — `CRM Stage Event` links the deal
	both via `deal` (reqd Link) and `reference_name` (Dynamic Link), and
	Stabler registers no `ignore_links_on_delete`.

	`CRM Stage Event` is an immutable audit log: its controller throws in
	`on_trash` (crm_stage_event.py:72), so `frappe.delete_doc` cannot be
	used and the rows are dropped directly. Same precedent:
	maintenance/seed_tender_demo.py:789-793.

	Only the deal's own history is cleared. `delete_deal` stays force-free,
	so a deal referenced by a Tender Sourcing Decision, quotation, RFQ or
	order is still refused by Frappe's link integrity — deliberate.
	"""
	frappe.db.delete("CRM Stage Event", {"deal": doc.name})


def clear_deal_automation_activities(doc, method=None):
	"""Drop the scheduler-written activities of a deal being trashed.

	`CRM Activity` links the deal only through the Dynamic Link pair
	(`reference_doctype` / `reference_name`), so it is caught one line later than
	a stage event — by `check_if_doc_is_dynamically_linked` (delete_doc.py:173)
	rather than `check_if_doc_is_linked` (:172). The static check raising first is
	why the production traceback named `CRM Stage Event` and never mentioned this.

	Left alone the blockade grows: `scheduled_daily_crm_automation` (hooks.py:97)
	writes a row per matching rule per day, so a deal becomes undeletable simply
	by getting old.

	Only the automation's own rows go. `create_crm_activity` (:650) is whitelisted
	— a rep's follow-up task lives in the same table, and a deal carrying one
	keeps refusing deletion, the same deliberate semantic as a Tender Sourcing
	Decision. `custom_rule_name` separates the two: only crm_automation.py:86
	writes it, and `_mutable_payload` admits no `custom_*` field, so it cannot be
	forged through the endpoint.

	As with `clear_deal_stage_events` the rows are dropped directly — `CRM
	Activity` is immutable and throws in its own `on_trash` (crm_activity.py:37).
	"""
	# A site that has not yet run `v72_crm_activity_automation_fields` has no such
	# column, and filtering on it would raise inside `on_trash` — breaking every
	# deal deletion on that site, a worse outage than the bug being fixed.
	if not frappe.db.has_column("CRM Activity", "custom_rule_name"):
		return

	frappe.db.delete(
		"CRM Activity",
		{
			"reference_doctype": "CRM Deal",
			"reference_name": doc.name,
			# `("is", "set")` compiles to `custom_rule_name != ''`
			# (operator_map.py:110-118). NULL does not satisfy that, so a row
			# without the marker is never matched — the safe direction for a
			# filter whose failure mode is deleting someone's work.
			"custom_rule_name": ("is", "set"),
		},
	)


_ACTIVITY_MUTABLE_FIELDS = frozenset(
	(
		"reference_doctype",
		"reference_name",
		"activity_type",
		"subject",
		"description",
		"due_at",
		"assigned_to",
	)
)
_ACTIVITY_REFERENCE_DOCTYPES = {"CRM Deal", "CRM Lead"}


def _deal_status_type(status: str) -> str:
	status_type = frappe.db.get_value("CRM Deal Status", status, "type")
	return str(status_type or status or "").strip().lower()


def _set_deal_outcome_fields(deal, status: str, status_type: str, changed_at, loss_reason: str) -> None:
	deal.status = status
	deal.stage_entered_at = changed_at
	if status_type == "won":
		deal.won_at = changed_at
		deal.lost_at = None
		deal.loss_reason = None
	elif status_type == "lost":
		deal.won_at = None
		deal.lost_at = changed_at
		deal.loss_reason = loss_reason
	else:
		deal.won_at = None
		deal.lost_at = None
		deal.loss_reason = None


def _insert_stage_event(
	name: str,
	company: str,
	from_stage: str,
	to_stage: str,
	changed_at,
	reason="",
	loss_reason="",
) -> None:
	event = frappe.new_doc("CRM Stage Event")
	event.update(
		{
			"company": company,
			"reference_doctype": "CRM Deal",
			# Bu fonksiyon STATÜ hattını kaydediyor. Tender kulvarı ayrı bir
			# eksen ve `api/tender.py:move_deal_stage` onu kendi sütunlarına
			# yazıyor — ikisi aynı logda ama aynı alanlarda değil.
			"axis": "status",
			"reference_name": name,
			"deal": name,
			"from_stage": from_stage,
			"to_stage": to_stage,
			"changed_at": changed_at,
			"changed_by": frappe.session.user,
			"reason": reason,
			"loss_reason": loss_reason,
		}
	)
	event.insert(ignore_permissions=True)


def _crm_hygiene_enforced() -> bool:
	value = frappe.db.get_single_value("Stabler Settings", "enforce_crm_next_action")
	return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _assert_open_deal_hygiene(deal, status: str | None) -> None:
	if not _crm_hygiene_enforced() or _deal_status_type(status or "") in {"won", "lost"}:
		return
	if not deal.get("deal_owner"):
		frappe.throw(_("An owner is required for an open deal."))
	if not deal.get("next_action_at"):
		frappe.throw(_("A dated next action is required for an open deal."))


def _maybe_convert_won_deal(deal, company: str) -> None:
	"""Preserve the existing best-effort Won handoff on every transition path."""
	try:
		if _is_won_status(deal.get("status")) and not deal.get("linked_customer"):
			convert_deal_to_customer(deal.name, company)
			deal.reload()
	except Exception:
		frappe.clear_last_message()


def validate_crm_deal_hygiene(doc, _method=None) -> None:
	"""Framework hook so REST, imports, and other direct writes share the invariant."""
	_assert_open_deal_hygiene(doc, doc.get("status"))


@frappe.whitelist()
def create_crm_activity(data: str | dict, company=""):
	_require_crm()
	company = _require_crm_company(company)
	payload = _mutable_payload(data, _ACTIVITY_MUTABLE_FIELDS)
	reference_doctype = payload.get("reference_doctype") or "CRM Deal"
	reference_name = payload.get("reference_name")
	if reference_doctype not in _ACTIVITY_REFERENCE_DOCTYPES or not reference_name:
		frappe.throw(_("A valid CRM reference is required."))
	_assert_crm_record_company(reference_doctype, reference_name, company, "read")
	if not frappe.has_permission("CRM Activity", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	activity = frappe.new_doc("CRM Activity")
	activity.update(payload)
	activity.reference_doctype = reference_doctype
	activity.company = company
	activity.created_by = frappe.session.user
	activity.status = "Planned"
	activity.insert()
	return activity.as_dict()


@frappe.whitelist()
def complete_crm_activity(name: str, company=""):
	_require_crm()
	company = _require_crm_company(company)
	_assert_crm_record_company("CRM Activity", name, company, "read")
	activity = frappe.get_doc("CRM Activity", name)
	_assert_crm_record_company(
		activity.reference_doctype,
		activity.reference_name,
		company,
		"write",
	)
	if activity.status == "Completed":
		return activity.as_dict()
	activity.status = "Completed"
	activity.completed_at = now_datetime()
	activity.completed_by = frappe.session.user
	previous_flag = getattr(frappe.flags, "crm_activity_completion", False)
	try:
		frappe.flags.crm_activity_completion = True
		activity.save(ignore_permissions=True)
	finally:
		frappe.flags.crm_activity_completion = previous_flag
	return activity.as_dict()


@frappe.whitelist()
def list_crm_activities(reference_doctype: str, reference_name: str, company=""):
	_require_crm()
	company = _require_crm_company(company)
	if reference_doctype not in _ACTIVITY_REFERENCE_DOCTYPES:
		frappe.throw(_("A valid CRM reference is required."))
	_assert_crm_record_company(reference_doctype, reference_name, company, "read")
	if not frappe.has_permission("CRM Activity", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_list(
		"CRM Activity",
		filters={
			"company": company,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		},
		fields=[
			"name",
			"activity_type",
			"subject",
			"description",
			"due_at",
			"assigned_to",
			"status",
			"completed_at",
			"completed_by",
			"created_by",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=500,
	)


@frappe.whitelist()
def transition_deal(
	name: str,
	status: str,
	company="",
	reason="",
	loss_reason="",
	next_action_type="",
	next_action_at=None,
	next_action_owner="",
):
	_require_crm()
	company = _require_crm_company(company)
	return _transition_deal(
		name,
		status,
		company,
		reason=reason,
		loss_reason=loss_reason,
		next_action_type=next_action_type,
		next_action_at=next_action_at,
		next_action_owner=next_action_owner,
	)


def _transition_deal(
	name: str,
	status: str,
	company: str,
	*,
	reason="",
	loss_reason="",
	next_action_type="",
	next_action_at=None,
	next_action_owner="",
	updates=None,
):
	deal = frappe.get_doc("CRM Deal", name, for_update=True)
	if not frappe.has_permission("CRM Deal", "write", doc=deal):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if deal.get("company") != company:
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
	if updates:
		deal.update(updates)
	old_status = deal.get("status") or ""
	status = str(status or "").strip()
	if not status:
		frappe.throw(_("Deal status is required."))
	if not frappe.db.exists("CRM Deal Status", status):
		frappe.throw(_("Please select a valid deal status."))
	if status == old_status:
		_assert_open_deal_hygiene(deal, status)
		if updates:
			deal.save()
		_maybe_convert_won_deal(deal, company)
		return deal.as_dict()

	status_type = _deal_status_type(status)
	changed_at = now_datetime()
	if next_action_type:
		deal.next_action_type = next_action_type
	if next_action_at:
		deal.next_action_at = next_action_at
	if next_action_owner:
		deal.next_action_owner = next_action_owner
	_set_deal_outcome_fields(deal, status, status_type, changed_at, loss_reason)
	_assert_open_deal_hygiene(deal, status)
	deal.save()

	_insert_stage_event(
		name,
		company,
		old_status,
		status,
		changed_at,
		reason,
		loss_reason if status_type == "lost" else "",
	)
	_maybe_convert_won_deal(deal, company)
	return deal.as_dict()


# ---------------------------------------------------------------------------
# Won-deal hand-off: CRM Deal -> Customer (+ best-effort SFA Outlet, freezer task)
# ---------------------------------------------------------------------------


def _is_won_status(status: str | None) -> bool:
	if not status:
		return False
	if str(status).strip().lower() == "won":
		return True
	return (frappe.db.get_value("CRM Deal Status", status, "type") or "").strip().lower() == "won"


# Deal outlet_type -> SFA Outlet channel.
_OUTLET_CHANNEL = {
	"Supermarket": "Modern Trade",
	"Shop": "Traditional Trade",
	"Kiosk": "Traditional Trade",
	"HoReCa": "HoReCa",
	"Distributor": "Other",
	"Wholesaler": "Other",
}


def _ensure_outlet(deal, customer: str) -> str | None:
	"""Best-effort: mirror the won customer as an SFA Outlet and assign the rep
	(deal owner → Outlet.assigned_field_user, which carries their route via the
	Field User's default_route). Never raises."""
	if not frappe.db.exists("DocType", "Outlet"):
		return None

	owner = deal.get("deal_owner")
	rep = owner if (owner and frappe.db.exists("User", owner)) else None

	existing = frappe.db.get_value("Outlet", {"customer": customer}, "name")
	if existing:
		# Backfill the rep if the outlet has none yet.
		if rep and not frappe.db.get_value("Outlet", existing, "assigned_field_user"):
			try:
				frappe.db.set_value("Outlet", existing, "assigned_field_user", rep)
			except Exception:
				frappe.clear_last_message()
		return existing

	company = deal.get("company")
	if not company:
		return None

	base = {
		"doctype": "Outlet",
		"outlet_code": "O-" + frappe.generate_hash(length=6).upper(),
		"outlet_name": deal.get("organization") or deal.get("lead_name") or customer,
		"company": company,
		"customer": customer,
		"is_active": 1,
	}
	if rep:
		base["assigned_field_user"] = rep
	channel = _OUTLET_CHANNEL.get(deal.get("outlet_type") or "")
	if channel:
		base["channel"] = channel

	try:
		doc = frappe.get_doc(base)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		frappe.clear_last_message()
		# Retry with only the mandatory fields if an optional link/select was rejected.
		try:
			doc = frappe.get_doc(
				{
					k: base[k]
					for k in ("doctype", "outlet_code", "outlet_name", "company", "customer", "is_active")
				}
			)
			doc.insert(ignore_permissions=True)
			return doc.name
		except Exception:
			frappe.clear_last_message()
			return None


def _freezer_todo(deal, customer: str) -> None:
	"""Best-effort freezer-placement reminder for the deal owner. Never raises."""
	try:
		td = frappe.new_doc("ToDo")
		td.description = _("Place branded freezer at {0} (deal {1})").format(
			deal.get("organization") or customer, deal.name
		)
		if deal.get("deal_owner") and frappe.db.exists("User", deal.deal_owner):
			td.allocated_to = deal.deal_owner
		td.reference_type = "Customer"
		td.reference_name = customer
		td.insert(ignore_permissions=True)
	except Exception:
		frappe.clear_last_message()


@frappe.whitelist()
def convert_deal_to_customer(name: str, company="") -> dict:
	"""Create (or link) a Customer from a Won deal and wire up the outlet/freezer.
	Idempotent: re-running returns the already-linked customer."""
	_require_crm()
	company = _require_crm_company(company)
	_assert_crm_record_company("CRM Deal", name, company, "write")
	deal = frappe.get_doc("CRM Deal", name)

	if deal.get("linked_customer") and frappe.db.exists("Customer", deal.linked_customer):
		return {"customer": deal.linked_customer, "created": False}

	cust_name = (deal.get("organization") or deal.get("lead_name") or "").strip()
	if not cust_name:
		frappe.throw(_("Deal has no organization or name to create a customer from."))

	existing = frappe.db.get_value("Customer", {"customer_name": cust_name}, "name")
	if existing:
		customer = existing
		created = False
	else:
		doc = frappe.new_doc("Customer")
		doc.customer_name = cust_name
		doc.customer_type = "Company"
		doc.customer_group = (
			frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
		)
		region = deal.get("region")
		doc.territory = (
			region
			if region and frappe.db.exists("Territory", region)
			else frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
		)
		if deal.get("email"):
			doc.email_id = deal.email
		if deal.get("mobile_no"):
			doc.mobile_no = deal.mobile_no
		doc.insert(ignore_permissions=True)
		customer = doc.name
		created = True

	deal.db_set("linked_customer", customer)
	outlet = _ensure_outlet(deal, customer)
	if deal.get("needs_freezer"):
		_freezer_todo(deal, customer)
	return {"customer": customer, "created": created, "outlet": outlet}


# ---------------------------------------------------------------------------
# Metadata (dropdown options for forms)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def crm_meta(company=""):
	_require_crm()
	_require_crm_company(company)
	return {
		"lead_statuses": frappe.get_all(
			"CRM Lead Status",
			fields=["name", "color", "position", "type"],
			order_by="position asc",
		),
		"deal_statuses": frappe.get_all(
			"CRM Deal Status",
			fields=["name", "color", "position", "type"],
			order_by="position asc",
		),
		"sources": frappe.get_all("CRM Lead Source", pluck="name", order_by="name"),
		"industries": frappe.get_all("CRM Industry", pluck="name", order_by="name"),
		# FMCG (ice-cream) deal field options — kept in sync with patch v18.
		"outlet_types": ["Shop", "Supermarket", "Kiosk", "HoReCa", "Distributor", "Wholesaler"],
		"price_tiers": ["Wholesale", "Retail", "HoReCa"],
		"win_loss_reasons": [
			"No freezer space",
			"Competitor exclusivity",
			"Credit terms",
			"Price",
			"Quality",
			"Other",
		],
	}


@frappe.whitelist()
def crm_metrics(company="") -> dict:
	"""Pipeline KPIs for the ice-cream board: monthly run-rate of open deals,
	wins this month, freezer-pending outlets, reactivation count, activation rate."""
	_require_crm()
	company = _require_crm_company(company)
	from frappe.utils import get_first_day, getdate, nowdate

	statuses = frappe.get_all("CRM Deal Status", fields=["name", "type"])
	won = {s.name for s in statuses if (s.type or "").lower() == "won"} | {"Won"}
	lost = {s.name for s in statuses if (s.type or "").lower() == "lost"} | {"Lost"}

	deal_filters: dict = {"company": company}

	deals = frappe.get_list(
		"CRM Deal",
		filters=deal_filters,
		fields=["status", "expected_monthly_volume", "deal_value", "needs_freezer", "modified"],
		limit_page_length=0,
	)
	month_start = getdate(get_first_day(nowdate()))
	open_rr = won_rr = 0.0
	won_total = won_month = freezer_open = reactivation = 0
	for d in deals:
		vol = flt(d.expected_monthly_volume or d.deal_value or 0)
		st = d.status or ""
		if st in won:
			won_total += 1
			won_rr += vol
			if d.modified and getdate(d.modified) >= month_start:
				won_month += 1
		elif st not in lost:
			open_rr += vol
			if d.needs_freezer:
				freezer_open += 1
		if st == "Reactivation":
			reactivation += 1

	total = len(deals)
	return {
		"open_run_rate": open_rr,
		"won_run_rate": won_rr,
		"won_total": won_total,
		"won_this_month": won_month,
		"freezer_open": freezer_open,
		"reactivation": reactivation,
		"deal_count": total,
		"activation_rate": round((won_total / total) * 100, 1) if total else 0,
	}


@frappe.whitelist()
def crm_analytics(company="") -> dict:
	"""Deeper acquisition KPIs from won deals × their sales: time-to-first-order,
	reorder rate, avg orders, lifetime sales, new outlets this month, freezer ROI.
	Built in ~4 batched queries."""
	_require_crm()
	company = _require_crm_company(company)
	from frappe.utils import get_first_day, getdate, nowdate

	deal_filters: dict = {"linked_customer": ["is", "set"], "company": company}

	deals = frappe.get_list(
		"CRM Deal",
		filters=deal_filters,
		fields=["linked_customer", "freezer_asset"],
		limit_page_length=0,
	)
	customers = list({d.linked_customer for d in deals if d.linked_customer})
	empty = {
		"won_customers": 0,
		"with_orders": 0,
		"avg_time_to_first_order_days": None,
		"reorder_rate": 0,
		"avg_orders_per_customer": 0,
		"lifetime_sales": 0.0,
		"new_outlets_this_month": 0,
		"freezer_cost": 0.0,
		"freezer_sales": 0.0,
		"freezer_roi": None,
	}
	if not customers:
		return empty

	inv = {
		row["customer"]: {
			"count": int(row.get("invoice_count") or 0),
			"first": row.get("first_invoice_date"),
			"total": flt(row.get("lifetime_sales")),
		}
		for row in _sales_invoice_aggregate_rows(
			company,
			customers,
			[
				("invoice_count", "count", "name"),
				("first_invoice_date", "min", "posting_date"),
				("lifetime_sales", "sum", "base_grand_total"),
			],
		)
	}

	created = {
		r.name: r.creation
		for r in frappe.get_list(
			"Customer", filters={"name": ["in", customers]}, fields=["name", "creation"], limit_page_length=0
		)
	}
	asset_ids = [d.freezer_asset for d in deals if d.freezer_asset]
	asset_cost = {}
	if asset_ids and frappe.db.exists("DocType", "Asset"):
		for r in frappe.get_list(
			"Asset",
			filters={"name": ["in", asset_ids]},
			fields=["name", "gross_purchase_amount"],
			limit_page_length=0,
		):
			asset_cost[r.name] = flt(r.gross_purchase_amount)

	ttfo = []
	with_orders = reorder = total_orders = 0
	lifetime = 0.0
	for c in customers:
		i = inv.get(c)
		if not i:
			continue
		with_orders += 1
		total_orders += i["count"]
		lifetime += i["total"]
		if i["count"] >= 2:
			reorder += 1
		cr = created.get(c)
		if cr and i["first"]:
			days = (getdate(i["first"]) - getdate(cr)).days
			if days >= 0:
				ttfo.append(days)

	month_start = getdate(get_first_day(nowdate()))
	new_month = sum(1 for c in customers if created.get(c) and getdate(created[c]) >= month_start)

	fz_cost = fz_sales = 0.0
	for d in deals:
		if d.freezer_asset in asset_cost:
			fz_cost += asset_cost[d.freezer_asset]
			i = inv.get(d.linked_customer)
			if i:
				fz_sales += i["total"]

	return {
		"won_customers": len(customers),
		"with_orders": with_orders,
		"avg_time_to_first_order_days": round(sum(ttfo) / len(ttfo), 1) if ttfo else None,
		"reorder_rate": round(reorder / with_orders * 100, 1) if with_orders else 0,
		"avg_orders_per_customer": round(total_orders / with_orders, 1) if with_orders else 0,
		"lifetime_sales": lifetime,
		"new_outlets_this_month": new_month,
		"freezer_cost": fz_cost,
		"freezer_sales": fz_sales,
		"freezer_roi": round(fz_sales / fz_cost, 2) if fz_cost else None,
	}


@frappe.whitelist()
def crm_report(from_date: str, to_date: str, company="") -> dict:
	"""Cohort acquisition report: outlets won (customer created) in [from,to],
	broken down by rep (deal owner) and region, each with new outlets, monthly
	run-rate, cohort sales, reorder rate, avg time-to-first-order, freezer ROI."""
	_require_crm()
	company = _require_crm_company(company)
	from collections import defaultdict

	from frappe.utils import getdate

	fd, td = getdate(from_date), getdate(to_date)
	empty = {
		"outlets": 0,
		"run_rate": 0.0,
		"sales": 0.0,
		"reorder_rate": 0,
		"avg_ttfo": None,
		"freezer_roi": None,
		"new_outlets": 0,
	}

	deal_filters: dict = {"linked_customer": ["is", "set"], "company": company}

	deals = frappe.get_list(
		"CRM Deal",
		filters=deal_filters,
		fields=[
			"linked_customer",
			"deal_owner",
			"region",
			"expected_monthly_volume",
			"deal_value",
			"freezer_asset",
		],
		limit_page_length=0,
	)
	cust_all = list({d.linked_customer for d in deals if d.linked_customer})
	if not cust_all:
		return {"summary": empty, "by_rep": [], "by_region": []}

	created = {
		r.name: r.creation
		for r in frappe.get_list(
			"Customer", filters={"name": ["in", cust_all]}, fields=["name", "creation"], limit_page_length=0
		)
	}
	cohort = {c for c in cust_all if created.get(c) and fd <= getdate(created[c]) <= td}
	cohort_deals = [d for d in deals if d.linked_customer in cohort]
	if not cohort:
		return {"summary": empty, "by_rep": [], "by_region": []}

	inv = {
		row["customer"]: {
			"count": int(row.get("invoice_count") or 0),
			"first": row.get("first_invoice_date"),
			"total": flt(row.get("lifetime_sales")),
		}
		for row in _sales_invoice_aggregate_rows(
			company,
			list(cohort),
			[
				("invoice_count", "count", "name"),
				("first_invoice_date", "min", "posting_date"),
				("lifetime_sales", "sum", "base_grand_total"),
			],
		)
	}

	asset_ids = [d.freezer_asset for d in cohort_deals if d.freezer_asset]
	asset_cost = {}
	if asset_ids and frappe.db.exists("DocType", "Asset"):
		for r in frappe.get_list(
			"Asset",
			filters={"name": ["in", asset_ids]},
			fields=["name", "gross_purchase_amount"],
			limit_page_length=0,
		):
			asset_cost[r.name] = flt(r.gross_purchase_amount)

	def agg(rows: list) -> dict:
		run = sales = fzc = fzs = 0.0
		reorder = with_orders = 0
		ttfo = []
		for d in rows:
			run += flt(d.expected_monthly_volume or d.deal_value or 0)
			i = inv.get(d.linked_customer)
			if i:
				with_orders += 1
				sales += i["total"]
				if i["count"] >= 2:
					reorder += 1
				cr = created.get(d.linked_customer)
				if cr and i["first"]:
					days = (getdate(i["first"]) - getdate(cr)).days
					if days >= 0:
						ttfo.append(days)
			if d.freezer_asset in asset_cost:
				fzc += asset_cost[d.freezer_asset]
				if i:
					fzs += i["total"]
		return {
			"outlets": len(rows),
			"run_rate": run,
			"sales": sales,
			"reorder_rate": round(reorder / with_orders * 100, 1) if with_orders else 0,
			"avg_ttfo": round(sum(ttfo) / len(ttfo), 1) if ttfo else None,
			"freezer_roi": round(fzs / fzc, 2) if fzc else None,
		}

	by_rep_map: dict = defaultdict(list)
	by_region_map: dict = defaultdict(list)
	for d in cohort_deals:
		by_rep_map[d.deal_owner or "—"].append(d)
		by_region_map[d.region or "—"].append(d)
	by_rep = sorted(({"key": k, **agg(v)} for k, v in by_rep_map.items()), key=lambda x: -x["sales"])
	by_region = sorted(({"key": k, **agg(v)} for k, v in by_region_map.items()), key=lambda x: -x["sales"])

	summary = agg(cohort_deals)
	summary["new_outlets"] = len(cohort)
	return {"summary": summary, "by_rep": by_rep, "by_region": by_region}


# ---------------------------------------------------------------------------
# Deal status (Kanban column) management
# ---------------------------------------------------------------------------


def _status_name_fields() -> list[str]:
	"""Fieldname(s) Frappe CRM names a CRM Deal Status from (label 'Status').
	We set every required Data field to the status name so insert never fails
	with 'Status is required', regardless of the exact field name."""
	return [
		f.fieldname
		for f in frappe.get_meta("CRM Deal Status").fields
		if f.fieldtype == "Data" and (f.reqd or f.fieldname in ("status", "deal_status", "title"))
	]


def _insert_deal_status(name: str, color=None, position=None, type_=None):
	doc = frappe.new_doc("CRM Deal Status")
	doc.name = name
	for fn in _status_name_fields():
		doc.set(fn, name)
	if color is not None:
		doc.color = color
	if position is not None:
		doc.position = position
	if type_:
		try:
			doc.type = type_
		except Exception:
			frappe.clear_last_message()
	doc.insert(ignore_permissions=True)
	return doc


@frappe.whitelist()
def save_deal_status(data):
	"""Upsert a CRM Deal Status. data = JSON {name, color, position, type}."""
	_require_crm_manager()
	d = json.loads(data) if isinstance(data, str) else data
	name = (d.get("name") or "").strip()
	if not name:
		frappe.throw(_("Status name is required"))

	if frappe.db.exists("CRM Deal Status", name):
		doc = frappe.get_doc("CRM Deal Status", name)
		for k in ("color", "position", "type"):
			if k in d:
				doc.set(k, d[k])
		doc.save(ignore_permissions=True)
	else:
		doc = _insert_deal_status(name, d.get("color"), d.get("position"), d.get("type"))

	return {
		"name": doc.name,
		"color": doc.get("color"),
		"position": doc.get("position"),
		"type": doc.get("type"),
	}


@frappe.whitelist()
def rename_deal_status(old_name: str, new_name: str):
	"""Rename a kanban column and let Frappe rewrite every Link value."""
	_assert_can_write("CRM Deal Status", old_name, "delete")
	_require_crm_manager()
	old_name = (old_name or "").strip()
	new_name = (new_name or "").strip()
	if not new_name:
		frappe.throw(_("Status name is required"))
	if old_name == new_name:
		return {"name": new_name}
	if not frappe.db.exists("CRM Deal Status", old_name):
		frappe.throw(_("Status not found"))
	if frappe.db.exists("CRM Deal Status", new_name):
		frappe.throw(_("A status with that name already exists."))

	frappe.rename_doc(
		"CRM Deal Status",
		old_name,
		new_name,
		force=True,
		show_alert=False,
		rebuild_search=False,
	)
	return {"name": new_name}


@frappe.whitelist()
def delete_deal_status(name):
	"""Delete a CRM Deal Status. Blocked if any deal is in that status."""
	_assert_can_write("CRM Deal Status", name, "delete")
	_require_crm_manager()
	count = frappe.db.count("CRM Deal", {"status": name})
	if count:
		frappe.throw(_("Cannot delete: {0} deal(s) are still in this status.").format(count))
	frappe.delete_doc("CRM Deal Status", name, ignore_permissions=True)
	return "ok"


@frappe.whitelist()
def reorder_deal_statuses(names):
	"""Bulk-update column positions. names = JSON array in desired display order."""
	_require_crm_manager()
	order = json.loads(names) if isinstance(names, str) else names
	for i, name in enumerate(order):
		frappe.db.set_value("CRM Deal Status", name, "position", i + 1, update_modified=False)
	return "ok"
