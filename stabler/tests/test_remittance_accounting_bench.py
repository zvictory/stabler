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

The register *command* is proved here too, for the same reason: its replay rests
on a real unique index, its version has to be the token `check_concurrency`
actually accepts, and its pickup code has to reach the database hashed. A fake
database can be told to agree with any of those —
`test_remittance_register_command.py` proves the ordering and the branching, this
proves the three claims only a real site can settle.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from stabler.api._common import check_concurrency
from stabler.api.remittance import is_hashed_pickup_code
from stabler.api.remittance_accounting import post_payout, post_refund, post_register
from stabler.api.remittance_commands import register_remittance

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

	def _register(self, **overrides):
		"""Drive the whole register command, the way the cashier's screen will."""
		request = {
			"company": self.company,
			"origin_branch": self.origin,
			"destination_branch": self.destination,
			"send_currency": self.send,
			"receive_currency": self.receive,
			"sender_name": "Bench Sender",
			"receiver_name": "Bench Receiver",
			"amount": 1000,
			"exchange_rate": 0.925,
			"commission_mode": "Inclusive",
			"commission_pct": 1,
			"client_request_id": "bench-req",
		}
		request.update(overrides)
		return register_remittance(**request)

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

	# --- the register command ------------------------------------------------ #

	def test_register_command_prices_posts_and_transitions(self) -> None:
		result = self._register(client_request_id="bench-register-1")

		self.assertEqual(result["operational_status"], "Registered")
		self.assertEqual(result["accounting_status"], "Posted")
		self.assertFalse(result["replayed"])
		# The cashier typed 1.000,00 inclusive of 1%; the command priced the triple.
		self.assertEqual(result["tendered"], 1000.00)
		self.assertEqual(result["principal"], 990.10)
		self.assertEqual(result["commission"], 9.90)
		self.assertEqual(result["receiver_amount"], 915.84)

		obligation_base, obligation_currency = self._movement(
			self.obligation, [result["register_journal_entry"]]
		)
		# The obligation opens at the principal, in the receive currency, and only
		# because the command actually reached the ledger — this is the assertion
		# that would have failed for every day the endpoint had no caller.
		self.assertEqual(obligation_currency, -915.84)
		self.assertLess(obligation_base, 0.0)

		stored = frappe.db.get_value(
			"Remittance Transfer", result["name"], ["pickup_code_hash", "verification_status"], as_dict=True
		)
		self.assertTrue(is_hashed_pickup_code(stored.pickup_code_hash))
		self.assertNotIn(result["pickup_code"], stored.pickup_code_hash)
		self.assertEqual(stored.verification_status, "Active")

	def test_register_command_replay_neither_posts_nor_reissues_the_code(self) -> None:
		first = self._register(client_request_id="bench-register-2")
		replay = self._register(client_request_id="bench-register-2")

		self.assertEqual(replay["name"], first["name"])
		self.assertTrue(replay["replayed"])
		# The response of a registering call carries a bearer secret. Replaying a
		# captured request is exactly how someone would ask for it a second time.
		self.assertIsNone(replay["pickup_code"])
		self.assertEqual(frappe.db.count("Remittance Transfer", {"client_request_id": "bench-register-2"}), 1)
		self.assertEqual(frappe.db.count("Journal Entry", {"stabler_remittance_id": first["name"]}), 1)

	def test_register_command_refuses_a_key_reused_with_different_money(self) -> None:
		self._register(client_request_id="bench-register-3")

		with self.assertRaises(frappe.ValidationError):
			self._register(client_request_id="bench-register-3", amount=2000)

		self.assertEqual(frappe.db.count("Remittance Transfer", {"client_request_id": "bench-register-3"}), 1)

	def test_register_command_version_is_the_token_check_concurrency_accepts(self) -> None:
		"""A version the caller cannot hand back is not a version."""
		result = self._register(client_request_id="bench-register-4")

		check_concurrency("Remittance Transfer", result["name"], result["version"])

		frappe.db.set_value("Remittance Transfer", result["name"], "receiver_name", "Someone Else")
		with self.assertRaises(Exception):
			check_concurrency("Remittance Transfer", result["name"], result["version"])
