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


if __name__ == "__main__":
	unittest.main()
