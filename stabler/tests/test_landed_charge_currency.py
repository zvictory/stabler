"""ADR-605 — a quotation landed-charge line quoted in a foreign currency (Frappe-free).

`get_quotation_landed` adds `parse_landed_charges`' total to `base_grand_total`,
which is company currency. Until ADR-605 the charge amounts were summed with no
currency and no rate, while `LandedChargesEditor` labelled the very same numbers
with the QUOTATION's currency: one stored number, two labels. A 1 200 USD freight
line therefore entered a so'm landed total as 1 200 -- four orders of magnitude
too small, so that vendor reads as CHEAP and wins the comparison. The bid price is
then computed from a mislabelled currency.

PO landed lines learned this in WP-T3 (`tender_landed_math.converted_amount`).
These pin that quotation lines now use the SAME rule and the same line shape:

  * `currency` empty  -> the figure is already company currency (every line
    stored before ADR-605); it passes through untouched.
  * `currency` named + usable rate -> `amount_original x fx_rate`, and the
    company-currency figure lands in `amount` exactly as it does on a PO line.
  * `currency` named + no usable rate -> the line CANNOT be valued. It is kept
    out of every total and marked `unvalued`, because adding it at its raw
    number, or as zero, both make the vendor look cheaper than it is.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_landed_charge_currency -v
"""

from __future__ import annotations

import unittest

from stabler.api._landed import (
	calculate_quotation_landed,
	parse_landed_charges,
	rank_quotations_landed,
)

# 1 200 USD of freight at 12 950 so'm = 15 540 000 so'm.
_FOREIGN = {
	"charge_type": "Freight",
	"amount_original": 1200,
	"currency": "USD",
	"fx_rate": 12950,
	"rate_date": "2026-09-03",
}
# The same line before anyone fetched a rate for it.
_FOREIGN_NO_RATE = {
	"charge_type": "Freight",
	"amount_original": 1200,
	"currency": "USD",
	"fx_rate": 0,
}
# Every line stored before ADR-605: a bare amount, already company currency.
_LEGACY = {"charge_type": "Customs Duty", "amount": 3_200_000}
# A PO landed line as `tender._parse_landed` stores it: `amount` ALREADY converted.
_PO_FOREIGN = {
	"type": "transport",
	"label": "Freight",
	"amount": 15_360_000.0,
	"actual": 0.0,
	"currency": "USD",
	"fx_rate": 12_800.0,
	"rate_date": "2026-09-01",
	"amount_original": 1200.0,
	"actual_original": 0.0,
}
# A customs line carries no currency by construction: `save_po_landed_charges`
# refuses the combination, because the ГТД declares the customs value in company
# currency at the rate customs itself applied.
_PO_CUSTOMS = {
	"type": "customs",
	"label": "GTD",
	"amount": 4_200_000.0,
	"actual": 0.0,
	"currency": "",
	"fx_rate": 0.0,
	"rate_date": "",
	"amount_original": None,
}


class TestForeignLineIsConverted(unittest.TestCase):
	def test_the_total_is_the_converted_figure_not_the_typed_one(self):
		# WHY: the total is added to `base_grand_total` (company currency). 1 200
		# reaching that sum unconverted is the whole defect ADR-605 exists for.
		total, clean, has_est = parse_landed_charges([_FOREIGN])
		self.assertTrue(has_est)
		self.assertEqual(total, 15_540_000.0)
		self.assertEqual(clean[0]["amount"], 15_540_000.0)

	def test_the_line_keeps_the_typed_figure_and_its_provenance(self):
		# Drop any of these and the officer can no longer tell WHICH day's rate
		# produced the company-currency number -- the same reason `_parse_landed`
		# round-trips them for a PO line.
		_total, clean, _has_est = parse_landed_charges([_FOREIGN])
		self.assertEqual(clean[0]["amount_original"], 1200.0)
		self.assertEqual(clean[0]["currency"], "USD")
		self.assertEqual(clean[0]["fx_rate"], 12950.0)
		self.assertEqual(clean[0]["rate_date"], "2026-09-03")
		self.assertFalse(clean[0]["unvalued"])

	def test_a_recoverable_vat_line_is_converted_but_still_not_capitalized(self):
		# IAS 2 s11 and the currency rule are independent: converting a VAT line
		# must not smuggle it back into the landed total.
		vat = dict(_FOREIGN, charge_type="VAT", is_recoverable_vat=True)
		total, clean, _has_est = parse_landed_charges([vat])
		self.assertEqual(total, 0.0)
		self.assertEqual(clean[0]["amount"], 15_540_000.0)
		self.assertEqual(clean[0]["capitalized_amount"], 0.0)


class TestUnvaluableLineLeavesTheTotal(unittest.TestCase):
	"""No figure is better than one that reads as cheap."""

	def test_a_currency_with_no_rate_contributes_nothing(self):
		total, _clean, _has_est = parse_landed_charges([_FOREIGN_NO_RATE])
		self.assertEqual(total, 0.0)

	def test_it_never_falls_back_to_the_unconverted_number(self):
		# The trap this test exists for: summing 1 200 into a so'm total hands
		# the tender to this vendor on a number 12 950x too small.
		total, _clean, _has_est = parse_landed_charges([_FOREIGN_NO_RATE])
		self.assertNotEqual(total, 1200.0)

	def test_the_line_is_marked_so_the_screen_can_say_so(self):
		# Excluding it silently is how a landed total quietly shrinks; the flag
		# is what lets the editor and the comparison table name the gap.
		_total, clean, _has_est = parse_landed_charges([_FOREIGN_NO_RATE])
		self.assertTrue(clean[0]["unvalued"])
		self.assertEqual(clean[0]["capitalized_amount"], 0.0)

	def test_the_valued_siblings_still_count(self):
		# One unusable rate must not void the rest of the estimate.
		total, clean, _has_est = parse_landed_charges([_FOREIGN, _FOREIGN_NO_RATE, _LEGACY])
		self.assertEqual(total, 18_740_000.0)
		self.assertEqual([c["unvalued"] for c in clean], [False, True, False])


class TestLegacyLinesDoNotMove(unittest.TestCase):
	"""Every charge stored before ADR-605 has no currency. None of them may move."""

	def test_a_bare_amount_passes_through(self):
		total, clean, has_est = parse_landed_charges([_LEGACY])
		self.assertTrue(has_est)
		self.assertEqual(total, 3_200_000.0)
		self.assertEqual(clean[0]["amount"], 3_200_000.0)
		self.assertEqual(clean[0]["currency"], "")
		self.assertFalse(clean[0]["unvalued"])

	def test_a_stray_rate_on_a_base_currency_line_is_ignored(self):
		# `converted_amount`'s stance: an empty currency means the figure is
		# already company currency, so a leftover rate must not multiply it.
		total, _clean, _has_est = parse_landed_charges([dict(_LEGACY, fx_rate=12950)])
		self.assertEqual(total, 3_200_000.0)

	def test_base_amount_is_still_read(self):
		# The pre-ADR-605 fallback field; a PO line reaching this function has no
		# `amount_original` for a customs line and must keep its stored figure.
		total, _clean, _has_est = parse_landed_charges([{"charge_type": "Freight", "base_amount": 500}])
		self.assertEqual(total, 500.0)


class TestAPurchaseOrderLineIsNotConvertedTwice(unittest.TestCase):
	"""`parse_landed_charges` also sums PO landed lines (`tender.po_control_board`).

	A PO line has ALREADY been converted by `tender._parse_landed` -- `amount` is
	the company-currency figure and `amount_original` the typed one. Converting
	from `amount` here would multiply it by the rate a second time: 1 200 USD would
	reach the board as 196 608 000 000 so'm. Reading `amount_original` whenever a
	currency is named is what keeps the two paths on one number.
	"""

	def test_the_board_total_is_unchanged_by_adr_605(self):
		total, _clean, _has_est = parse_landed_charges([_PO_FOREIGN, _PO_CUSTOMS])
		self.assertEqual(total, 19_560_000.0)

	def test_the_foreign_po_line_keeps_the_figure_the_po_editor_stored(self):
		_total, clean, _has_est = parse_landed_charges([_PO_FOREIGN])
		self.assertEqual(clean[0]["amount"], 15_360_000.0)

	def test_a_customs_line_keeps_the_declared_figure(self):
		_total, clean, _has_est = parse_landed_charges([_PO_CUSTOMS])
		self.assertEqual(clean[0]["amount"], 4_200_000.0)


class TestTheExclusionSurvivesTheRanking(unittest.TestCase):
	"""Whoever reads the total must read the same total the editor showed."""

	def test_calculate_quotation_landed_excludes_and_reports(self):
		q = calculate_quotation_landed(
			{
				"name": "SQ-1",
				"base_grand_total": 100_000_000.0,
				"custom_landed_charges": [_FOREIGN, _FOREIGN_NO_RATE],
			}
		)
		self.assertEqual(q["landed_charges_total"], 15_540_000.0)
		self.assertEqual(q["base_landed_total"], 115_540_000.0)
		self.assertTrue(q["has_unvalued_charges"])

	def test_a_fully_valued_quotation_is_not_flagged(self):
		q = calculate_quotation_landed(
			{"name": "SQ-1", "base_grand_total": 100_000_000.0, "custom_landed_charges": [_FOREIGN]}
		)
		self.assertFalse(q["has_unvalued_charges"])

	def test_ranking_cannot_crown_a_vendor_on_an_unconverted_charge(self):
		"""The failure in one assertion: who wins.

		Both bids cost 100 000 000 at sticker. The dear one adds 1 200 USD of
		freight; summed unconverted that is 1 200 so'm and it still "wins" by
		9 998 800. Converted it is 15 540 000 and the other bid wins.
		"""
		ranked = rank_quotations_landed(
			[
				{
					"name": "SQ-FOREIGN-FREIGHT",
					"base_grand_total": 100_000_000.0,
					"custom_landed_charges": [_FOREIGN],
				},
				{
					"name": "SQ-LOCAL-FREIGHT",
					"base_grand_total": 100_000_000.0,
					"custom_landed_charges": [{"charge_type": "Freight", "amount": 10_000_000}],
				},
			]
		)
		self.assertTrue(ranked["estimate_complete"])
		self.assertEqual(ranked["cheapest_landed_quote"], "SQ-LOCAL-FREIGHT")


if __name__ == "__main__":
	unittest.main()
