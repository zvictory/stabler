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
import json
import sys
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
	return _load_tender()._parse_landed


def _load_tender():
	"""`api.tender` against the two Frappe names its landed readers actually touch."""
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
	return importlib.import_module("stabler.api.tender")


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
# A PO landed line as it sits in the column after ADR-605's second review: the save
# stores what it was GIVEN, so `amount` here is a figure that really was typed in
# company currency once. It is NOT a cached conversion any more -- a fresh save of a
# foreign line leaves `amount` at 0 (see `_PO_FOREIGN_FRESH`). Both shapes are in the
# column on a live site, and the reader has to reach the same total for both.
_PO_FOREIGN = {
	"type": "transport",
	"label": "Freight",
	"amount": 15_360_000.0,
	"actual": 0.0,
	"currency": "USD",
	"fx_rate": 12_800.0,
	"rate_date": "2026-09-01",
	"amount_original": 1200.0,
}
# The same charge as `_PO_FOREIGN` saved TODAY: nothing was typed in company
# currency, so `amount` is 0 and the figure lives in `amount_original` alone. Reading
# it must produce the same 15 360 000, or the two shapes disagree about one charge.
_PO_FOREIGN_FRESH = {
	"type": "transport",
	"label": "Freight",
	"amount": 0.0,
	"actual": 0.0,
	"currency": "USD",
	"fx_rate": 12_800.0,
	"rate_date": "2026-09-01",
	"amount_original": 1200.0,
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

	def test_the_pre_review_and_post_review_shapes_agree(self):
		"""One charge, two stored shapes, one answer.

		Before ADR-605's second review the save cached the conversion into `amount`;
		it now stores only what was typed. Both are in the column on a live site, and
		a reader that treated the cached figure as authoritative would price the old
		rows off a number nobody can reproduce today.
		"""
		cached, _c, _e = parse_landed_charges([_PO_FOREIGN])
		fresh, _c2, _e2 = parse_landed_charges([_PO_FOREIGN_FRESH])
		self.assertEqual(cached, 15_360_000.0)
		self.assertEqual(cached, fresh)

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


#: A legacy so'm line onto which USD has been picked and a GOOD rate fetched, with
#: nothing yet typed in USD. `save_po_landed_charges` does not refuse it -- its
#: refusal reads the rate, and the rate is fine.
_HALF_SWITCHED_PO = {
	"type": "transport",
	"label": "Freight",
	"amount": 3_200_000.0,
	"actual": 0.0,
	"currency": "USD",
	"fx_rate": 12_950.0,
	"rate_date": "2026-09-03",
	"amount_original": 0.0,
}
#: A foreign-currency freight line whose invoice HAS arrived: 1 200 USD planned at
#: 12 800, and 15 500 000 so'm actually paid. The actual is company currency by
#: construction -- the editor's box is `:currency="ccy"` and `landed_actual_from_
#: voucher` returns only base-currency totals -- so it is never converted.
_PO_FOREIGN_INVOICED = {
	"type": "transport",
	"label": "Freight",
	"amount": 0.0,
	"actual": 15_500_000.0,
	"currency": "USD",
	"fx_rate": 12_800.0,
	"rate_date": "2026-09-01",
	"amount_original": 1200.0,
}


class TestThePoRoundTripIsAFixedPoint(unittest.TestCase):
	"""ADR-605 third review, P0. Storing RAW fixed the first hop, not the second.

	`save_po_landed_charges` stores the given figure, but `po_landed_charges` returns
	`_parse_landed`'s VALUED shape, where `amount` is 0.0 on a line nothing can value.
	The editor binds that into its own row, and its save filter then reads the same
	0.0 -- so reopening a half-switched line and pressing Save DELETES it. The PO's
	landed total drops by the charge, and the cheapest-vendor badge can flip on the
	difference.

	The loop has to close: what a read hands the editor must be what the editor can
	hand back. `poControlBoardLandedTotal.spec.js` pins the client half -- which key
	the component reads into its company-currency box -- and this pins the server
	half, so neither can drift without the other going red.
	"""

	def setUp(self):
		self.tender = _load_tender()

	def _store(self, payload: list[dict]) -> str:
		"""Exactly what `save_po_landed_charges` writes to the column."""
		return json.dumps(self.tender._raw_landed_lines(payload), ensure_ascii=False)

	@staticmethod
	def _editor_would_send(line: dict) -> dict:
		"""The payload `PoControlBoard.saveEditor` builds from one line it read.

		Mirrors that function's object literal field for field. `amount` comes from
		`amount_given` because that is the key the component binds into its
		company-currency box -- asserted over the real source in the vitest spec, so
		this is a contract the two tests share rather than one this file invented.
		"""
		return {
			"type": line["type"],
			"label": line["label"],
			"amount": line["amount_given"],
			"actual": line["actual"],
			"tnved": line["tnved"],
			"supplier": line["supplier"],
			"supplier_name": line["supplier_name"],
			"cif": line["cif"],
			"duty_pct": line["duty_pct"],
			"vat_pct": line["vat_pct"],
			"excise_pct": line["excise_pct"],
			"vat_recoverable": line["vat_recoverable"],
			"actual_voucher_type": line["actual_voucher_type"],
			"actual_voucher": line["actual_voucher"],
			"currency": line["currency"],
			"fx_rate": line["fx_rate"],
			"rate_date": line["rate_date"],
			"amount_original": line["amount_original"],
		}

	def test_a_reopened_half_switched_line_still_carries_the_officers_figure(self):
		read = self.tender._parse_landed(self._store([_HALF_SWITCHED_PO]))[0]
		self.assertTrue(read["unvalued"], "the line cannot be valued and must say so")
		self.assertEqual(read["amount"], 0.0, "the summed key stays the derived one")
		self.assertEqual(
			read["amount_given"],
			3_200_000.0,
			"the read gave the editor nothing to put in its company-currency box, so "
			"the officer's figure is off the screen as well as out of the total",
		)

	def test_saving_a_reopened_line_again_writes_the_same_column(self):
		first = self._store([_HALF_SWITCHED_PO])
		read = self.tender._parse_landed(first)
		second = self._store([self._editor_would_send(read[0])])
		self.assertEqual(json.loads(second)[0]["amount"], 3_200_000.0)
		self.assertEqual(second, first, "the second save is not a no-op — the line drifted")

	def test_the_editor_would_still_send_the_line_at_all(self):
		"""`saveEditor` filters on `Number(l.amount) || Number(l.amount_original)`.

		Both were 0 on a reopened half-switch, so the row was not merely blank on
		screen -- it was dropped from the payload, and `save_po_landed_charges`
		replaces the whole array. That is how 3.2M left a Purchase Order silently.
		"""
		read = self.tender._parse_landed(self._store([_HALF_SWITCHED_PO]))[0]
		sent = self._editor_would_send(read)
		self.assertTrue(float(sent["amount"]) or float(sent["amount_original"]))

	def test_an_ordinary_converted_line_round_trips_too(self):
		line = dict(_HALF_SWITCHED_PO, amount=0.0, amount_original=1200.0)
		first = self._store([line])
		read = self.tender._parse_landed(first)
		self.assertEqual(read[0]["amount"], 15_540_000.0, "the summed key is the derived one")
		self.assertEqual(read[0]["amount_given"], 0.0, "nothing was typed in company currency")
		self.assertEqual(self._store([self._editor_would_send(read[0])]), first)

	def test_the_stored_shape_carries_no_derived_key(self):
		"""The PO twin of `test_what_is_stored_is_the_raw_shape_never_the_valued_one`.

		`unvalued` was emitted unconditionally by the raw builder and dumped straight
		to the column -- a derived verdict frozen into storage, against the rule the
		quotation side is already held to. It is derived on every read; a stored copy
		can only ever go stale.
		"""
		stored = json.loads(self._store([_HALF_SWITCHED_PO]))[0]
		for derived in ("unvalued", "amount_given", "actual_given"):
			self.assertNotIn(derived, stored, f"a derived {derived} reached the column")

	def test_an_invoiced_foreign_line_keeps_its_actual_across_the_round_trip(self):
		"""ADR-605 fourth review, P1. The actual has to survive both hops too.

		The planned side was fixed by handing the editor `amount_given`; the actual
		side needed the opposite fix, because `actual` was being CONVERTED on read
		against an `actual_original` that no control has ever written. A reopened
		invoiced line therefore printed the officer's figure in its box while the
		footer under it printed nothing.
		"""
		first = self._store([_PO_FOREIGN_INVOICED])
		self.assertEqual(json.loads(first)[0]["actual"], 15_500_000.0, "the save lost the actual")
		read = self.tender._parse_landed(first)
		self.assertEqual(read[0]["actual"], 15_500_000.0, "the read zeroed the actual")
		self.assertEqual(self._store([self._editor_would_send(read[0])]), first)

	def test_the_stored_shape_carries_no_currency_field_for_the_actual(self):
		"""`actual_original` was write-only and load-bearing in the wrong direction.

		Introduced with the currency work, it never got an input control: the manual
		box is `v-model="l.actual"` at the company currency and `landed_actual_from_
		voucher` returns `base_grand_total` / `base_paid_amount` / `total_debit`. So
		it was 0 on every line, and the read fed that 0 to `line_value`, which reads
		"a currency is named and nothing was typed in it" and answers 0.0 -- zeroing
		the actual of EVERY foreign-currency line, silently, in the deal's actual
		landed cost and its actual profit. A key nothing can write must not be a key
		something divides by.
		"""
		stored = json.loads(self._store([_PO_FOREIGN_INVOICED]))[0]
		self.assertNotIn("actual_original", stored)


class _Row(dict):
	"""A `frappe._dict`-alike: `_deal_landed_split` reads rows both ways."""

	__getattr__ = dict.__getitem__

	def __init__(self, **kwargs):
		super().__init__(**kwargs)


class TestThePoActualIsAlreadyCompanyCurrency(unittest.TestCase):
	"""ADR-605 fourth review, P1. The actual is base currency at every source.

	Both writers put a company-currency figure in `actual`: the modal's own
	`MoneyInput` is bound `:currency="ccy"`, and `landed_actual_from_voucher` pulls
	the BASE total of the linked Purchase Invoice / Payment Entry / Journal Entry.
	Converting it is therefore never right, and the conversion that was there
	answered 0.0 for every currency line -- so a PO over plan showed an actual
	landed cost UNDER plan, in green.
	"""

	def setUp(self):
		self.tender = _load_tender()

	def _read(self, line: dict) -> dict:
		return self.tender._parse_landed([line])[0]

	def test_a_currency_line_keeps_the_figure_that_was_recorded(self):
		self.assertEqual(self._read(_PO_FOREIGN_INVOICED)["actual"], 15_500_000.0)

	def test_the_planned_side_of_the_same_line_is_still_converted(self):
		# The asymmetry is the point, not an oversight: `amount_original` HAS a
		# control (the row's own foreign-currency box), `actual_original` never did.
		self.assertEqual(self._read(_PO_FOREIGN_INVOICED)["amount"], 15_360_000.0)

	def test_an_unusable_rate_does_not_take_the_actual_down_with_it(self):
		# The plan cannot be valued, but the invoice was still paid and its figure is
		# still company currency. Zeroing it here would understate what was spent.
		line = dict(_PO_FOREIGN_INVOICED, fx_rate=0.0)
		read = self._read(line)
		self.assertTrue(read["unvalued"])
		self.assertEqual(read["amount"], 0.0)
		self.assertEqual(read["actual"], 15_500_000.0)

	def test_a_company_currency_line_is_unaffected(self):
		line = {"type": "transport", "label": "Freight", "amount": 3_200_000, "actual": 3_100_000}
		self.assertEqual(self._read(line)["actual"], 3_100_000.0)

	def test_the_board_total_the_screen_prints_includes_it(self):
		"""`po_landed_charges` itself, not a re-implementation of its sum."""
		stored = json.dumps(self.tender._raw_landed_lines([_PO_FOREIGN_INVOICED]))
		values = {"company": "Mikas", "custom_landed_charges": stored, "base_grand_total": 100_000_000.0}
		# `_po_scope` is authorization, not arithmetic — but it is left running rather
		# than stubbed out, so this test also fails if the read stops being gated.
		sys.modules["stabler.stabler.doctype.stabler_settings.stabler_settings"].module_map_for = lambda _c: {
			"tender": 1
		}
		self.tender.frappe.db.exists = lambda *_a, **_k: True
		self.tender.frappe.db.has_column = lambda *_a, **_k: True
		self.tender.frappe.db.get_value = lambda _dt, _name, field: values.get(field, "UZS")
		out = self.tender.po_landed_charges("PUR-ORD-0001")
		self.assertEqual(out["actual_total"], 15_500_000.0)
		self.assertEqual(out["actual_landed"], 115_500_000.0)

	def test_the_deals_actual_landed_cost_includes_it(self):
		"""One hop further out: `_deal_landed_split` feeds `_actual_block`'s
		`actual_landed`, which feeds the actual P&L. A zeroed actual charge there is
		not a display bug -- it overstates realized profit by the whole amount."""
		stored = json.dumps(self.tender._raw_landed_lines([_PO_FOREIGN_INVOICED]))
		row = _Row(name="PUR-ORD-0001", base_grand_total=100_000_000.0, custom_landed_charges=stored)
		self.tender.frappe.db.has_column = lambda *_a, **_k: True
		self.tender.frappe.get_list = lambda *_a, **_k: [row]
		planned, actual, count = self.tender._deal_landed_split("CRM-DEAL-0001", "Mikas")
		self.assertEqual(count, 1)
		self.assertEqual(planned, 115_360_000.0)
		self.assertEqual(actual, 115_500_000.0)
