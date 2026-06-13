from __future__ import annotations

import unittest
from unittest.mock import patch
import frappe
from frappe import ValidationError
try:
	from frappe import TimestampMismatchError
except ImportError:
	TimestampMismatchError = ValidationError

from stabler.api._common import check_concurrency
from stabler.api.sales import update_sales_order, delete_sales_order, delete_sales_invoice, submit_quotation
from stabler.api.purchasing import update_purchase_order, update_purchase_invoice, delete_purchase_invoice
from stabler.api.money import update_payment_entry, delete_payment_entry


class TestConcurrency(unittest.TestCase):
	def setUp(self):
		frappe.local.response = {}

	@patch("frappe.db.get_value")
	def test_check_concurrency_stale_token(self, mock_get_value):
		# Setup mock database timestamp
		mock_get_value.return_value = "2026-06-13 12:00:00"

		# A stale token should raise TimestampMismatchError
		with self.assertRaises(TimestampMismatchError):
			check_concurrency("Sales Order", "SO-00001", modified="2026-06-13 11:00:00")

		# Check that local response carries doctype and name
		self.assertEqual(frappe.local.response.get("doctype"), "Sales Order")
		self.assertEqual(frappe.local.response.get("name"), "SO-00001")

	@patch("frappe.db.get_value")
	def test_check_concurrency_missing_token_existing_doc(self, mock_get_value):
		# Setup mock database timestamp (meaning doc exists)
		mock_get_value.return_value = "2026-06-13 12:00:00"

		# A missing token on an existing doc should be rejected (T2 policy)
		with self.assertRaises(ValidationError) as ctx:
			check_concurrency("Sales Order", "SO-00001", modified=None)
		
		self.assertIn("Stale request: reload the document.", str(ctx.exception))

	@patch("frappe.db.get_value")
	def test_check_concurrency_missing_doc(self, mock_get_value):
		# Document does not exist in DB (returns None)
		mock_get_value.return_value = None

		# Missing doc should pass concurrency check silently (e.g. create path)
		check_concurrency("Sales Order", "SO-00001", modified=None)
		check_concurrency("Sales Order", "SO-00001", modified="2026-06-13 12:00:00")

	@patch("frappe.db.get_value")
	@patch("stabler.api.sales._assert_can_read")
	def test_sales_order_endpoints(self, mock_read, mock_get_value):
		mock_get_value.return_value = "2026-06-13 12:00:00"

		# Test update
		with self.assertRaises(TimestampMismatchError):
			update_sales_order("SO-00001", items=[], modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			update_sales_order("SO-00001", items=[], modified=None)

		# Test delete
		with self.assertRaises(TimestampMismatchError):
			delete_sales_order("SO-00001", modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			delete_sales_order("SO-00001", modified=None)

	@patch("frappe.db.get_value")
	@patch("stabler.api.sales._assert_can_read")
	def test_sales_invoice_endpoints(self, mock_read, mock_get_value):
		mock_get_value.return_value = "2026-06-13 12:00:00"

		# Test delete
		with self.assertRaises(TimestampMismatchError):
			delete_sales_invoice("SI-00001", modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			delete_sales_invoice("SI-00001", modified=None)

	@patch("frappe.db.get_value")
	def test_purchase_order_endpoints(self, mock_get_value):
		mock_get_value.return_value = "2026-06-13 12:00:00"

		# Test update
		with self.assertRaises(TimestampMismatchError):
			update_purchase_order("PO-00001", items=[], modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			update_purchase_order("PO-00001", items=[], modified=None)

	@patch("frappe.db.get_value")
	def test_purchase_invoice_endpoints(self, mock_get_value):
		mock_get_value.return_value = "2026-06-13 12:00:00"

		# Test update
		with self.assertRaises(TimestampMismatchError):
			update_purchase_invoice("PI-00001", supplier="Test Supplier", items=[], modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			update_purchase_invoice("PI-00001", supplier="Test Supplier", items=[], modified=None)

		# Test delete
		with self.assertRaises(TimestampMismatchError):
			delete_purchase_invoice("PI-00001", modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			delete_purchase_invoice("PI-00001", modified=None)

	@patch("frappe.db.get_value")
	def test_payment_entry_endpoints(self, mock_get_value):
		mock_get_value.return_value = "2026-06-13 12:00:00"

		# Test update
		with self.assertRaises(TimestampMismatchError):
			update_payment_entry("PE-00001", modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			update_payment_entry("PE-00001", modified=None)

		# Test delete
		with self.assertRaises(TimestampMismatchError):
			delete_payment_entry("PE-00001", modified="2026-06-13 11:00:00")
		with self.assertRaises(ValidationError):
			delete_payment_entry("PE-00001", modified=None)


if __name__ == "__main__":
	unittest.main()
