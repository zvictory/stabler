"""Unit tests for the pure stock-reconciliation prep logic (no Frappe)."""

from __future__ import annotations

import unittest

from stabler.api._stock_recon import is_changed, prepare_reconciliation


class IsChangedTest(unittest.TestCase):
	def test_equal_not_changed(self):
		self.assertFalse(is_changed(10, 10))

	def test_tiny_diff_not_changed(self):
		self.assertFalse(is_changed(10, 10.0000001))

	def test_real_diff_changed(self):
		self.assertTrue(is_changed(10, 8))


class PrepareTest(unittest.TestCase):
	def test_only_changed_lines_returned(self):
		rows = [
			{
				"item_code": "A",
				"warehouse": "W",
				"current_qty": 10,
				"counted_qty": 10,
				"valuation_rate": 5,
			},  # unchanged
			{
				"item_code": "B",
				"warehouse": "W",
				"current_qty": 10,
				"counted_qty": 7,
				"valuation_rate": 5,
			},  # -3
		]
		res = prepare_reconciliation(rows)
		self.assertEqual(res["summary"]["changed_count"], 1)
		self.assertEqual(res["lines"][0]["item_code"], "B")
		self.assertEqual(res["lines"][0]["qty"], 7)
		self.assertEqual(res["lines"][0]["variance_qty"], -3)
		self.assertEqual(res["lines"][0]["variance_value"], -15)

	def test_summary_totals(self):
		rows = [
			{
				"item_code": "A",
				"warehouse": "W",
				"current_qty": 0,
				"counted_qty": 5,
				"valuation_rate": 2,
			},  # +5, +10
			{
				"item_code": "B",
				"warehouse": "W",
				"current_qty": 10,
				"counted_qty": 8,
				"valuation_rate": 3,
			},  # -2, -6
		]
		s = prepare_reconciliation(rows)["summary"]
		self.assertEqual(s["changed_count"], 2)
		self.assertEqual(s["total_qty_delta"], 3)
		self.assertEqual(s["total_value_delta"], 4)

	def test_rows_missing_item_or_warehouse_skipped(self):
		rows = [
			{"item_code": "", "warehouse": "W", "current_qty": 0, "counted_qty": 5},
			{"item_code": "A", "warehouse": "", "current_qty": 0, "counted_qty": 5},
		]
		self.assertEqual(prepare_reconciliation(rows)["summary"]["changed_count"], 0)

	def test_empty(self):
		res = prepare_reconciliation([])
		self.assertEqual(res["lines"], [])
		self.assertEqual(res["summary"]["changed_count"], 0)


if __name__ == "__main__":
	unittest.main()
