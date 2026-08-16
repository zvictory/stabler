"""Posts a Remittance Transfer's three entries. Frappe-facing half of the pair.

The arithmetic lives in `_remittance_accounting`, which has no Frappe import and
is unit-tested without a bench. This module does the four things that need a
database: resolve the accounts from Remittance Settings, check that each
account's real currency is the one the leg assumes, freeze the market rate at
register, and build and submit the Journal Entry.

**Account currency is checked, not asserted.** Measured 2026-08-17:
`JournalEntry.validate_multi_currency` (erpnext journal_entry.py:955) overwrites
every row's `account_currency` from the Account record. Posting a EUR leg to a
UZS account therefore does not fail — it silently reinterprets the EUR figure as
UZS. So the currency is verified here, before the amounts are built.

**The rate of the day is switched off, twice over.** `set_exchange_rate` refetches
whenever a row's rate is blank **or exactly 1**. Two things stop it, and the
order matters:

1. every row carries an explicit derived rate. This is what actually holds:
   measured by mutation on 2026-08-17, omitting `exchange_rate` and letting
   ERPNext fetch its own — the convention `money.py::_clean_je_rows` documents —
   turns all four bench tests red with a residue on the obligation.
2. `flags.ignore_exchange_rate` is the backstop for the one case (1) misses: a
   derived rate that lands on exactly 1 for a foreign account would be refetched
   despite being explicit. Removing the flag alone leaves the bench tests green,
   so the flag is insurance, not the mechanism — do not read a green suite as
   proof that it is doing the work.

Callers own the state machine. These functions post and record the accounting
facts (`register_base_rate`, the Journal Entry links, `accounting_status`); they
do not touch `operational_status` and they do not lock. The caller must already
hold the transfer's row lock — see stabler-qzr9.10.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, getdate

from stabler.api._remittance_accounting import (
	AccountingError,
	base_values,
	payout_legs,
	refund_legs,
	register_legs,
)
from stabler.api.money import get_exchange_rate_for_currencies
from stabler.stabler.doctype.remittance_settings.remittance_settings import (
	get_desk_account,
	get_settings,
)

REGISTER = "Register"
PAYOUT = "Payout"
REFUND = "Refund"


def _base_precision() -> int:
	"""Two decimals, one rule, no per-currency branch (plan line 180).

	Read from the site rather than hard-coded so this module rounds exactly where
	ERPNext rounds — the two have to agree or every entry drifts.
	"""
	return cint(frappe.db.get_default("currency_precision")) or 2


def _base_currency(company: str) -> str:
	return frappe.db.get_value("Company", company, "default_currency") or "UZS"


def _account_currency(account: str, company: str) -> str:
	currency = frappe.get_cached_value("Account", account, "account_currency")
	return currency or _base_currency(company)


def _require_currency(account: str, expected: str, company: str, label: str) -> None:
	actual = _account_currency(account, company)
	if actual != expected:
		frappe.throw(
			_(
				"{0} account {1} is held in {2}, but this transfer needs {3}. Fix it in Remittance Settings."
			).format(label, account, actual, expected)
		)


def resolve_accounts(transfer, stage: str) -> dict:
	"""The GL accounts one stage writes to, each checked against its currency.

	Accounts are never hard-coded (ADR-006): the desk cash leaves come from the
	per-desk, per-currency table and the three company accounts from Remittance
	Settings. A missing mapping throws inside `get_desk_account` and names what
	is missing.
	"""
	company = transfer.company
	base = _base_currency(company)
	settings = get_settings(company)
	if not settings:
		frappe.throw(
			_("Remittance is not configured for {0}. Set it up in Remittance Settings.").format(company)
		)

	accounts: dict[str, str] = {}

	if stage in (REGISTER, REFUND):
		accounts["origin_cash"] = get_desk_account(company, transfer.origin_branch, transfer.send_currency)
		_require_currency(accounts["origin_cash"], transfer.send_currency, company, _("Origin desk cash"))

	if stage == PAYOUT:
		accounts["destination_cash"] = get_desk_account(
			company, transfer.destination_branch, transfer.receive_currency
		)
		_require_currency(
			accounts["destination_cash"], transfer.receive_currency, company, _("Destination desk cash")
		)

	accounts["obligation"] = settings.receiver_obligation_account
	if not accounts["obligation"]:
		frappe.throw(_("Remittance Settings for {0} has no receiver obligation account.").format(company))
	# ADR-006 carries the obligation in the receive currency. One settings field
	# holds one account, so a corridor whose receive currency differs from that
	# account is a configuration gap, not something to paper over by posting the
	# receiver's money in the wrong currency — see stabler-wgnh.
	_require_currency(accounts["obligation"], transfer.receive_currency, company, _("Receiver obligation"))

	accounts["deferred_commission"] = settings.deferred_commission_account
	if not accounts["deferred_commission"]:
		frappe.throw(_("Remittance Settings for {0} has no deferred commission account.").format(company))
	_require_currency(accounts["deferred_commission"], base, company, _("Deferred commission"))

	if stage == PAYOUT:
		accounts["commission_income"] = settings.commission_income_account
		if not accounts["commission_income"]:
			frappe.throw(_("Remittance Settings for {0} has no commission income account.").format(company))
		_require_currency(accounts["commission_income"], base, company, _("Commission revenue"))

	return accounts


def _amounts_at_register(transfer, posting_date) -> dict:
	"""Base values as of registration, from the frozen triple and the market rate."""
	company = transfer.company
	base = _base_currency(company)
	send = transfer.send_currency

	send_to_base = (
		Decimal(1)
		if send == base
		else Decimal(str(get_exchange_rate_for_currencies(send, base, posting_date)))
	)

	return base_values(
		principal=transfer.principal,
		commission=transfer.commission,
		tendered=transfer.tendered,
		receiver_amount=transfer.receiver_amount,
		send_to_base=send_to_base,
		send_is_base=send == base,
		receive_is_base=transfer.receive_currency == base,
		base_precision=_base_precision(),
	)


def _amounts_from_register_entry(transfer) -> dict:
	"""Base values read back off the entry that actually posted.

	ADR-008 wants payout to be a mirror of the register leg. Reading the posted
	row is the only way to be certain it is one: recomputing would need the
	market rate of the registration day, and re-fetching that rate is the very
	thing the ADR forbids.
	"""
	if not transfer.register_journal_entry:
		frappe.throw(_("Transfer {0} has no register entry to mirror.").format(transfer.name))

	rows = frappe.get_all(
		"Journal Entry Account",
		filters={"parent": transfer.register_journal_entry},
		fields=["account", "debit", "credit"],
	)
	if not rows:
		frappe.throw(_("Register entry {0} has no rows.").format(transfer.register_journal_entry))

	accounts = resolve_accounts(transfer, REGISTER)
	places = _base_precision()

	def _total(account: str, side: str) -> Decimal:
		return sum((Decimal(str(row[side] or 0)) for row in rows if row["account"] == account), Decimal(0))

	amounts = {
		"cash_base": _total(accounts["origin_cash"], "debit"),
		"commission_base": _total(accounts["deferred_commission"], "credit"),
		"obligation_base": _total(accounts["obligation"], "credit"),
		"base_precision": places,
	}
	if amounts["obligation_base"] <= 0:
		frappe.throw(
			_("Register entry {0} carries no receiver obligation.").format(transfer.register_journal_entry)
		)
	return amounts


def _build_entry(transfer, stage: str, legs: list, posting_date, submit: bool):
	base = _base_currency(transfer.company)
	remark = _("Remittance {0} — {1}").format(transfer.name, stage)
	multi_currency = int(transfer.send_currency != base or transfer.receive_currency != base)

	entry = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"posting_date": getdate(posting_date),
			"company": transfer.company,
			"voucher_type": "Journal Entry",
			"multi_currency": multi_currency,
			"user_remark": remark,
			"cheque_no": transfer.name,
			"cheque_date": getdate(posting_date),
			"stabler_remittance_id": transfer.name,
			"stabler_remittance_stage": stage,
			"stabler_sender_name": (transfer.sender_name or "")[:140],
			"stabler_receiver_name": (transfer.receiver_name or "")[:140],
			"accounts": [{key: _plain(value) for key, value in leg.items()} for leg in legs],
		}
	)
	# ADR-008: never the rate of the day. Without this flag ERPNext refetches the
	# rate for any row whose rate is blank or exactly 1, and the obligation would
	# then close at a different value from the one it opened at.
	entry.flags.ignore_exchange_rate = True
	entry.insert(ignore_permissions=True)
	if submit:
		entry.flags.ignore_approval_gate = True
		entry.flags.ignore_exchange_rate = True
		entry.submit()
	return entry


def _plain(value):
	return float(value) if isinstance(value, Decimal) else value


def post_register(transfer, *, posting_date=None, submit: bool = True) -> dict:
	"""Dr origin desk cash / Cr deferred commission / Cr receiver obligation."""
	posting_date = posting_date or frappe.utils.nowdate()
	accounts = resolve_accounts(transfer, REGISTER)
	amounts = _amounts_at_register(transfer, posting_date)

	built = register_legs(
		amounts=amounts,
		accounts=accounts,
		tendered=transfer.tendered,
		receiver_amount=transfer.receiver_amount,
		send_currency=transfer.send_currency,
		receive_currency=transfer.receive_currency,
		base_currency=_base_currency(transfer.company),
		remark=_("Remittance {0} — Register").format(transfer.name),
	)

	entry = _build_entry(transfer, REGISTER, built["legs"], posting_date, submit)
	transfer.db_set(
		{
			"register_base_rate": float(built["register_base_rate"]),
			"register_journal_entry": entry.name,
			"accounting_status": "Posted",
		},
		notify=False,
	)
	return {"journal_entry": entry.name, "register_base_rate": built["register_base_rate"]}


def post_payout(transfer, *, posting_date=None, submit: bool = True) -> dict:
	"""Dr obligation / Cr destination cash ; Dr deferred commission / Cr revenue."""
	posting_date = posting_date or frappe.utils.nowdate()
	accounts = resolve_accounts(transfer, PAYOUT)
	amounts = _amounts_from_register_entry(transfer)

	built = payout_legs(
		amounts=amounts,
		accounts=accounts,
		receiver_amount=transfer.receiver_amount,
		register_base_rate=transfer.register_base_rate,
		receive_currency=transfer.receive_currency,
		base_currency=_base_currency(transfer.company),
		remark=_("Remittance {0} — Payout").format(transfer.name),
	)

	entry = _build_entry(transfer, PAYOUT, built["legs"], posting_date, submit)
	transfer.db_set("payout_journal_entry", entry.name, notify=False)
	return {"journal_entry": entry.name}


def post_refund(transfer, *, posting_date=None, submit: bool = True) -> dict:
	"""Dr obligation / Dr deferred commission / Cr origin desk cash, in full."""
	posting_date = posting_date or frappe.utils.nowdate()
	accounts = resolve_accounts(transfer, REFUND)
	amounts = _amounts_from_register_entry(transfer)

	built = refund_legs(
		amounts=amounts,
		accounts=accounts,
		tendered=transfer.tendered,
		receiver_amount=transfer.receiver_amount,
		register_base_rate=transfer.register_base_rate,
		send_currency=transfer.send_currency,
		receive_currency=transfer.receive_currency,
		base_currency=_base_currency(transfer.company),
		remark=_("Remittance {0} — Refund").format(transfer.name),
	)

	entry = _build_entry(transfer, REFUND, built["legs"], posting_date, submit)
	transfer.db_set({"refund_journal_entry": entry.name, "accounting_status": "Reversed"}, notify=False)
	return {"journal_entry": entry.name}


__all__ = [
	"PAYOUT",
	"REFUND",
	"REGISTER",
	"AccountingError",
	"post_payout",
	"post_refund",
	"post_register",
	"resolve_accounts",
]
