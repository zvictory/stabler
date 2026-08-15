"""Unit tests for CI Transport Purchase Invoice linking, unlinking, listing and Landed Cost routing.

Run:
    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_transport_pi_link -v
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from stabler.api import imports


class TestCiTransportPiLink(unittest.TestCase):
	def setUp(self):
		import frappe

		frappe.local.db = MagicMock()
		frappe.local.flags = frappe._dict()
		frappe.local.site = "test"

	def test_get_ci_transport_invoices_calculation(self):
		ci_doc = MagicMock()
		ci_doc.name = "CI-TEST-001"
		ci_doc.company = "MSA"
		ci_doc.total_kg = 50000.0
		ci_doc.currency = "USD"

		mock_invoices = [
			{
				"name": "PINV-001",
				"supplier": "SUPP-CARRIER-1",
				"supplier_name": "Trans Logistic",
				"posting_date": "2026-08-15",
				"bill_no": "BILL-101",
				"grand_total": 3000.0,
				"outstanding_amount": 3000.0,
				"currency": "USD",
				"status": "Unpaid",
				"docstatus": 1,
				"custom_import_truck": "TRK-001",
				"expense_account": "Expenses Included In Valuation - MSA",
				"item_code": "Cross-Border Transport",
			},
			{
				"name": "PINV-002",
				"supplier": "SUPP-CARRIER-2",
				"supplier_name": "Fast Freight",
				"posting_date": "2026-08-15",
				"bill_no": "BILL-102",
				"grand_total": 2000.0,
				"outstanding_amount": 0.0,
				"currency": "USD",
				"status": "Paid",
				"docstatus": 1,
				"custom_import_truck": "TRK-002",
				"expense_account": "Expenses Included In Valuation - MSA",
				"item_code": "Cross-Border Transport",
			},
		]

		with (
			patch("frappe.db.sql", return_value=mock_invoices),
			patch("frappe.get_cached_value", return_value="UZS"),
			patch("frappe.db.get_value", return_value="Expenses Included In Valuation"),
			patch("stabler.api.imports._ci_landed_cost_rate", return_value=(12800.0, "cbu", "2026-08-15")),
			patch(
				"stabler.stabler.imports_module.hooks.resolve_lcv_expense_account",
				return_value="Expenses Included In Valuation - MSA",
			),
		):
			res = imports._get_ci_transport_invoices(ci_doc)

		self.assertEqual(res["invoice_count"], 2)
		self.assertEqual(res["total_usd"], 5000.0)
		self.assertEqual(res["total_company_currency"], 5000.0 * 12800.0)
		# 5000 USD / 50000 kg = 0.10 USD/kg
		self.assertEqual(res["rate_per_kg_usd"], 0.10)
		self.assertEqual(res["rate_per_kg_company"], round(5000.0 * 12800.0 / 50000.0, 2))
		self.assertTrue(res["invoices"][0]["is_landed_cost_account"])
		self.assertTrue(res["invoices"][1]["is_landed_cost_account"])

	def test_link_transport_purchase_invoice_company_guard(self):
		ci_doc = MagicMock(company="MSA")
		pi_doc = MagicMock(company="OTHER_COMPANY", docstatus=0)

		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_doc", side_effect=[ci_doc, pi_doc]),
			patch("stabler.api.imports._assert_imports_access"),
			patch("stabler.api.imports._assert_can_write"),
			patch("stabler.api.imports._assert_cost_visible"),
		):
			with self.assertRaises(Exception):
				imports.link_transport_purchase_invoice("CI-TEST", "PINV-TEST")

	def test_link_transport_purchase_invoice_draft_account_update(self):
		ci_doc = MagicMock(company="MSA")
		item_mock = MagicMock(expense_account="Direct Expenses - MSA")
		pi_doc = MagicMock(company="MSA", docstatus=0, items=[item_mock])

		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_doc", side_effect=[ci_doc, pi_doc]),
			patch("stabler.api.imports._assert_imports_access"),
			patch("stabler.api.imports._assert_can_write"),
			patch("stabler.api.imports._assert_cost_visible"),
			patch(
				"stabler.stabler.imports_module.hooks.resolve_lcv_expense_account",
				return_value="Expenses Included In Valuation - MSA",
			),
		):
			res = imports.link_transport_purchase_invoice("CI-TEST", "PINV-TEST")

		self.assertTrue(res["success"])
		self.assertEqual(item_mock.expense_account, "Expenses Included In Valuation - MSA")
		self.assertEqual(pi_doc.custom_commercial_invoice, "CI-TEST")
		pi_doc.save.assert_called_once()

	def test_unlink_transport_purchase_invoice(self):
		ci_doc = MagicMock(company="MSA")

		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_doc", return_value=ci_doc),
			patch("frappe.db.get_value", return_value="CI-TEST"),
			patch("frappe.db.set_value") as mock_set_val,
			patch("stabler.api.imports._assert_imports_access"),
			patch("stabler.api.imports._assert_can_write"),
		):
			res = imports.unlink_transport_purchase_invoice("CI-TEST", "PINV-TEST")

		self.assertTrue(res["success"])
		mock_set_val.assert_called_once_with(
			"Purchase Invoice", "PINV-TEST", "custom_commercial_invoice", None
		)


if __name__ == "__main__":
	unittest.main()
