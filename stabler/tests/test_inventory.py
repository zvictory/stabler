"""Tests for inventory API helpers."""

from __future__ import annotations

import unittest

from stabler.api.inventory import _format_warehouse_stock_row


class WarehouseStockRowTest(unittest.TestCase):
	def test_formats_quantities_and_stock_value_for_drilldown(self):
		row = _format_warehouse_stock_row({
			"item_code": "ITEM-001",
			"item_name": "Cotton Thread",
			"item_group": "Raw Material",
			"stock_uom": "Kg",
			"actual_qty": "12.5",
			"reserved_qty": "2.5",
			"ordered_qty": "4",
			"projected_qty": "14",
			"valuation_rate": "8000",
		})

		self.assertEqual(row["item_code"], "ITEM-001")
		self.assertEqual(row["free_qty"], 10)
		self.assertEqual(row["stock_value"], 100000)


if __name__ == "__main__":
	unittest.main()
