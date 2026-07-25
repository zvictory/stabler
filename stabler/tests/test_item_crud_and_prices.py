"""Unit tests for Item update/disabled CRUD and Price List APIs."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock

mock_frappe = MagicMock()
mock_frappe._ = lambda s: s
def _passthrough_whitelist(*args, **kwargs):
	if len(args) == 1 and callable(args[0]):
		return args[0]
	return lambda fn: fn
mock_frappe.whitelist = _passthrough_whitelist
sys.modules['frappe'] = mock_frappe
mock_utils = MagicMock()
mock_utils.flt = lambda v, p=None: float(v or 0)
mock_utils.cint = lambda v, p=None: int(v or 0)
sys.modules['frappe.utils'] = mock_utils
mock_common = MagicMock()
sys.modules['stabler.api._common'] = mock_common
mock_appr = MagicMock()
sys.modules['stabler.api.approvals'] = mock_appr
mock_recon = MagicMock()
sys.modules['stabler.api._stock_recon'] = mock_recon

mock_erpnext = MagicMock()
sys.modules['erpnext'] = mock_erpnext
sys.modules['erpnext.stock'] = mock_erpnext
sys.modules['erpnext.stock.get_item_details'] = mock_erpnext

from stabler.api import inventory


class TestItemCrudAndPrices(unittest.TestCase):
	def test_update_item_modifies_doc_and_saves(self):
		mock_frappe.db.exists.return_value = True
		item_doc = MagicMock()
		item_doc.name = "TEST-ITEM-1"
		item_doc.item_code = "TEST-ITEM-1"
		item_doc.item_name = "Old Name"
		item_doc.disabled = 0
		mock_frappe.get_doc.return_value = item_doc

		res = inventory.update_item(
			name="TEST-ITEM-1",
			item_name="New Updated Name",
			standard_rate=150.0,
			disabled=1,
		)

		self.assertEqual(item_doc.item_name, "New Updated Name")
		self.assertEqual(item_doc.standard_rate, 150.0)
		self.assertEqual(item_doc.disabled, 1)
		item_doc.save.assert_called_once()
		self.assertEqual(res["name"], "TEST-ITEM-1")
		self.assertEqual(res["disabled"], 1)

	def test_list_price_lists(self):
		mock_frappe.db.sql.return_value = [
			{"name": "Standard Selling", "currency": "USD", "buying": 0, "selling": 1},
			{"name": "Standard Buying", "currency": "USD", "buying": 1, "selling": 0},
		]

		pls = inventory.list_price_lists(selling=1)
		self.assertEqual(len(pls), 2)
		self.assertEqual(pls[0]["name"], "Standard Selling")

	def test_create_price_list(self):
		mock_frappe.db.exists.return_value = False
		pl_doc = MagicMock()
		pl_doc.name = "VIP Wholesale"
		pl_doc.price_list_name = "VIP Wholesale"
		pl_doc.currency = "USD"
		mock_frappe.new_doc.return_value = pl_doc

		res = inventory.create_price_list("VIP Wholesale", currency="USD", selling=1)
		pl_doc.insert.assert_called_once()
		self.assertEqual(res["name"], "VIP Wholesale")

	def test_save_item_price_new(self):
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.get_value.return_value = None

		pl_doc = MagicMock()
		pl_doc.currency = "USD"
		mock_frappe.get_doc.return_value = pl_doc

		ip_doc = MagicMock()
		ip_doc.name = "IP-001"
		ip_doc.item_code = "ITEM-1"
		ip_doc.price_list = "Standard Selling"
		ip_doc.price_list_rate = 120.0
		ip_doc.currency = "USD"
		mock_frappe.new_doc.return_value = ip_doc

		res = inventory.save_item_price("ITEM-1", "Standard Selling", 120.0)
		ip_doc.save.assert_called_once()
		self.assertEqual(res["price_list_rate"], 120.0)

	def test_delete_item_price(self):
		mock_frappe.db.exists.return_value = True
		mock_frappe.delete_doc.reset_mock()
		res = inventory.delete_item_price("IP-001")
		mock_frappe.delete_doc.assert_called_once_with("Item Price", "IP-001", ignore_permissions=False)
		self.assertEqual(res["status"], "ok")


if __name__ == "__main__":
	unittest.main()
