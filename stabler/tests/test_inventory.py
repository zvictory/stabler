"""Tests for inventory API helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from stabler.api.inventory import _format_warehouse_stock_row, _get_stock_anomalies


class WarehouseStockRowTest(unittest.TestCase):
	def test_formats_quantities_and_stock_value_for_drilldown(self):
		row = _format_warehouse_stock_row(
			{
				"item_code": "ITEM-001",
				"item_name": "Cotton Thread",
				"item_group": "Raw Material",
				"stock_uom": "Kg",
				"actual_qty": "12.5",
				"reserved_qty": "2.5",
				"ordered_qty": "4",
				"projected_qty": "14",
				"valuation_rate": "8000",
			}
		)

		self.assertEqual(row["item_code"], "ITEM-001")
		self.assertEqual(row["free_qty"], 10)
		self.assertEqual(row["stock_value"], 100000)

	@patch("frappe.get_cached_doc")
	def test_detects_zero_rate_anomaly(self, mock_get_cached_doc):
		company_mock = MagicMock()
		company_mock.default_currency = "USD"
		mock_get_cached_doc.return_value = company_mock

		items = [
			{
				"item_code": "ITEM-001",
				"item_name": "etiketka hello",
				"item_group": "Packaging",
				"stock_uom": "Dona",
				"actual_qty": 100.0,
				"valuation_rate": 0.0,
				"stock_value": 0.0,
			}
		]
		anomalies = _get_stock_anomalies(items, "MockCompany")
		self.assertEqual(len(anomalies), 1)
		self.assertEqual(anomalies[0]["type"], "zero_rate")
		self.assertIn("Valuation rate is missing", anomalies[0]["message"])

	@patch("frappe.get_cached_doc")
	def test_detects_high_rate_anomaly_by_keyword(self, mock_get_cached_doc):
		company_mock = MagicMock()
		company_mock.default_currency = "USD"
		mock_get_cached_doc.return_value = company_mock

		items = [
			{
				"item_code": "ITEM-002",
				"item_name": "chopak #1",
				"item_group": "Packaging",
				"stock_uom": "Dona",
				"actual_qty": 680000.0,
				"valuation_rate": 23.03,
				"stock_value": 15660224.93,
			}
		]
		anomalies = _get_stock_anomalies(items, "MockCompany")
		self.assertEqual(len(anomalies), 1)  # Returns high_rate anomaly and continues
		self.assertEqual(anomalies[0]["type"], "high_rate")
		self.assertIn("Suspiciously high rate for low-cost item", anomalies[0]["message"])

	@patch("frappe.get_cached_doc")
	def test_detects_high_rate_anomaly_by_median_deviation(self, mock_get_cached_doc):
		company_mock = MagicMock()
		company_mock.default_currency = "USD"
		mock_get_cached_doc.return_value = company_mock

		# Group median is calculated from active rates. Items: rate 0.5, 0.6, 0.7 (median 0.6)
		# ITEM-005 has rate 10.0 (> 10 * 0.6)
		items = [
			{
				"item_code": "I1",
				"item_name": "Normal Item 1",
				"item_group": "Group A",
				"actual_qty": 10,
				"valuation_rate": 0.5,
				"stock_value": 5.0,
			},
			{
				"item_code": "I2",
				"item_name": "Normal Item 2",
				"item_group": "Group A",
				"actual_qty": 10,
				"valuation_rate": 0.6,
				"stock_value": 6.0,
			},
			{
				"item_code": "I3",
				"item_name": "Normal Item 3",
				"item_group": "Group A",
				"actual_qty": 10,
				"valuation_rate": 0.7,
				"stock_value": 7.0,
			},
			{
				"item_code": "ITEM-005",
				"item_name": "Outlier Item",
				"item_group": "Group A",
				"actual_qty": 10,
				"valuation_rate": 10.0,
				"stock_value": 100.0,
			},
		]
		anomalies = _get_stock_anomalies(items, "MockCompany")
		# Only outlier item should trigger median-deviation anomaly
		outlier_anomalies = [a for a in anomalies if a["item_code"] == "ITEM-005"]
		self.assertEqual(len(outlier_anomalies), 1)
		self.assertEqual(outlier_anomalies[0]["type"], "high_rate")
		self.assertIn("Abnormally high rate", outlier_anomalies[0]["message"])


if __name__ == "__main__":
	unittest.main()
