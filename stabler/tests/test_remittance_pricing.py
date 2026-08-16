"""Unit tests for the pure remittance pricing engine (no Frappe, no DB).

What these tests defend, in the order the plan decided it
(``docs/plans/2026-08-16-remittance-operations-center.md``):

* ADR-002 — one percentage, and it is always a percentage OF THE PRINCIPAL.
  The rejected alternative charged Inclusive on the gross, which made the same
  tariff mean two different effective prices.
* ADR-007 — the two modes are not inverses. That is a measured fact, not a
  worry, and it is the whole reason the triple is stored at registration and
  never recomputed. If a test here ever "fixes" the drift by reordering the
  formula, the drift moved, it did not go away.
* The third figure is always the plug, so the triple closes to the minor unit
  by construction — the invariant Remittance Transfer.validate() then enforces.

Bench-free: the engine imports nothing from Frappe, so this module belongs in
``.github/frappe-free-tests.txt`` and gates every push.
"""

from __future__ import annotations

import json
import os
import unittest
from decimal import ROUND_HALF_UP, Decimal

from stabler.api._remittance_pricing import EXCLUSIVE, INCLUSIVE, MODES, PricingError, price_transfer

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CENT = Decimal("0.01")

#: The measurement of record from ADR-007, reproduced in ``_round_trip`` below.
#: 55,000 consecutive amounts, one minor unit apart.
_SWEEP_MINOR_UNITS = 55_000


def _round_trip(pct: str) -> dict:
	"""Re-run the ADR-007 round-trip measurement for one percentage.

	Inclusive-price an amount, hand the resulting principal back to Exclusive,
	and see whether the customer is asked for the same money again.

	`alternative_drifted` runs the other candidate formula — round the principal
	first and plug the commission — because the plan's finding is not "our
	formula is unlucky", it is "rounding to the minor unit makes the two
	directions mathematically irreversible". If the alternative drifted less,
	freezing the triple would be the wrong fix.
	"""
	p = Decimal(pct)
	drifted = 0
	alternative_drifted = 0
	max_delta = Decimal("0")

	for minor in range(1, _SWEEP_MINOR_UNITS + 1):
		tendered = Decimal(minor) / 100

		principal = price_transfer(mode=INCLUSIVE, amount=tendered, commission_pct=p)["principal"]
		back = price_transfer(mode=EXCLUSIVE, amount=principal, commission_pct=p)["tendered"]
		if back != tendered:
			drifted += 1
			max_delta = max(max_delta, abs(back - tendered))

		# The rejected ordering: principal rounded, commission plugged.
		alt_principal = (tendered * Decimal("100") / (Decimal("100") + p)).quantize(
			_CENT, rounding=ROUND_HALF_UP
		)
		alt_back = price_transfer(mode=EXCLUSIVE, amount=alt_principal, commission_pct=p)["tendered"]
		if alt_back != tendered:
			alternative_drifted += 1

	return {"drifted": drifted, "alternative_drifted": alternative_drifted, "max_delta": max_delta}


_MEASURED: dict = {}


def _measured(pct: str) -> dict:
	"""One sweep per percentage, shared by the three ADR-007 tests."""
	if pct not in _MEASURED:
		_MEASURED[pct] = _round_trip(pct)
	return _MEASURED[pct]


class OnePercentageOnThePrincipal(unittest.TestCase):
	"""ADR-002. 'Our commission is 1%' has to mean one thing in both modes."""

	def test_exclusive_charges_the_percentage_on_top_of_what_was_typed(self):
		r = price_transfer(mode=EXCLUSIVE, amount="1000.00", commission_pct="1.00")
		self.assertEqual(r["principal"], Decimal("1000.00"))
		self.assertEqual(r["commission"], Decimal("10.00"))
		self.assertEqual(r["tendered"], Decimal("1010.00"))

	def test_inclusive_matches_the_worked_example_in_the_plan(self):
		# ADR-007's worked example: 1.000,00 USD on the counter at 1%.
		r = price_transfer(mode=INCLUSIVE, amount="1000.00", commission_pct="1.00")
		self.assertEqual(r["commission"], Decimal("9.90"))
		self.assertEqual(r["principal"], Decimal("990.10"))
		self.assertEqual(r["tendered"], Decimal("1000.00"))

	def test_the_percentage_is_of_the_principal_in_both_modes(self):
		# The rejected gross-base alternative would charge 10.00 on an Inclusive
		# 1000 — a 1.0101% effective rate on the principal, from a 1% tariff.
		for mode in MODES:
			with self.subTest(mode=mode):
				r = price_transfer(mode=mode, amount="1000.00", commission_pct="1.00")
				on_principal = (r["principal"] * Decimal("1.00") / Decimal("100")).quantize(
					_CENT, rounding=ROUND_HALF_UP
				)
				self.assertEqual(r["commission"], on_principal)

	def test_inclusive_does_not_charge_the_percentage_on_the_tendered_amount(self):
		r = price_transfer(mode=INCLUSIVE, amount="1000.00", commission_pct="1.00")
		self.assertNotEqual(r["commission"], Decimal("10.00"))


class TheThirdFigureIsThePlug(unittest.TestCase):
	"""One rounding per branch. The triple closes because nothing rounds twice."""

	def test_the_triple_closes_for_every_amount_and_rate(self):
		for pct in ("0", "0.25", "0.50", "1.00", "2.75", "13.00"):
			for amount in ("0.01", "0.07", "3.33", "99.99", "1000.00", "123456.78"):
				for mode in MODES:
					with self.subTest(pct=pct, amount=amount, mode=mode):
						r = price_transfer(mode=mode, amount=amount, commission_pct=pct)
						self.assertEqual(r["principal"] + r["commission"], r["tendered"])

	def test_the_plug_is_the_exact_difference_not_a_second_rounding(self):
		r = price_transfer(mode=INCLUSIVE, amount="0.07", commission_pct="1.00")
		# 0.07 * 1 / 101 = 0.000693... -> 0.00; the principal keeps the whole 0.07.
		self.assertEqual(r["commission"], Decimal("0.00"))
		self.assertEqual(r["principal"], Decimal("0.07"))

	def test_precision_comes_from_the_currency_not_from_a_constant(self):
		# UZS has no minor unit; the same single rounding rule still applies.
		r = price_transfer(mode=EXCLUSIVE, amount="100000", commission_pct="1.00", precision=0)
		self.assertEqual(r["commission"], Decimal("1000"))
		self.assertEqual(r["tendered"], Decimal("101000"))

	def test_an_amount_finer_than_the_currency_is_refused(self):
		# Accepting it would leave the plug carrying a sub-unit tail, which the
		# Currency field then rounds at storage time — and the stored triple
		# would no longer close.
		with self.assertRaises(PricingError):
			price_transfer(mode=EXCLUSIVE, amount="100.005", commission_pct="1.00")
		with self.assertRaises(PricingError):
			price_transfer(mode=EXCLUSIVE, amount="100.50", commission_pct="1.00", precision=0)


class TheTwoModesAreNotInverses(unittest.TestCase):
	"""ADR-007, measured. These numbers are why the triple is frozen at register."""

	def test_the_drift_matches_the_measurement_in_the_plan(self):
		# 55,000 consecutive amounts, one minor unit apart. The count depends on
		# the number of minor units, not on the scale — the same 274/545 come
		# out of 0.01..550.00 and of 1..55000, so this is not a small-amount
		# problem that a minimum-amount rule would hide.
		self.assertEqual(_measured("0.50")["drifted"], 274)
		self.assertEqual(_measured("1.00")["drifted"], 545)

	def test_the_drift_is_always_exactly_one_minor_unit(self):
		# A cent is a rounding artefact. Anything larger would be a formula bug,
		# and freezing the triple would be hiding it rather than accepting it.
		for pct in ("0.50", "1.00"):
			with self.subTest(pct=pct):
				self.assertEqual(_measured(pct)["max_delta"], _CENT)

	def test_rounding_the_principal_first_drifts_on_the_same_count(self):
		# Both orderings fail identically, so no reordering of the formula
		# rescues reversibility. Store the triple; never recompute it.
		for pct in ("0.50", "1.00"):
			with self.subTest(pct=pct):
				measured = _measured(pct)
				self.assertEqual(measured["alternative_drifted"], measured["drifted"])


class Guards(unittest.TestCase):
	"""The edges a cashier reaches on a normal day, and the ones that must stop."""

	def test_zero_pct_is_a_free_transfer_not_an_error(self):
		for mode in MODES:
			with self.subTest(mode=mode):
				r = price_transfer(mode=mode, amount="500.00", commission_pct="0")
				self.assertEqual(r["commission"], Decimal("0.00"))
				self.assertEqual(r["principal"], Decimal("500.00"))
				self.assertEqual(r["tendered"], Decimal("500.00"))

	def test_a_commission_that_rounds_to_zero_still_closes(self):
		r = price_transfer(mode=EXCLUSIVE, amount="0.10", commission_pct="1.00")
		self.assertEqual(r["commission"], Decimal("0.00"))
		self.assertEqual(r["tendered"], Decimal("0.10"))

	def test_inclusive_commission_may_not_swallow_the_principal(self):
		# Same rejection Remittance Transfer.validate() makes; the engine must
		# not hand the doctype a row it is about to refuse.
		with self.assertRaises(PricingError):
			price_transfer(mode=INCLUSIVE, amount="0.01", commission_pct="1000")

	def test_a_non_positive_amount_is_refused(self):
		for amount in ("0", "-5.00"):
			with self.subTest(amount=amount):
				with self.assertRaises(PricingError):
					price_transfer(mode=EXCLUSIVE, amount=amount, commission_pct="1.00")

	def test_a_negative_percentage_is_refused(self):
		with self.assertRaises(PricingError):
			price_transfer(mode=EXCLUSIVE, amount="100.00", commission_pct="-1.00")

	def test_garbage_raises_instead_of_pricing_at_zero(self):
		# _budget.py and _fx_revaluation.py coerce junk to 0. Here that would
		# quietly waive the commission on real cash.
		with self.assertRaises(PricingError):
			price_transfer(mode=EXCLUSIVE, amount="", commission_pct="1.00")
		with self.assertRaises(PricingError):
			price_transfer(mode=EXCLUSIVE, amount="100.00", commission_pct=None)

	def test_an_unknown_mode_is_refused(self):
		with self.assertRaises(PricingError):
			price_transfer(mode="Gross", amount="100.00", commission_pct="1.00")


class ModeVocabularyMatchesTheDoctype(unittest.TestCase):
	"""The July helper spelled the modes lower-case, so it matched no stored row."""

	def _options(self) -> list:
		path = os.path.join(_PKG, "stabler", "doctype", "remittance_transfer", "remittance_transfer.json")
		with open(path, encoding="utf-8") as fh:
			fields = {f["fieldname"]: f for f in json.load(fh)["fields"]}
		return fields["commission_mode"]["options"].split("\n")

	def test_the_engine_speaks_the_select_options_verbatim(self):
		self.assertEqual(list(MODES), self._options())

	def test_a_lower_case_caller_gets_the_stored_spelling_back(self):
		r = price_transfer(mode="inclusive", amount="1000.00", commission_pct="1.00")
		self.assertEqual(r["mode"], INCLUSIVE)


if __name__ == "__main__":
	unittest.main()
