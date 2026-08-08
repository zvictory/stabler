"""Unit tests for the Landed Cost Voucher aggregation (Frappe-free).

Covers currency conversion, VAT exclusion, full (never divided) clearance fee,
multi-LCV delta selection via ``lcv_ref``, and the DRAFT payload shape.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_lcv_math -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import lcv_math


def _line(component, currency, amount, include=1, lcv_ref=None):
	return {
		"cost_component": component,
		"currency": currency,
		"amount": amount,
		"include_in_landed_cost": include,
		"lcv_ref": lcv_ref,
	}


class TestLineCompanyAmount(unittest.TestCase):
	def test_company_currency_passthrough(self):
		self.assertEqual(lcv_math.line_company_amount("UZS", 1_000_000, 12500, "UZS"), 1_000_000.0)

	def test_usd_converted(self):
		self.assertEqual(lcv_math.line_company_amount("USD", 100, 12500, "UZS"), 1_250_000.0)


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
		agg = lcv_math.aggregate_components(lines, usd_rate=12500, company_currency="UZS")
		self.assertEqual(agg["Freight"], 1_875_000.0)  # (100+50) * 12500
		self.assertEqual(agg["Uzbekistan Customs Duty"], 2_000_000.0)

	def test_vat_excluded(self):
		lines = [_line("Freight", "USD", 100), _line("Uzbekistan VAT 12%", "USD", 40)]
		agg = lcv_math.aggregate_components(lines, usd_rate=12500, company_currency="UZS")
		self.assertIn("Freight", agg)
		self.assertNotIn("Uzbekistan VAT 12%", agg)

	def test_clearance_fee_full_amount_not_divided(self):
		# One CI-level clearance fee across 4 containers must land whole, not /4.
		lines = [_line("Customs Clearance Fee", "UZS", 8_000_000)]
		agg = lcv_math.aggregate_components(lines, usd_rate=12500, company_currency="UZS")
		self.assertEqual(agg["Customs Clearance Fee"], 8_000_000.0)

	def test_excluded_lines_skipped(self):
		lines = [_line("Freight", "USD", 100, include=0)]
		self.assertEqual(lcv_math.aggregate_components(lines, 12500, "UZS"), {})

	def test_consumed_lines_skipped(self):
		lines = [
			_line("Freight", "USD", 100, lcv_ref="LCV-0001"),
			_line("Iran Demurrage", "USD", 30),
		]
		agg = lcv_math.aggregate_components(lines, 12500, "UZS")
		self.assertNotIn("Freight", agg)
		self.assertEqual(agg["Iran Demurrage"], 375_000.0)

	def test_zero_amounts_dropped(self):
		lines = [_line("Freight", "USD", 0)]
		self.assertEqual(lcv_math.aggregate_components(lines, 12500, "UZS"), {})


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


if __name__ == "__main__":
	unittest.main()
