"""Remittance accounting invariants — no Frappe, no DB.

These tests exist to make three failures loud that are otherwise silent and only
surface in reconciliation months later:

* the obligation opening at anything other than the principal, so the entry
  needs a plug account the ADR model does not have;
* the base value drifting a minor unit away from the calculated one because the
  rate was rounded and then multiplied back;
* payout closing the obligation at a rate other than the one it opened at.

The bench half of the ADR-008 test (post, move the market rate, pay out, read the
GL balance) lives in `test_remittance_accounting_bench.py`. This half proves the
arithmetic refuses; that one proves ERPNext does not undo the refusal.
"""

from __future__ import annotations

import pathlib
import unittest
from decimal import Decimal

from stabler.api._remittance_accounting import (
	AccountingError,
	base_values,
	derive_rate,
	payout_legs,
	refund_legs,
	register_legs,
)
from stabler.api._remittance_pricing import price_transfer

ACCOUNTS = {
	"origin_cash": "Cash on hand - TAS-C",
	"destination_cash": "Cash on hand - IST-1",
	"obligation": "Receiver obligation - IST",
	"deferred_commission": "Deferred commission",
	"commission_income": "Commission revenue",
}


def _d(value: str) -> Decimal:
	return Decimal(value)


def _totals(legs: list) -> tuple[Decimal, Decimal]:
	return (
		sum((leg["debit"] for leg in legs), Decimal(0)),
		sum((leg["credit"] for leg in legs), Decimal(0)),
	)


def _by_account(legs: list, account: str) -> dict:
	rows = [leg for leg in legs if leg["account"] == account]
	if len(rows) != 1:
		raise AssertionError(f"expected exactly one {account} leg, got {len(rows)}")
	return rows[0]


class WorkedExample(unittest.TestCase):
	"""The example the plan works by hand, reproduced figure for figure.

	`docs/plans/2026-08-16-remittance-operations-center.md` lines 182-201:
	Tashkent -> Istanbul, USD->EUR, 1%, Inclusive, base currency USD. The plan
	states the answer, so this is a check against a published number rather than
	against whatever the code happens to produce.
	"""

	def setUp(self) -> None:
		self.priced = price_transfer(mode="Inclusive", amount="1000.00", commission_pct="1")
		self.amounts = base_values(
			principal=self.priced["principal"],
			commission=self.priced["commission"],
			tendered=self.priced["tendered"],
			receiver_amount="915.84",
			send_to_base=1,
			send_is_base=True,
			receive_is_base=False,
			base_precision=2,
		)

	def test_the_triple_matches_the_plan(self) -> None:
		self.assertEqual(self.priced["commission"], _d("9.90"))
		self.assertEqual(self.priced["principal"], _d("990.10"))
		self.assertEqual(self.priced["tendered"], _d("1000.00"))

	def test_obligation_opens_at_the_principal(self) -> None:
		# 990,10 = 1.000,00 - 9,90. The plan calls this mandatory, and it is what
		# lets the entry close without an FX margin account (ADR-009 removed it).
		self.assertEqual(self.amounts["obligation_base"], _d("990.10"))
		self.assertEqual(self.amounts["cash_base"], _d("1000.00"))
		self.assertEqual(self.amounts["commission_base"], _d("9.90"))

	def test_register_closes_and_freezes_a_rate_that_reproduces_the_principal(self) -> None:
		built = register_legs(
			amounts=self.amounts,
			accounts=ACCOUNTS,
			tendered=self.priced["tendered"],
			receiver_amount="915.84",
			send_currency="USD",
			receive_currency="EUR",
			base_currency="USD",
		)
		debit, credit = _totals(built["legs"])
		self.assertEqual(debit, credit)
		self.assertEqual(debit, _d("1000.00"))

		obligation = _by_account(built["legs"], ACCOUNTS["obligation"])
		self.assertEqual(obligation["credit_in_account_currency"], _d("915.84"))
		self.assertEqual(obligation["credit"], _d("990.10"))
		# The rate is derived from 990,10 — not typed, and not the market EUR rate.
		# Multiplying it back has to land on 990,10 exactly, because ERPNext
		# recomputes the base from it and keeps only that result.
		self.assertEqual((_d("915.84") * built["register_base_rate"]).quantize(_d("0.01")), _d("990.10"))


class ObligationClosesAtExactlyZero(unittest.TestCase):
	"""ADR-008. Payout mirrors the register leg or it refuses to post."""

	def setUp(self) -> None:
		self.amounts = base_values(
			principal="990.10",
			commission="9.90",
			tendered="1000.00",
			receiver_amount="915.84",
			send_to_base=1,
			send_is_base=True,
			receive_is_base=False,
			base_precision=2,
		)
		self.frozen = register_legs(
			amounts=self.amounts,
			accounts=ACCOUNTS,
			tendered="1000.00",
			receiver_amount="915.84",
			send_currency="USD",
			receive_currency="EUR",
			base_currency="USD",
		)["register_base_rate"]

	def test_payout_debits_exactly_what_register_credited(self) -> None:
		opened = _by_account(self._register_legs(), ACCOUNTS["obligation"])
		paid = _by_account(self._payout_legs(self.frozen), ACCOUNTS["obligation"])
		# Both currencies, not just base: same receive-currency amount and same
		# base value means the account balance is zero on every column the GL
		# carries, which is what "tam sıfırlandığı" asks for.
		self.assertEqual(opened["credit_in_account_currency"], paid["debit_in_account_currency"])
		self.assertEqual(opened["credit"], paid["debit"])

	def test_a_rate_that_moved_after_registration_is_refused(self) -> None:
		# This is the failure the ADR calls silent. The market rate moving is
		# normal; what must never happen is payout quietly valuing the obligation
		# at the new rate and leaving a residue nobody looks at.
		moved = self.frozen * _d("1.05")
		with self.assertRaises(AccountingError) as caught:
			self._payout_legs(moved)
		self.assertIn("residue", str(caught.exception))

	def test_refund_hands_back_the_whole_tendered_amount(self) -> None:
		legs = refund_legs(
			amounts=self.amounts,
			accounts=ACCOUNTS,
			tendered="1000.00",
			receiver_amount="915.84",
			register_base_rate=self.frozen,
			send_currency="USD",
			receive_currency="EUR",
			base_currency="USD",
		)["legs"]
		cash = _by_account(legs, ACCOUNTS["origin_cash"])
		# The commission is refunded too: it was never earned. The customer gets
		# back the 1.000,00 that went on the counter, not 990,10.
		self.assertEqual(cash["credit_in_account_currency"], _d("1000.00"))
		debit, credit = _totals(legs)
		self.assertEqual(debit, credit)

	def _register_legs(self) -> list:
		return register_legs(
			amounts=self.amounts,
			accounts=ACCOUNTS,
			tendered="1000.00",
			receiver_amount="915.84",
			send_currency="USD",
			receive_currency="EUR",
			base_currency="USD",
		)["legs"]

	def _payout_legs(self, rate) -> list:
		return payout_legs(
			amounts=self.amounts,
			accounts=ACCOUNTS,
			receiver_amount="915.84",
			register_base_rate=rate,
			receive_currency="EUR",
			base_currency="USD",
		)["legs"]


class AnchorRegimes(unittest.TestCase):
	"""Every currency arrangement closes, because a different leg holds the plug.

	A row whose account currency is the company currency has no free rate —
	ERPNext pins it to 1 (journal_entry.py:955). So which leg can absorb the
	rounding depends on the arrangement, and all three arrangements occur: base
	UZS with USD sent and UZS paid out is as ordinary here as USD to EUR.
	"""

	def _close(self, **kwargs) -> Decimal:
		amounts = base_values(base_precision=2, **kwargs)
		legs = register_legs(
			amounts=amounts,
			accounts=ACCOUNTS,
			tendered=kwargs["tendered"],
			receiver_amount=kwargs["receiver_amount"],
			send_currency="SND" if not kwargs["send_is_base"] else "BAS",
			receive_currency="RCV" if not kwargs["receive_is_base"] else "BAS",
			base_currency="BAS",
		)["legs"]
		debit, credit = _totals(legs)
		self.assertEqual(debit, credit)
		return amounts["obligation_base"]

	def test_receive_is_foreign_so_the_obligation_holds_the_plug(self) -> None:
		obligation = self._close(
			principal="990.10",
			commission="9.90",
			tendered="1000.00",
			receiver_amount="915.84",
			send_to_base="12500",
			send_is_base=False,
			receive_is_base=False,
		)
		# tendered 1000 * 12500 = 12.500.000; commission 9,90 * 12500 = 123.750
		self.assertEqual(obligation, _d("12376250.00"))

	def test_receive_is_base_so_the_cash_leg_holds_the_plug(self) -> None:
		# USD in, UZS out, base UZS. The obligation is pinned to the receiver's
		# own figure; the margin between the cashier's rate and the market rate
		# stays inside the cash account's valuation and is picked up at period-end
		# FX revaluation, which is where ADR-008 puts it.
		obligation = self._close(
			principal="990.10",
			commission="9.90",
			tendered="1000.00",
			receiver_amount="12000000.00",
			send_to_base="12500",
			send_is_base=False,
			receive_is_base=True,
		)
		self.assertEqual(obligation, _d("12000000.00"))

	def test_one_currency_everywhere_needs_the_receiver_to_get_the_principal(self) -> None:
		obligation = self._close(
			principal="990.10",
			commission="9.90",
			tendered="1000.00",
			receiver_amount="990.10",
			send_to_base=1,
			send_is_base=True,
			receive_is_base=True,
		)
		self.assertEqual(obligation, _d("990.10"))

		with self.assertRaises(AccountingError):
			# No leg has a free rate here, so a receiver amount that is not the
			# principal cannot be made to balance — it has to be refused, not
			# absorbed somewhere.
			self._close(
				principal="990.10",
				commission="9.90",
				tendered="1000.00",
				receiver_amount="915.84",
				send_to_base=1,
				send_is_base=True,
				receive_is_base=True,
			)


class RateDerivation(unittest.TestCase):
	def test_the_rate_is_derived_from_the_base_not_the_other_way_round(self) -> None:
		rate = derive_rate(base_amount="990.10", account_amount="915.84")
		self.assertEqual((_d("915.84") * rate).quantize(_d("0.01")), _d("990.10"))

	def test_an_amount_too_large_for_the_rate_column_is_refused(self) -> None:
		# Nine rate decimals cannot hold a cent once the amount is large enough:
		# one ulp of rate then moves the base by more than a minor unit. Refusing
		# is the point — the alternative is an entry that is off by a cent and
		# posts anyway.
		with self.assertRaises(AccountingError):
			derive_rate(base_amount="123456789012.34", account_amount="98765432109.87")

	def test_a_triple_that_does_not_close_is_refused(self) -> None:
		# The triple is stored at registration and never recomputed (ADR-007).
		# If a caller ever recomputes it and drifts a minor unit, the entry must
		# not be built on top of the drift.
		with self.assertRaises(AccountingError) as caught:
			base_values(
				principal="990.10",
				commission="9.90",
				tendered="1000.01",
				receiver_amount="915.84",
				send_to_base=1,
				send_is_base=True,
				receive_is_base=False,
			)
		self.assertIn("does not close", str(caught.exception))


class BalancesInBaseOnly(unittest.TestCase):
	def test_a_cross_currency_entry_does_not_balance_per_currency(self) -> None:
		# Plan lines 212-214 correcting an older note: only same-currency
		# transfers balance per currency. A test that demanded per-currency
		# balance would reject every correct cross-currency entry, so this pins
		# the intended asymmetry rather than leaving it to be rediscovered.
		amounts = base_values(
			principal="990.10",
			commission="9.90",
			tendered="1000.00",
			receiver_amount="915.84",
			send_to_base=1,
			send_is_base=True,
			receive_is_base=False,
			base_precision=2,
		)
		legs = register_legs(
			amounts=amounts,
			accounts=ACCOUNTS,
			tendered="1000.00",
			receiver_amount="915.84",
			send_currency="USD",
			receive_currency="EUR",
			base_currency="USD",
		)["legs"]

		debit, credit = _totals(legs)
		self.assertEqual(debit, credit)

		in_currency_debit = sum((leg["debit_in_account_currency"] for leg in legs), Decimal(0))
		in_currency_credit = sum((leg["credit_in_account_currency"] for leg in legs), Decimal(0))
		self.assertNotEqual(in_currency_debit, in_currency_credit)


class TheFreezeIsWiredIntoTheBuilder(unittest.TestCase):
	"""Source-level invariants the bench suite cannot catch.

	Measured by mutation on 2026-08-17: removing `flags.ignore_exchange_rate`
	leaves every bench test green, because no rate in those fixtures happens to
	be exactly 1 — and `set_exchange_rate` only refetches for a blank rate or a
	rate of exactly 1. So the flag's one job is the case the fixtures do not
	reach, and a behavioural test would have to contrive it. Pinning the source
	is the honest alternative; the repo already does this in
	`test_imports_api_invariants.py`.
	"""

	def setUp(self) -> None:
		self.source = (
			pathlib.Path(__file__).resolve().parent.parent / "api" / "remittance_accounting.py"
		).read_text(encoding="utf-8")

	def test_every_entry_is_built_with_the_rate_of_the_day_switched_off(self) -> None:
		self.assertIn("entry.flags.ignore_exchange_rate = True\n\tentry.insert", self.source)
		self.assertIn("entry.flags.ignore_exchange_rate = True\n\t\tentry.submit()", self.source)

	def test_no_leg_is_posted_without_an_explicit_rate(self) -> None:
		# This is the mutation that actually turns the bench suite red: omit
		# exchange_rate and ERPNext supplies the rate of the day, revaluing the
		# obligation and leaving a residue. Every leg `_leg` builds carries one.
		self.assertNotIn('if key != "exchange_rate"', self.source)
		self.assertIn('"exchange_rate": rate,', self.builder_source())

	def builder_source(self) -> str:
		return (
			pathlib.Path(__file__).resolve().parent.parent / "api" / "_remittance_accounting.py"
		).read_text(encoding="utf-8")


if __name__ == "__main__":
	unittest.main()
