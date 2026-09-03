"""WP-T3 — a landed-charge line quoted in a foreign currency (Frappe-free).

The tender PO control board picks the winning vendor by comparing `landed_total`,
and every consumer of `_parse_landed` sums `c["amount"]` assuming it is already in
company currency. A line quoted in USD that reaches that sum unconverted makes the
board compare so'm against dollars and crown the wrong vendor -- the same defect
class as P0-MONEY-1, where a list column summed two currencies under one label.

The failure direction is what makes the missing-rate case the important one. An
unconverted 1 200 USD sitting in a so'm total does not look wrong, it looks
CHEAP: that vendor wins on a number four orders of magnitude too small. So a line
whose rate is missing must refuse to produce a figure at all rather than fall
back to the raw number or to zero -- the same stance `lcv_math.line_company_amount`
takes for the imports LCV, which had to learn it first.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_landed_math -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.tender_landed_math import converted_amount, line_value


class TestBaseCurrencyLines(unittest.TestCase):
	"""Every row stored before WP-T3 has no currency. None of them may move."""

	def test_empty_currency_passes_through(self):
		self.assertEqual(converted_amount(15_540_000, "", 0), 15_540_000.0)

	def test_empty_currency_ignores_any_rate(self):
		# A stray rate on a base-currency line must not multiply it.
		self.assertEqual(converted_amount(15_540_000, "", 12_950), 15_540_000.0)

	def test_none_amount_is_zero(self):
		self.assertEqual(converted_amount(None, "", 0), 0.0)


class TestForeignCurrencyLines(unittest.TestCase):
	def test_converts_at_the_line_rate(self):
		self.assertEqual(converted_amount(1_200, "USD", 12_950), 15_540_000.0)

	def test_rounds_to_two_places_like_the_imports_sibling(self):
		# A CBU quote carries three decimals; the stored figure must not.
		self.assertEqual(converted_amount(1, "USD", 12_950.567), 12_950.57)

	def test_a_rebate_keeps_its_sign(self):
		# Landed charges can be negative (a credit note from the forwarder).
		self.assertEqual(converted_amount(-500, "USD", 12_950), -6_475_000.0)


class TestMissingRateRefuses(unittest.TestCase):
	"""The whole point: no figure is better than a wrong one that reads as cheap."""

	def test_zero_rate_yields_nothing(self):
		self.assertIsNone(converted_amount(1_200, "USD", 0))

	def test_missing_rate_yields_nothing(self):
		self.assertIsNone(converted_amount(1_200, "USD", None))

	def test_negative_rate_yields_nothing(self):
		self.assertIsNone(converted_amount(1_200, "USD", -12_950))

	def test_it_never_falls_back_to_the_unconverted_number(self):
		# The trap: returning 1200 into a so'm total makes this vendor cheapest.
		self.assertNotEqual(converted_amount(1_200, "USD", 0), 1_200.0)

	def test_it_never_falls_back_to_zero(self):
		# The other trap: a free charge also makes this vendor cheapest.
		self.assertNotEqual(converted_amount(1_200, "USD", 0), 0.0)


class TestLineValueIsTheOneRule(unittest.TestCase):
	"""ADR-605 review, item 1/6. Both readers of a stored line come through here.

	Until this function existed they disagreed: `_parse_landed` kept the stored
	`amount` when the rate was unusable and `parse_landed_charges` dropped the
	line, so one Purchase Order showed two different landed totals depending on
	which screen asked for it.
	"""

	def test_no_currency_passes_the_stored_figure_through(self):
		self.assertEqual(line_value(3_200_000, None, "", 0), (3_200_000.0, False))

	def test_a_currency_line_is_valued_from_what_was_typed_in_it(self):
		self.assertEqual(line_value(0, 1_200, "USD", 12_950), (15_540_000.0, False))

	def test_an_unusable_rate_leaves_the_line_unvalued(self):
		self.assertEqual(line_value(0, 1_200, "USD", 0), (0.0, True))

	def test_a_currency_with_no_typed_figure_is_unvalued_not_zero(self):
		"""The P0 this function was extracted for.

		Picking USD on a line already holding 3 200 000 so'm leaves
		`amount_original` empty. Valuing that as 0.0 and NOT flagging it is how a
		vendor wins on a landed total that silently lost a charge -- and the zero
		then propagates into the pre-win bid price.
		"""
		self.assertEqual(line_value(3_200_000, 0, "USD", 12_950), (0.0, True))

	def test_it_never_relabels_the_company_currency_figure_as_foreign(self):
		# The other way to get this wrong: treat the stored 3 200 000 so'm as
		# 3 200 000 USD and multiply. That is the ADR-605 defect, sign reversed.
		amount, _unvalued = line_value(3_200_000, 0, "USD", 12_950)
		self.assertNotEqual(amount, 3_200_000.0 * 12_950)
		self.assertNotEqual(amount, 3_200_000.0)

	def test_an_empty_currency_line_is_not_flagged(self):
		# A row the officer has only started typing must not park a warning.
		self.assertEqual(line_value(0, 0, "USD", 0), (0.0, False))
		self.assertEqual(line_value(None, None, "USD", 12_950), (0.0, False))

	def test_a_flagged_line_never_carries_a_figure(self):
		"""`unvalued` implies the amount is 0.0 -- for every shape, not by accident.

		`_landed.parse_landed_charges` keeps a flagged line out of the capitalized
		total with `0.0 if (is_vat or unvalued) else amount`. That `or unvalued`
		clause is a guard, and a guard that can never fire is a guard nobody notices
		has stopped guarding: if this function ever started returning a partial
		figure alongside the flag, the clause is the only thing between that figure
		and a delivered total. This pins the contract the clause rests on, so the
		redundancy is guaranteed rather than assumed.
		"""
		shapes = [
			(3_200_000, 0, "USD", 12_950),  # half-finished currency switch
			(3_200_000, 0, "USD", 0),  # ... and no rate either
			(0, 1_200, "USD", 0),  # typed in USD, no rate
			(15_540_000, 1_200, "EUR", -1),  # a negative rate is not a rate
		]
		for shape in shapes:
			with self.subTest(shape=shape):
				amount, unvalued = line_value(*shape)
				self.assertTrue(unvalued)
				self.assertEqual(amount, 0.0)


if __name__ == "__main__":
	unittest.main()
