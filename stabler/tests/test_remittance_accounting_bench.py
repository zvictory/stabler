"""ADR-008 against a real ledger: the market rate moves, the obligation still closes.

The arithmetic is proved without a bench in `test_remittance_accounting.py`. What
that cannot prove is that ERPNext leaves the arithmetic alone, and ERPNext is the
half that fails silently:

* `JournalEntry.set_exchange_rate` refetches the rate of the day for any row whose
  rate is blank or exactly 1;
* `set_amounts_in_company_currency` then recomputes the base value from whatever
  rate survived, discarding the one that was calculated.

So the test that matters posts a register entry, moves the market rate, pays out,
and reads the general ledger. The obligation account has to be at exactly zero —
not "close", not "within a cent". A residue here is the failure ADR-008 says
surfaces months later in reconciliation.

These tests were mutation-checked on 2026-08-17 rather than assumed to bite.
Dropping `exchange_rate` from the payload — the convention `money.py` documents —
turns all four red. Dropping `flags.ignore_exchange_rate` alone leaves them
green, because no rate here happens to be exactly 1; the flag is the backstop for
that case and `test_remittance_accounting.py` pins it at the source instead.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from stabler.api.remittance_accounting import post_payout, post_refund, post_register

#: A 12.5% move, deliberately inside the +/-20% CBU tolerance that
#: `stabler.api._accounts.validate_exchange_rate` enforces on every foreign row.
#: The freeze and that tolerance can collide on a bigger move — see stabler-22vj.
REGISTER_RATE = 12000.0
MOVED_RATE = 13500.0
#: The receive leg needs a CBU rate on file too, within tolerance of the rate the
#: obligation implies (principal / receiver_amount, ~1.081 * REGISTER_RATE here).
RECEIVE_RATE = 13000.0


def _ensure(doctype: str, name: str, values: dict) -> str:
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	return doc.name


class RemittanceAccountingBenchTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			raise AssertionError("No Company on this site — the accounting test cannot post anything.")
		cls.company = company
		cls.base = frappe.db.get_value("Company", company, "default_currency")
		# Both legs must be foreign, or no rate is free and the freeze is untested.
		cls.send = "EUR" if cls.base == "USD" else "USD"
		cls.receive = "GBP" if cls.base == "EUR" else "EUR"

	def setUp(self) -> None:
		super().setUp()
		# FrappeTestCase rolls each test back, so the masters are rebuilt per test.
		self.origin = _ensure("Branch", "REM-TEST-ORIGIN", {"branch": "REM-TEST-ORIGIN"})
		self.destination = _ensure("Branch", "REM-TEST-DEST", {"branch": "REM-TEST-DEST"})

		self.origin_cash = self._account("REM Test Origin Cash", "Asset", self.send)
		self.destination_cash = self._account("REM Test Destination Cash", "Asset", self.receive)
		self.obligation = self._account("REM Test Receiver Obligation", "Liability", self.receive)
		self.deferred = self._account("REM Test Deferred Commission", "Liability", self.base)
		self.income = self._account("REM Test Commission Revenue", "Income", self.base)

		self._settings()
		self._rates(add_days(nowdate(), -1), REGISTER_RATE)

	def _account(self, title: str, root_type: str, currency: str) -> str:
		parent = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 1, "root_type": root_type}, "name"
		)
		if not parent:
			raise AssertionError(f"{self.company} has no {root_type} group account to post under.")
		name = f"{title} - {frappe.get_cached_value('Company', self.company, 'abbr')}"
		return _ensure(
			"Account",
			name,
			{
				"account_name": title,
				"company": self.company,
				"parent_account": parent,
				"root_type": root_type,
				"account_currency": currency,
				"is_group": 0,
			},
		)

	def _settings(self) -> None:
		if frappe.db.exists("Remittance Settings", self.company):
			settings = frappe.get_doc("Remittance Settings", self.company)
			settings.cash_desk_accounts = []
		else:
			settings = frappe.get_doc({"doctype": "Remittance Settings", "company": self.company})
		settings.receiver_obligation_account = self.obligation
		settings.deferred_commission_account = self.deferred
		settings.commission_income_account = self.income
		settings.append(
			"cash_desk_accounts",
			{"branch": self.origin, "currency": self.send, "account": self.origin_cash},
		)
		settings.append(
			"cash_desk_accounts",
			{"branch": self.destination, "currency": self.receive, "account": self.destination_cash},
		)
		settings.save(ignore_permissions=True)

	def _rate(self, date: str, rate: float, currency: str | None = None) -> None:
		"""Publish a CBU rate for one currency on one date.

		`stabler.api._accounts.validate_exchange_rate` refuses a Journal Entry
		whose foreign row has no CBU rate on or before the posting date, so both
		the send and the receive leg need one — not just the one this module reads.
		"""
		currency = currency or self.send
		if currency == self.base:
			return
		name = _ensure(
			"Currency Exchange",
			f"{currency}-{self.base}-{date}",
			{
				"from_currency": currency,
				"to_currency": self.base,
				"date": date,
				"exchange_rate": rate,
				"for_buying": 1,
				"for_selling": 1,
			},
		)
		frappe.db.set_value("Currency Exchange", name, "exchange_rate", rate)

	def _rates(self, date: str, send_rate: float) -> None:
		self._rate(date, send_rate)
		self._rate(date, RECEIVE_RATE, self.receive)

	def _transfer(self):
		transfer = frappe.get_doc(
			{
				"doctype": "Remittance Transfer",
				"company": self.company,
				"sender_name": "Bench Sender",
				"receiver_name": "Bench Receiver",
				"origin_branch": self.origin,
				"destination_branch": self.destination,
				"send_currency": self.send,
				"receive_currency": self.receive,
				"commission_mode": "Inclusive",
				"commission_pct": 1,
				"principal": 990.10,
				"commission": 9.90,
				"tendered": 1000.00,
				"receiver_amount": 915.84,
				"exchange_rate": 0.925,
				"operational_status": "Draft",
			}
		)
		transfer.insert(ignore_permissions=True)
		return transfer

	def _movement(self, account: str, vouchers: list) -> tuple[float, float]:
		"""Net movement on an account across the given entries, base and currency."""
		rows = frappe.get_all(
			"GL Entry",
			filters={"account": account, "voucher_no": ["in", vouchers], "is_cancelled": 0},
			fields=["debit", "credit", "debit_in_account_currency", "credit_in_account_currency"],
		)
		base = sum(row.debit - row.credit for row in rows)
		currency = sum(row.debit_in_account_currency - row.credit_in_account_currency for row in rows)
		return base, currency

	def test_obligation_closes_at_zero_after_the_rate_moves(self) -> None:
		transfer = self._transfer()
		registered = post_register(transfer, posting_date=add_days(nowdate(), -1))

		# The market moves 12.5% between registration and payout. Under the rate of
		# the day the obligation would close at a different base value and leave a
		# residue; ADR-008 says it must close at the rate it opened at.
		self._rates(nowdate(), MOVED_RATE)
		transfer.reload()
		paid = post_payout(transfer, posting_date=nowdate())

		vouchers = [registered["journal_entry"], paid["journal_entry"]]
		base, currency = self._movement(self.obligation, vouchers)
		self.assertEqual(base, 0.0, "receiver obligation left a base-currency residue")
		self.assertEqual(currency, 0.0, "receiver obligation left a receive-currency residue")

	def test_payout_row_keeps_the_frozen_rate(self) -> None:
		transfer = self._transfer()
		post_register(transfer, posting_date=add_days(nowdate(), -1))
		self._rates(nowdate(), MOVED_RATE)
		transfer.reload()
		frozen = transfer.register_base_rate
		paid = post_payout(transfer, posting_date=nowdate())

		# Read the rate back off the saved row, not off the payload: this is the
		# assertion that ERPNext did not substitute the rate of the day during
		# validation.
		stored = frappe.db.get_value(
			"Journal Entry Account",
			{"parent": paid["journal_entry"], "account": self.obligation},
			"exchange_rate",
		)
		self.assertAlmostEqual(stored, frozen, places=9)

	def test_commission_is_earned_only_at_payout(self) -> None:
		transfer = self._transfer()
		registered = post_register(transfer, posting_date=add_days(nowdate(), -1))
		transfer.reload()
		paid = post_payout(transfer, posting_date=nowdate())

		deferred_base, _ = self._movement(self.deferred, [registered["journal_entry"], paid["journal_entry"]])
		income_base, _ = self._movement(self.income, [paid["journal_entry"]])
		# Deferred at register, released at payout: the liability nets to zero and
		# the same amount lands in revenue. Recognising it at register would book
		# income on money that can still be refunded.
		self.assertEqual(deferred_base, 0.0)
		self.assertLess(income_base, 0.0)

	def test_refund_returns_the_whole_tendered_amount(self) -> None:
		transfer = self._transfer()
		registered = post_register(transfer, posting_date=add_days(nowdate(), -1))
		self._rates(nowdate(), MOVED_RATE)
		transfer.reload()
		refunded = post_refund(transfer, posting_date=nowdate())

		vouchers = [registered["journal_entry"], refunded["journal_entry"]]
		obligation_base, obligation_currency = self._movement(self.obligation, vouchers)
		self.assertEqual(obligation_base, 0.0)
		self.assertEqual(obligation_currency, 0.0)

		cash_base, cash_currency = self._movement(self.origin_cash, vouchers)
		# The customer gets back the 1.000,00 they put on the counter, commission
		# included — it was never earned. Both the cash and the obligation return
		# to where they started, so a registered-then-refunded transfer leaves no
		# trace in any balance.
		self.assertEqual(cash_currency, 0.0)
		self.assertEqual(cash_base, 0.0)
