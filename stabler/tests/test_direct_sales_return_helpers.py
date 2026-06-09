from __future__ import annotations

import unittest

from frappe import ValidationError

from stabler.api.sales import _normalize_direct_return_items


class DirectSalesReturnHelperTest(unittest.TestCase):
	def test_rejects_empty_direct_return_items(self):
		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([])

	def test_normalizes_positive_return_items(self):
		items = _normalize_direct_return_items(
			[
				{"item_code": "ITEM-1", "qty": "2", "uom": "Box", "rate": "12000"},
				{"item_code": "ITEM-2", "qty": 1, "rate": 5000},
			]
		)

		self.assertEqual(
			items,
			[
				{"item_code": "ITEM-1", "qty": 2.0, "rate": 12000.0, "uom": "Box"},
				{"item_code": "ITEM-2", "qty": 1.0, "rate": 5000.0, "uom": None},
			],
		)

	def test_rejects_zero_qty_and_non_positive_rate(self):
		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([{"item_code": "ITEM-1", "qty": 0, "rate": 1}])

		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([{"item_code": "ITEM-1", "qty": 1, "rate": -1}])

		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([{"item_code": "ITEM-1", "qty": 1, "rate": 0}])


if __name__ == "__main__":
	unittest.main()
