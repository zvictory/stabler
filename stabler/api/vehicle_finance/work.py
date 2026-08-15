"""Vehicle Finance Center — work queue, follow-ups, promises and the daily
generator (Phase 4, stabler-l0m.4).

Nothing in this module moves money. It turns the schedule into daily work and
records what humans did about it.

Two structural decisions worth stating once, here:

* **The queue is derived live, the work item table is history.** Every row in
  `work_queue` is recomputed from `_row_states` (Phase 2's derived paid /
  outstanding) at read time, so there is exactly one definition of "overdue" in
  this codebase and a re-opened row shows up the moment its reversal is
  submitted — not the next morning. `Vehicle Finance Work Item` supplies the
  independent work-status axis, the owner and the scheduler's idempotency
  guard; it is never the source of truth for whether money is owed.
* **`policy_date` is the date the policy fired.** For a schedule row that is the
  row's due date; for a promise it is the promise date. It is never the run
  date — see the module docstring of `work_policy` for why that distinction is
  the difference between one collection task and ninety.

Guard order on every endpoint, unchanged from v1.py / read.py:
company -> tenant scope -> module -> engine -> capability -> document permission.
"""

from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import flt, getdate, now, today

from stabler.api.vehicle_finance import work_policy as policy
from stabler.api.vehicle_finance.permissions import _assert_capability
from stabler.api.vehicle_finance.read import _guard_view, _has_capability
from stabler.api.vehicle_finance.v1 import (
	_COLLECTIBLE_STATUSES,
	_currency_precision,
	_load_agreement,
	_row_states,
)

_AGREEMENT_FIELDS = (
	"name",
	"company",
	"direction",
	"party_type",
	"party",
	"party_name",
	"currency",
	"vehicle_unit",
	"serial_no",
	"owner_user",
	"agreement_status",
	"active_schedule_version",
)

_ROW_ACTIONS = ("log_followup", "record_promise", "settle_payment")

_REASON_BY_EVENT = {
	policy.EVENT_OVERDUE: "Overdue",
	policy.EVENT_DUE_TODAY: "Due today",
	policy.EVENT_UPCOMING_7D: "Due within 7 days",
	policy.EVENT_PROMISE_DUE: "Promise due",
	policy.EVENT_PROMISE_BROKEN: "Promise broken",
}

_PROMISE_ERRORS = {
	policy.PROMISE_ERR_AMOUNT: "A promise amount must be greater than zero.",
	policy.PROMISE_ERR_EXCEEDS: "A promise cannot exceed the outstanding amount of the row.",
	policy.PROMISE_ERR_PAST_DATE: "A promise date cannot be in the past.",
	policy.PROMISE_ERR_ROW_SETTLED: "This schedule row has nothing outstanding.",
}


# --- shared helpers -------------------------------------------------------------


def _money_capability(party_type: str | None) -> str:
	"""Receivable legs are collected, payable legs are paid. `party_type` rather
	than `direction` is the discriminator: it is the field that says who owes
	whom, whatever the leg is called."""
	return "pay_supplier" if party_type == "Supplier" else "collect"


def _guard_action(agreement: str) -> object:
	"""Full guard chain for the two writing endpoints. `_load_agreement` already
	runs company -> scope -> module -> engine -> read permission; the capability
	gate on top is what turns a missing role into a permission error from the
	endpoint rather than a hidden button."""
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, _money_capability(doc.party_type))
	return doc


def _escalation_threshold(company: str) -> int:
	value = frappe.db.get_value("Vehicle Finance Settings", company, "escalation_threshold_days")
	return int(value or policy.DEFAULT_ESCALATION_THRESHOLD_DAYS)


def _version_doc(agreement: dict | object) -> object | None:
	"""The active schedule version, or None. A Draft/Review/Approved agreement
	has no schedule to work yet and simply produces no queue rows."""
	name = (
		agreement.get("active_schedule_version")
		if isinstance(agreement, dict)
		else agreement.active_schedule_version
	)
	if not name:
		return None
	return frappe.get_doc("Vehicle Finance Schedule Version", name)


def _non_reversal_allocations(agreement: str) -> list[dict]:
	"""Real allocations only — a promise is judged against money that actually
	arrived, never against a flag someone set by hand."""
	return frappe.db.sql(
		"""
		select row_sequence, date(applied_on) as applied_date, allocated_amount
		from `tabVehicle Finance Payment Application`
		where agreement = %s and docstatus = 1 and ifnull(is_reversal, 0) = 0
		""",
		agreement,
		as_dict=True,
	)


def _allocated_on_or_before(allocations: list[dict], row_sequence: int, cutoff: datetime.date) -> float:
	return flt(
		sum(
			flt(a.allocated_amount)
			for a in allocations
			if int(a.row_sequence or 0) == int(row_sequence)
			and a.applied_date
			and policy.as_date(a.applied_date) <= cutoff
		)
	)


def _latest_promises(agreement: str) -> dict[int, dict]:
	"""Latest live promise per schedule row. A later promise supersedes an
	earlier one for the same row — the customer restated their intent."""
	rows = frappe.get_all(
		"Vehicle Finance Follow-up Log",
		filters={"agreement": agreement, "promise_amount": [">", 0]},
		fields=["name", "row_sequence", "schedule_row", "promise_amount", "promise_date", "logged_on"],
		order_by="logged_on asc, creation asc",
	)
	latest: dict[int, dict] = {}
	for row in rows:
		if not row.promise_date:
			continue
		latest[int(row.row_sequence or 0)] = row
	return latest


def _last_contact(agreement: str) -> dict[int, dict]:
	"""Most recent follow-up per schedule row, for the queue's `last contact`
	and `next action` columns."""
	rows = frappe.get_all(
		"Vehicle Finance Follow-up Log",
		filters={"agreement": agreement},
		fields=[
			"row_sequence",
			"contact_type",
			"contact_result",
			"next_action",
			"next_action_date",
			"logged_on",
		],
		order_by="logged_on asc, creation asc",
	)
	last: dict[int, dict] = {}
	for row in rows:
		last[int(row.row_sequence or 0)] = row
	return last


def _work_items(agreement: str) -> dict[tuple[int, str], dict]:
	"""Open work items keyed by (row_sequence, event_type), newest last."""
	rows = frappe.get_all(
		"Vehicle Finance Work Item",
		filters={"agreement": agreement},
		fields=["name", "row_sequence", "event_type", "work_status", "owner_user", "policy_date"],
		order_by="policy_date asc, creation asc",
	)
	return {(int(r.row_sequence or 0), r.event_type): r for r in rows}


def _collectible_agreements(
	company: str,
	direction: str | None = None,
	currency: str | None = None,
	search: str | None = None,
) -> list[dict]:
	filters: dict = {
		"company": company,
		"docstatus": 1,
		"agreement_status": ["in", _COLLECTIBLE_STATUSES],
	}
	if direction:
		filters["direction"] = direction
	if currency:
		filters["currency"] = currency
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {
			"name": ["like", like],
			"vehicle_unit": ["like", like],
			"serial_no": ["like", like],
			"party_name": ["like", like],
		}
	return frappe.get_all(
		"Vehicle Agreement",
		filters=filters,
		or_filters=or_filters,
		fields=list(_AGREEMENT_FIELDS),
		order_by="name asc",
	)


def _permitted_actions(user: str, company: str, party_type: str | None) -> list[str]:
	"""The row actions this user may actually take. The server decides; the UI
	does not guess and does not hide what it was not told about."""
	capability = _money_capability(party_type)
	if not _has_capability(user, company, capability):
		return []
	return list(_ROW_ACTIONS)


def _queue_rows_for_agreement(
	agreement: dict,
	today_: datetime.date,
	threshold: int,
	user: str,
) -> list[dict]:
	version = _version_doc(agreement)
	if not version:
		return []
	states = _row_states(version)
	open_states = [s for s in states if policy.is_open(s["amount"], s["paid"])]
	if not open_states:
		return []

	precision = _currency_precision(agreement.get("currency"))
	allocations = _non_reversal_allocations(agreement["name"])
	promises = _latest_promises(agreement["name"])
	contacts = _last_contact(agreement["name"])
	items = _work_items(agreement["name"])
	actions = _permitted_actions(user, agreement["company"], agreement.get("party_type"))

	rows: list[dict] = []
	for state in open_states:
		sequence = int(state["sequence"])
		outstanding = policy.row_outstanding(state["amount"], state["paid"])
		promise = promises.get(sequence)
		promise_event = None
		if promise:
			promise_event = policy.promise_event(
				promise.promise_date,
				promise.promise_amount,
				_allocated_on_or_before(allocations, sequence, policy.as_date(promise.promise_date)),
				today_,
				precision,
			)
		has_open_promise = bool(promise) and promise_event != policy.EVENT_PROMISE_BROKEN
		contact = contacts.get(sequence)
		views = policy.row_views(
			state["due_date"],
			today_,
			escalation_threshold_days=threshold,
			has_broken_promise=promise_event == policy.EVENT_PROMISE_BROKEN,
			has_open_promise=has_open_promise,
			has_open_followup=bool(contact and contact.next_action),
		)
		if not views:
			continue
		row_event = policy.row_event(state["due_date"], today_)
		work_item = items.get((sequence, promise_event)) or items.get((sequence, row_event))
		rows.append(
			{
				"agreement": agreement["name"],
				"company": agreement["company"],
				"direction": agreement.get("direction"),
				"party_type": agreement.get("party_type"),
				"party": agreement.get("party"),
				"party_name": agreement.get("party_name"),
				"vehicle_unit": agreement.get("vehicle_unit"),
				"vin": agreement.get("serial_no"),
				"schedule_row": state["row_name"],
				"row_sequence": sequence,
				"due_date": state["due_date"],
				"outstanding": flt(outstanding, precision),
				"currency": agreement.get("currency"),
				"reason": _REASON_BY_EVENT.get(promise_event or row_event or ""),
				"views": sorted(views),
				"owner": (work_item or {}).get("owner_user") or agreement.get("owner_user"),
				"work_status": (work_item or {}).get("work_status") or policy.WORK_UNASSIGNED,
				"work_item": (work_item or {}).get("name"),
				"promise_amount": flt(promise.promise_amount, precision) if promise else None,
				"promise_date": promise.promise_date if promise else None,
				"last_contact": contact.logged_on if contact else None,
				"last_contact_result": contact.contact_result if contact else None,
				"next_action": contact.next_action if contact else None,
				"next_action_date": contact.next_action_date if contact else None,
				"actions": actions,
			}
		)
	return rows


# --- 1. work_queue --------------------------------------------------------------


@frappe.whitelist()
def work_queue(
	company: str | None = None,
	view: str = policy.VIEW_CRITICAL_OVERDUE,
	direction: str | None = None,
	currency: str | None = None,
	search: str | None = None,
	limit: int = 50,
	start: int = 0,
) -> dict:
	company = _guard_view(company)
	if view not in policy.VIEWS:
		frappe.throw(_("Unknown work queue view {0}.").format(view))

	limit = max(1, min(int(limit or 50), 200))
	start = max(0, int(start or 0))
	today_ = getdate(today())
	threshold = _escalation_threshold(company)
	user = frappe.session.user

	rows: list[dict] = []
	for agreement in _collectible_agreements(company, direction, currency, search):
		rows.extend(_queue_rows_for_agreement(agreement, today_, threshold, user))

	rows = [r for r in rows if view in r["views"]]
	rows.sort(key=lambda r: (str(r["due_date"]), r["agreement"], r["row_sequence"]))

	totals_by_currency: dict[str, float] = {}
	for row in rows:
		policy.add_currency_total(totals_by_currency, row["currency"], row["outstanding"])

	page = rows[start : start + limit]
	return {
		"company": company,
		"view": view,
		"rows": page,
		"count": len(rows),
		"totals_by_currency": totals_by_currency,
		"has_more": start + limit < len(rows),
	}


# --- 2. log_followup ------------------------------------------------------------


@frappe.whitelist()
def log_followup(agreement: str, payload: dict | str | None = None) -> dict:
	doc = _guard_action(agreement)
	data = frappe.parse_json(payload) if isinstance(payload, str) else dict(payload or {})

	log = frappe.get_doc(
		{
			"doctype": "Vehicle Finance Follow-up Log",
			"company": doc.company,
			"agreement": doc.name,
			"schedule_row": data.get("schedule_row"),
			"row_sequence": data.get("row_sequence"),
			"owner_user": data.get("owner_user") or frappe.session.user,
			"contact_type": data.get("contact_type") or "Other",
			"contact_result": data.get("contact_result") or "Other",
			"next_action": data.get("next_action") or data.get("note"),
			"next_action_date": data.get("next_action_date"),
		}
	)
	log.insert()

	_advance_work_status(
		doc.name,
		data.get("row_sequence"),
		policy.WORK_CONTACTED,
		only_from=(policy.WORK_UNASSIGNED, policy.WORK_ASSIGNED),
	)
	return {"name": log.name, "agreement": doc.name, "logged_on": log.logged_on}


def _advance_work_status(
	agreement: str,
	row_sequence: object,
	work_status: str,
	only_from: tuple[str, ...] | None = None,
) -> int:
	"""Moves the work status axis only. It never touches the agreement status,
	the vehicle status, the schedule or any money, and it never moves a Resolved
	item back into the queue."""
	filters: dict = {"agreement": agreement, "work_status": ["!=", policy.WORK_RESOLVED]}
	if row_sequence not in (None, ""):
		filters["row_sequence"] = int(row_sequence)
	if only_from:
		filters["work_status"] = ["in", list(only_from)]
	names = frappe.get_all("Vehicle Finance Work Item", filters=filters, pluck="name")
	for name in names:
		frappe.db.set_value("Vehicle Finance Work Item", name, "work_status", work_status)
	return len(names)


# --- 3. record_promise ----------------------------------------------------------


@frappe.whitelist()
def record_promise(
	agreement: str,
	row_sequence: int,
	amount: float,
	promise_date: str,
	note: str | None = None,
) -> dict:
	doc = _guard_action(agreement)
	version = _version_doc(doc)
	if not version:
		frappe.throw(_("Agreement {0} has no active schedule version.").format(doc.name))

	sequence = int(row_sequence)
	state = next((s for s in _row_states(version) if int(s["sequence"]) == sequence), None)
	if not state:
		frappe.throw(_("Schedule row {0} does not exist on agreement {1}.").format(sequence, doc.name))

	outstanding = policy.row_outstanding(state["amount"], state["paid"])
	error = policy.promise_validation_error(amount, promise_date, getdate(today()), outstanding)
	if error:
		frappe.throw(_(_PROMISE_ERRORS[error]))

	precision = _currency_precision(doc.currency)
	log = frappe.get_doc(
		{
			"doctype": "Vehicle Finance Follow-up Log",
			"company": doc.company,
			"agreement": doc.name,
			"schedule_row": state["row_name"],
			"row_sequence": sequence,
			"owner_user": frappe.session.user,
			# The frozen signature carries no channel argument, so the channel is
			# recorded honestly as Other rather than invented as a call or a visit.
			"contact_type": "Other",
			"contact_result": "Promise",
			"promise_amount": flt(amount, precision),
			"promise_date": promise_date,
			"next_action": note,
			"next_action_date": promise_date,
		}
	)
	log.insert()

	_advance_work_status(doc.name, sequence, policy.WORK_PROMISE)
	return {
		"name": log.name,
		"agreement": doc.name,
		"row_sequence": sequence,
		"promise_amount": flt(amount, precision),
		"promise_date": promise_date,
		"outstanding": flt(outstanding, precision),
		"currency": doc.currency,
	}


# --- 4. calendar_events ---------------------------------------------------------


def _month_bounds(month: str) -> tuple[datetime.date, datetime.date]:
	first = policy.as_date(f"{month}-01")
	nxt = datetime.date(first.year + (first.month == 12), (first.month % 12) + 1, 1)
	return first, nxt - datetime.timedelta(days=1)


@frappe.whitelist()
def calendar_events(
	company: str | None = None,
	month: str | None = None,
	direction: str | None = None,
	currency: str | None = None,
) -> dict:
	company = _guard_view(company)
	month = month or getdate(today()).strftime("%Y-%m")
	try:
		first, last = _month_bounds(month)
	except ValueError:
		frappe.throw(_("Month must be given as YYYY-MM."))

	events: list[dict] = []
	totals_by_day: dict[str, dict[str, float]] = {}

	for agreement in _collectible_agreements(company, direction, currency):
		version = _version_doc(agreement)
		if not version:
			continue
		precision = _currency_precision(agreement.get("currency"))
		row_currency = agreement.get("currency")
		for state in _row_states(version):
			if not policy.is_open(state["amount"], state["paid"]):
				continue
			due = policy.as_date(state["due_date"])
			if not (first <= due <= last):
				continue
			outstanding = flt(policy.row_outstanding(state["amount"], state["paid"]), precision)
			events.append(
				{
					"date": due.isoformat(),
					"kind": "due",
					"agreement": agreement["name"],
					"vehicle_unit": agreement.get("vehicle_unit"),
					"vin": agreement.get("serial_no"),
					"party_name": agreement.get("party_name"),
					"direction": agreement.get("direction"),
					"row_sequence": int(state["sequence"]),
					"schedule_row": state["row_name"],
					"amount": outstanding,
					"currency": row_currency,
				}
			)
			policy.add_currency_total(
				totals_by_day.setdefault(due.isoformat(), {}), row_currency, outstanding
			)

		for sequence, promise in _latest_promises(agreement["name"]).items():
			promised = policy.as_date(promise.promise_date)
			if not (first <= promised <= last):
				continue
			events.append(
				{
					"date": promised.isoformat(),
					"kind": "promise",
					"agreement": agreement["name"],
					"vehicle_unit": agreement.get("vehicle_unit"),
					"vin": agreement.get("serial_no"),
					"party_name": agreement.get("party_name"),
					"direction": agreement.get("direction"),
					"row_sequence": sequence,
					"schedule_row": promise.schedule_row,
					"amount": flt(promise.promise_amount, precision),
					"currency": row_currency,
				}
			)

	events.sort(key=lambda e: (e["date"], e["kind"], e["agreement"], e["row_sequence"]))
	return {
		"company": company,
		"month": month,
		"events": events,
		"totals_by_day": totals_by_day,
	}


# --- 5. the daily generator -----------------------------------------------------


def _agreement_v1_companies() -> list[str]:
	from stabler.api.vehicle_finance.permissions import _vehicle_finance_module_enabled
	from stabler.stabler.doctype.vehicle_finance_settings.vehicle_finance_settings import get_engine

	companies = []
	for company in frappe.get_all("Company", pluck="name"):
		if not _vehicle_finance_module_enabled(company):
			continue
		if get_engine(company) != "Agreement V1":
			continue
		companies.append(company)
	return companies


def _create_work_item(
	agreement: dict,
	state: dict | None,
	event_type: str,
	policy_date: datetime.date,
	work_status: str,
	outstanding: float,
	note: str | None = None,
) -> str | None:
	"""Creates one work item unless its identity tuple already exists. The guard
	is the query below and nothing else — no timestamp comparison, no
	"has the job run today" flag — so a worker restart that runs the job twice
	is a no-op."""
	schedule_row = (state or {}).get("row_name") or ""
	if frappe.db.exists(
		"Vehicle Finance Work Item",
		{
			"company": agreement["company"],
			"agreement": agreement["name"],
			"schedule_row": schedule_row,
			"event_type": event_type,
			"policy_date": policy_date,
		},
	):
		return None
	item = frappe.get_doc(
		{
			"doctype": "Vehicle Finance Work Item",
			"company": agreement["company"],
			"agreement": agreement["name"],
			"schedule_row": schedule_row,
			"row_sequence": int((state or {}).get("sequence") or 0),
			"event_type": event_type,
			"policy_date": policy_date,
			"due_date": (state or {}).get("due_date"),
			"work_status": work_status,
			"owner_user": agreement.get("owner_user"),
			"currency": agreement.get("currency"),
			"outstanding": outstanding,
			"note": note,
			"generated_on": now(),
		}
	)
	item.insert(ignore_permissions=True)
	return item.name


def _generate_for_agreement(agreement: dict, today_: datetime.date) -> int:
	version = _version_doc(agreement)
	if not version:
		return 0
	states = _row_states(version)
	open_states = [s for s in states if policy.is_open(s["amount"], s["paid"])]
	precision = _currency_precision(agreement.get("currency"))
	allocations = _non_reversal_allocations(agreement["name"])
	promises = _latest_promises(agreement["name"])
	by_sequence = {int(s["sequence"]): s for s in states}
	created = 0

	for state in open_states:
		event = policy.row_event(state["due_date"], today_)
		if not event:
			continue
		if _create_work_item(
			agreement,
			state,
			event,
			policy.policy_date_for(event, due_date=state["due_date"]),
			policy.WORK_UNASSIGNED,
			flt(policy.row_outstanding(state["amount"], state["paid"]), precision),
		):
			created += 1

	for sequence, promise in promises.items():
		state = by_sequence.get(sequence)
		if not state or not policy.is_open(state["amount"], state["paid"]):
			continue
		event = policy.promise_event(
			promise.promise_date,
			promise.promise_amount,
			_allocated_on_or_before(allocations, sequence, policy.as_date(promise.promise_date)),
			today_,
			precision,
		)
		if not event:
			continue
		work_status = policy.WORK_ESCALATED if event == policy.EVENT_PROMISE_BROKEN else policy.WORK_PROMISE
		if _create_work_item(
			agreement,
			state,
			event,
			policy.policy_date_for(event, promise_date=promise.promise_date),
			work_status,
			flt(policy.row_outstanding(state["amount"], state["paid"]), precision),
			note=promise.name,
		):
			created += 1
		if event == policy.EVENT_PROMISE_BROKEN:
			_advance_work_status(agreement["name"], sequence, policy.WORK_ESCALATED)

	return created


def _generate_for_company(company: str, today_: datetime.date) -> int:
	created = 0
	for agreement in _collectible_agreements(company):
		created += _generate_for_agreement(agreement, today_)
	return created


def generate_daily_work() -> dict:
	"""Daily scheduler entry point (`hooks.py` -> `scheduler_events["daily"]`).

	Commits once per company so one company with bad data cannot roll back the
	work generated for the other six tenants."""
	today_ = getdate(today())
	summary = {"date": today_.isoformat(), "companies": 0, "created": 0, "failed": []}
	for company in _agreement_v1_companies():
		try:
			summary["created"] += _generate_for_company(company, today_)
			summary["companies"] += 1
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			summary["failed"].append(company)
			frappe.log_error(
				title="Vehicle Finance daily work generation failed",
				message=f"company={company}\n{frappe.get_traceback()}",
			)
	return summary
