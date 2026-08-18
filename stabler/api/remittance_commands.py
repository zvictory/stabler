"""The remittance commands: one lock, one transaction, one pickup code.

Until this module existed the remittance master row had no writer. The four beads
that built the pieces — `get_desk_account`, `Remittance Transfer`, `price_transfer`
and `post_register` — had no caller outside their own tests, so the Journal Entry
chain was still the record and the append-only trail was empty by construction.
This is the command handler `RemittanceTransfer`'s docstring defers to: a document
cannot serialise or de-duplicate its own callers.

Three things are load-bearing, in this order.

**The lock comes first — and the state is read through it.** Both halves are
load-bearing, because a lock without a locking read only serialises; it does not
refresh. This bench runs REPEATABLE READ, where `SELECT ... FOR UPDATE` returns
the latest committed row but leaves the transaction's consistent-read snapshot
where it was — and by the time a handler runs, the session and permission reads
have already opened that snapshot. So the loser of a race blocks on the lock,
acquires it after the winner commits, and a plain `frappe.get_doc` still hands
back the *pre-race* row. It would then decide on state that no longer exists: two
cashiers both seeing `Registered`, both handing over the cash. Hence
`frappe.db.get_value(..., for_update=True)` to take the lock (and to turn a
missing row into a sentence instead of a traceback), then
`frappe.get_doc(..., for_update=True)` to read the state that the decision rests
on. `register_remittance` is the one exception and stays a plain re-read: it is
re-reading a row its own transaction just inserted, and a transaction always sees
its own writes. The transition and the Journal Entry submit then share one
transaction, which is what makes `Registered + Unposted` unreachable rather than
merely rejected — `RemittanceTransfer._assert_registered_is_posted` rejects the
pair, this ordering is what stops it ever being written. Precedent:
`api/sales.py:3264`, `integrations/uzpay/payme.py:150`, `api/crm.py:746` for the
locked read.

**A replayed key never re-executes.** `client_request_id` carries a real unique
index (`remittance_transfer.json`), so the duplicate-key race is settled by the
database and answered with the original row rather than a second transfer. The
new part is the payload check: `api/crm_automation.py` covers replay and the race
but treats any reuse of a key as the same command. Here a key reused with
*different* money is a conflict and is refused — a client that changed the amount
and kept the key has a bug, and handing it back someone else's transfer would
hide it. No payload hash is stored: the transfer already holds every field the
request set, so re-pricing the incoming request and comparing is both cheaper and
impossible to leave stale.

**The pickup code is returned exactly once.** A replay gets the transfer back
without it. Idempotency usually means "same key, same response", but this response
carries a bearer secret, and replaying a captured request is exactly how someone
would ask for it a second time. No read path exposes it either — only the hash is
stored.

The aggregate version returned on every mutation is `modified`, the token
`_common.check_concurrency` already validates. A monotonic integer was considered
and rejected: there is no precedent for one anywhere in the app, and adding one
costs a doctype field plus a patch to buy a guarantee `modified` already gives
inside a single-writer transaction.

Permissions are deliberately NOT ignored on the master row or the event, so the
right this endpoint actually spends is `create` — on `Remittance Transfer` for
`transfer.insert()` and on `Remittance Event` for the trail. Since stabler-tvma
that is Remittance Cashier, Remittance Finance Manager and System Manager.

It spends no `create` right beyond those and no `write` right at all: every
mutation after the insert goes through `transfer.db_set(...)`, which writes the
column directly and checks no permission. That is why the DocPerm rows grant no
write — a write grant could only ever serve a caller that skipped this module,
and nothing freezes the record against one. A bypass here would silently outlive
the role model, which is the whole reason it is not taken.

The SPA still shows the module to admins only: `remittance` is absent from
`_MODULE_ROLES` in `api/organization.py`. That is a UX gate, not the boundary —
the boundary is the DocPerm rows above.

**Payout is the mirror, and reuses all of the above.** `payout_transfer` takes the
same lock and reads the state it decides on through it, transitions and posts in
the same transaction, appends to the same trail and returns the same version token.
Three things are specific to it.

The pickup code is compared against the stored digest in constant time, through
the helpers in `api/remittance` — a plaintext stored value never matches, and is
refused with its real cause (an unrun migration) instead of being blamed on the
receiver. A wrong code costs an attempt; `max_code_attempts` wrong codes lock the
transfer and only a manager reopens it. There is deliberately **no time-based
auto-unlock**: `Remittance Settings.lockout_minutes` is not read here, because
whether a lockout expires on its own is an open policy question and a lockout
that silently expires is indistinguishable from one that was never applied.

The payout queue selects `Registered` **and** `Posted` positively rather than
excluding the pair, so a row whose obligation was never posted cannot reach a
cashier's screen at all — the same invariant `RemittanceTransfer` rejects and the
register command makes unreachable, enforced a third time at the point of use.

Payout carries no money in its request — the amounts come off the register entry —
so unlike register there is no payload for a replayed `client_request_id` to
conflict with. The row lock plus the recorded payout event settle it instead: a
key replayed against a transfer already paid out under that same key gets the
original result, and any other second payout is refused.

**Refund is three states, and only the last one moves cash.** `Requested` at the
origin desk, `Approved` by a Remittance Finance Manager, `Completed` when the cash
is actually counted back out — plus `Rejected`, which ends the request without
touching a ledger. Approving deliberately posts nothing: an approval that moved
money would make the manager's decision and the cashier's count the same event,
and the sender could be paid from a drawer nobody opened.

The decision that defines this shape (council decision D32) is that
`approve_refund` re-validates the *operational* state after taking the row lock,
not merely the caller's role. A role check answers "may this person approve
refunds", which is true of the manager whatever the row is doing; it says nothing
about the state at the moment of the write. Concurrent payout versus refund is a
named acceptance test, not an edge case: the cashier at the destination and the
manager at the origin act on the same row seconds apart, and without the locked
re-read the transfer is both paid out *and* refunded, with the second writer
winning silently and the obligation reversed twice. So every refund step reads
`operational_status`, `accounting_status` and `refund_status` off
`frappe.get_doc(..., for_update=True)` — through the lock, for the REPEATABLE READ
reason spelled out above — and decides on that row only.

`reject_refund` is the one step that does *not* require the transfer to still be
refundable. A request that sat in the queue while the receiver collected the cash
must still be closeable, or the row is stranded in `Requested` forever with the
only exit being a manual edit.

Every refund step is gated on a real role, and that gate is load-bearing rather
than decorative: `@frappe.whitelist()` admits any authenticated user, `db_set`
checks no permission, and `remittance_accounting._build_entry` inserts the Journal
Entry with `ignore_permissions=True`. Nothing else stands between a logged-in
stranger and a refund. The desk set (request, complete) and the approver set
(approve, reject) are deliberately different — a cashier who could approve their
own request is not a control.

**ADR-008 and the CBU band collide, and this module does not resolve it.** A
refund reverses at the frozen `register_base_rate`, while
`_accounts.validate_exchange_rate` (wired on `Journal Entry.validate`) refuses any
foreign row more than +/-20% from the CBU rate of the posting day. A corridor that
moved that far between registration and refund therefore refuses at JE validate.
Exempting, widening or approval-gating that band is an open policy decision for
the business — bead `stabler-22vj` — so nothing here widens it, overrides it or
invents a second rate. What `complete_refund` does is make the refusal legible:
the refund's own failure names the transfer and the frozen rate it tried to use,
and carries the validator's message inside it, instead of surfacing as a bare
sentence about a conversion rate the cashier never typed.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime_str, now_datetime, nowdate

from stabler.api import _remittance_actions as actions
from stabler.api._common import _require_company
from stabler.api._remittance_pricing import PricingError, price_transfer
from stabler.api.approvals import _assert_company_scope
from stabler.api.remittance import (
	_gen_pickup_code,
	_pickup_code_matches,
	is_hashed_pickup_code,
	store_pickup_code,
)
from stabler.api.remittance_accounting import post_payout, post_refund, post_register

TRANSFER = "Remittance Transfer"
EVENT = "Remittance Event"
SETTINGS = "Remittance Settings"

# What makes two requests the SAME request. A key replayed with a different value
# for any of these is a different command wearing a used key, not a retry.
_IDENTITY = (
	"company",
	"origin_branch",
	"destination_branch",
	"send_currency",
	"receive_currency",
	"sender_name",
	"receiver_name",
	"commission_mode",
)
# Field -> decimal places the comparison is made at. The rate needs more than the
# money does: two rates that differ in the fifth decimal price a large transfer
# differently, and rounding the comparison to 2 would call that a retry.
_NUMERIC = {
	"commission_pct": 4,
	"principal": 2,
	"commission": 2,
	"tendered": 2,
	"receiver_amount": 2,
	"exchange_rate": 6,
}


def _send_precision() -> int:
	# Currency.fraction stores a UOM *name* ("Cent"), not a digit count, so the
	# usable metadata is the system-wide default — same resolution as
	# vehicle_finance/v1.py:138 and remittance_accounting._base_precision.
	return cint(frappe.db.get_default("currency_precision")) or 2


def _is_duplicate_err(err: Exception) -> bool:
	"""MariaDB/MySQL duplicate-key error, however Frappe happens to wrap it."""
	dup_classes = (
		getattr(frappe, "UniqueValidationError", type("UniqueValidationError", (Exception,), {})),
		getattr(frappe, "DuplicateEntryError", type("DuplicateEntryError", (Exception,), {})),
	)
	if isinstance(err, dup_classes):
		return True
	err_str = str(err)
	return "1062" in err_str or "Duplicate entry" in err_str


def _price(payload: dict) -> dict:
	"""Turn the typed figure into the frozen triple, or refuse the request.

	`price_transfer` raises `PricingError` for a sub-unit amount or a commission
	that swallows the principal. Those are bad input, not server faults, so they
	surface as a normal validation message rather than a traceback.
	"""
	try:
		return price_transfer(
			mode=payload["commission_mode"],
			amount=payload["amount"],
			commission_pct=payload["commission_pct"],
			precision=_send_precision(),
		)
	except PricingError as err:
		frappe.throw(str(err))


def _canonical(
	*,
	company: str,
	origin_branch: str,
	destination_branch: str,
	send_currency: str,
	receive_currency: str,
	sender_name: str,
	receiver_name: str,
	amount,
	exchange_rate,
	commission_mode: str,
	commission_pct,
) -> dict:
	"""The stored shape of one request — the thing a replay is compared against."""
	rate = flt(exchange_rate)
	if rate <= 0:
		frappe.throw(_("An exchange rate is required to register a transfer."))

	priced = _price({"commission_mode": commission_mode, "amount": amount, "commission_pct": commission_pct})
	principal = float(priced["principal"])

	return {
		"company": company,
		"origin_branch": origin_branch,
		"destination_branch": destination_branch,
		"send_currency": send_currency,
		"receive_currency": receive_currency,
		"sender_name": sender_name,
		"receiver_name": receiver_name,
		"commission_mode": priced["mode"],
		"commission_pct": float(priced["commission_pct"]),
		"principal": principal,
		"commission": float(priced["commission"]),
		"tendered": float(priced["tendered"]),
		# ADR-006 carries the obligation in the receive currency, and it opens at
		# the principal — the commission never crosses the corridor.
		"receiver_amount": flt(principal * rate, 2),
		"exchange_rate": rate,
	}


def _conflicting_fields(stored, payload: dict) -> list[str]:
	"""Which fields a replay disagrees with. Empty means it is a genuine retry."""
	differs = [field for field in _IDENTITY if (stored.get(field) or "") != (payload[field] or "")]
	differs += [
		field
		for field, places in _NUMERIC.items()
		if flt(stored.get(field), places) != flt(payload[field], places)
	]
	return differs


def _version(name: str) -> str:
	"""The aggregate version: `modified`, read back from the row that just changed."""
	return get_datetime_str(frappe.db.get_value(TRANSFER, name, "modified"))


def _state(transfer, *, replayed: bool) -> dict:
	"""What every mutation returns: the money, the three statuses, the version."""
	return {
		"name": transfer.name,
		"version": _version(transfer.name),
		"replayed": replayed,
		"operational_status": transfer.operational_status,
		"accounting_status": transfer.accounting_status,
		"verification_status": transfer.verification_status,
		"principal": flt(transfer.principal, 2),
		"commission": flt(transfer.commission, 2),
		"tendered": flt(transfer.tendered, 2),
		"receiver_amount": flt(transfer.receiver_amount, 2),
		"register_journal_entry": transfer.register_journal_entry,
	}


def _result(transfer, *, pickup_code: str | None, replayed: bool) -> dict:
	return {
		**_state(transfer, replayed=replayed),
		# Present on the registering call and on no other call, ever.
		"pickup_code": pickup_code,
	}


def _replayed(name: str, payload: dict) -> dict:
	"""Answer a reused key: the original transfer, or a refusal if the money moved."""
	transfer = frappe.get_doc(TRANSFER, name)
	differs = _conflicting_fields(transfer, payload)
	if differs:
		frappe.throw(
			_(
				"Client request id {0} already registered transfer {1} with different "
				"values ({2}). Use a new request id — replaying a key must never change "
				"a transfer."
			).format(transfer.client_request_id, transfer.name, ", ".join(sorted(differs)))
		)
	return _result(transfer, pickup_code=None, replayed=True)


def _new_transfer(key: str, payload: dict, code: str, *, origin_city, destination_city):
	"""Insert the master row Draft/Unposted. Registered comes after the posting.

	The digest is written AFTER the insert, not in the payload. `pickup_code_hash` is
	permlevel 1, and Frappe resets a permlevel field the saving user cannot write --
	silently, at insert. Carrying it in the payload therefore made every registration
	depend on the v89 write grant existing on that site, and on a guard to notice when
	it did not. `db_set` writes below the permlevel layer, so the field cannot be reset
	and the site no longer has to have been migrated for a cashier to take money.

	Same transaction as the insert, so no other reader ever sees the row without it;
	and the row is Draft until `register_remittance` posts and promotes it anyway.
	"""
	transfer = frappe.get_doc(
		{
			"doctype": TRANSFER,
			"client_request_id": key,
			"origin_city": origin_city,
			"destination_city": destination_city,
			"operational_status": "Draft",
			"accounting_status": "Unposted",
			"verification_status": "Not Issued",
			"refund_status": "None",
			"code_attempts": 0,
			**payload,
		}
	)
	transfer.insert()
	transfer.db_set("pickup_code_hash", store_pickup_code(code), notify=False)
	return transfer


def _append_event(transfer, *, event_type: str, key: str | None, details: str, branch: str) -> None:
	"""One way in to the append-only trail, for every command in this module."""
	frappe.get_doc(
		{
			"doctype": EVENT,
			"transfer": transfer.name,
			"event_type": event_type,
			"occurred_at": now_datetime(),
			"actor": frappe.session.user,
			"branch": branch,
			"client_request_id": key,
			"details": details,
		}
	).insert()


@frappe.whitelist()
def register_remittance(
	company: str,
	origin_branch: str,
	destination_branch: str,
	send_currency: str,
	receive_currency: str,
	sender_name: str,
	receiver_name: str,
	amount,
	exchange_rate,
	client_request_id: str,
	commission_mode: str = "Exclusive",
	commission_pct=0,
	posting_date: str | None = None,
	origin_city: str | None = None,
	destination_city: str | None = None,
) -> dict:
	"""Take the cash, open the obligation, hand back the pickup code once."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)

	key = (client_request_id or "").strip()
	if not key:
		frappe.throw(_("A client request id is required, so a retry cannot register twice."))

	payload = _canonical(
		company=company,
		origin_branch=origin_branch,
		destination_branch=destination_branch,
		send_currency=send_currency,
		receive_currency=receive_currency,
		sender_name=sender_name,
		receiver_name=receiver_name,
		amount=amount,
		exchange_rate=exchange_rate,
		commission_mode=commission_mode,
		commission_pct=commission_pct,
	)

	seen = frappe.db.get_value(TRANSFER, {"client_request_id": key, "company": company}, "name")
	if seen:
		return _replayed(seen, payload)

	code = _gen_pickup_code()
	try:
		transfer = _new_transfer(
			key, payload, code, origin_city=origin_city, destination_city=destination_city
		)
	except Exception as err:
		# The SELECT above and this INSERT are not atomic together; the unique
		# index is what actually settles the race. Losing it is a replay, not a
		# failure — but only after the payload is checked like any other replay.
		if not _is_duplicate_err(err):
			raise
		frappe.db.rollback()
		won = frappe.db.get_value(TRANSFER, {"client_request_id": key, "company": company}, "name")
		if not won:
			raise
		return _replayed(won, payload)

	# The lock FIRST, then the state, then the write. Reading state before taking
	# it would let two callers both see Unposted and both post the obligation.
	frappe.db.get_value(TRANSFER, transfer.name, "name", for_update=True)
	transfer.reload()

	if transfer.accounting_status != "Unposted" or transfer.operational_status != "Draft":
		# Someone finished this row while we waited on the lock. Their code, not ours.
		return _result(transfer, pickup_code=None, replayed=True)

	post_register(transfer, posting_date=posting_date or nowdate())
	# Only now: post_register has already written accounting_status = Posted, so the
	# row never passes through Registered + Unposted, even for another reader.
	transfer.db_set(
		{
			"operational_status": "Registered",
			"verification_status": "Active",
			"registered_by": frappe.session.user,
			"registered_at": now_datetime(),
		},
		notify=False,
	)
	_append_event(
		transfer,
		event_type="Register",
		key=key,
		branch=transfer.origin_branch,
		details=_("Registered {0} {1} at {2}").format(
			flt(transfer.tendered, 2), transfer.send_currency, flt(transfer.exchange_rate, 6)
		),
	)

	return _result(transfer, pickup_code=code, replayed=False)


# --------------------------------------------------------------------------- #
# Payout
# --------------------------------------------------------------------------- #

# The doctype's own default, used for a company that has never opened the form.
_DEFAULT_MAX_CODE_ATTEMPTS = 5

# What the payout screen may see. `pickup_code_hash` is deliberately absent: the
# alphabet is 32 glyphs and the code is 8 long, so handing out the digest hands
# out the code to anyone willing to spend a few core-seconds on it. That absence
# is now ENFORCED rather than observed — `payout_queue` runs the tuple through
# `actions.assert_safe_fields` before it reaches the query.
_QUEUE_FIELDS = (
	"name",
	"client_request_id",
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
	# Read for `allowed_actions`, not for display: a transfer with an Approved or
	# Completed refund is in the queue's state filter but is not payable, and
	# without this column the queue would offer Pay out on it.
	"refund_status",
	"code_locked",
	"code_attempts",
	"registered_at",
	"modified",
)

# What a free-text search matches. The two names are why this endpoint exists:
# v1 could only match an exact remittance id, so a receiver who had lost the slip
# sent the cashier off the payout screen to go and find it.
_QUEUE_SEARCH_FIELDS = ("name", "client_request_id", "receiver_name", "sender_name")


def _max_code_attempts(company: str) -> int:
	"""How many wrong codes lock the transfer, per company."""
	configured = cint(frappe.db.get_value(SETTINGS, company, "max_code_attempts"))
	return configured if configured > 0 else _DEFAULT_MAX_CODE_ATTEMPTS


def _payout_result(transfer, *, replayed: bool) -> dict:
	return {
		**_state(transfer, replayed=replayed),
		"payout_journal_entry": transfer.payout_journal_entry,
		"code_locked": cint(transfer.code_locked),
		"code_attempts": cint(transfer.code_attempts),
	}


@frappe.whitelist()
def payout_queue(company: str, query: str | None = None, limit=50) -> list[dict]:
	"""The transfers a cashier may actually pay out, searchable by name."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)

	term = (query or "").strip()
	# `get_list`, never `get_all`. `get_all` sets `ignore_permissions`, which turns
	# `permissions.remittance_transfer_query` off and skips the DocPerm read as well
	# — and `_assert_company_scope` above deliberately passes a caller who has no
	# Allowed Companies list at all, so on a `get_all` this endpoint answered any
	# logged-in user, holding no remittance role, for any company they named: every
	# payable transfer's sender, receiver, principal, commission and corridor.
	# `remittance_queries` states the same rule at the top of its own module; this is
	# the other module that lists this doctype for a screen.
	rows = frappe.get_list(
		TRANSFER,
		filters={
			"company": company,
			# Stated as an inclusion, not as "everything except". Registered +
			# Unposted would debit an obligation that was never created, and an
			# operational status added later cannot leak into this list by default.
			"operational_status": "Registered",
			"accounting_status": "Posted",
		},
		or_filters=[[field, "like", f"%{term}%"] for field in _QUEUE_SEARCH_FIELDS] if term else None,
		fields=list(actions.assert_safe_fields(_QUEUE_FIELDS)),
		order_by="registered_at desc, modified desc",
		limit=max(1, min(cint(limit) or 50, 200)),
	)
	# One role read for the whole page, and the server — not the screen — decides.
	return actions.assert_no_pickup_code(actions.annotate(rows, frappe.get_roles()))


def _assert_payable(transfer) -> None:
	"""Refuse anything that is not a registered, posted, unlocked transfer.

	Every field read here is read under the row lock. Deciding this on unlocked
	state is the double payout: both cashiers see `Registered`, both hand over cash.
	"""
	if transfer.operational_status != "Registered":
		frappe.throw(
			_("Transfer {0} is {1} and cannot be paid out.").format(
				transfer.name, transfer.operational_status
			)
		)
	if transfer.accounting_status != "Posted":
		frappe.throw(
			_(
				"Transfer {0} is {1}: the receiver obligation was never posted, so there "
				"is nothing to pay out."
			).format(transfer.name, transfer.accounting_status)
		)
	if transfer.refund_status in ("Approved", "Completed"):
		# The cash is already committed back to the sender at the origin desk.
		# A merely *Requested* refund deliberately does not block: it is not yet a
		# commitment, and letting a request freeze the receiver's cash would make
		# the refund request a denial-of-service on the person waiting at the counter.
		frappe.throw(
			_("Transfer {0} has a {1} refund and cannot be paid out.").format(
				transfer.name, transfer.refund_status
			)
		)
	if cint(transfer.code_locked):
		frappe.throw(
			_(
				"The pickup code for {0} is locked after too many failed attempts. A manager must unlock it."
			).format(transfer.name),
			frappe.PermissionError,
		)


def _refuse_the_code(transfer, key: str) -> None:
	"""Count the attempt, lock at the limit, and only then refuse.

	`frappe.throw` rolls the transaction back, so the counter has to reach disk
	*before* the refusal is raised — an uncommitted lockout is not a lockout, and a
	brute-force attempt that costs nothing is not counted at all. This is the only
	place in this module that commits, and it is safe precisely here: on this path
	no money has moved and the only writes are the counter, the lock flag and the
	trail. The commit releases the row lock, which is correct — this caller is done.
	"""
	attempts = cint(transfer.code_attempts) + 1
	limit = _max_code_attempts(transfer.company)
	locked = attempts >= limit

	patch = {"code_attempts": attempts}
	if locked:
		patch.update({"code_locked": 1, "code_locked_at": now_datetime(), "verification_status": "Locked"})
	transfer.db_set(patch, notify=False)

	_append_event(
		transfer,
		event_type="Failed code attempt",
		key=key,
		branch=transfer.destination_branch,
		details=_("Wrong pickup code — attempt {0} of {1}").format(attempts, limit),
	)
	locked_message = _(
		"The pickup code for {0} is locked after {1} failed attempts. A manager must unlock it."
	).format(transfer.name, attempts)
	if locked:
		_append_event(
			transfer,
			event_type="Lock",
			key=key,
			branch=transfer.destination_branch,
			details=locked_message,
		)

	frappe.db.commit()

	if locked:
		frappe.throw(locked_message, frappe.PermissionError)
	frappe.throw(
		_("Invalid pickup code. {0} attempt(s) left before this transfer is locked.").format(
			limit - attempts
		),
		frappe.PermissionError,
	)


def _verify_the_code(transfer, provided: str, key: str) -> None:
	"""Constant-time compare against the stored digest, or spend an attempt."""
	stored = (transfer.pickup_code_hash or "").strip()
	if not is_hashed_pickup_code(stored):
		# Missing, or still in the pre-hash plaintext format on a site where the
		# migration has not run. Neither is the receiver's doing, so neither costs
		# an attempt: locking a transfer over a deployment gap punishes the wrong
		# person and hides the real cause.
		frappe.throw(
			_(
				"Transfer {0} has no usable pickup code on file — it is missing or still "
				"in the pre-hash format. Run `bench migrate` on this site, then retry."
			).format(transfer.name)
		)
	if not _pickup_code_matches(stored, provided):
		_refuse_the_code(transfer, key)


def _replayed_payout(transfer, key: str) -> dict:
	"""Answer a second payout: the original result, or a refusal.

	Payout carries no money in its request, so unlike register there is no payload
	to disagree about. What decides is whether *this* key is the one that paid the
	transfer out, and the trail is the record of that.
	"""
	paid_under = frappe.db.get_value(
		EVENT, {"transfer": transfer.name, "event_type": "Payout"}, "client_request_id"
	)
	if paid_under and paid_under == key:
		return _payout_result(transfer, replayed=True)
	frappe.throw(_("Transfer {0} has already been paid out.").format(transfer.name))


@frappe.whitelist()
def verify_pickup_code(name: str, pickup_code: str, client_request_id: str) -> dict:
	"""Answer whether this code opens this transfer, without handing anything over.

	Why it exists: the payout button used to be clickable with an unverified code,
	so a wrong code was discovered AFTER the click — an error line under a form that
	had already asked the cashier to count the cash out. The screen now keeps the
	button disabled until the code has been checked, and this is the call it makes.

	Why it costs an attempt: verification is verification. An endpoint that compares
	a code against the stored digest for free is a brute-force oracle standing in
	front of the counter that exists to stop one, and adding it would leave the money
	path weaker than it was before the convenience. So the guards below are the ones
	`payout_transfer` uses, in the same order, and the compare is the same
	`_verify_the_code` — same counter, same lockout, same trail. What changes is only
	WHEN a wrong code is discovered, never what it costs.

	A successful check writes nothing and appends no event: the trail records money
	and refusals, and a correct code read out at the counter is neither.
	"""
	key = (client_request_id or "").strip()
	if not key:
		frappe.throw(_("A client request id is required, so a refused attempt can be traced."))

	# Role before row, exactly as payout: a caller who may not pay out must not be
	# able to burn the receiver's attempts by asking the cheaper question instead.
	if not actions.holds(actions.PAYOUT, frappe.get_roles()):
		frappe.throw(_("Only the remittance desk can verify a pickup code."), frappe.PermissionError)

	if not frappe.db.get_value(TRANSFER, name, "name", for_update=True):
		frappe.throw(_("Transfer {0} does not exist.").format(name))

	# ...and the state is read THROUGH the lock, for the reason payout gives: an
	# answer taken from this request's own snapshot could say "verified" about a
	# transfer another cashier is paying out at this moment.
	transfer = frappe.get_doc(TRANSFER, name, for_update=True)
	_assert_company_scope(transfer.company)
	_require_company(transfer.company)

	_assert_payable(transfer)
	_verify_the_code(transfer, pickup_code, key)

	return {"name": transfer.name, "verified": True}


@frappe.whitelist()
def payout_transfer(
	name: str,
	pickup_code: str,
	client_request_id: str,
	posting_date: str | None = None,
) -> dict:
	"""Verify the receiver's code, close the obligation, hand over the cash."""
	key = (client_request_id or "").strip()
	if not key:
		frappe.throw(_("A client request id is required, so a retry cannot pay out twice."))

	# The role, before the row. Handing over cash was the one mutation in this
	# module with no role gate: `db_set` consults no DocPerm, `get_doc` checks no
	# read right, and `_assert_company_scope` passes any caller who has no Allowed
	# Companies list at all — so the guards below stopped the wrong transfer, never
	# the wrong person. Read from the same table the read paths answer with, so the
	# offer and the enforcement cannot drift apart. See stabler-o6rt.
	if not actions.holds(actions.PAYOUT, frappe.get_roles()):
		frappe.throw(_("Only the remittance desk can pay out a transfer."), frappe.PermissionError)

	# The lock FIRST — before the state, before the code check, before the posting.
	# It doubles as the existence check: a row nobody can lock is a row that is not
	# there, and it is what turns a missing name into a sentence rather than a
	# traceback. Same ordering as `register_remittance`, for the same reason.
	if not frappe.db.get_value(TRANSFER, name, "name", for_update=True):
		frappe.throw(_("Transfer {0} does not exist.").format(name))

	# ...and the state is read THROUGH it. Under REPEATABLE READ the lock alone
	# serialises without refreshing: a plain `get_doc` answers from the snapshot this
	# request opened before it blocked, so the loser of the race would wake up, see
	# the pre-race `Registered`, and pay out a second time. See the module docstring.
	transfer = frappe.get_doc(TRANSFER, name, for_update=True)
	# Tenant isolation on the row's own company: the caller never names one here.
	_assert_company_scope(transfer.company)
	_require_company(transfer.company)

	if transfer.operational_status == "Paid Out":
		return _replayed_payout(transfer, key)

	_assert_payable(transfer)
	_verify_the_code(transfer, pickup_code, key)

	post_payout(transfer, posting_date=posting_date or nowdate())
	# Only now: the payout entry is submitted, so no reader can see a transfer
	# marked Paid Out whose obligation is still open.
	transfer.db_set(
		{"operational_status": "Paid Out", "verification_status": "Consumed"},
		notify=False,
	)
	_append_event(
		transfer,
		event_type="Payout",
		key=key,
		branch=transfer.destination_branch,
		details=_("Paid out {0} {1} to {2}").format(
			flt(transfer.receiver_amount, 2), transfer.receive_currency, transfer.receiver_name
		),
	)

	return _payout_result(transfer, replayed=False)


@frappe.whitelist()
def unlock_pickup_code(name: str, reason: str | None = None) -> dict:
	"""A manager reopens a locked pickup code. Today this is the only exit.

	`Remittance Settings.lockout_minutes` is deliberately NOT read and no expiry is
	implemented. Whether a lockout should time out on its own is an open policy
	question (its own bead), and a lockout that quietly expires is indistinguishable
	from one that was never applied — so until someone decides, the exit is a person
	who leaves a row in the trail.

	Gated through `_remittance_actions`, the same table every read path consults,
	so the offer and the refusal cannot disagree: a caller who is not offered
	Unlock is a caller this line turns away. The set is the remittance Finance
	Manager (stabler-tvma created the role) plus the money-control managers this
	endpoint originally shipped gated on — an Accounts Manager who could unlock
	before the roles existed can still unlock now.
	"""
	if not actions.holds(actions.UNLOCK_PICKUP_CODE, frappe.get_roles()):
		frappe.throw(_("Only a manager can unlock a pickup code."), frappe.PermissionError)

	if not frappe.db.get_value(TRANSFER, name, "name", for_update=True):
		frappe.throw(_("Transfer {0} does not exist.").format(name))

	# Locked read, for the reason spelled out in `payout_transfer`: two managers on
	# the same row must not both read `code_locked = 1` out of a stale snapshot.
	transfer = frappe.get_doc(TRANSFER, name, for_update=True)
	_assert_company_scope(transfer.company)
	_require_company(transfer.company)

	if transfer.operational_status != "Registered":
		frappe.throw(
			_("Transfer {0} is {1}; there is no pickup left to unlock.").format(
				transfer.name, transfer.operational_status
			)
		)
	if not cint(transfer.code_locked):
		# Two managers pressing Unlock must not produce a failure for the second.
		return _payout_result(transfer, replayed=True)

	# The counter goes back to zero with the flag. Leaving it at the limit would
	# re-lock on the very next mistyped character, which is not an unlock; the
	# attempt history survives in the trail, which is where it belongs anyway.
	transfer.db_set(
		{
			"code_locked": 0,
			"code_attempts": 0,
			"code_locked_at": None,
			"verification_status": "Active",
		},
		notify=False,
	)
	_append_event(
		transfer,
		event_type="Unlock",
		key=None,
		branch=transfer.destination_branch,
		details=_("Pickup code unlocked by {0}. {1}").format(
			frappe.session.user, (reason or "").strip() or _("No reason given.")
		),
	)

	return _payout_result(transfer, replayed=False)


# --------------------------------------------------------------------------- #
# Refund — three states, and only the last one moves cash
# --------------------------------------------------------------------------- #

# Who may ask and who may decide, and the gap between them is the control. Both
# sets are real roles created by `patches/v87_remittance_roles.py`; System Manager
# is in each because it already holds every DocPerm on the aggregate, so excluding
# it would only mean a locked-out site is repaired by hand instead of by endpoint.
#
# These gates are not belt-and-braces over a permission check that happens
# elsewhere — there is no such check. `@frappe.whitelist()` admits any logged-in
# user, `db_set` writes columns without consulting permissions, and the refund
# Journal Entry is inserted with `ignore_permissions=True`. This tuple is the only
# thing between an authenticated stranger and the origin desk's cash drawer.


def _refund_result(transfer, *, replayed: bool) -> dict:
	return {
		**_state(transfer, replayed=replayed),
		"refund_status": transfer.refund_status,
		"refund_journal_entry": transfer.refund_journal_entry,
	}


def _assert_refund_desk() -> None:
	"""The origin desk: it takes the request in and it counts the cash back out."""
	if not actions.holds(actions.REQUEST_REFUND, frappe.get_roles()):
		frappe.throw(_("Only the remittance desk can request or complete a refund."), frappe.PermissionError)


def _assert_refund_manager() -> None:
	"""The decision. Separate from the desk on purpose: approving your own request
	is not an approval."""
	if not actions.holds(actions.APPROVE_REFUND, frappe.get_roles()):
		frappe.throw(
			_("Only a Remittance Finance Manager can approve or reject a refund."),
			frappe.PermissionError,
		)


def _assert_refundable(transfer) -> None:
	"""The operational facts a refund rests on — re-read under the lock, every step.

	This is council decision D32 in code. The caller's role is checked before the
	lock because roles do not change per row; *this* cannot be, because it is
	exactly what a concurrent payout changes. A manager who was allowed to approve
	when the screen was drawn is still allowed to approve a second later — but the
	receiver may have collected the cash in between, and approving then would
	reverse an obligation that a payout has already closed.

	Every field read here comes off `frappe.get_doc(..., for_update=True)`. Reading
	it off an unlocked `get_doc` under REPEATABLE READ returns the snapshot this
	request opened before it blocked on the lock, which is the pre-race row — the
	loser of the race would wake up, see `Registered`, and refund a transfer that
	was paid out while it waited.
	"""
	if transfer.operational_status != "Registered":
		frappe.throw(
			_("Transfer {0} is {1} and can no longer be refunded.").format(
				transfer.name, transfer.operational_status
			)
		)
	if transfer.accounting_status != "Posted":
		frappe.throw(
			_("Transfer {0} is {1}: there is no posted obligation to reverse.").format(
				transfer.name, transfer.accounting_status
			)
		)


def _already(transfer, *, key: str, event_type: str, refusal: str) -> dict:
	"""Answer a repeated refund step: the original result, or a refusal.

	A refund step carries no money in its request — every amount comes off the
	register entry — so unlike register there is no payload for a replay to
	disagree with. What decides is whether *this* key is the one that took the
	step, and the trail is the record of that. The most recent event of the kind is
	the one that counts: a request that was rejected and then made again leaves two.
	"""
	taken_under = frappe.db.get_value(
		EVENT,
		{"transfer": transfer.name, "event_type": event_type},
		"client_request_id",
		order_by="creation desc",
	)
	if taken_under and taken_under == key:
		return _refund_result(transfer, replayed=True)
	frappe.throw(refusal)


def _locked_transfer(name: str, key: str):
	"""The opening of every refund step: a key, the lock, the state read through it.

	The lock doubles as the existence check — a row nobody can lock is a row that is
	not there — and the `get_doc` that follows is a *locking* read for the reason in
	the module docstring. Both halves are load-bearing and neither is negotiable;
	this helper exists so that no refund step can accidentally acquire only one.
	"""
	if not key:
		frappe.throw(_("A client request id is required, so a retry cannot refund twice."))

	if not frappe.db.get_value(TRANSFER, name, "name", for_update=True):
		frappe.throw(_("Transfer {0} does not exist.").format(name))

	transfer = frappe.get_doc(TRANSFER, name, for_update=True)
	# Tenant isolation on the row's own company: the caller never names one here.
	_assert_company_scope(transfer.company)
	_require_company(transfer.company)
	return transfer


@frappe.whitelist()
def request_refund(name: str, reason: str, client_request_id: str) -> dict:
	"""The sender wants the money back. Records the ask; moves nothing."""
	_assert_refund_desk()

	key = (client_request_id or "").strip()
	note = (reason or "").strip()
	if not note:
		# A refund request with no reason is an audit trail that explains nothing —
		# and this is the only field on the whole three-step path that carries why.
		frappe.throw(_("A reason is required to request a refund."))

	transfer = _locked_transfer(name, key)

	if transfer.refund_status == "Requested":
		return _already(
			transfer,
			key=key,
			event_type="Refund request",
			refusal=_("Transfer {0} already has a refund request awaiting a decision.").format(transfer.name),
		)
	if transfer.refund_status in ("Approved", "Completed"):
		frappe.throw(
			_("Transfer {0} already has a {1} refund.").format(transfer.name, transfer.refund_status)
		)

	# Locked state, then the decision. A transfer that was paid out while the form
	# was open has nothing left to refund, and the request must not be recorded as
	# though it did.
	_assert_refundable(transfer)

	transfer.db_set({"refund_status": "Requested"}, notify=False)
	_append_event(
		transfer,
		event_type="Refund request",
		key=key,
		branch=transfer.origin_branch,
		details=_("Refund of {0} {1} requested: {2}").format(
			flt(transfer.tendered, 2), transfer.send_currency, note
		),
	)

	return _refund_result(transfer, replayed=False)


@frappe.whitelist()
def approve_refund(name: str, client_request_id: str, note: str | None = None) -> dict:
	"""A Remittance Finance Manager authorises the refund. Still no cash moves.

	The role is checked first because it needs no row and refusing early avoids
	holding a lock for a caller who was never allowed one. Everything the decision
	actually rests on is read afterwards, off the locked row — see `_assert_refundable`.
	"""
	_assert_refund_manager()

	key = (client_request_id or "").strip()
	transfer = _locked_transfer(name, key)

	if transfer.refund_status == "Approved":
		return _already(
			transfer,
			key=key,
			event_type="Refund approval",
			refusal=_("Transfer {0} already has an approved refund.").format(transfer.name),
		)

	# D32: the operational re-check, on the locked row, before anything is written.
	_assert_refundable(transfer)

	if transfer.refund_status != "Requested":
		frappe.throw(
			_("Transfer {0} has no refund request to approve (refund status is {1}).").format(
				transfer.name, transfer.refund_status
			)
		)

	# No posting here, deliberately. The obligation is reversed when the cash is
	# counted back out at the origin desk, in `complete_refund`, and not a moment
	# earlier — an approval that posted would let the sender be paid from a drawer
	# nobody opened.
	transfer.db_set({"refund_status": "Approved"}, notify=False)
	_append_event(
		transfer,
		event_type="Refund approval",
		key=key,
		branch=transfer.origin_branch,
		details=_("Refund approved by {0}. {1}").format(
			frappe.session.user, (note or "").strip() or _("No note given.")
		),
	)

	return _refund_result(transfer, replayed=False)


@frappe.whitelist()
def reject_refund(name: str, reason: str, client_request_id: str) -> dict:
	"""A Remittance Finance Manager refuses the request, and says why.

	Deliberately does NOT require the transfer to still be refundable. A request
	that sat in the queue while the receiver collected the cash must still be
	closeable — otherwise the row is stranded in `Requested` forever and the only
	exit is someone editing the database by hand.
	"""
	_assert_refund_manager()

	key = (client_request_id or "").strip()
	note = (reason or "").strip()
	if not note:
		frappe.throw(_("A reason is required to reject a refund."))

	transfer = _locked_transfer(name, key)

	if transfer.refund_status == "Rejected":
		return _already(
			transfer,
			key=key,
			event_type="Refund rejection",
			refusal=_("Transfer {0} already has a rejected refund request.").format(transfer.name),
		)
	if transfer.refund_status != "Requested":
		frappe.throw(
			_("Transfer {0} has no refund request to reject (refund status is {1}).").format(
				transfer.name, transfer.refund_status
			)
		)

	transfer.db_set({"refund_status": "Rejected"}, notify=False)
	_append_event(
		transfer,
		event_type="Refund rejection",
		key=key,
		branch=transfer.origin_branch,
		details=_("Refund rejected by {0}: {1}").format(frappe.session.user, note),
	)

	return _refund_result(transfer, replayed=False)


def _post_the_refund(transfer, posting_date: str) -> None:
	"""Reverse the obligation at the frozen rate, and name the freeze if it refuses.

	ADR-008 reverses at `register_base_rate`, the rate the obligation opened at.
	`_accounts.validate_exchange_rate` refuses a foreign Journal Entry row more than
	+/-20% from the CBU rate of the posting day, so a corridor that moved that far
	between registration and refund is refused *at Journal Entry validate*, by a
	sentence about a conversion rate the cashier never typed. Whether that band
	should exempt, widen for, or approval-gate a frozen reversal is an open policy
	decision (`stabler-22vj`) — it is not silently widened here, and no second rate
	is invented to slip past it. Only the refusal is made legible, and the
	validator's own message is carried inside it rather than replaced.

	The re-throw preserves the original exception class, and only `ValidationError`
	is wrapped: a database or programming fault must not come back dressed as a
	rejected refund.
	"""
	try:
		post_refund(transfer, posting_date=posting_date)
	except frappe.ValidationError as err:
		frappe.throw(
			_(
				"Refund for {0} could not be posted at its frozen register rate {1}, which is "
				"the rate the obligation opened at and the only rate it may close at: {2}"
			).format(transfer.name, flt(transfer.register_base_rate, 6), str(err)),
			type(err),
		)


@frappe.whitelist()
def complete_refund(
	name: str,
	client_request_id: str,
	posting_date: str | None = None,
) -> dict:
	"""The cash is counted back out at the origin desk. This is the step that posts."""
	_assert_refund_desk()

	key = (client_request_id or "").strip()
	transfer = _locked_transfer(name, key)

	if transfer.refund_status == "Completed":
		return _already(
			transfer,
			key=key,
			event_type="Refund completion",
			refusal=_("Transfer {0} has already been refunded.").format(transfer.name),
		)

	# The same locked re-check as the approval, and for the same reason: an approval
	# is not a reservation, so the receiver may still have collected the cash between
	# the two steps.
	_assert_refundable(transfer)

	if transfer.refund_status != "Approved":
		frappe.throw(
			_(
				"Transfer {0} cannot be refunded: its refund status is {1}, and cash only "
				"goes back out on an approved refund."
			).format(transfer.name, transfer.refund_status)
		)

	_post_the_refund(transfer, posting_date or nowdate())
	# Only now: `post_refund` has already written `accounting_status = Reversed`, so
	# no reader sees a Refunded transfer whose obligation is still open. The pickup
	# code dies with it — the cash left by the origin desk, so there is nothing at
	# the destination counter left to collect.
	transfer.db_set(
		{
			"operational_status": "Refunded",
			"refund_status": "Completed",
			"verification_status": "Expired",
		},
		notify=False,
	)
	_append_event(
		transfer,
		event_type="Refund completion",
		key=key,
		branch=transfer.origin_branch,
		details=_("Refunded {0} {1} to {2}").format(
			flt(transfer.tendered, 2), transfer.send_currency, transfer.sender_name
		),
	)

	return _refund_result(transfer, replayed=False)


__all__ = [
	"approve_refund",
	"complete_refund",
	"payout_queue",
	"payout_transfer",
	"register_remittance",
	"reject_refund",
	"request_refund",
	"unlock_pickup_code",
	"verify_pickup_code",
]
