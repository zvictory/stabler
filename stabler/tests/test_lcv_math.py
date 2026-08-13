"""Unit tests for the Landed Cost Voucher aggregation (Frappe-free).

Covers currency conversion, VAT exclusion, full (never divided) clearance fee,
multi-LCV delta selection via ``lcv_ref``, and the DRAFT payload shape.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_lcv_math -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import lcv_math


def _line(component, currency, amount, include=1, lcv_ref=None, name=None):
	return {
		"name": name,
		"cost_component": component,
		"currency": currency,
		"amount": amount,
		"include_in_landed_cost": include,
		"lcv_ref": lcv_ref,
	}


class TestUnvaluableLineNames(unittest.TestCase):
	"""The set that must NOT be stamped ``lcv_ref``.

	``aggregate_components`` drops an unvaluable line silently, so if the build
	path stamps it anyway the money is gone: no voucher carries it and ``unconsumed``
	will never offer it again. These tests are the guard on that set.
	"""

	def test_line_without_a_rate_is_unvaluable(self):
		lines = [_line("Freight", "USD", 100, name="r1")]
		self.assertEqual(lcv_math.unvaluable_line_names(lines, {}, "UZS"), {"r1"})

	def test_line_with_a_rate_is_valuable(self):
		lines = [_line("Freight", "USD", 100, name="r1")]
		self.assertEqual(lcv_math.unvaluable_line_names(lines, {"USD": 12500}, "UZS"), set())

	def test_company_currency_line_never_needs_a_rate(self):
		lines = [_line("Uzbekistan Customs Duty", "UZS", 2_000_000, name="r1")]
		self.assertEqual(lcv_math.unvaluable_line_names(lines, {}, "UZS"), set())

	def test_vat_is_excluded_on_purpose_so_it_stays_stampable(self):
		# VAT is never capitalized by design — consuming it is correct, and leaving
		# it unstamped would re-offer it on every future voucher forever.
		lines = [_line("Import VAT", "USD", 100, name="r1")]
		self.assertEqual(lcv_math.unvaluable_line_names(lines, {}, "UZS"), set())

	def test_already_vouchered_line_is_not_in_scope(self):
		lines = [_line("Freight", "USD", 100, lcv_ref="LCV-0001", name="r1")]
		self.assertEqual(lcv_math.unvaluable_line_names(lines, {}, "UZS"), set())

	def test_only_the_unvaluable_of_a_mixed_set_is_returned(self):
		lines = [
			_line("Freight", "USD", 100, name="r1"),
			_line("Insurance", "EUR", 50, name="r2"),
			_line("Uzbekistan Customs Duty", "UZS", 2_000_000, name="r3"),
		]
		# EUR has a rate, USD does not: r1 alone must survive the stamp.
		self.assertEqual(lcv_math.unvaluable_line_names(lines, {"EUR": 13500}, "UZS"), {"r1"})

	def test_the_unstamped_set_matches_exactly_what_aggregation_dropped(self):
		# The invariant the whole fix rests on: every line the voucher could not
		# value is in the set, and no line it DID value is.
		lines = [
			_line("Freight", "USD", 100, name="r1"),
			_line("Insurance", "EUR", 50, name="r2"),
		]
		rates = {"EUR": 13500}
		agg, _warnings = lcv_math.aggregate_components(lines, rates, "UZS")
		self.assertEqual(sorted(agg), ["Insurance"])
		self.assertEqual(lcv_math.unvaluable_line_names(lines, rates, "UZS"), {"r1"})

	def test_translate_hook_is_applied_to_the_template_not_the_sentence(self):
		# The catalog key must be the template, so the lookup happens before the
		# currency is interpolated — otherwise no catalog could ever match.
		seen = []

		def fake(message):
			seen.append(message)
			return "TR:" + message

		_agg, warnings = lcv_math.aggregate_components(
			[_line("Freight", "USD", 100, name="r1")], {}, "UZS", translate=fake
		)
		self.assertEqual(len(warnings), 1)
		self.assertTrue(warnings[0].startswith("TR:"))
		self.assertIn("{0}", seen[0])
		self.assertNotIn("USD", seen[0])


class TestLineCompanyAmount(unittest.TestCase):
	def test_company_currency_passthrough(self):
		self.assertEqual(lcv_math.line_company_amount("UZS", 1_000_000, {}, "UZS"), 1_000_000.0)

	def test_usd_converted(self):
		self.assertEqual(lcv_math.line_company_amount("USD", 100, {"USD": 12500}, "UZS"), 1_250_000.0)

	def test_eur_converted(self):
		self.assertEqual(lcv_math.line_company_amount("EUR", 100, {"EUR": 13500}, "UZS"), 1_350_000.0)

	def test_none_if_rate_missing(self):
		self.assertIsNone(lcv_math.line_company_amount("EUR", 100, {"USD": 12500}, "UZS"))


class TestIsVat(unittest.TestCase):
	def test_detects_vat(self):
		self.assertTrue(lcv_math.is_vat_component("Uzbekistan VAT 12%"))
		self.assertTrue(lcv_math.is_vat_component("import vat"))
		self.assertFalse(lcv_math.is_vat_component("Freight"))


class TestAggregateComponents(unittest.TestCase):
	def test_conversion_and_sum_by_component(self):
		lines = [
			_line("Freight", "USD", 100),
			_line("Freight", "USD", 50),
			_line("Uzbekistan Customs Duty", "UZS", 2_000_000),
		]
		agg, warnings = lcv_math.aggregate_components(lines, rates={"USD": 12500}, company_currency="UZS")
		self.assertEqual(agg["Freight"], 1_875_000.0)  # (100+50) * 12500
		self.assertEqual(agg["Uzbekistan Customs Duty"], 2_000_000.0)
		self.assertEqual(warnings, [])

	def test_vat_excluded(self):
		lines = [_line("Freight", "USD", 100), _line("Uzbekistan VAT 12%", "USD", 40)]
		agg, warnings = lcv_math.aggregate_components(lines, rates={"USD": 12500}, company_currency="UZS")
		self.assertIn("Freight", agg)
		self.assertNotIn("Uzbekistan VAT 12%", agg)
		self.assertEqual(warnings, [])

	def test_clearance_fee_full_amount_not_divided(self):
		# One CI-level clearance fee across 4 containers must land whole, not /4.
		lines = [_line("Customs Clearance Fee", "UZS", 8_000_000)]
		agg, warnings = lcv_math.aggregate_components(lines, rates={"USD": 12500}, company_currency="UZS")
		self.assertEqual(agg["Customs Clearance Fee"], 8_000_000.0)
		# Company-currency line: no rate needed, so an empty-of-UZS map must not warn.
		self.assertEqual(warnings, [])

	def test_excluded_lines_skipped(self):
		lines = [_line("Freight", "USD", 100, include=0)]
		agg, warnings = lcv_math.aggregate_components(lines, rates={"USD": 12500}, company_currency="UZS")
		self.assertEqual(agg, {})
		self.assertEqual(warnings, [])

	def test_consumed_lines_skipped(self):
		lines = [
			_line("Freight", "USD", 100, lcv_ref="LCV-0001"),
			_line("Iran Demurrage", "USD", 30),
		]
		agg, warnings = lcv_math.aggregate_components(lines, {"USD": 12500}, "UZS")
		self.assertNotIn("Freight", agg)
		self.assertEqual(agg["Iran Demurrage"], 375_000.0)
		self.assertEqual(warnings, [])

	def test_zero_amounts_dropped(self):
		lines = [_line("Freight", "USD", 0)]
		agg, warnings = lcv_math.aggregate_components(lines, {"USD": 12500}, "UZS")
		self.assertEqual(agg, {})
		self.assertEqual(warnings, [])

	def test_missing_rate_warns_and_excludes(self):
		lines = [_line("Freight", "EUR", 100)]
		agg, warnings = lcv_math.aggregate_components(lines, {"USD": 12500}, "UZS")
		self.assertEqual(agg, {})
		self.assertEqual(len(warnings), 1)
		self.assertIn("EUR", warnings[0])

	def test_many_unvaluable_lines_of_one_currency_warn_once(self):
		# A CI with twelve USD freight lines and no USD rate is ONE problem. Warning
		# per line would put twelve identical alerts on the review screen and bury
		# the one line that is genuinely different.
		lines = [_line("Freight", "USD", 100) for _ in range(12)]
		agg, warnings = lcv_math.aggregate_components(lines, {}, "UZS")
		self.assertEqual(agg, {})
		self.assertEqual(len(warnings), 1)
		self.assertIn("USD", warnings[0])
		self.assertIn("Freight", warnings[0])

	def test_each_unvaluable_currency_gets_its_own_warning(self):
		# Deduping must not collapse two genuinely separate missing rates into one.
		lines = [_line("Freight", "USD", 100), _line("Insurance", "EUR", 50)]
		_, warnings = lcv_math.aggregate_components(lines, {}, "UZS")
		self.assertEqual(len(warnings), 2)
		self.assertEqual(sorted("EUR" in w for w in warnings), [False, True])

	def test_one_currency_lists_every_component_it_could_not_value(self):
		# The operator has to know WHICH costs fell out, not just that some did.
		lines = [_line("Freight", "USD", 100), _line("Insurance", "USD", 50)]
		_, warnings = lcv_math.aggregate_components(lines, {}, "UZS")
		self.assertEqual(len(warnings), 1)
		self.assertIn("Freight", warnings[0])
		self.assertIn("Insurance", warnings[0])

	def test_mixed_currencies_aggregate(self):
		lines = [
			_line("Freight", "USD", 100),
			_line("Insurance", "EUR", 200),
			_line("Uzbekistan Customs Duty", "UZS", 2_000_000),
		]
		rates = {"USD": 12500, "EUR": 13500}
		agg, warnings = lcv_math.aggregate_components(lines, rates, "UZS")
		self.assertEqual(agg["Freight"], 1_250_000.0)
		self.assertEqual(agg["Insurance"], 2_700_000.0)
		self.assertEqual(agg["Uzbekistan Customs Duty"], 2_000_000.0)
		self.assertEqual(warnings, [])


class TestUnconsumed(unittest.TestCase):
	def test_delta_selection(self):
		lines = [
			_line("Freight", "USD", 100, lcv_ref="LCV-0001"),
			_line("Iran Storage", "USD", 20),
		]
		remaining = lcv_math.unconsumed(lines)
		self.assertEqual(len(remaining), 1)
		self.assertEqual(remaining[0]["cost_component"], "Iran Storage")


class TestBuildLcvPayload(unittest.TestCase):
	def test_draft_payload_shape(self):
		payload = lcv_math.build_lcv_payload(
			company="MSA",
			purchase_receipts=["PR-1", "PR-2"],
			components={"Freight": 1_875_000.0, "Insurance": 250_000.0},
			expense_account="Expenses Included In Valuation - MSA",
		)
		self.assertEqual(payload["distribute_charges_based_on"], "Qty")
		self.assertEqual(len(payload["purchase_receipts"]), 2)
		self.assertEqual(payload["purchase_receipts"][0]["receipt_document_type"], "Purchase Receipt")
		self.assertEqual(len(payload["taxes"]), 2)
		self.assertTrue(
			all(t["expense_account"] == "Expenses Included In Valuation - MSA" for t in payload["taxes"])
		)
		self.assertNotIn("docstatus", payload)

	def test_none_when_no_receipts_or_no_costs(self):
		self.assertIsNone(
			lcv_math.build_lcv_payload(
				company="MSA", purchase_receipts=[], components={"Freight": 1.0}, expense_account="X"
			)
		)
		self.assertIsNone(
			lcv_math.build_lcv_payload(
				company="MSA", purchase_receipts=["PR-1"], components={}, expense_account="X"
			)
		)


def _billable(component, container, purchase_invoice=None, amount=100.0):
	return {
		"cost_component": component,
		"container": container,
		"purchase_invoice": purchase_invoice,
		"currency": "USD",
		"amount": amount,
		"include_in_landed_cost": 1,
		"lcv_ref": None,
	}


def _vouchered(component, container, lcv_ref, purchase_invoice=None, amount=100.0):
	line = _billable(component, container, purchase_invoice=purchase_invoice, amount=amount)
	line["lcv_ref"] = lcv_ref
	return line


class SupersedeBilledTest(unittest.TestCase):
	"""The carrier's own invoice replaces the hand-typed guess of the same cost.

	This is the guard for the double-count hand-attribution made possible: the
	same freight can sit on one container twice — typed in by an operator so it
	reaches the landed cost, and again as the transporter's Purchase Invoice so it
	reaches A/P. Once the bill capitalizes, an unguarded aggregate charges that
	money to stock valuation twice, permanently, through a submitted LCV.
	"""

	def test_a_billed_line_drops_the_hand_typed_line_beside_it(self):
		lines = [
			_billable("Freight", "CNT-1", amount=900.0),
			_billable("Freight", "CNT-1", purchase_invoice="PINV-1", amount=1000.0),
		]
		kept, warnings = lcv_math.supersede_billed(lines)
		self.assertEqual([ln["amount"] for ln in kept], [1000.0])
		self.assertEqual(len(warnings), 1)

	def test_the_bill_is_the_one_that_survives_not_the_larger_figure(self):
		# Precedence is by source, never by amount: the invoice is what the carrier
		# will actually be paid, even when the operator guessed higher.
		lines = [
			_billable("Freight", "CNT-1", amount=5000.0),
			_billable("Freight", "CNT-1", purchase_invoice="PINV-1", amount=1.0),
		]
		kept, _ = lcv_math.supersede_billed(lines)
		self.assertEqual([ln["purchase_invoice"] for ln in kept], ["PINV-1"])

	def test_a_bill_on_one_container_does_not_touch_another_container(self):
		# The whole point of scoping per container: CNT-2's operator typed a real,
		# separate freight cost that no invoice covers yet.
		lines = [
			_billable("Freight", "CNT-1", purchase_invoice="PINV-1"),
			_billable("Freight", "CNT-2"),
		]
		kept, warnings = lcv_math.supersede_billed(lines)
		self.assertEqual(len(kept), 2)
		self.assertEqual(warnings, [])

	def test_a_bill_only_supersedes_its_own_component(self):
		lines = [
			_billable("Freight", "CNT-1", purchase_invoice="PINV-1"),
			_billable("Insurance", "CNT-1"),
		]
		kept, warnings = lcv_math.supersede_billed(lines)
		self.assertEqual(len(kept), 2)
		self.assertEqual(warnings, [])

	def test_two_bills_for_the_same_component_are_both_real_money(self):
		# Two carriers on one leg is not a duplicate; dropping one would lose a
		# cost the company genuinely owes.
		lines = [
			_billable("Cross-Border Transport", "CNT-1", purchase_invoice="PINV-1", amount=400.0),
			_billable("Cross-Border Transport", "CNT-1", purchase_invoice="PINV-2", amount=600.0),
		]
		kept, warnings = lcv_math.supersede_billed(lines)
		self.assertEqual(round(sum(ln["amount"] for ln in kept), 2), 1000.0)
		self.assertEqual(warnings, [])

	def test_nothing_changes_on_a_container_with_no_linked_bills(self):
		# Every import that predates the feature goes through this path unchanged.
		lines = [_billable("Freight", "CNT-1"), _billable("Insurance", "CNT-1")]
		kept, warnings = lcv_math.supersede_billed(lines)
		self.assertEqual(kept, lines)
		self.assertEqual(warnings, [])

	def test_a_blank_purchase_invoice_is_not_a_bill(self):
		lines = [
			_billable("Freight", "CNT-1", purchase_invoice="   "),
			_billable("Freight", "CNT-1"),
		]
		kept, warnings = lcv_math.supersede_billed(lines)
		self.assertEqual(len(kept), 2)
		self.assertEqual(warnings, [])

	def test_the_drop_is_never_silent_and_says_how_to_undo_it(self):
		# A line vanishing from the valuation with no trace is how the operator
		# loses a cost they meant to charge separately.
		lines = [
			_billable("Freight", "CNT-1"),
			_billable("Freight", "CNT-1", purchase_invoice="PINV-1"),
		]
		_, warnings = lcv_math.supersede_billed(lines)
		self.assertIn("Freight", warnings[0])
		self.assertIn("CNT-1", warnings[0])
		self.assertIn("Remove the bill link", warnings[0])

	def test_it_reports_like_the_customs_precedence_it_mirrors(self):
		kept, warnings = lcv_math.supersede_billed([])
		self.assertEqual((kept, warnings), ([], []))


class VoucheredHandLineTest(unittest.TestCase):
	"""The half of the double-count that ``supersede_billed`` structurally cannot see.

	Supersession happens while the voucher is being built, over the lines that are
	still candidates. When the operator's estimate was already consumed by an
	earlier LCV it carries an ``lcv_ref``, ``unconsumed`` drops it from every later
	candidate set, and a bill linked afterwards writes a second line for the same
	money that the next voucher capitalizes again — measured on the UAT chain as
	150 USD charged to stock valuation twice, across two vouchers, silently
	(stabler-wen). This read is what the link path uses to refuse that second write.
	"""

	def test_it_names_the_voucher_that_already_took_the_money(self):
		# The operator's estimate is inside MAT-LCV-13; capitalizing the bill on top
		# of it is the double-count. The ref is returned, not a bare True, because
		# the warning has to tell the accountant which voucher to look at.
		lines = [_vouchered("Freight", "CNT-1", "MAT-LCV-13")]
		self.assertEqual(lcv_math.vouchered_hand_line(lines, "CNT-1", "Freight"), "MAT-LCV-13")

	def test_an_unvouchered_estimate_is_left_alone(self):
		# Still a candidate, so ``supersede_billed`` will drop it at build time with
		# a warning. Refusing the bill's line here too would lose the cost entirely.
		lines = [_billable("Freight", "CNT-1")]
		self.assertIsNone(lcv_math.vouchered_hand_line(lines, "CNT-1", "Freight"))

	def test_a_voucher_on_one_container_says_nothing_about_another(self):
		lines = [_vouchered("Freight", "CNT-1", "MAT-LCV-13")]
		self.assertIsNone(lcv_math.vouchered_hand_line(lines, "CNT-2", "Freight"))

	def test_the_two_transport_legs_are_not_the_same_cost(self):
		# Freight is the sea leg, Cross-Border Transport the trucking leg. Treating
		# them as one family would silently under-capitalize the second leg, and a
		# vouchered line never comes back.
		lines = [_vouchered("Freight", "CNT-1", "MAT-LCV-13")]
		self.assertIsNone(lcv_math.vouchered_hand_line(lines, "CNT-1", "Cross-Border Transport"))

	def test_another_bill_is_a_second_real_invoice_not_a_duplicate(self):
		# Same rule ``supersede_billed`` applies: two carriers on one leg are two
		# costs. Only a hand-typed estimate yields to a bill.
		lines = [_vouchered("Freight", "CNT-1", "MAT-LCV-13", purchase_invoice="PINV-9")]
		self.assertIsNone(lcv_math.vouchered_hand_line(lines, "CNT-1", "Freight"))

	def test_a_line_excluded_from_the_landed_cost_never_reached_valuation(self):
		line = _vouchered("Freight", "CNT-1", "MAT-LCV-13")
		line["include_in_landed_cost"] = 0
		self.assertIsNone(lcv_math.vouchered_hand_line([line], "CNT-1", "Freight"))


if __name__ == "__main__":
	unittest.main()
