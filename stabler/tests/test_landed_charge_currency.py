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

import importlib
import types
import unittest

from stabler.api._landed import (
	calculate_quotation_landed,
	parse_landed_charges,
	rank_quotations_landed,
)
from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide -- hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _load_parse_landed():
	"""`tender._parse_landed` against the two Frappe names it actually touches."""
	_SANDBOX.evict(
		"stabler.api.tender",
		"stabler.api.purchasing",
		"frappe",
		"frappe.utils",
		"stabler.api.approvals",
		"stabler.api._common",
		"stabler.api._bid_package",
		"stabler.api.organization",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
	)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.DoesNotExistError = LookupError
	frappe.session = types.SimpleNamespace(user="buyer@example.com")
	frappe.db = types.SimpleNamespace(has_column=lambda *_a, **_k: False)
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if args == () else args[0]
	frappe.get_roles = lambda _user=None: []
	frappe.has_permission = lambda *_a, **_k: True
	frappe.get_list = lambda *_a, **_k: []
	frappe.get_all = lambda *_a, **_k: []
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.getdate = lambda value: value
	utils.add_months = lambda value, months: value
	utils.cint = lambda value=0: int(float(value or 0))
	utils.today = lambda: "2026-09-03"
	utils.now = lambda: "2026-09-03 09:00:00"
	frappe.utils = utils
	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})
	for name, attrs in (
		("stabler.api.approvals", {"_assert_company_scope": lambda _c: None}),
		("stabler.api._common", {"_require_company": lambda _c: None}),
		(
			"stabler.api._bid_package",
			{
				"assemble_bid_package": lambda *_a, **_k: {},
				"build_bid_docx": lambda *_a, **_k: b"",
			},
		),
		("stabler.api.organization", {"_can_access_module": lambda *_a, **_k: True}),
		("stabler.api.purchasing", {"tender_quotations": lambda _d: {"rows": []}}),
		("stabler.stabler.doctype.stabler_settings.stabler_settings", {"module_map_for": lambda _c: {}}),
	):
		mod = types.ModuleType(name)
		for attr, value in attrs.items():
			setattr(mod, attr, value)
		_SANDBOX.install({name: mod})
	return importlib.import_module("stabler.api.tender")._parse_landed


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
# A PO line whose rate no longer values it. `amount` was a real conversion when it
# was written, but nobody reading the row today can reproduce it.
_STALE_PO = {
	"type": "transport",
	"label": "Freight",
	"amount": 15_360_000.0,
	"actual": 0.0,
	"currency": "USD",
	"fx_rate": 0.0,
	"rate_date": "",
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
		self.assertEqual(clean[0]["company_amount"], 15_540_000.0)
		# ... and the officer's own box is left alone. `amount` is the company-currency
		# figure AS GIVEN; on a currency line that is nothing, because the figure was
		# typed into the currency box instead.
		self.assertEqual(clean[0]["amount"], 0.0)

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
		self.assertEqual(clean[0]["company_amount"], 15_540_000.0)
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
		# With no currency the given figure and the derived one are the same number.
		# They are still two keys, because on the lines that matter they differ.
		self.assertEqual(clean[0]["amount"], 3_200_000.0)
		self.assertEqual(clean[0]["company_amount"], 3_200_000.0)
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


class TestACurrencyWithoutATypedFigure(unittest.TestCase):
	"""The P0 the ADR-605 review caught, at the level a caller sees it.

	Reachable straight through the product: the editor loads a legacy so'm line with
	`amount_original: null`, the officer picks USD from the dropdown, the CBU button
	fills a real rate -- and `converted_amount(0, "USD", 12950)` is 0.0, not None. The
	line was therefore valued at a bare zero and NOT flagged, so `has_unvalued_charges`
	stayed False, `estimate_complete` stayed True, `cheapest_landed` could be awarded
	to that vendor, and the zero propagated into the pre-win bid price.
	"""

	def test_a_named_currency_with_nothing_typed_in_it_is_flagged(self):
		line = {"charge_type": "Freight", "amount": 3_200_000, "currency": "USD", "fx_rate": 12_950}
		total, clean, _has_est = parse_landed_charges([line])
		self.assertEqual(total, 0.0)
		self.assertTrue(clean[0]["unvalued"], "a bare 0.0 that nothing flags is the P0")

	def test_it_does_not_relabel_the_company_currency_figure(self):
		# The opposite failure: treating 3 200 000 so'm as 3 200 000 USD. Both are
		# wrong; refusing to value the line is the only honest answer.
		line = {"charge_type": "Freight", "amount": 3_200_000, "currency": "USD", "fx_rate": 12_950}
		_total, clean, _has_est = parse_landed_charges([line])
		self.assertEqual(clean[0]["company_amount"], 0.0)
		# The so'm figure is NOT collateral damage. It is the only evidence the line
		# is half-switched, it is what the officer sees when the editor reopens, and
		# it is what the save path now stores. Zeroing it here is the second review's
		# P0 one layer up.
		self.assertEqual(clean[0]["amount"], 3_200_000.0)

	def test_the_quotation_reports_it_so_the_ranking_cannot_hide_it(self):
		q = calculate_quotation_landed(
			{
				"name": "SQ-1",
				"base_grand_total": 100_000_000.0,
				"custom_landed_charges": [
					{"charge_type": "Freight", "amount": 3_200_000, "currency": "USD", "fx_rate": 12_950}
				],
			}
		)
		self.assertTrue(q["has_unvalued_charges"])
		self.assertEqual(q["base_landed_total"], 100_000_000.0)

	def test_a_line_with_nothing_on_either_side_is_not_flagged(self):
		# A row the officer only just added must not park a permanent warning.
		_total, clean, _has_est = parse_landed_charges(
			[{"charge_type": "Freight", "currency": "USD", "fx_rate": 0, "description": "tbd"}]
		)
		self.assertFalse(clean[0]["unvalued"])


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
		self.assertEqual(clean[0]["company_amount"], 15_360_000.0)

	def test_a_customs_line_keeps_the_declared_figure(self):
		_total, clean, _has_est = parse_landed_charges([_PO_CUSTOMS])
		self.assertEqual(clean[0]["company_amount"], 4_200_000.0)


class TestBothReadersOfAPoLineAgree(unittest.TestCase):
	"""ADR-605 review, item 6. One Purchase Order, two readers, one total.

	`tender._parse_landed` serves the PO landed editor and `_deal_landed_split`;
	`_landed.parse_landed_charges` sums the very same stored JSON for the PO control
	board. They disagreed on a line naming a currency with an unusable rate -- one
	kept the stored figure, the other dropped it -- so the same PO showed two
	different landed totals depending on which screen the officer opened.

	`save_po_landed_charges` refuses to CREATE that state, so it only arrives by
	hand-edited JSON; that is precisely why neither reader may throw on it, and why
	they must agree about what it is worth.
	"""

	def setUp(self):
		self._parse_landed = _load_parse_landed()

	def test_the_two_totals_match(self):
		editor_total = sum(c["amount"] for c in self._parse_landed([_STALE_PO]))
		board_total, _clean, _has_est = parse_landed_charges([_STALE_PO])
		self.assertEqual(editor_total, board_total)
		self.assertEqual(board_total, 0.0)

	def test_the_two_flags_match(self):
		editor_line = self._parse_landed([_STALE_PO])[0]
		_total, board_lines, _has_est = parse_landed_charges([_STALE_PO])
		self.assertTrue(editor_line["unvalued"])
		self.assertEqual(editor_line["unvalued"], board_lines[0]["unvalued"])

	def test_a_healthy_foreign_line_still_agrees(self):
		# The rule must not have been "align by dropping everything".
		healthy = dict(_STALE_PO, fx_rate=12_800.0)
		editor_total = sum(c["amount"] for c in self._parse_landed([healthy]))
		board_total, _clean, _has_est = parse_landed_charges([healthy])
		self.assertEqual(editor_total, 15_360_000.0)
		self.assertEqual(editor_total, board_total)


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
