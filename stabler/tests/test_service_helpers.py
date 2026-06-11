from __future__ import annotations

import unittest

from frappe import ValidationError

from stabler.api.service import _normalize_visit_items, _visit_needs_billing


class ServiceHelperTest(unittest.TestCase):
	def test_normalize_visit_items_rejects_empty_payload(self):
		with self.assertRaises(ValidationError):
			_normalize_visit_items([])

	def test_normalize_visit_items_accepts_rates_and_warehouses(self):
		items = _normalize_visit_items(
			[
				{"item_code": "LABOR", "qty": "1", "rate": "250000"},
				{"item_code": "FILTER", "qty": 2, "basic_rate": "10000", "warehouse": "Van - A"},
			]
		)

		self.assertEqual(
			items,
			[
				{
					"item_code": "LABOR",
					"qty": 1.0,
					"rate": 250000.0,
					"basic_rate": None,
					"warehouse": None,
					"uom": None,
				},
				{
					"item_code": "FILTER",
					"qty": 2.0,
					"rate": None,
					"basic_rate": 10000.0,
					"warehouse": "Van - A",
					"uom": None,
				},
			],
		)

	def test_normalize_visit_items_rejects_missing_item_and_non_positive_qty(self):
		with self.assertRaises(ValidationError):
			_normalize_visit_items([{"qty": 1}])

		with self.assertRaises(ValidationError):
			_normalize_visit_items([{"item_code": "FILTER", "qty": 0}])

	def test_visit_needs_billing_for_billable_issue_types_only(self):
		self.assertTrue(_visit_needs_billing("Refill", False))
		self.assertTrue(_visit_needs_billing("Repair", False))
		self.assertFalse(_visit_needs_billing("Repair", True))
		self.assertFalse(_visit_needs_billing("Inspection", False))


if __name__ == "__main__":
	unittest.main()
