"""Read paths for the Transfer V1 remittance model — the half `remittance_commands` never grew.

`remittance_commands` can register, pay out, refund and unlock, but the only thing
it can *show* is `payout_queue`. Every screen the operations centre asks for —
the scorecards, the six work queues, the searchable transfer list, one transfer's
full history, the reconciliation exceptions — had no endpoint at all. This module
is that half, and nothing here writes.

Four rules hold across every endpoint, and each one is a rule because breaking it
has a specific failure:

**The pickup code never leaves.** Every field list is run through
`actions.assert_safe_fields` *before* it reaches a query, and every response is
run through `actions.assert_no_pickup_code` on the way out. The first stops a
future edit that adds `pickup_code_hash` to a projection; the second stops one
that builds a response dict by hand. `payout_queue` set the precedent; this
module holds it on eleven more projections. `code_attempts` and `code_locked`
are here on purpose — how many times someone guessed wrong is not the secret,
and the payout screen cannot show a lockout without it.

**Lists go through `frappe.get_list`, never `frappe.get_all`.** `get_all` sets
`ignore_permissions`, so `permissions.remittance_transfer_query` — the hook that
scopes rows to the caller's companies — is never consulted, and a cashier in
Tashkent reads Samarkand's transfers. `get_all` is correct in
`remittance_commands.payout_queue` only because that function has already proven
the company; it is not correct for a browse screen, a summary or a reconciliation
pass, which is what everything here is.

**The server decides which buttons exist.** Every row carries `allowed_actions`
from `_remittance_actions`, and one `frappe.get_roles()` read serves a whole
page. A screen that derives a button from a role instead is a screen that will
disagree with the endpoint that refuses it.

**Nothing invents a number.** `expires_at` is on the doctype and *nothing writes
it* — measured 2026-08-17, no assignment exists anywhere in the app. So the two
expiry queues do not guess a deadline: they probe for the data, report
`policy_configured: False` when there is none, and return an empty list. A
fabricated 12-hour window would put real transfers in an "expired, refund
required" queue on the strength of a constant somebody typed.

Currencies are never summed. Every money figure is reported as a list of rows,
one per currency, exactly as ADR-011 requires — an "all currencies" total is a
number with no meaning and a screen that renders it is lying at a cash desk.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime, nowdate

from stabler.api import _remittance_actions as actions
from stabler.api._common import _assert_can_read, _require_company
from stabler.api.approvals import _assert_company_scope
from stabler.api.remittance_accounting import PAYOUT, REFUND, build_legs
from stabler.api.remittance_commands import _max_code_attempts, _send_precision

TRANSFER = "Remittance Transfer"
EVENT = "Remittance Event"
JOURNAL = "Journal Entry"

# --------------------------------------------------------------------------- #
# Projections
# --------------------------------------------------------------------------- #

#: What a queue row and a list row carry. The spec's row is "reference, sender,
#: receiver, route, sender pays, receiver gets, age/expiry, owner, next action":
#: `name`/`client_request_id` are the reference, the four branch/city columns ARE
#: the route (the arrow between them is a rendering decision, not a server one),
#: `tendered`+`send_currency` is what the sender paid, `receiver_amount`+
#: `receive_currency` is what the receiver gets, `registered_at`/`expires_at` is
#: the age, `registered_by` is the owner, and `next_action` is derived below.
#:
#: The four status axes and `code_locked` are here because `_remittance_actions`
#: needs them to answer — `actions.STATE_FIELDS` is the contract, and dropping one
#: would silently make `allowed_actions` wrong rather than raise.
_ROW_FIELDS = (
	"name",
	"client_request_id",
	"company",
	"sender_name",
	"receiver_name",
	"origin_branch",
	"origin_city",
	"destination_branch",
	"destination_city",
	"send_currency",
	"receive_currency",
	"principal",
	"commission",
	"tendered",
	"receiver_amount",
	"operational_status",
	"accounting_status",
	"verification_status",
	"refund_status",
	"code_locked",
	"code_attempts",
	"registered_by",
	"registered_at",
	"expires_at",
	"modified",
)

#: One transfer, in full. Adds the frozen quote (ADR-009: the triple the cashier
#: typed, plus the base rate the register leg actually posted at), the lockout
#: timestamp and the three Journal Entry links.
_DETAIL_FIELDS = (
	*_ROW_FIELDS,
	"commission_mode",
	"commission_pct",
	"exchange_rate",
	"register_base_rate",
	"code_locked_at",
	"register_journal_entry",
	"payout_journal_entry",
	"refund_journal_entry",
	"creation",
	"owner",
)

#: The append-only trail. `details` is the only free text on the whole path and
#: it is what a refund reason lands in, so the timeline is unreadable without it.
_EVENT_FIELDS = (
	"name",
	"event_type",
	"occurred_at",
	"actor",
	"branch",
	"client_request_id",
	"details",
)

#: What a linked stage voucher shows. `stabler_pickup_code` — the v33 custom field
#: that v86 rewrote as a digest — is the third name for the secret and is absent
#: here for the same reason `pickup_code_hash` is absent from the transfer rows.
_JOURNAL_FIELDS = (
	"name",
	"posting_date",
	"docstatus",
	"total_debit",
	"total_credit",
	"user_remark",
	"stabler_remittance_stage",
)

#: Only what reconciliation adds up, plus the JE links it checks the master
#: against. Narrower than `_ROW_FIELDS` because this one is pulled unpaged — but
#: it still carries every one of `actions.STATE_FIELDS`, because these rows are
#: annotated too and a MISSING state column does not raise, it reads as None. Drop
#: `code_locked` here and every locked transfer in the reconciliation list is
#: offered Pay out.
_RECON_FIELDS = (
	"name",
	"company",
	"sender_name",
	"receiver_name",
	"origin_branch",
	"destination_branch",
	"send_currency",
	"receive_currency",
	"principal",
	"commission",
	"tendered",
	"receiver_amount",
	"operational_status",
	"accounting_status",
	"verification_status",
	"refund_status",
	"code_locked",
	"code_attempts",
	"registered_at",
	"expires_at",
	"register_journal_entry",
	"payout_journal_entry",
	"refund_journal_entry",
	"modified",
)

#: What a free-text search matches. "kasa" is the branch: a supervisor looking for
#: "everything that went through Samarkand today" searches the desk, not a party.
_SEARCH_FIELDS = (
	"name",
	"client_request_id",
	"sender_name",
	"receiver_name",
	"origin_branch",
	"destination_branch",
	"origin_city",
	"destination_city",
)

_ORDER = "registered_at desc, modified desc"

#: How many exception/aged rows a reconciliation response carries. A paging cap,
#: not a policy threshold — the counts beside them are the untruncated figures.
_EXCEPTION_LIST_CAP = 100

# --------------------------------------------------------------------------- #
# The six queues
# --------------------------------------------------------------------------- #
READY_FOR_PAYOUT = "ready_for_payout"
EXPIRING_12H = "expiring_12h"
EXPIRED_REFUND_REQUIRED = "expired_refund_required"
REFUND_AWAITING_APPROVAL = "refund_awaiting_approval"
LOCKED_PICKUP_CODE = "locked_pickup_code"
ACCOUNTING_EXCEPTION = "accounting_exception"

#: In the order the operations screen stacks them.
QUEUES = (
	READY_FOR_PAYOUT,
	EXPIRING_12H,
	EXPIRED_REFUND_REQUIRED,
	REFUND_AWAITING_APPROVAL,
	LOCKED_PICKUP_CODE,
	ACCOUNTING_EXCEPTION,
)

#: The two that need a deadline nothing writes yet. Both answer with
#: `policy_configured: False` and no rows until `expires_at` carries data.
EXPIRY_QUEUES = (EXPIRING_12H, EXPIRED_REFUND_REQUIRED)

#: Each queue's own urgency signal, because `_ORDER` is the wrong one for all six.
#: Newest-first is right for a list somebody is browsing and wrong for a list
#: somebody is working: "expiring within 12 hours" sorted by registration date is
#: very nearly the reverse of soonest-deadline-first, and a locked queue that
#: ignores `code_attempts` buries the transfer the desk is about to lose.
#: Recorded as D11 by the design council (2026-08-16-remittance-design-council-
#: decision.md:201-204); the wording is PROMPT_remittance_design_v2.txt:315-316 —
#: "soonest expiry first, oldest request first, most failed attempts first".
#:
#: Every clause ends on `name` so a page boundary is stable. Without a total order
#: two rows sharing an expiry can swap between page 1 and page 2, and the cashier
#: sees one of them twice and the other never.
_QUEUE_ORDER = {
	READY_FOR_PAYOUT: "registered_at asc, name asc",
	EXPIRING_12H: "expires_at asc, name asc",
	EXPIRED_REFUND_REQUIRED: "expires_at asc, name asc",
	REFUND_AWAITING_APPROVAL: "registered_at asc, name asc",
	LOCKED_PICKUP_CODE: "code_attempts desc, registered_at asc, name asc",
	ACCOUNTING_EXCEPTION: "registered_at asc, name asc",
}

#: How long "expiring soon" is, in hours. Named after the queue the spec names;
#: it is a *window over data*, not a deadline this module assigns to anything.
_EXPIRING_WITHIN_HOURS = 12

#: A transfer whose accounting does not agree with itself. Each entry is an
#: AND-shape; the queue is their union.
#:
#: 1. `register_remittance` posts the obligation and only then writes
#:    `Registered` — "the row never passes through Registered + Unposted, even
#:    for another reader" (remittance_commands.py:433). So a row in that state is
#:    not mid-flight, it is broken.
#: 2/3. The doctype's own explicit failure states. Nothing writes either one
#:    today; they are read because reading a state that exists costs one filter,
#:    and a queue that ignores it would go quiet exactly when it matters.
#: 4. The master says the obligation is posted and names no entry — the
#:    master ↔ JE variance the reconciliation section asks for, in its cheapest
#:    form.
_EXCEPTION_SHAPES = (
	{"operational_status": "Registered", "accounting_status": "Unposted"},
	{"operational_status": "Exception"},
	{"accounting_status": "Posting Error"},
	{"accounting_status": "Posted", "register_journal_entry": ["is", "not set"]},
)

#: Every way a stage that posted can fail to name the entry that posted it.
#: A superset of `_EXCEPTION_SHAPES[3]` — reconciliation checks all three stages,
#: the queue only checks the one that opens the obligation.
_VARIANCE_SHAPES = (
	{"operational_status": "Registered", "accounting_status": "Unposted"},
	{"accounting_status": "Posted", "register_journal_entry": ["is", "not set"]},
	{"operational_status": "Paid Out", "payout_journal_entry": ["is", "not set"]},
	{"operational_status": "Refunded", "refund_journal_entry": ["is", "not set"]},
)


#: The obligation the ledger is still carrying. `register_remittance` writes this
#: pair in the same transaction as the posting, and only `complete_refund` and
#: `payout_transfer` move a row out of it — the first to `Refunded`/`Reversed`, the
#: second to `Paid Out`. So this pair, and nothing narrower, is what the GL is
#: still short: it is the master-side reading of "the register JE is submitted and
#: has not been reversed".
_OPEN_OBLIGATION = {"operational_status": "Registered", "accounting_status": "Posted"}


def _refund_open(base: dict) -> tuple[dict, ...]:
	"""`base` minus the rows a refund has taken off the desk, NULL-safe.

	This is the PAYABLE filter — it mirrors `_remittance_actions._payable` and
	`remittance_commands._assert_payable:563`, which both refuse a transfer whose
	`refund_status` is `Approved` or `Completed`. Use it for work queues and for
	anything that answers "what may a cashier do now".

	**It is not the liability filter, and using it as one understates the books.**
	`approve_refund` posts nothing (remittance_commands.py:982, "No posting here,
	deliberately") — the obligation and the deferred commission stay submitted in
	the GL until `complete_refund` reverses them. A balance built on this filter
	drops an approved-but-unpaid refund out of the open liability while the ledger
	is still carrying it. Balances take `_OPEN_OBLIGATION` on its own.

	The split exists because `refund_status` is a Select, so the column is nullable
	and rows written before the field existed hold NULL. SQL `NOT IN (...)` on NULL
	is NULL, which is not true, which means a plain `["not in", ...]` filter would
	quietly hide exactly the oldest transfers. `_remittance_actions._refund_state`
	already normalises None and "" to "None" for the same reason; this is that
	normalisation expressed as two shapes a database can index.
	"""
	return (
		{**base, "refund_status": ["not in", ("Approved", "Completed")]},
		{**base, "refund_status": ["is", "not set"]},
	)


def _payable_rows(rows: list[dict]) -> list[dict]:
	"""The subset of an open-obligation set a cashier could pay out today.

	The Python twin of `_refund_open`, for the one caller that needs both readings
	of the same set and would otherwise pay for a second query to get them.
	`actions._refund_state` is reused rather than re-tested here so "a refund is in
	flight" has exactly one definition in the app.
	"""
	return [row for row in rows if actions._refund_state(row) not in ("Approved", "Completed")]


def _queue_shapes(queue: str) -> tuple[dict, ...]:
	"""The AND-shapes whose union is `queue`. Company is added by the caller."""
	if queue == READY_FOR_PAYOUT:
		# Mirrors `_remittance_actions._payable`: posted obligation, unlocked code,
		# no refund in flight. `code_locked` is a Check, so it is never NULL and
		# needs no split.
		return _refund_open(
			{"operational_status": "Registered", "accounting_status": "Posted", "code_locked": 0}
		)
	if queue == EXPIRING_12H:
		horizon = add_to_date(now_datetime(), hours=_EXPIRING_WITHIN_HOURS)
		return _refund_open(
			{
				"operational_status": "Registered",
				"accounting_status": "Posted",
				"expires_at": ["between", (now_datetime(), horizon)],
			}
		)
	if queue == EXPIRED_REFUND_REQUIRED:
		# Still owed to somebody, and the deadline is behind us. `Expired` is
		# included beside `Registered` because whatever eventually writes
		# `expires_at` is expected to move the operational status too, and a
		# transfer that has been marked Expired is the *most* refund-required row
		# there is — a queue that dropped it would go empty at the moment it filled.
		return _refund_open(
			{
				"operational_status": ["in", ("Registered", "Expired")],
				"expires_at": ["<", now_datetime()],
			}
		)
	if queue == REFUND_AWAITING_APPROVAL:
		# Requested AND Approved. `Requested` alone left the approved-but-unpaid
		# refund in NO queue on the whole screen: `_refund_open` deliberately takes
		# it off the three payout queues, `LOCKED_PICKUP_CODE` wants a locked code,
		# and the exception shapes describe a broken row, which this one is not. So
		# the single state that has a cashier standing at a drawer — origin desk,
		# counting the cash back out — was the state operations could not see.
		# PROMPT_remittance_design_v2.txt:271-273 requires it be reachable and
		# visible. One queue can carry both because the row's own `allowed_actions`
		# is what separates "approve this" from "pay this refund out"; the screen
		# reads that array and never infers a button from a status.
		return ({"refund_status": ["in", ("Requested", "Approved")]},)
	if queue == LOCKED_PICKUP_CODE:
		return ({"operational_status": "Registered", "code_locked": 1},)
	if queue == ACCOUNTING_EXCEPTION:
		return _EXCEPTION_SHAPES
	frappe.throw(_("Unknown remittance queue: {0}").format(queue))


# --------------------------------------------------------------------------- #
# Query plumbing
# --------------------------------------------------------------------------- #
def _money(value) -> float:
	"""Round to the system currency precision — the same read the commands make."""
	return flt(value, _send_precision())


def _date_window(field: str, from_date: str | None, to_date: str | None) -> dict:
	"""A half-open or closed window on a Datetime column, without a made-up bound.

	`["<=", "2026-08-17"]` on a Datetime means midnight, which silently drops the
	whole day the caller asked for. Frappe's `between` expands a bare date pair to
	the full span; a single bound has to be widened by hand.
	"""
	if from_date and to_date:
		return {field: ["between", (from_date, to_date)]}
	if from_date:
		return {field: [">=", f"{from_date} 00:00:00"]}
	if to_date:
		return {field: ["<=", f"{to_date} 23:59:59.999999"]}
	return {}


def _sort_value(value):
	"""One comparable per cell: NULL-safe, and type-safe across a mixed column.

	The leading flag keeps NULLs in a class of their own, so a `None` is never
	compared against a datetime. They land first on ascending, which is what
	MariaDB does — the SQL path and the Python path below must not disagree about
	where an unset `expires_at` goes.

	Numbers stay numbers: `code_attempts` is an Int, and sorting it as text would
	rank 9 above 10 — the queue would bury the transfer closest to being lost.
	Everything else compares as text, which is chronological for a datetime
	because the rendering is ISO-shaped, and lets a `datetime` object and a stored
	string sit in the same set without either being converted first.
	"""
	if value is None or value == "":
		return (0, 0.0, "")
	if isinstance(value, (int, float)) and not isinstance(value, bool):
		return (1, float(value), "")
	return (1, 0.0, str(value))


def _sorted_by(rows, order_by: str) -> list[dict]:
	"""`rows` in the order `order_by` asks for, for the union path where SQL cannot.

	One spelling of the order and two executors: the single-shape path hands the
	string to the database, the union path hands it here. A queue must not be
	sorted by urgency until the moment a second shape appears and then silently
	fall back to something else.

	Applied right to left because Python's sort is stable — that is how a
	multi-key order is built out of single-key passes, and it is the only way to
	honour a clause that mixes `asc` and `desc`.
	"""
	ordered = list(rows)
	for clause in reversed([part.strip() for part in (order_by or "").split(",") if part.strip()]):
		field, _sep, direction = clause.partition(" ")
		ordered.sort(
			key=lambda row, f=field: _sort_value(row.get(f)),
			reverse=direction.strip().lower() == "desc",
		)
	return ordered


def _select(
	shapes,
	fields,
	*,
	or_filters=None,
	order_by: str = _ORDER,
	limit: int = 0,
	offset: int = 0,
) -> tuple[list[dict], int]:
	"""Rows and an untruncated total for the union of `shapes`.

	`frappe.get_list`, never `frappe.get_all`: the row scope for Remittance
	Transfer lives in `permissions.remittance_transfer_query`, and `get_all` sets
	`ignore_permissions`, which is the switch that turns that hook off.

	One shape is the common case and SQL does the paging and the counting. More
	than one means an OR across different columns, which Frappe's filter API
	cannot express in a single query, so those are unioned by name in Python.
	Only the exception shapes and the refund-NULL split take that path, and both
	are bounded by construction — an exception queue with thousands of rows is a
	broken ledger, not a paging problem.
	"""
	safe = list(actions.assert_safe_fields(fields))
	if "name" not in safe:
		# The union dedupes on it, and a missing key would be a KeyError at runtime.
		safe = ["name", *safe]
	page = max(0, cint(limit))
	start = max(0, cint(offset))
	if not shapes:
		# No shape can satisfy the caller's filters — an honest empty answer, not
		# an unfiltered query. See `transfers`, where an explicit status can rule
		# out every exception shape.
		return [], 0

	if len(shapes) == 1:
		args = {"filters": dict(shapes[0]), "fields": safe, "order_by": order_by}
		if or_filters:
			args["or_filters"] = list(or_filters)
		rows = frappe.get_list(TRANSFER, limit_page_length=page, limit_start=start, **args)
		# Counted by pulling names, not with `count(name) as total`: Frappe v16
		# rejects a SQL function in a string SELECT — same refusal that took the
		# imports board down on msa (see crm.py:220).
		count_args = dict(args)
		count_args["fields"] = ["name"]
		count_args.pop("order_by", None)
		total = len(frappe.get_list(TRANSFER, limit_page_length=0, **count_args))
		return rows, total

	seen: dict[str, dict] = {}
	for shape in shapes:
		args = {"filters": dict(shape), "fields": safe, "order_by": order_by, "limit_page_length": 0}
		if or_filters:
			args["or_filters"] = list(or_filters)
		for row in frappe.get_list(TRANSFER, **args):
			seen[row["name"]] = row

	rows = _sorted_by(seen.values(), order_by)
	total = len(rows)
	if page:
		return rows[start : start + page], total
	return rows[start:], total


def _scoped(company: str, shapes) -> tuple[dict, ...]:
	"""Stamp the company onto every shape. The row-level hook scopes too; this is
	the caller's explicit ask, and the two agreeing is the point."""
	return tuple({"company": company, **shape} for shape in shapes)


def _search(query: str | None) -> list | None:
	term = (query or "").strip()
	if not term:
		return None
	return [[field, "like", f"%{term}%"] for field in _SEARCH_FIELDS]


def _decorate(rows: list[dict]) -> list[dict]:
	"""Stamp the server's answer onto every row: what may be done, and what next.

	One `frappe.get_roles()` read for the whole page — the role set cannot change
	mid-response and a per-row lookup would be N queries to answer one question.
	`next_action` is the first entry of `allowed_actions`, in `_remittance_actions`
	table order; that order runs payout → unlock → refund request → decision →
	completion, which is the order a desk works them. The full list stays on the
	row and is the authority.
	"""
	actions.annotate(rows, frappe.get_roles())
	for row in rows:
		offered = row.get("allowed_actions") or []
		row["next_action"] = offered[0] if offered else None
	return rows


def _expiry_policy_configured(company: str) -> bool:
	"""Does ANY transfer in this company carry an expiry?

	Measured, not assumed. Nothing in the app writes `expires_at` today, so this
	is `False` everywhere — but it is `False` because the data says so, not
	because a constant here says so, and the day a policy lands the queues fill
	on their own instead of waiting for someone to remember this line.
	"""
	return bool(
		frappe.get_list(
			TRANSFER,
			filters={"company": company, "expires_at": ["is", "set"]},
			fields=["name"],
			limit_page_length=1,
		)
	)


def _by_currency(rows: list[dict], currency_field: str, amount_field: str) -> list[dict]:
	"""Money grouped by its own currency, never added across them (ADR-011).

	`currency_field` differs per scorecard on purpose: what the sender handed over
	is denominated in `send_currency`, what the receiver collects in
	`receive_currency`. Summing the two would produce a number that is not an
	amount of anything.
	"""
	buckets: dict[str, dict] = {}
	for row in rows:
		code = row.get(currency_field) or ""
		bucket = buckets.setdefault(code, {"currency": code, "count": 0, "amount": 0.0})
		bucket["count"] += 1
		bucket["amount"] += flt(row.get(amount_field))
	for bucket in buckets.values():
		bucket["amount"] = _money(bucket["amount"])
	return sorted(buckets.values(), key=lambda bucket: bucket["currency"])


def _currency_filter(currency: str | None) -> dict:
	"""Restrict to one currency on either leg, or to none at all.

	Expressed as an OR over the two legs would need `or_filters`, which the search
	term already owns — so a currency filter matches the SEND leg, which is the
	leg the cashier took the cash in. Documented rather than guessed at.
	"""
	code = (currency or "").strip()
	return {"send_currency": code} if code else {}


def _narrow(shapes, extra: dict):
	"""Stamp one more condition onto every shape. An AND across the whole union."""
	if not extra:
		return tuple(shapes)
	return tuple({**shape, **extra} for shape in shapes)


def _desk_shapes(shapes, desk: str | None):
	"""Narrow every shape to one cash desk — on EITHER leg, which is the point.

	A desk's work on the operations screen sits on both legs. It pays out the
	transfers arriving at it, and it counts cash back out on refunds of transfers
	it registered — `complete_refund` happens at the ORIGIN desk. Filtering on one
	leg would hide half of what that desk owes, which is the same failure this
	bead was opened for.

	Expressed as doubled shapes rather than as `or_filters`: `or_filters` is
	already owned by the search term (`_search`), and `_select` unions shapes by
	name anyway — the route `_refund_open` already takes for its NULL split. The
	cost is one extra query per shape, paid only when a desk is actually picked.
	"""
	branch = (desk or "").strip()
	if not branch:
		return tuple(shapes)
	return tuple(
		{**shape, leg: branch} for shape in shapes for leg in ("origin_branch", "destination_branch")
	)


def _transfers_named(
	company: str,
	names: list[str],
	fields,
	extra: dict | None = None,
	desk: str | None = None,
) -> list[dict]:
	"""Rows for a set of names the caller already narrowed, still permission-scoped."""
	if not names:
		return []
	rows, _total = _select(
		_scoped(company, _desk_shapes(({**(extra or {}), "name": ["in", names]},), desk)),
		fields,
		order_by=_ORDER,
	)
	return rows


def _event_transfer_names(event_type: str, from_date: str | None, to_date: str | None) -> list[str]:
	"""Which transfers saw `event_type` inside the window.

	The master carries `registered_at` and nothing else — there is no
	`paid_out_at`, no `refunded_at`. The append-only event trail is the only place
	the app records *when* a stage happened, so every "today" and every window
	that is not about registration is answered from it. Remittance Event has no
	company column of its own; `permissions.remittance_event_query` scopes it
	through the parent transfer, and the company filter is applied again when the
	transfers themselves are fetched.
	"""
	filters = {"event_type": event_type}
	filters.update(_date_window("occurred_at", from_date, to_date))
	rows = frappe.get_list(
		EVENT,
		filters=filters,
		fields=["transfer"],
		limit_page_length=0,
	)
	return sorted({row["transfer"] for row in rows if row.get("transfer")})


# --------------------------------------------------------------------------- #
# 1. Operations summary
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def operations_summary(company: str, currency: str | None = None, desk: str | None = None) -> dict:
	"""The scorecards and the six queue counts for one company's operations screen.

	Every money figure is a list of per-currency rows. There is no grand total and
	there will not be one: USD, EUR and USDT do not add up, and the screen is a
	cash desk's, where a wrong total is a wrong drawer.

	Counts *are* summed, because a count is dimensionless — "eleven transfers"
	means the same thing whatever they are denominated in.

	`commission` reports two figures with different shapes on purpose, and says so
	in the key names: `deferred_open` is a BALANCE (commission sitting in the
	deferred account against obligations nobody has collected yet, all-time), and
	`earned_today` is a FLOW (commission that moved to income when a transfer was
	paid out today). Reporting them under one heading without saying which is
	which is how a desk double-counts its own revenue.

	`currency` narrows to one send leg, `desk` to one cash desk on either leg. Both
	narrow the queue COUNTS as well as the scorecards, because the counts sit on
	the same screen as the queue rows the same two filters narrow — a tile reading
	11 above a list of 3 is a screen contradicting itself.
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company = _require_company(company)
	today = nowdate()
	code = _currency_filter(currency)

	def scoped(*shapes):
		return _scoped(company, _desk_shapes(shapes, desk))

	registered_today, _n = _select(
		scoped({**code, **_date_window("registered_at", today, today)}),
		_ROW_FIELDS,
	)
	# Read once, split twice. `open_obligation` is what the ledger is still short;
	# `in_transit` is the payable subset of it. An approved-but-uncompleted refund
	# is in the first and not the second, and that difference is the whole reason
	# the two are not the same list — see `_refund_open`.
	open_obligation, _n = _select(scoped({**code, **_OPEN_OBLIGATION}), _ROW_FIELDS)
	in_transit = _payable_rows(open_obligation)
	paid_out_today = _transfers_named(
		company, _event_transfer_names("Payout", today, today), _ROW_FIELDS, extra=code, desk=desk
	)

	queues = {}
	for queue in QUEUES:
		configured = queue not in EXPIRY_QUEUES or _expiry_policy_configured(company)
		if not configured:
			queues[queue] = {"count": 0, "policy_configured": False}
			continue
		_rows, total = _select(
			_scoped(company, _desk_shapes(_narrow(_queue_shapes(queue), code), desk)),
			("name",),
			limit=1,
		)
		queues[queue] = {"count": total, "policy_configured": True}

	payload = {
		"company": company,
		"currency": (currency or "").strip() or None,
		"desk": (desk or "").strip() or None,
		"as_of": str(now_datetime()),
		"scorecards": {
			"registered_today": {
				"count": len(registered_today),
				"denominated_in": "send_currency",
				"rows": _by_currency(registered_today, "send_currency", "tendered"),
			},
			"in_transit_ready_payout": {
				"count": len(in_transit),
				"denominated_in": "receive_currency",
				"rows": _by_currency(in_transit, "receive_currency", "receiver_amount"),
			},
			"paid_out_today": {
				"count": len(paid_out_today),
				"denominated_in": "receive_currency",
				"rows": _by_currency(paid_out_today, "receive_currency", "receiver_amount"),
			},
			"commission": {
				"denominated_in": "send_currency",
				# The BALANCE, so it reads the open obligation and not the payable
				# subset: commission deferred against a transfer whose refund was
				# approved this morning is still sitting in the deferred account
				# tonight, because only `complete_refund` reverses that leg.
				"deferred_open": _by_currency(open_obligation, "send_currency", "commission"),
				"earned_today": _by_currency(paid_out_today, "send_currency", "commission"),
			},
			"exceptions": {"count": queues[ACCOUNTING_EXCEPTION]["count"]},
		},
		"queues": queues,
	}
	return actions.assert_no_pickup_code(payload)


# --------------------------------------------------------------------------- #
# 2. Work queues
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def work_queue(
	company: str,
	queue: str,
	limit=50,
	offset=0,
	currency: str | None = None,
	desk: str | None = None,
) -> dict:
	"""One of the six operations queues, paged, sorted by its own urgency signal.

	The two expiry queues answer `policy_configured: False` with no rows until
	something actually writes `expires_at`. That flag is the whole contract with
	the screen: it must render "no expiry policy is configured" rather than "no
	transfers are expiring", because those are opposite statements and only one of
	them is true today.

	`currency` and `desk` are the same two filters `operations_summary` takes, and
	they exist here because a filter that narrowed only the scorecards above the
	queue read as a filter that had silently failed.
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company = _require_company(company)
	queue = (queue or "").strip()
	if queue not in QUEUES:
		frappe.throw(_("Unknown remittance queue: {0}").format(queue))

	configured = queue not in EXPIRY_QUEUES or _expiry_policy_configured(company)
	if not configured:
		return actions.assert_no_pickup_code(
			{
				"company": company,
				"queue": queue,
				"currency": (currency or "").strip() or None,
				"desk": (desk or "").strip() or None,
				"policy_configured": False,
				"total": 0,
				"limit": max(1, min(cint(limit) or 50, 200)),
				"offset": max(0, cint(offset)),
				"rows": [],
			}
		)

	page = max(1, min(cint(limit) or 50, 200))
	start = max(0, cint(offset))
	shapes = _desk_shapes(_narrow(_queue_shapes(queue), _currency_filter(currency)), desk)
	rows, total = _select(
		_scoped(company, shapes),
		_ROW_FIELDS,
		order_by=_QUEUE_ORDER[queue],
		limit=page,
		offset=start,
	)
	return actions.assert_no_pickup_code(
		{
			"company": company,
			"queue": queue,
			"currency": (currency or "").strip() or None,
			"desk": (desk or "").strip() or None,
			"policy_configured": True,
			"total": total,
			"limit": page,
			"offset": start,
			"rows": _decorate(rows),
		}
	)


# --------------------------------------------------------------------------- #
# 3. Transfer list
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def transfers(
	company: str,
	query: str | None = None,
	status: str | None = None,
	currency: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	has_exception=None,
	limit=50,
	offset=0,
) -> dict:
	"""The searchable, filterable transfer list behind the Transfers tab.

	`query` matches the reference (either the remittance id or the client request
	id), either party, or the desk — origin and destination branch and city. A
	supervisor looking for "what went through Samarkand" searches the desk, and
	before this endpoint the only way to find a transfer was to know its id.

	`status` filters `operational_status`, the axis a human means by "status".
	The other three axes are on every row and the detail view separates all four.

	`has_exception` truthy narrows to the accounting exceptions; explicitly falsy
	excludes them; omitted filters nothing.
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company = _require_company(company)
	page = max(1, min(cint(limit) or 50, 200))
	start = max(0, cint(offset))

	base: dict = {}
	base.update(_currency_filter(currency))
	base.update(_date_window("registered_at", from_date, to_date))
	if (status or "").strip():
		base["operational_status"] = status.strip()

	if has_exception in (None, ""):
		shapes: tuple[dict, ...] = (base,)
	elif cint(has_exception):
		# An exception shape that pins `operational_status` and an explicit status
		# filter can contradict each other. Drop the shapes that cannot hold rather
		# than letting either side silently win — if none survive, the honest answer
		# is that no exception can be in that status, which is an empty list.
		wanted = base.get("operational_status")
		shapes = tuple(
			{**base, **shape}
			for shape in _EXCEPTION_SHAPES
			if not wanted or shape.get("operational_status") in (None, wanted)
		)
	else:
		# The complement, expressed as AND-able conditions. `!=` on a NULL column
		# would drop the row, so this deliberately does not touch nullable Selects
		# it does not have to: `operational_status` and `accounting_status` are
		# written on insert by `register_remittance` and are never NULL for a V1 row.
		shapes = (
			{
				**base,
				"operational_status": ["!=", "Exception"],
				"accounting_status": ["not in", ("Unposted", "Posting Error")],
			},
		)

	rows, total = _select(
		_scoped(company, shapes),
		_ROW_FIELDS,
		or_filters=_search(query),
		limit=page,
		offset=start,
	)
	return actions.assert_no_pickup_code(
		{
			"company": company,
			"total": total,
			"limit": page,
			"offset": start,
			"rows": _decorate(rows),
		}
	)


# --------------------------------------------------------------------------- #
# 4. One transfer, in full
# --------------------------------------------------------------------------- #
def _refund_trail(events: list[dict]) -> dict:
	"""Who asked for the refund, who decided, and what they said.

	Read off the event trail rather than off the master, because the master holds
	only the current `refund_status` — it cannot say who approved it or why it was
	rejected, and "the manager who signed off" is the entire audit question.
	"""
	wanted = {
		"Refund request": "requested",
		"Refund approval": "approved",
		"Refund rejection": "rejected",
		"Refund completion": "completed",
	}
	trail: dict = {stage: None for stage in wanted.values()}
	for event in events:
		stage = wanted.get(event.get("event_type"))
		if not stage:
			continue
		# Last one wins: a request can be rejected, re-requested and approved, and
		# the screen shows the decision that stands.
		trail[stage] = {
			"at": str(event.get("occurred_at") or ""),
			"actor": event.get("actor"),
			"branch": event.get("branch"),
			"details": event.get("details"),
		}
	return trail


@frappe.whitelist()
def transfer_detail(name: str) -> dict:
	"""Everything about one transfer except the one thing nobody may read.

	The quote is the frozen triple the cashier typed plus `register_base_rate` —
	the rate the register leg actually posted at. ADR-008 forbids re-fetching a
	rate on the payout leg, so the stored one is the only honest thing to show:
	recomputing it here would render a number the ledger does not contain.

	`code_state` returns the attempt COUNTER and the lockout, never the code or
	its digest. `code_attempts` against `max_attempts` is what tells a manager
	whether to unlock; the code itself was shown once, at registration, and this
	endpoint is not a second chance at it.

	That block is called `code_state` and not `pickup_code` because
	`assert_no_pickup_code` checks response KEYS, and a key with the forbidden
	name fails the guard whatever it holds. Which is correct: the reviewer reading
	`"pickup_code": {...}` in a response body cannot tell from the name that the
	value is a counter, and neither can the guard.
	"""
	name = (name or "").strip()
	if not name:
		frappe.throw(_("A transfer id is required."))
	# @frappe.whitelist() gates the method, not the record — this is the IDOR guard.
	_assert_can_read(TRANSFER, name)

	rows = frappe.get_list(
		TRANSFER,
		filters={"name": name},
		fields=list(actions.assert_safe_fields(_DETAIL_FIELDS)),
		limit_page_length=1,
	)
	if not rows:
		frappe.throw(_("Transfer {0} was not found.").format(name))
	transfer = rows[0]

	events = frappe.get_list(
		EVENT,
		filters={"transfer": name},
		fields=list(actions.assert_safe_fields(_EVENT_FIELDS)),
		order_by="occurred_at asc, name asc",
		limit_page_length=0,
	)

	links = [
		transfer.get("register_journal_entry"),
		transfer.get("payout_journal_entry"),
		transfer.get("refund_journal_entry"),
	]
	entry_names = [link for link in links if link]
	# Asked, not attempted. `frappe.get_list` on another doctype calls
	# `has_permission(..., throw=True)` (frappe/model/db_query.py:621), and none of
	# the four remittance roles carries Journal Entry read — the JE doctype grants
	# it to Accounts User, Accounts Manager and Auditor only, and v87 grants no
	# DocPerm on it. Letting the read throw would 403 the WHOLE endpoint, so a
	# cashier could not open any transfer at all: not the quote, not the four
	# status axes, not the lockout counter. The ledger block is the Auditor's
	# (plan:460); everyone else gets the transfer without it.
	entries_readable = frappe.has_permission(JOURNAL, "read")
	entries = (
		frappe.get_list(
			JOURNAL,
			filters={"name": ["in", entry_names]},
			fields=list(actions.assert_safe_fields(_JOURNAL_FIELDS)),
			order_by="posting_date asc, name asc",
			limit_page_length=0,
		)
		if entry_names and entries_readable
		else []
	)

	payload = {
		"transfer": transfer,
		"allowed_actions": actions.allowed_actions(transfer, frappe.get_roles()),
		"quote": {
			"commission_mode": transfer.get("commission_mode"),
			"commission_pct": transfer.get("commission_pct"),
			"principal": _money(transfer.get("principal")),
			"commission": _money(transfer.get("commission")),
			"tendered": _money(transfer.get("tendered")),
			"receiver_amount": _money(transfer.get("receiver_amount")),
			"send_currency": transfer.get("send_currency"),
			"receive_currency": transfer.get("receive_currency"),
			"exchange_rate": transfer.get("exchange_rate"),
			"register_base_rate": transfer.get("register_base_rate"),
		},
		# Four axes, kept apart. Collapsing them into one badge is what made the
		# legacy screen unable to say "paid out, but the reversal never posted".
		"status": {
			"operational": transfer.get("operational_status"),
			"accounting": transfer.get("accounting_status"),
			"verification": transfer.get("verification_status"),
			"refund": transfer.get("refund_status"),
		},
		"stages": events,
		"journal_entries": entries,
		# An empty list means two opposite things and the screen must be able to
		# tell them apart: "this transfer has posted nothing" and "you may not read
		# the ledger". Rendering "No journal entries" at a caller who simply lacks
		# the permission is the same class of lie as an expiry queue reporting
		# "nothing is expiring" when no policy exists.
		"journal_entries_visible": entries_readable,
		"code_state": {
			"attempts": cint(transfer.get("code_attempts")),
			"max_attempts": _max_code_attempts(transfer.get("company")),
			"locked": bool(cint(transfer.get("code_locked"))),
			"locked_at": str(transfer.get("code_locked_at") or "") or None,
		},
		"refund": {"status": transfer.get("refund_status"), **_refund_trail(events)},
		"audit": {
			"created_by": transfer.get("owner"),
			"created_at": str(transfer.get("creation") or "") or None,
			"registered_by": transfer.get("registered_by"),
			"registered_at": str(transfer.get("registered_at") or "") or None,
			"last_modified_at": str(transfer.get("modified") or "") or None,
		},
	}
	return actions.assert_no_pickup_code(payload)


# --------------------------------------------------------------------------- #
# 5. Reconciliation
# --------------------------------------------------------------------------- #
def _aged(rows: list[dict]) -> list[dict]:
	"""Open transfers with their age in days, oldest first.

	No aging THRESHOLD is applied, because none exists: nothing in the app defines
	when an open obligation becomes overdue. Reporting the age and letting a human
	judge is honest; picking 7 or 30 here would be this module inventing policy
	and then presenting it as a finding.
	"""
	now = now_datetime()
	aged = []
	for row in rows:
		registered = row.get("registered_at")
		if not registered:
			continue
		age = (now - get_datetime(registered)).days
		aged.append({**row, "age_days": age})
	return sorted(aged, key=lambda row: row["age_days"], reverse=True)


def _by_branch(rows: list[dict]) -> list[dict]:
	"""Open liability per desk and per currency — the shape a branch reconciles in."""
	buckets: dict[tuple, dict] = {}
	for row in rows:
		key = (row.get("origin_branch") or "", row.get("receive_currency") or "")
		bucket = buckets.setdefault(
			key,
			{"branch": key[0], "currency": key[1], "count": 0, "open_amount": 0.0},
		)
		bucket["count"] += 1
		bucket["open_amount"] += flt(row.get("receiver_amount"))
	for bucket in buckets.values():
		bucket["open_amount"] = _money(bucket["open_amount"])
	return sorted(buckets.values(), key=lambda bucket: (bucket["branch"], bucket["currency"]))


@frappe.whitelist()
def reconciliation(company: str, from_date: str | None = None, to_date: str | None = None) -> dict:
	"""What the cash desk took in, what it paid out, and what it still owes.

	Two of these figures are FLOWS over the window and one is a BALANCE that
	ignores it, and conflating them is the classic reconciliation error:

	* `register_cash_in`, `payout_cash_out`, `refund_cash_out` are flows — they
	  answer "in this window".
	* `open_in_transit_liability` is a balance and is deliberately ALL-TIME. An
	  obligation opened three months ago is still owed today; windowing it would
	  report a liability that shrinks when you narrow the date filter, which is
	  the opposite of what a liability does.

	For the same reason it does not exclude transfers whose refund has been
	APPROVED. Approval authorises the cash; it posts nothing. Until
	`complete_refund` runs, the obligation and its deferred commission are still
	submitted in the GL, so a screen that dropped those rows would report a
	liability the ledger disagrees with — the same error as windowing it, arrived
	at from the other side.

	Cash-out is dated from the event trail, not from `modified`: the master has no
	payout timestamp, and `modified` moves on any write at all.
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company = _require_company(company)

	registered, _n = _select(
		_scoped(
			company,
			(
				{
					**_date_window("registered_at", from_date, to_date),
					"accounting_status": ["in", ("Posted", "Reversed")],
				},
			),
		),
		_RECON_FIELDS,
	)
	# `_OPEN_OBLIGATION` alone, deliberately not `_refund_open`: an approved refund
	# reverses nothing (remittance_commands.py:982), so the row is still a debt
	# until `complete_refund` posts. Filtering it out here is how a reconciliation
	# screen reports less than the general ledger is carrying.
	open_rows, _n = _select(_scoped(company, (dict(_OPEN_OBLIGATION),)), _RECON_FIELDS)
	paid_out = _transfers_named(company, _event_transfer_names("Payout", from_date, to_date), _RECON_FIELDS)
	refunded = _transfers_named(
		company, _event_transfer_names("Refund completion", from_date, to_date), _RECON_FIELDS
	)
	variance, variance_total = _select(
		_scoped(company, _VARIANCE_SHAPES), _RECON_FIELDS, limit=_EXCEPTION_LIST_CAP
	)

	aged = _aged(open_rows)
	configured = _expiry_policy_configured(company)

	payload = {
		"company": company,
		"from_date": from_date or None,
		"to_date": to_date or None,
		"as_of": str(now_datetime()),
		"register_cash_in": _by_currency(registered, "send_currency", "tendered"),
		"payout_cash_out": _by_currency(paid_out, "receive_currency", "receiver_amount"),
		"refund_cash_out": _by_currency(refunded, "send_currency", "tendered"),
		"open_in_transit_liability": _by_currency(open_rows, "receive_currency", "receiver_amount"),
		"commission": {
			"denominated_in": "send_currency",
			"deferred_open": _by_currency(open_rows, "send_currency", "commission"),
			"earned_in_window": _by_currency(paid_out, "send_currency", "commission"),
			"registered_in_window": _by_currency(registered, "send_currency", "commission"),
		},
		# A stage whose status says it posted, naming no entry. This is the
		# master ↔ JE difference, read off the master; the ledger-side total is a
		# separate bench-only report and is not claimed here.
		"variance": {
			"count": variance_total,
			"truncated": variance_total > len(variance),
			"rows": _decorate(variance),
		},
		"aged_open": {
			"count": len(aged),
			"truncated": len(aged) > _EXCEPTION_LIST_CAP,
			"rows": _decorate(aged[:_EXCEPTION_LIST_CAP]),
		},
		# Empty and honest about why: nothing writes `expires_at`, so there is no
		# expired set to report — not "none expired", but "no policy exists".
		"expired": {"policy_configured": configured, "count": 0, "rows": []},
		"by_branch": _by_branch(open_rows),
	}

	if configured:
		expired, expired_total = _select(
			_scoped(company, _queue_shapes(EXPIRED_REFUND_REQUIRED)),
			_RECON_FIELDS,
			limit=_EXCEPTION_LIST_CAP,
		)
		payload["expired"] = {
			"policy_configured": True,
			"count": expired_total,
			"truncated": expired_total > len(expired),
			"rows": _decorate(expired),
		}

	return actions.assert_no_pickup_code(payload)


#: The stage a caller may preview, and the action that entitles them to it. The
#: gate is the action and not `read` on the doctype — see `posting_preview`.
#: Register is absent on purpose, and the docstring says why.
_PREVIEW_STAGES = {
	PAYOUT: actions.PAYOUT,
	REFUND: actions.COMPLETE_REFUND,
}


@frappe.whitelist()
def posting_preview(name: str, stage: str, posting_date: str | None = None) -> dict:
	"""The rows one stage will write to the ledger, before it writes them.

	Built by `remittance_accounting.build_legs` — the same call the poster makes,
	not a second model of it. A screen that computes its own version of a journal
	entry agrees with the books right up until one of the two is edited, and what
	is at stake on this particular screen is a cashier counting notes against a
	number the ledger does not hold.

	WHAT THE BASE COLUMN IS. Every leg carries its amount twice: once in the
	account's own currency and once in the company's base currency, which is what
	`debit`/`credit` hold and what the entry balances on. Cross-currency entries do
	not balance per currency and are not supposed to — the base column is the only
	place the reader can see it close.

	WHERE THE BASE VALUE COMES FROM, and its limit. At Register the send->base rate
	is the market rate of the posting day, fetched once. From then on Payout and
	Refund use `register_base_rate`, frozen at registration and never re-fetched
	(ADR-008) — which is why a payout mirrors its register leg exactly instead of
	drifting with the market. So the base figures are honest about the ledger and
	are NOT a live valuation: a transfer registered in March is still shown at
	March's rate. That is the accounting intent, not a gap. The gap is upstream —
	one rate per currency per day, rather than the accounting period's rate table
	— and it is the same rate the entry itself posts at, so the screen cannot be
	more accurate than the books it previews.

	Read-only in the strict sense: nothing here inserts, and no draft Journal Entry
	is created to render a preview.

	WHO MAY ASK. The gate is the action, not `read` on the doctype. This payload is
	GL account names, debits, credits and a transfer's base valuation — the class of
	content `transfer_detail` withholds from a caller who cannot read Journal Entry.
	Doctype read would be the wrong gate: `Remittance Viewer` and `Remittance
	Auditor` hold it, and a loop over their own list would enumerate every desk cash,
	obligation, deferred-commission and commission-income account the company has,
	with `resolve_accounts`'s configuration errors as a bonus probe. Journal Entry
	read would be the wrong gate too — none of the four remittance roles carries it,
	so gating on that would blank the preview on the one screen it exists for. What
	is left is the right one: a caller sees the legs of a posting they may actually
	make on THIS transfer, decided by the same `allowed_actions` that decides whether
	the button exists. So a stage that cannot happen is not previewed, whether the
	reason is the caller's roles or the state the transfer already reached.

	Register is not previewable here, and that is not an oversight. It is the one
	stage with no action to gate it; no screen asks for it, because the screen that
	would — New Transfer — has no transfer yet, and this endpoint refuses
	caller-supplied amounts by design (below); and once a transfer HAS registered,
	`transfer_detail` already serves the entry that was actually posted. The
	pre-registration preview stays unbuilt rather than half-built.

	Deliberately keyed on an EXISTING transfer and not on caller-supplied amounts:
	an endpoint that resolves GL accounts and builds legs from numbers in the
	request is a convenient way to probe another company's account configuration.
	The pre-registration preview on New Transfer is therefore not served from here.
	"""
	name = (name or "").strip()
	stage = (stage or "").strip()
	if not name:
		frappe.throw(_("A transfer id is required."))
	if stage not in _PREVIEW_STAGES:
		frappe.throw(_("{0} is not a remittance posting stage.").format(stage or "—"))

	# @frappe.whitelist() gates the method, not the record — this is the IDOR guard.
	_assert_can_read(TRANSFER, name)
	transfer = frappe.get_doc(TRANSFER, name)
	_assert_company_scope(transfer.company)
	_require_company(transfer.company)

	if _PREVIEW_STAGES[stage] not in actions.allowed_actions(transfer, frappe.get_roles()):
		frappe.throw(_("You cannot make this posting, so it is not previewed."), frappe.PermissionError)

	built = build_legs(transfer, stage, posting_date or frappe.utils.nowdate())
	base_currency = frappe.get_cached_value("Company", transfer.company, "default_currency")

	rows = []
	# Summed as Decimal, because `build_legs` already proved these two EXACTLY equal
	# (`_remittance_accounting._assert_closes` raises otherwise) and re-adding them as
	# float reopens a question that was closed. A fixed 1e-9 epsilon is below one
	# float64 ulp above ~4.5e6, and the base currency this app falls back to is UZS —
	# so the float version answered "does not balance" for sound entries, under which
	# the screen tells a cashier to refuse the payout and report a ledger fault that
	# does not exist. The screen's verdict has to be the builder's verdict.
	debit_total = Decimal(0)
	credit_total = Decimal(0)
	for leg in built["legs"]:
		row = {
			"account": leg["account"],
			"currency": leg["account_currency"],
			"debit_in_account_currency": float(leg["debit_in_account_currency"]),
			"credit_in_account_currency": float(leg["credit_in_account_currency"]),
			"debit": float(leg["debit"]),
			"credit": float(leg["credit"]),
			"exchange_rate": float(leg["exchange_rate"]),
		}
		debit_total += leg["debit"]
		credit_total += leg["credit"]
		rows.append(row)

	# Wrapped like every other whitelisted return in this module. Nothing here can
	# carry the code today — the payload is built from legs — and that is the point:
	# the guard is what catches the future edit that adds a transfer field to it.
	return actions.assert_no_pickup_code(
		{
			"stage": stage,
			"base_currency": base_currency,
			"rows": rows,
			# Summed from the same legs the rows are projected from, so a reader
			# adding the column by eye reaches the figure the totals line shows.
			"total_debit": float(debit_total),
			"total_credit": float(credit_total),
			"balanced": debit_total == credit_total,
		}
	)


__all__ = [
	"ACCOUNTING_EXCEPTION",
	"EXPIRED_REFUND_REQUIRED",
	"EXPIRING_12H",
	"EXPIRY_QUEUES",
	"LOCKED_PICKUP_CODE",
	"QUEUES",
	"READY_FOR_PAYOUT",
	"REFUND_AWAITING_APPROVAL",
	"operations_summary",
	"posting_preview",
	"reconciliation",
	"transfer_detail",
	"transfers",
	"work_queue",
]
