"""Integration tests for the unified Landed Cost Voucher (LCV) engine."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from stabler.api.lcv import create_additional_lcv, get_landed_cost_review, toggle_cost_line_include


def _first_company():
	return frappe.db.get_value("Company", {}, "name")


def _first_supplier():
	return frappe.db.get_value("Supplier", {}, "name")


def _first_item():
	return frappe.db.get_value("Item", {"is_sales_item": 1}, "name")


class TestLcvUnification(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _first_company()
		cls.supplier = _first_supplier()
		cls.item = _first_item()

	def setUp(self):
		if not (self.company and self.supplier and self.item):
			self.skipTest("no Company / Supplier / Item fixtures available")

		# Ensure custom settings exist/enable
		settings = frappe.get_single("Stabler Settings")
		settings.enable_landed_cost = 1
		settings.save(ignore_permissions=True)

		warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")

		# 1. Create Purchase Order with custom_landed_charges JSON
		po = frappe.new_doc("Purchase Order")
		po.company = self.company
		po.supplier = self.supplier
		po.transaction_date = today()
		po.schedule_date = today()
		po.append(
			"items",
			{
				"item_code": self.item,
				"qty": 10,
				"rate": 100,
				"warehouse": warehouse,
			},
		)
		po.custom_landed_charges = json.dumps(
			[
				{"type": "transport", "label": "PO Freight Charge", "amount": 150.0},
				{"type": "insurance", "label": "PO Insurance Charge", "amount": 50.0},
			]
		)
		po.insert(ignore_permissions=True)
		po.submit()
		self.po = po

		# 2. Create Purchase Receipt linked to PO
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = self.company
		pr.supplier = self.supplier
		pr.posting_date = today()
		pr.append(
			"items",
			{
				"item_code": self.item,
				"qty": 10,
				"rate": 100,
				"purchase_order": self.po.name,
				"purchase_order_item": self.po.items[0].name,
				"warehouse": warehouse,
			},
		)
		pr.insert(ignore_permissions=True)
		pr.submit()
		self.pr = pr

	def tearDown(self):
		frappe.db.rollback()

	def test_get_landed_cost_review_purchase_receipt(self):
		# Verify review aggregates charges correctly
		res = get_landed_cost_review("Purchase Receipt", self.pr.name)
		self.assertEqual(res["grn"]["name"], self.pr.name)

		preview = res["preview"]
		self.assertEqual(flt(preview["total"]), 200.0)

		components = {c["component"]: flt(c["amount"]) for c in preview["components"]}
		self.assertEqual(components["PO Freight Charge"], 150.0)
		self.assertEqual(components["PO Insurance Charge"], 50.0)

	def test_toggle_landed_cost_include(self):
		# Toggle the Insurance Charge off (include = 0)
		toggle_cost_line_include("Purchase Receipt", self.pr.name, "po_charges", "PO Insurance Charge", 0)

		res = get_landed_cost_review("Purchase Receipt", self.pr.name)
		preview = res["preview"]
		self.assertEqual(flt(preview["total"]), 150.0)

		components = {c["component"]: flt(c["amount"]) for c in preview["components"]}
		self.assertNotIn("PO Insurance Charge", components)
		self.assertIn("PO Freight Charge", components)

	def test_create_additional_lcv_purchase_receipt(self):
		# Configure the expense account first
		settings = frappe.get_single("Stabler Settings")
		expense_account = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 0, "root_type": "Expense"}, "name"
		)
		if not expense_account:
			expense_account = frappe.db.get_value("Account", {"company": self.company, "is_group": 0}, "name")

		settings.landed_cost_expense_account = expense_account
		settings.save(ignore_permissions=True)

		lcv_res = create_additional_lcv("Purchase Receipt", self.pr.name)
		self.assertEqual(lcv_res["status"], "ok")
		lcv_name = lcv_res["lcv"]
		self.assertTrue(frappe.db.exists("Landed Cost Voucher", lcv_name))

		lcv = frappe.get_doc("Landed Cost Voucher", lcv_name)
		self.assertEqual(len(lcv.taxes), 2)
		descriptions = [t.description for t in lcv.taxes]
		self.assertIn("PO Freight Charge", descriptions)
		self.assertIn("PO Insurance Charge", descriptions)
