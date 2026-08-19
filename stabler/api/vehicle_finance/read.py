"""Vehicle Finance Center — read/query API surface (Phase 2.5, stabler-l0m.7).

Split from v1.py (which owns the write/action surface and is already 1000+
lines) so the Phase 3 UI screens have a place to read from. Same gate order
as v1.py on every endpoint: company -> tenant scope -> module -> engine ->
capability -> document permission. Currency amounts are never summed across
currencies — every `totals_by_currency` value is a dict keyed by currency.
Every derived number (outstanding, paid, schedule total) is recomputed from
stored documents here, never trusted from the caller.
"""

from __future__ import annotations

from itertools import pairwise

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from stabler.api._common import _assert_can_read, _assert_can_write, _require_company
from stabler.api.approvals import _assert_company_scope
from stabler.api.vehicle_finance import chain
from stabler.api.vehicle_finance.permissions import (
	_ADMIN_ROLES,
	CAPABILITY_ROLES,
	_assert_capability,
	_require_agreement_v1,
)
from stabler.api.vehicle_finance.schedule import build_schedule
from stabler.api.vehicle_finance.v1 import (
	_COLLECTIBLE_STATUSES,
	_currency_precision,
	_load_agreement,
	_open_total,
	_row_states,
)

# Reported to the agreement screen so it can show or hide each action.
# `settlement_writeoff` joined the list when `terminate_agreement` became its first
# consumer: a capability the screen cannot see is an action the screen cannot offer.
_DETAIL_CAPABILITIES = (
	"collect",
	"pay_supplier",
	"cancel_same_day",
	"reschedule",
	"view_cost_margin",
	"settlement_writeoff",
)

_DRAFT_FIELDS = (
	"naming_series",
	"direction",
	"settlement_mode",
	"party_type",
	"party",
	"party_name",
	"vehicle_unit",
	"currency",
	"agreement_date",
	"cash_price",
	"disclosed_markup",
	"approved_fees",
	"tax_amount",
	"down_payment",
	"total_contract_price",
	"financed_amount",
	"remarks",
)


# --- shared guards / helpers ---------------------------------------------------


def _guard_view(company: str | None) -> str:
	company = _require_company(company)
	_assert_company_scope(company)
	_require_agreement_v1(company)
	_assert_capability(frappe.session.user, company, "view")
	return company


def _has_capability(user: str, company: str | None, capability: str) -> bool:
	"""Same rule as `_assert_capability`, without throwing — used to tell the
	UI which actions a user may take instead of hiding them client-side."""
	allowed = CAPABILITY_ROLES.get(capability) or frozenset()
	roles = set(frappe.get_roles(user))
	if roles & set(_ADMIN_ROLES):
		return True
	return bool(roles & allowed)


def _agreement_schedule_state(agreement_name: str, active_schedule_version: str | None, total: float) -> dict:
	"""Paid/outstanding/next-due/payment-state for one agreement. No active
	version yet (pre-activation) reads as Not Started with the full total
	outstanding — there is nothing to pay against until activation."""
	if not active_schedule_version:
		return {
			"paid": 0.0,
			"outstanding": flt(total),
			"next_due": None,
			"payment_state": "Not Started",
			"is_overdue": False,
		}
	_assert_can_read("Vehicle Finance Schedule Version", active_schedule_version)
	version = frappe.get_doc("Vehicle Finance Schedule Version", active_schedule_version)
	states = _row_states(version)
	outstanding = _open_total(states)
	paid = flt(sum(flt(r["paid"]) for r in states))
	today_ = getdate(today())
	open_rows = [r for r in states if flt(r["amount"]) - flt(r["paid"]) > 0]
	next_due = min((r["due_date"] for r in open_rows), default=None)
	is_overdue = any(getdate(r["due_date"]) < today_ for r in open_rows)
	if outstanding <= 0:
		payment_state = "Paid"
	elif is_overdue:
		payment_state = "Overdue"
	elif paid > 0:
		payment_state = "Partial"
	else:
		payment_state = "Current"
	return {
		"paid": paid,
		"outstanding": outstanding,
		"next_due": next_due,
		"payment_state": payment_state,
		"is_overdue": is_overdue,
	}


def _vehicle_finance_state(acquisition_status: str | None, disposition_status: str | None) -> str:
	"""Derived from the two legs' agreement statuses — Vehicle Unit itself
	carries no lifecycle field of its own."""
	if disposition_status in _COLLECTIBLE_STATUSES or disposition_status == "Completed":
		return "Financed Out"
	if acquisition_status in _COLLECTIBLE_STATUSES or acquisition_status == "Completed":
		return "Financed In"
	if acquisition_status in ("Draft", "Review", "Approved") or disposition_status in (
		"Draft",
		"Review",
		"Approved",
	):
		return "Pending Agreement"
	return "No Agreement"


def _chain_positions(names) -> dict[str, dict]:
	"""Restructure-chain position for each named agreement.

	`chain.positions` needs a CLOSED set — the whole chain, not just the page —
	so this walks `restructured_from` in both directions until nothing new turns
	up. Two queries per hop, never one per row: a page of fifty agreements with
	no restructures anywhere costs exactly two extra queries, and chains are
	expected to be two or three links long.

	Cancelled agreements are excluded. A restructure that was cancelled did not
	happen, so it is not part of the history, and a successor pointing at one
	reads as a chain root.
	"""
	wanted = {name for name in names if name}
	if not wanted:
		return {}

	predecessor_by_name: dict[str, str | None] = {}
	queried: set[str] = set()
	frontier = set(wanted)
	while frontier:
		batch = sorted(frontier)
		queried.update(batch)
		found = frappe.get_all(
			"Vehicle Agreement",
			filters={"name": ["in", batch], "docstatus": ("!=", 2)},
			fields=["name", "restructured_from"],
		) + frappe.get_all(
			"Vehicle Agreement",
			filters={"restructured_from": ["in", batch], "docstatus": ("!=", 2)},
			fields=["name", "restructured_from"],
		)
		frontier = set()
		for row in found:
			predecessor_by_name[row["name"]] = row["restructured_from"] or None
			frontier.add(row["name"])
			if row["restructured_from"]:
				frontier.add(row["restructured_from"])
		frontier -= queried

	return chain.positions(predecessor_by_name)


# --- 1. agreement_list ----------------------------------------------------------


@frappe.whitelist()
def agreement_list(
	company: str | None = None,
	direction: str | None = None,
	currency: str | None = None,
	payment_state: str | None = None,
	search: str | None = None,
	limit: int | str = 50,
	start: int | str = 0,
) -> dict:
	company = _guard_view(company)
	limit = cint(limit) or 50
	start = cint(start) or 0

	filters: dict = {"company": company, "docstatus": ("!=", 2)}
	if direction:
		filters["direction"] = direction
	if currency:
		filters["currency"] = currency

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [
			["name", "like", like],
			["vehicle_unit", "like", like],
			["serial_no", "like", like],
			["party_name", "like", like],
		]

	names = frappe.get_all(
		"Vehicle Agreement",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"vehicle_unit",
			"serial_no",
			"party",
			"party_name",
			"direction",
			"settlement_mode",
			"currency",
			"agreement_date",
			"total_contract_price",
			"agreement_status",
			"owner_user",
			"active_schedule_version",
			"restructured_from",
		],
		order_by="agreement_date desc, name desc",
	)

	rows = []
	totals_by_currency: dict[str, dict[str, float]] = {}
	for row in names:
		_assert_can_read("Vehicle Agreement", row["name"])
		state = _agreement_schedule_state(
			row["name"], row["active_schedule_version"], row["total_contract_price"]
		)
		if payment_state and state["payment_state"] != payment_state:
			continue
		rows.append({**row, **state})
		bucket = totals_by_currency.setdefault(
			row["currency"], {"total": 0.0, "paid": 0.0, "outstanding": 0.0}
		)
		bucket["total"] = flt(bucket["total"] + flt(row["total_contract_price"]))
		bucket["paid"] = flt(bucket["paid"] + state["paid"])
		bucket["outstanding"] = flt(bucket["outstanding"] + state["outstanding"])

	page = rows[start : start + limit]
	# Only the page pays for the chain lookup — the rows filtered out above are
	# never rendered, so their history is nobody's question.
	chain_by_name = _chain_positions(row["name"] for row in page)
	for row in page:
		row.update(chain_by_name.get(row["name"], chain.SOLE_AGREEMENT))
	return {
		"rows": page,
		"totals_by_currency": totals_by_currency,
		"has_more": start + limit < len(rows),
	}


# --- 2. agreement_detail ---------------------------------------------------------


def _payment_entries_by_row(version_name: str) -> dict[str, list[str]]:
	apps = frappe.get_all(
		"Vehicle Finance Payment Application",
		filters={"schedule_version": version_name, "docstatus": 1},
		fields=["schedule_row", "payment_entry"],
		order_by="applied_on asc",
	)
	out: dict[str, list[str]] = {}
	for a in apps:
		bucket = out.setdefault(a["schedule_row"], [])
		if a["payment_entry"] not in bucket:
			bucket.append(a["payment_entry"])
	return out


@frappe.whitelist()
def agreement_detail(agreement: str) -> dict:
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, "view")

	version_name = doc.active_schedule_version or frappe.db.get_value(
		"Vehicle Finance Schedule Version",
		{"agreement": doc.name, "docstatus": ("!=", 2)},
		"name",
		order_by="version_number desc",
	)

	precision = _currency_precision(doc.currency)
	schedule_rows: list[dict] = []
	schedule_total = 0.0
	outstanding = flt(doc.total_contract_price)
	paid = 0.0

	if version_name:
		_assert_can_read("Vehicle Finance Schedule Version", version_name)
		version = frappe.get_doc("Vehicle Finance Schedule Version", version_name)
		states = _row_states(version)
		payment_entries = _payment_entries_by_row(version_name)
		today_ = getdate(today())
		schedule_total = flt(sum(flt(r["amount"]) for r in states))
		outstanding = _open_total(states)
		paid = flt(sum(flt(r["paid"]) for r in states))
		for r in states:
			row_outstanding = flt(r["amount"]) - flt(r["paid"])
			if row_outstanding <= 0:
				health = "Paid"
			elif getdate(r["due_date"]) < today_:
				health = "Overdue"
			elif flt(r["paid"]) > 0:
				health = "Partial"
			else:
				health = "Upcoming"
			schedule_rows.append(
				{
					"row_name": r["row_name"],
					"sequence": r["sequence"],
					"due_date": r["due_date"],
					"scheduled": flt(r["amount"]),
					"paid": flt(r["paid"]),
					"outstanding": max(0.0, row_outstanding),
					"payment_health": health,
					"payment_entries": payment_entries.get(r["row_name"], []),
				}
			)

	capabilities = {
		cap: _has_capability(frappe.session.user, doc.company, cap) for cap in _DETAIL_CAPABILITIES
	}

	return {
		"agreement": doc.as_dict(),
		"schedule_version": version_name,
		"schedule_rows": schedule_rows,
		"schedule_total": schedule_total,
		"schedule_matches_total": round(schedule_total, precision)
		== round(flt(doc.total_contract_price), precision),
		"paid": paid,
		"outstanding": outstanding,
		"capabilities": capabilities,
	}


# --- 3. vehicle_list --------------------------------------------------------------


@frappe.whitelist()
def vehicle_list(
	company: str | None = None,
	search: str | None = None,
	limit: int | str = 50,
	start: int | str = 0,
) -> dict:
	company = _guard_view(company)
	limit = cint(limit) or 50
	start = cint(start) or 0

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [
			["serial_no", "like", like],
			["vin", "like", like],
			["registration_number", "like", like],
		]

	units = frappe.get_all(
		"Vehicle Unit",
		filters={"company": company},
		or_filters=or_filters,
		fields=[
			"name",
			"serial_no",
			"vin",
			"item_code",
			"model_label",
			"operational_status",
			"title_status",
			"possession_note",
			"acquisition_agreement",
			"disposition_agreement",
		],
		order_by="modified desc",
	)

	agreement_names = {u["acquisition_agreement"] for u in units if u["acquisition_agreement"]}
	agreement_names |= {u["disposition_agreement"] for u in units if u["disposition_agreement"]}
	statuses: dict[str, str] = {}
	if agreement_names:
		statuses = {
			r["name"]: r["agreement_status"]
			for r in frappe.get_all(
				"Vehicle Agreement",
				filters={"name": ("in", list(agreement_names))},
				fields=["name", "agreement_status"],
			)
		}

	rows = [
		{
			**u,
			"finance_state": _vehicle_finance_state(
				statuses.get(u["acquisition_agreement"]), statuses.get(u["disposition_agreement"])
			),
		}
		for u in units
	]

	page = rows[start : start + limit]
	return {"rows": page, "has_more": start + limit < len(rows)}


# --- 4. vehicle_detail -------------------------------------------------------------


def _leg_payload(agreement_name: str | None) -> dict | None:
	if not agreement_name:
		return None
	_assert_can_read("Vehicle Agreement", agreement_name)
	doc = frappe.get_doc("Vehicle Agreement", agreement_name)
	return {
		"agreement": doc.name,
		"direction": doc.direction,
		"party": doc.party,
		"party_name": doc.party_name,
		"currency": doc.currency,
		"cash_price": flt(doc.cash_price),
		"total_contract_price": flt(doc.total_contract_price),
		"agreement_status": doc.agreement_status,
		"agreement_date": doc.agreement_date,
	}


@frappe.whitelist()
def vehicle_detail(vehicle_unit: str) -> dict:
	_assert_can_read("Vehicle Unit", vehicle_unit)
	unit = frappe.get_doc("Vehicle Unit", vehicle_unit)
	company = _guard_view(unit.company)

	acquisition = _leg_payload(unit.acquisition_agreement)
	disposition = _leg_payload(unit.disposition_agreement)

	payload = {
		"vehicle_unit": unit.name,
		"vehicle": {
			"serial_no": unit.serial_no,
			"vin": unit.vin,
			"item_code": unit.item_code,
			"model_label": unit.model_label,
			"operational_status": unit.operational_status,
		},
		"title": {
			"title_status": unit.title_status,
			"registration_number": unit.registration_number,
			"registration_expiry": unit.registration_expiry,
			"inspection_due": unit.inspection_due,
		},
		"possession": {
			"possession_note": unit.possession_note,
			"document_folder": unit.document_folder,
			"keys_count": unit.keys_count,
			"condition_notes": unit.condition_notes,
		},
		"acquisition": acquisition,
		"disposition": disposition,
		"finance_state": _vehicle_finance_state(
			acquisition["agreement_status"] if acquisition else None,
			disposition["agreement_status"] if disposition else None,
		),
	}

	# Cost/margin key is only ever added to the payload for a viewer with the
	# capability — it must be genuinely absent, not merely hidden, for anyone
	# else (Phase 3 acceptance criterion 5 checks the response body, not the DOM).
	if _has_capability(frappe.session.user, company, "view_cost_margin"):
		margin = None
		if acquisition and disposition and acquisition["currency"] == disposition["currency"]:
			margin = flt(disposition["total_contract_price"] - acquisition["cash_price"])
		payload["cost_margin"] = {
			"acquisition_cash_price": acquisition["cash_price"] if acquisition else None,
			"disposition_total_contract_price": disposition["total_contract_price"] if disposition else None,
			"margin": margin,
		}

	return payload


# --- 5. operations_summary ----------------------------------------------------------


@frappe.whitelist()
def operations_summary(
	company: str | None = None,
	direction: str | None = None,
	currency: str | None = None,
) -> dict:
	company = _guard_view(company)

	filters: dict = {"company": company, "docstatus": 1}
	if direction:
		filters["direction"] = direction
	if currency:
		filters["currency"] = currency

	agreements = frappe.get_all(
		"Vehicle Agreement",
		filters=filters,
		fields=[
			"name",
			"currency",
			"agreement_status",
			"total_contract_price",
			"active_schedule_version",
		],
	)

	lifecycle: dict[str, int] = {}
	totals_by_currency: dict[str, dict[str, float]] = {}
	overdue_count = 0
	overdue_outstanding_by_currency: dict[str, float] = {}
	today_ = getdate(today())

	for row in agreements:
		lifecycle[row["agreement_status"]] = lifecycle.get(row["agreement_status"], 0) + 1
		bucket = totals_by_currency.setdefault(
			row["currency"], {"agreements": 0, "total_contract_price": 0.0, "outstanding": 0.0}
		)
		bucket["agreements"] += 1
		bucket["total_contract_price"] = flt(
			bucket["total_contract_price"] + flt(row["total_contract_price"])
		)

		if row["agreement_status"] not in _COLLECTIBLE_STATUSES or not row["active_schedule_version"]:
			continue
		_assert_can_read("Vehicle Finance Schedule Version", row["active_schedule_version"])
		version = frappe.get_doc("Vehicle Finance Schedule Version", row["active_schedule_version"])
		states = _row_states(version)
		outstanding = _open_total(states)
		bucket["outstanding"] = flt(bucket["outstanding"] + outstanding)

		open_rows = [r for r in states if flt(r["amount"]) - flt(r["paid"]) > 0]
		if any(getdate(r["due_date"]) < today_ for r in open_rows):
			overdue_count += 1
			overdue_outstanding_by_currency[row["currency"]] = flt(
				overdue_outstanding_by_currency.get(row["currency"], 0) + outstanding
			)

	return {
		"company": company,
		"agreement_count": len(agreements),
		"lifecycle": lifecycle,
		"totals_by_currency": totals_by_currency,
		"overdue_count": overdue_count,
		"overdue_outstanding_by_currency": overdue_outstanding_by_currency,
	}


# --- 6. schedule_preview ---------------------------------------------------------


@frappe.whitelist()
def schedule_preview(payload: dict | None = None) -> dict:
	payload = payload or {}
	company = _require_company(payload.get("company"))
	_assert_company_scope(company)
	_require_agreement_v1(company)
	_assert_capability(frappe.session.user, company, "draft_write")

	total = flt(payload.get("total"))
	precision = cint(payload.get("currency_precision")) or _currency_precision(payload.get("currency"))

	try:
		rows = build_schedule(
			total=total,
			down_payment=flt(payload.get("down_payment")),
			currency_precision=precision,
			plan_type=payload.get("plan_type") or "Equal Monthly",
			agreement_date=payload.get("agreement_date") or today(),
			first_installment_date=payload.get("first_installment_date"),
			installment_count=cint(payload.get("installment_count")) or None,
			balloon_amount=flt(payload.get("balloon_amount") or 0),
			custom_rows=payload.get("custom_rows"),
			settlement_mode=payload.get("settlement_mode") or "Installment",
		)
	except ValueError as exc:
		return {
			"ok": False,
			"rows": [],
			"schedule_total": 0.0,
			"invariants": [{"name": "schedule_builds", "passed": False, "message": str(exc)}],
		}

	# Frontend totals are never trusted; the server re-derives the same
	# invariants the row model enforces instead of trusting the builder blindly.
	row_sum = flt(sum(flt(r["amount"]) for r in rows))
	total_matches = round(row_sum, precision) == round(total, precision)
	dates = [getdate(r["due_date"]) for r in rows]
	dates_increasing = all(a < b for a, b in pairwise(dates))

	invariants = [
		{"name": "schedule_builds", "passed": True, "message": ""},
		{
			"name": "rows_sum_equals_total",
			"passed": total_matches,
			"message": ""
			if total_matches
			else _("Rows sum to {0} but the agreement total is {1}.").format(row_sum, total),
		},
		{
			"name": "due_dates_increasing",
			"passed": dates_increasing,
			"message": "" if dates_increasing else _("Schedule due dates are not strictly increasing."),
		},
	]

	return {
		"ok": all(i["passed"] for i in invariants),
		"rows": rows,
		"schedule_total": row_sum,
		"invariants": invariants,
	}


# --- 7. save_draft_agreement -------------------------------------------------------


def _save_draft_schedule_version(doc, schedule_payload: dict, rows: list[dict]) -> str:
	existing = frappe.db.get_value(
		"Vehicle Finance Schedule Version", {"agreement": doc.name, "docstatus": 0}, "name"
	)
	version = (
		frappe.get_doc("Vehicle Finance Schedule Version", existing)
		if existing
		else frappe.new_doc("Vehicle Finance Schedule Version")
	)
	version.agreement = doc.name
	version.status = "Draft"
	version.version_number = version.version_number or 1
	version.effective_date = doc.agreement_date or today()
	version.plan_type = schedule_payload.get("plan_type") or "Equal Monthly"
	version.first_installment_date = schedule_payload.get("first_installment_date")
	version.installment_count = schedule_payload.get("installment_count")
	version.balloon_amount = flt(schedule_payload.get("balloon_amount") or 0)
	version.set("rows", [])
	for row in rows:
		version.append(
			"rows",
			{
				"sequence": row["sequence"],
				"due_date": row["due_date"],
				"amount": row["amount"],
				"row_type": row["row_type"],
			},
		)
	if version.is_new():
		version.insert()
	else:
		version.save()
	return version.name


@frappe.whitelist()
def save_draft_agreement(payload: dict | None = None) -> dict:
	payload = payload or {}
	company = _require_company(payload.get("company"))
	_assert_company_scope(company)
	_require_agreement_v1(company)
	_assert_capability(frappe.session.user, company, "draft_write")

	name = payload.get("name")
	if name:
		_assert_can_write("Vehicle Agreement", name)
		doc = frappe.get_doc("Vehicle Agreement", name)
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft agreement (docstatus 0) can be saved this way."))
		if doc.company != company:
			frappe.throw(_("Agreement {0} does not belong to company {1}.").format(name, company))
	else:
		doc = frappe.new_doc("Vehicle Agreement")
		doc.company = company

	for field in _DRAFT_FIELDS:
		if field in payload:
			doc.set(field, payload[field])

	if doc.is_new() and not doc.naming_series:
		# Reqd Select with a single configured series — fall back to it rather
		# than making every caller know the exact series string.
		options = frappe.get_meta("Vehicle Agreement").get_field("naming_series").options or ""
		first_option = options.split("\n")[0].strip()
		if first_option:
			doc.naming_series = first_option

	if doc.is_new():
		doc.insert()
	else:
		doc.save()

	schedule_payload = payload.get("schedule")
	version_name = None
	if schedule_payload:
		precision = _currency_precision(doc.currency)
		try:
			rows = build_schedule(
				total=flt(doc.total_contract_price),
				down_payment=flt(doc.down_payment),
				currency_precision=precision,
				plan_type=schedule_payload.get("plan_type") or "Equal Monthly",
				agreement_date=doc.agreement_date or today(),
				first_installment_date=schedule_payload.get("first_installment_date"),
				installment_count=cint(schedule_payload.get("installment_count")) or None,
				balloon_amount=flt(schedule_payload.get("balloon_amount") or 0),
				custom_rows=schedule_payload.get("custom_rows"),
				settlement_mode=doc.settlement_mode or "Installment",
			)
		except ValueError as exc:
			frappe.throw(str(exc))
		version_name = _save_draft_schedule_version(doc, schedule_payload, rows)

	return {
		"agreement": doc.name,
		"docstatus": doc.docstatus,
		"agreement_status": doc.agreement_status,
		"schedule_version": version_name,
	}
