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

from stabler.stabler.tender_landed_math import converted_amount


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


if __name__ == "__main__":
	unittest.main()
