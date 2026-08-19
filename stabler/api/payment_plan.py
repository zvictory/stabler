"""Payment calendar API — everyone's own plan, and one authorised view across all of them.

Two things are decided here and nowhere else, so both are pure functions with
their own tests: `visibility_filter` (whose rows a caller may see) and
`clean_payload` (which fields a caller may write). Everything else is query
plumbing around them.

The module posts nothing. A plan row is a forecast; money leaves through
Payments / Kassa / Journal and a row is closed by hand, so there is no Payment
Entry anywhere in this file and a test asserts that absence.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from stabler.api._common import _assert_can_read, _assert_can_write, _require_company
from stabler.api.organization import _ADMIN_ROLES, _can_access_module, _user_allowed_companies

DOCTYPE = "Payment Plan Entry"
MODULE_KEY = "payment_calendar"
MANAGER_ROLE = "Payment Plan Manager"

# What a client may send. A whitelist, not a blocklist: every field added to the
# doctype later would otherwise become client-writable the moment it exists.
# `direction`, `base_amount` and `party_name` are computed on validate, and
# `owner_user` / `company` are set from the session and the request — none of
# them are ever copied off a payload.
WRITABLE_FIELDS = (
	"kind",
	"due_date",
	"party_type",
	"party",
	"reference_doctype",
	"reference_name",
	"expense_account",
	"item_code",
	"qty",
	"rate",
	"currency",
	"amount",
	"exchange_rate",
	"confidence",
	"status",
	"realized_on",
	"note",
)

LIST_FIELDS = (
	"name",
	"owner_user",
	"kind",
	"direction",
	"due_date",
	"party_type",
	"party",
	"party_name",
	"reference_doctype",
	"reference_name",
	"expense_account",
	"item_code",
	"qty",
	"rate",
	"currency",
	"amount",
	"exchange_rate",
	"base_amount",
	"confidence",
	"status",
	"realized_on",
	"note",
	"modified",
)

# Where the smart form reads an amount and a date from, per document. Keyed by
# the same closed set the controller enforces — a doctype missing here cannot be
# looked up even if someone widens the controller's tuple.
_REFERENCE_MAP = {
	"Sales Invoice": {
		"party_type": "Customer",
		"party": "customer",
		"amount": "outstanding_amount",
		"date": "due_date",
	},
	"Purchase Invoice": {
		"party_type": "Supplier",
		"party": "supplier",
		"amount": "outstanding_amount",
		"date": "due_date",
	},
	"Sales Order": {
		"party_type": "Customer",
		"party": "customer",
		"amount": "grand_total",
		"paid": "advance_paid",
		"date": "delivery_date",
	},
	"Purchase Order": {
		"party_type": "Supplier",
		"party": "supplier",
		"amount": "grand_total",
		"paid": "advance_paid",
		"date": "schedule_date",
	},
	"Proforma Invoice": {
		"party_type": "Supplier",
		"party": "supplier",
		"amount": "grand_total",
		"date": "expected_payment_date",
	},
}


def _require_payment_calendar() -> None:
	"""@frappe.whitelist() gates method access only — any logged-in user on any
	tenant can call these, so the module gate lives inside every endpoint."""
	if not _can_access_module(frappe.session.user, MODULE_KEY):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_plan_company(company: str | None) -> str:
	"""An explicit company, checked against the caller's allow-list.

	Never inferred from user defaults: on a multi-company site that would read
	another tenant's forecast whenever the default drifted from the SPA's
	active company.
	"""
	company = _require_company(company)
	roles = frappe.get_roles(frappe.session.user)
	if any(role in roles for role in _ADMIN_ROLES):
		return company
	allowed = _user_allowed_companies(frappe.session.user)
	if allowed and company not in allowed:
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
	return company


def is_plan_manager(roles) -> bool:
	roles = tuple(roles or ())
	return MANAGER_ROLE in roles or any(role in roles for role in _ADMIN_ROLES)


def _require_plan_manager() -> None:
	"""Holding the module is not enough for the cross-user aggregate — a
	Payment Plan User holds it and must still not read everyone's totals."""
	if not is_plan_manager(frappe.get_roles(frappe.session.user)):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def visibility_filter(user: str, roles, owner_user: str | None = None) -> dict:
	"""Whose rows the caller may see. The module's whole confidentiality model.

	A plain user is pinned to their own rows regardless of what the request
	asked for — if a parameter could widen this, any Payment Plan User would
	read the director's forecast. A manager sees everyone, and may narrow to one
	planner because drilling into a name is the point of the totals view.
	"""
	if not is_plan_manager(roles):
		return {"owner_user": user}
	owner_user = (owner_user or "").strip()
	return {"owner_user": owner_user} if owner_user else {}


def clean_payload(payload) -> dict:
	"""Keep only what a client may write.

	`read_only` in a DocType JSON is a form hint, not a write guard: copying a
	payload wholesale onto the doc writes `base_amount` straight into the number
	a director reads as a total.
	"""
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid payload."))
	return {key: payload[key] for key in WRITABLE_FIELDS if key in payload}


def _date_range(filters: dict, from_date, to_date) -> dict:
	if from_date and to_date:
		filters["due_date"] = ["between", [from_date, to_date]]
	elif from_date:
		filters["due_date"] = [">=", from_date]
	elif to_date:
		filters["due_date"] = ["<=", to_date]
	return filters


def _list_filters(company, from_date, to_date, owner_user, status, kind, confidence) -> dict:
	filters = {"company": company}
	filters.update(visibility_filter(frappe.session.user, frappe.get_roles(frappe.session.user), owner_user))
	_date_range(filters, from_date, to_date)
	for field, value in (("status", status), ("kind", kind), ("confidence", confidence)):
		if value:
			filters[field] = value
	return filters


@frappe.whitelist()
def payment_plan_list(
	company: str,
	from_date=None,
	to_date=None,
	owner_user=None,
	status=None,
	kind=None,
	confidence=None,
	limit=500,
):
	"""The rows themselves, for the calendar and the list beneath it."""
	_require_payment_calendar()
	company = _require_plan_company(company)
	return frappe.get_all(
		DOCTYPE,
		filters=_list_filters(company, from_date, to_date, owner_user, status, kind, confidence),
		fields=list(LIST_FIELDS),
		order_by="due_date asc, modified desc",
		limit_page_length=min(cint(limit) or 500, 2000),
	)


@frappe.whitelist()
def payment_plan_calendar(company: str, from_date: str, to_date: str, owner_user=None, confidence=None):
	"""One bucket per day: in, out, and how many rows.

	Aggregated in SQL over the stored `base_amount` — the reason that column is
	stored rather than converted at read time is exactly this query.
	"""
	_require_payment_calendar()
	company = _require_plan_company(company)
	filters = _list_filters(company, from_date, to_date, owner_user, None, None, confidence)
	# Cancelled rows are history, not forecast; they would inflate every day.
	filters["status"] = ["!=", "Cancelled"]
	rows = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=["due_date", "direction", "count(name) as entries", "sum(base_amount) as total"],
		group_by="due_date, direction",
		order_by="due_date asc",
	)
	days: dict[str, dict] = {}
	for row in rows:
		key = str(row["due_date"])
		day = days.setdefault(key, {"due_date": key, "inflow": 0.0, "outflow": 0.0, "entries": 0})
		day["inflow" if row["direction"] == "In" else "outflow"] += flt(row["total"])
		day["entries"] += cint(row["entries"])
	return list(days.values())


@frappe.whitelist()
def payment_plan_totals(company: str, from_date: str, to_date: str):
	"""What a director reads: the period's net, split by confidence and by planner.

	Manager-only. The module gate is not sufficient here — a Payment Plan User
	holds the module and must not see anyone else's numbers.
	"""
	_require_payment_calendar()
	_require_plan_manager()
	company = _require_plan_company(company)
	filters = _date_range({"company": company, "status": ["!=", "Cancelled"]}, from_date, to_date)

	def _grouped(axis: str) -> list[dict]:
		rows = frappe.get_all(
			DOCTYPE,
			filters=filters,
			fields=[axis, "direction", "sum(base_amount) as total", "count(name) as entries"],
			group_by=f"{axis}, direction",
		)
		out: dict[str, dict] = {}
		for row in rows:
			key = row[axis] or ""
			bucket = out.setdefault(key, {axis: key, "inflow": 0.0, "outflow": 0.0, "entries": 0})
			bucket["inflow" if row["direction"] == "In" else "outflow"] += flt(row["total"])
			bucket["entries"] += cint(row["entries"])
		return list(out.values())

	by_confidence = _grouped("confidence")
	inflow = sum(b["inflow"] for b in by_confidence)
	outflow = sum(b["outflow"] for b in by_confidence)
	return {
		"inflow": inflow,
		"outflow": outflow,
		"net": inflow - outflow,
		"by_confidence": by_confidence,
		"by_planner": _grouped("owner_user"),
		"by_kind": _grouped("kind"),
	}


@frappe.whitelist()
def save_payment_plan_entry(company: str, payload, name=None):
	"""Create or update one plan row.

	`owner_user` is never read off the payload: on create it is the session, and
	on update it is left alone, so a row cannot be handed to someone else or
	claimed from them through the form.
	"""
	_require_payment_calendar()
	company = _require_plan_company(company)
	values = clean_payload(payload)

	if name:
		_assert_can_write(DOCTYPE, name)
		doc = frappe.get_doc(DOCTYPE, name)
		if doc.company != company:
			frappe.throw(_("This plan belongs to another company."), frappe.PermissionError)
		if (
			not is_plan_manager(frappe.get_roles(frappe.session.user))
			and doc.owner_user != frappe.session.user
		):
			frappe.throw(_("You can only change your own plan."), frappe.PermissionError)
	else:
		doc = frappe.new_doc(DOCTYPE)
		doc.company = company
		doc.owner_user = frappe.session.user

	for field, value in values.items():
		setattr(doc, field, value)
	doc.party_name = _party_name(doc.party_type, doc.party)
	doc.save()
	return doc.name


def _party_name(party_type, party) -> str:
	if not party_type or not party:
		return ""
	field = {"Customer": "customer_name", "Supplier": "supplier_name", "Employee": "employee_name"}.get(
		party_type
	)
	if not field:
		return ""
	return frappe.db.get_value(party_type, party, field) or ""


@frappe.whitelist()
def delete_payment_plan_entry(company: str, name: str):
	"""Remove a plan row. Nothing was posted from it, so nothing is reversed."""
	_require_payment_calendar()
	company = _require_plan_company(company)
	_assert_can_write(DOCTYPE, name, ptype="delete")
	owner, doc_company = frappe.db.get_value(DOCTYPE, name, ["owner_user", "company"]) or (None, None)
	if doc_company != company:
		frappe.throw(_("This plan belongs to another company."), frappe.PermissionError)
	if not is_plan_manager(frappe.get_roles(frappe.session.user)) and owner != frappe.session.user:
		frappe.throw(_("You can only delete your own plan."), frappe.PermissionError)
	frappe.delete_doc(DOCTYPE, name)
	return {"ok": True}


@frappe.whitelist()
def payment_plan_document_options(company: str, reference_doctype: str, search=None, limit=20):
	"""Documents the form may link a plan row to, newest first.

	This is what makes the form smart: pick the invoice and the amount, the due
	date and the party come off the real record instead of being retyped.
	"""
	_require_payment_calendar()
	company = _require_plan_company(company)
	spec = _REFERENCE_MAP.get(reference_doctype)
	if not spec:
		frappe.throw(_("A payment plan cannot be linked to {0}.").format(reference_doctype or "-"))

	fields = ["name", spec["party"], "currency", spec["amount"], spec["date"]]
	if spec.get("paid"):
		fields.append(spec["paid"])
	filters = {"company": company, "docstatus": ["<", 2]}
	if search:
		filters["name"] = ["like", f"%{search}%"]

	rows = frappe.get_all(
		reference_doctype,
		filters=filters,
		fields=fields,
		order_by="modified desc",
		limit_page_length=min(cint(limit) or 20, 100),
	)
	out = []
	for row in rows:
		outstanding = flt(row.get(spec["amount"])) - flt(row.get(spec.get("paid") or ""))
		out.append(
			{
				"name": row["name"],
				"party_type": spec["party_type"],
				"party": row.get(spec["party"]),
				"currency": row.get("currency"),
				"amount": outstanding,
				"due_date": row.get(spec["date"]),
			}
		)
	return out


@frappe.whitelist()
def payment_plan_reference_doctypes(company: str):
	"""The closed set the form's document-type picker offers."""
	_require_payment_calendar()
	_require_plan_company(company)
	return list(_REFERENCE_MAP)
