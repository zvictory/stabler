from __future__ import annotations

import unittest

from frappe import ValidationError

from stabler.api.pos import _assert_cart_available, _normalize_cart_items


class POSHelperTest(unittest.TestCase):
	def test_normalize_cart_items_rejects_empty_payload(self):
		with self.assertRaises(ValidationError):
			_normalize_cart_items([])

	def test_normalize_cart_items_merges_duplicate_items(self):
		items = _normalize_cart_items(
			[
				{"item_code": "ITEM-1", "qty": "1"},
				{"item_code": "ITEM-1", "qty": "2.5"},
			]
		)

		self.assertEqual(items, [{"item_code": "ITEM-1", "qty": 3.5}])

	def test_assert_cart_available_blocks_short_shop_stock(self):
		with self.assertRaises(ValidationError):
			_assert_cart_available(
				[{"item_code": "ITEM-1", "qty": 3}],
				{"ITEM-1": 2},
			)


if __name__ == "__main__":
	unittest.main()
