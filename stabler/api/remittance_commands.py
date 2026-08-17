"""Register a transfer: one lock, one transaction, one pickup code.

Until this module existed the remittance master row had no writer. The four beads
that built the pieces — `get_desk_account`, `Remittance Transfer`, `price_transfer`
and `post_register` — had no caller outside their own tests, so the Journal Entry
chain was still the record and the append-only trail was empty by construction.
This is the command handler `RemittanceTransfer`'s docstring defers to: a document
cannot serialise or de-duplicate its own callers.

Three things are load-bearing, in this order.

**The lock comes first.** `frappe.db.get_value(..., for_update=True)` is taken
before the state is re-read and before anything is written, so two cashiers
pressing Register on the same row cannot both see `Unposted` and both post the
obligation. The transition and the Journal Entry submit then share one
transaction, which is what makes `Registered + Unposted` unreachable rather than
merely rejected — `RemittanceTransfer._assert_registered_is_posted` rejects the
pair, this ordering is what stops it ever being written. Precedent:
`api/sales.py:3264`, `integrations/uzpay/payme.py:150`.

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

Permissions are deliberately NOT ignored on the master row or the event. Today
that makes this endpoint System-Manager-only, which is what `Remittance Transfer`
actually grants (see stabler-tvma) and what `api/organization.py` documents. A
bypass here would silently outlive the missing role model.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime_str, now_datetime, nowdate

from stabler.api._common import _require_company
from stabler.api._remittance_pricing import PricingError, price_transfer
from stabler.api.approvals import _assert_company_scope
from stabler.api.remittance import _gen_pickup_code, store_pickup_code
from stabler.api.remittance_accounting import post_register

TRANSFER = "Remittance Transfer"
EVENT = "Remittance Event"

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


def _result(transfer, *, pickup_code: str | None, replayed: bool) -> dict:
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
	"""Insert the master row Draft/Unposted. Registered comes after the posting."""
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
			"pickup_code_hash": store_pickup_code(code),
			"code_attempts": 0,
			**payload,
		}
	)
	transfer.insert()
	return transfer


def _append_event(transfer, key: str) -> None:
	frappe.get_doc(
		{
			"doctype": EVENT,
			"transfer": transfer.name,
			"event_type": "Register",
			"occurred_at": now_datetime(),
			"actor": frappe.session.user,
			"branch": transfer.origin_branch,
			"client_request_id": key,
			"details": _("Registered {0} {1} at {2}").format(
				flt(transfer.tendered, 2), transfer.send_currency, flt(transfer.exchange_rate, 6)
			),
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
	_append_event(transfer, key)

	return _result(transfer, pickup_code=code, replayed=False)


__all__ = ["register_remittance"]
