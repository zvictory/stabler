"""Vehicle Finance work queue — pure policy (Phase 4, stabler-l0m.4).

Frappe-free by construction: every function here is a total function of its
arguments, so the queue classification, the scheduler's event derivation and
the promise rules are testable without a bench, a site or a database.

The frappe-dependent half (whitelisted endpoints, document writes, the daily
generator) lives in `work.py` and imports this module. Nothing here reads or
writes anything.

Two invariants this module exists to protect:

1. **One definition of "overdue".** A row is overdue when it still has money
   outstanding and its due date is in the past — the same rule Phase 2 uses to
   derive outstanding (`_open_total`) and Phase 2.5 uses for `is_overdue`.
   `row_outstanding` here mirrors the per-row half of `_open_total` exactly.

2. **One identity per policy firing.** `policy_date` is the date the policy
   fired — the row's due date, or the promise's promise date — never the date
   the job happened to run. A row that went overdue on 2026-03-01 produces
   exactly one `overdue` work item, whether the scheduler runs once, twice on
   the same day, or every day for the next six months. A generator keyed on the
   run date would file a fresh item every night and turn one late installment
   into ninety collection tasks against the same customer.
"""

from __future__ import annotations

import datetime

# --- event types ---------------------------------------------------------------

EVENT_DUE_TODAY = "due_today"
EVENT_OVERDUE = "overdue"
EVENT_PROMISE_DUE = "promise_due"
EVENT_PROMISE_BROKEN = "promise_broken"
EVENT_UPCOMING_7D = "upcoming_7d"

EVENT_TYPES = (
	EVENT_DUE_TODAY,
	EVENT_OVERDUE,
	EVENT_PROMISE_DUE,
	EVENT_PROMISE_BROKEN,
	EVENT_UPCOMING_7D,
)

_PROMISE_EVENTS = (EVENT_PROMISE_DUE, EVENT_PROMISE_BROKEN)

# --- work status axis ----------------------------------------------------------
# Independent of agreement status, vehicle status, payment health and title
# status. It is computed from human activity, never from money.

WORK_UNASSIGNED = "Unassigned"
WORK_ASSIGNED = "Assigned"
WORK_CONTACTED = "Contacted"
WORK_PROMISE = "Promise"
WORK_ESCALATED = "Escalated"
WORK_RESOLVED = "Resolved"

WORK_STATUSES = (
	WORK_UNASSIGNED,
	WORK_ASSIGNED,
	WORK_CONTACTED,
	WORK_PROMISE,
	WORK_ESCALATED,
	WORK_RESOLVED,
)

OPEN_WORK_STATUSES = tuple(s for s in WORK_STATUSES if s != WORK_RESOLVED)

# --- queue views ---------------------------------------------------------------

VIEW_CRITICAL_OVERDUE = "critical_overdue"
VIEW_DUE_TODAY = "due_today"
VIEW_NEXT_7_DAYS = "next_7_days"
VIEW_MONITORING = "monitoring"
VIEW_OVERDUE = "overdue"

VIEWS = (
	VIEW_CRITICAL_OVERDUE,
	VIEW_DUE_TODAY,
	VIEW_NEXT_7_DAYS,
	VIEW_MONITORING,
	VIEW_OVERDUE,
)

UPCOMING_WINDOW_DAYS = 7
DEFAULT_ESCALATION_THRESHOLD_DAYS = 7

# --- promise validation codes --------------------------------------------------
# Returned as codes, not sentences: the translated message literals belong at
# the throw site in `work.py` so the i18n extractor can find them.

PROMISE_ERR_AMOUNT = "amount_not_positive"
PROMISE_ERR_EXCEEDS = "amount_exceeds_outstanding"
PROMISE_ERR_PAST_DATE = "promise_date_in_past"
PROMISE_ERR_ROW_SETTLED = "row_has_no_outstanding"

# --- queue reason codes ---------------------------------------------------------
# Why a row is in the queue when no date event fired. Codes rather than
# sentences, for the same reason as the promise errors above.

REASON_OPEN_PROMISE = "open_promise"
REASON_OPEN_FOLLOWUP = "open_followup"


def as_date(value: object) -> datetime.date:
	"""Accepts a `date`, a `datetime` or an ISO-ish string. Frappe hands dates
	back in all three shapes depending on whether the value came from a document
	field, a raw SQL row or a whitelisted call's JSON payload."""
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	return datetime.date.fromisoformat(str(value)[:10])


def row_outstanding(amount: object, paid: object) -> float:
	"""Per-row outstanding — the same `max(0, amount - paid)` that `_open_total`
	sums in v1.py. Never negative: an over-allocated row does not lend its
	surplus to its neighbours."""
	return max(0.0, float(amount) - float(paid))


def is_open(amount: object, paid: object) -> bool:
	return row_outstanding(amount, paid) > 0


def days_past_due(due_date: object, today: object) -> int:
	"""Positive when late, zero on the due date, negative when still upcoming."""
	return (as_date(today) - as_date(due_date)).days


def row_event(due_date: object, today: object, upcoming_days: int = UPCOMING_WINDOW_DAYS) -> str | None:
	"""The single schedule-row policy that fires for an *open* row today.

	Callers must check `is_open` first — a settled row fires nothing, which is
	what stops a row allocated between two runs from producing an `overdue`
	item on the second run."""
	late = days_past_due(due_date, today)
	if late > 0:
		return EVENT_OVERDUE
	if late == 0:
		return EVENT_DUE_TODAY
	if -late <= upcoming_days:
		return EVENT_UPCOMING_7D
	return None


def promise_is_kept(promise_amount: object, allocated_on_or_before: object, precision: int = 2) -> bool:
	"""A promise is kept when real allocations against the row on or before the
	promise date reach the promised amount. Rounded to the currency precision so
	a 0.004 float residue is not read as a broken promise."""
	return round(float(allocated_on_or_before), precision) >= round(float(promise_amount), precision)


def promise_event(
	promise_date: object,
	promise_amount: object,
	allocated_on_or_before: object,
	today: object,
	precision: int = 2,
) -> str | None:
	"""`promise_due` on the promise date itself, `promise_broken` after it, and
	nothing at all once the allocations cover the promise — including a promise
	kept exactly on `promise_date`, because `allocated_on_or_before` is
	inclusive of that date."""
	if promise_is_kept(promise_amount, allocated_on_or_before, precision):
		return None
	late = days_past_due(promise_date, today)
	if late > 0:
		return EVENT_PROMISE_BROKEN
	if late == 0:
		return EVENT_PROMISE_DUE
	return None


def policy_date_for(event_type: str, due_date: object = None, promise_date: object = None) -> datetime.date:
	"""The date the policy fired, not the moment the job ran."""
	source = promise_date if event_type in _PROMISE_EVENTS else due_date
	if source is None:
		raise ValueError(f"no policy date available for event type {event_type!r}")
	return as_date(source)


def identity(
	company: str, agreement: str, schedule_row: object, event_type: str, policy_date: object
) -> tuple[str, str, str, str, str]:
	"""`company + agreement + schedule_row + event_type + policy_date` — the
	whole idempotency story. The generator queries on this tuple; it never
	compares timestamps and never asks "has the job run today"."""
	return (
		str(company),
		str(agreement),
		str(schedule_row or ""),
		str(event_type),
		as_date(policy_date).isoformat(),
	)


def row_views(
	due_date: object,
	today: object,
	escalation_threshold_days: int = DEFAULT_ESCALATION_THRESHOLD_DAYS,
	has_broken_promise: bool = False,
	has_open_promise: bool = False,
	has_open_followup: bool = False,
	upcoming_days: int = UPCOMING_WINDOW_DAYS,
) -> frozenset[str]:
	"""Every queue view an *open* row belongs to. Views deliberately overlap:
	`overdue` is the saved view holding every late row, `critical_overdue` is the
	subset that is late beyond the company's threshold or carries a broken
	promise."""
	views: set[str] = set()
	late = days_past_due(due_date, today)
	if late > 0:
		views.add(VIEW_OVERDUE)
		if late >= max(1, int(escalation_threshold_days)):
			views.add(VIEW_CRITICAL_OVERDUE)
	elif late == 0:
		views.add(VIEW_DUE_TODAY)
	elif -late <= upcoming_days:
		views.add(VIEW_NEXT_7_DAYS)
	if has_broken_promise:
		# A broken promise is critical on its own, even on a row not yet late.
		views.add(VIEW_CRITICAL_OVERDUE)
	if not views and (has_open_promise or has_open_followup):
		views.add(VIEW_MONITORING)
	return frozenset(views)


def row_reason(
	event: str | None,
	has_open_promise: bool = False,
	has_open_followup: bool = False,
) -> str | None:
	"""The one fact that explains why this row is in the queue.

	`row_views` and this function have to agree, because they answer two halves of
	the same question: the first decides that a row belongs in a queue, the second
	says why. A monitoring row has no date event *by definition* — it is neither
	late, nor due today, nor inside the upcoming window — so `event` is None and
	the answer has to come from whatever put it in `monitoring`: someone is still
	working it. Deriving the reason from the event alone returned nothing there,
	which left the Reason column blank on exactly the rows whose presence is the
	least self-explanatory.

	A promise outranks a follow-up: it carries a date and an amount, so it is the
	more specific thing to tell the operator.
	"""
	if event:
		return event
	if has_open_promise:
		return REASON_OPEN_PROMISE
	if has_open_followup:
		return REASON_OPEN_FOLLOWUP
	return None


def promise_validation_error(
	amount: object, promise_date: object, today: object, outstanding: object
) -> str | None:
	"""Rules for `record_promise`. A promise states intent; it moves no money,
	so the only things worth refusing are a non-positive amount, an amount the
	row cannot owe, and a date in the past."""
	value = float(amount or 0)
	if value <= 0:
		return PROMISE_ERR_AMOUNT
	open_amount = float(outstanding or 0)
	if open_amount <= 0:
		return PROMISE_ERR_ROW_SETTLED
	if round(value, 2) > round(open_amount, 2):
		return PROMISE_ERR_EXCEEDS
	if as_date(promise_date) < as_date(today):
		return PROMISE_ERR_PAST_DATE
	return None


def add_currency_total(totals: dict, currency: str, amount: object) -> dict:
	"""The only way this phase accumulates money. A currency key is mandatory,
	which is what makes summing two currencies into one number impossible to
	write by accident."""
	if not currency:
		raise ValueError("a currency total needs a currency")
	totals[currency] = float(totals.get(currency, 0.0)) + float(amount)
	return totals
