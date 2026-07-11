"""Integration tests for the Stabler Customer Hierarchy (K2) and Auto-GRN status hook.

Wired against a live test database under `bench run-tests --app stabler`.
"""

from __future__ import annotations

import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from stabler.api.sales import (
	create_parent_bulk_payment,
	reallocate_parent_payment,
)
from stabler.api.imports import create_grn_for_ci


def _first_company():
	return frappe.db.get_value("Company", {}, "name")


def _first_supplier():
	return frappe.db.get_value("Supplier", {}, "name")


def _first_item():
	return frappe.db.get_value("Item", {"is_sales_item": 1}, "name")


class CustomerHierarchyIntegrationTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _first_company()
		cls.supplier = _first_supplier()
		cls.item = _first_item()

	def setUp(self):
		if not (self.company and self.supplier and self.item):
			self.skipTest("no Company / Supplier / Item fixtures available")

		# Ensure parent credit check toggle is enabled in Stabler Settings
		settings = frappe.get_single("Stabler Settings")
		settings.enable_parent_credit_check = 1
		# Enable imports for test company
		row = None
		for r in settings.company_modules or []:
			if r.company == self.company:
				row = r
				break
		if row is None:
			row = settings.append("company_modules", {"company": self.company})
		row.enable_imports = 1
		settings.save(ignore_permissions=True)

		# Bypass mandatory Sales Order / Delivery Note requirements on Selling Settings
		self.selling_settings = frappe.get_single("Selling Settings")
		self.old_so_required = self.selling_settings.so_required
		self.old_dn_required = self.selling_settings.dn_required
		self.selling_settings.so_required = 0
		self.selling_settings.dn_required = 0
		self.selling_settings.save(ignore_permissions=True)

		self.parent_cust = self._create_customer("Parent_Cust_" + frappe.generate_hash(length=6))
		self.child_cust = self._create_customer(
			"Child_Cust_" + frappe.generate_hash(length=6),
			parent=self.parent_cust.name
		)

	def tearDown(self):
		if hasattr(self, "selling_settings") and hasattr(self, "old_so_required"):
			self.selling_settings.so_required = self.old_so_required
			self.selling_settings.dn_required = self.old_dn_required
			self.selling_settings.save(ignore_permissions=True)
		frappe.db.rollback()

	def _create_customer(self, name: str, parent: str | None = None) -> frappe.Document:
		doc = frappe.new_doc("Customer")
		doc.customer_name = name
		doc.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "Individual"
		doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
		if parent:
			doc.custom_parent_customer = parent
		doc.insert(ignore_permissions=True)
		return doc

	def test_customer_hierarchy_validations(self):
		# 1. Self parenting is blocked
		self.child_cust.custom_parent_customer = self.child_cust.name
		with self.assertRaises(frappe.ValidationError):
			self.child_cust.save(ignore_permissions=True)

		# Reset parent
		self.child_cust.reload()

		# 2. Grandparenting (2 levels) is blocked
		gp = self._create_customer("GP_" + frappe.generate_hash(length=6))
		# Try to make GP the parent of our parent (Parent_Cust)
		self.parent_cust.custom_parent_customer = gp.name
		with self.assertRaises(frappe.ValidationError):
			self.parent_cust.save(ignore_permissions=True)

		# 3. Parent cannot become child of its child
		self.parent_cust.reload()
		self.parent_cust.custom_parent_customer = self.child_cust.name
		with self.assertRaises(frappe.ValidationError):
			self.parent_cust.save(ignore_permissions=True)

	def test_credit_limit_validation(self):
		# Set group credit limit on the parent customer
		parent_doc = frappe.get_doc("Customer", self.parent_cust.name)
		parent_doc.append("credit_limits", {
			"company": self.company,
			"credit_limit": 5000.0
		})
		parent_doc.save(ignore_permissions=True)

		# Create a Sales Invoice for child customer within the limit
		si1 = frappe.new_doc("Sales Invoice")
		si1.company = self.company
		si1.customer = self.child_cust.name
		company_doc = frappe.get_doc("Company", self.company)
		company_currency = company_doc.default_currency or "UZS"
		si1.debit_to = company_doc.default_receivable_account or frappe.db.get_value(
			"Account", {"account_type": "Receivable", "company": self.company}
		)
		si1.currency = frappe.db.get_value("Account", si1.debit_to, "account_currency") or company_currency
		si1.update_stock = 0
		si1.append("items", {
			"item_code": self.item,
			"qty": 1,
			"rate": 3000.0,
			"income_account": company_doc.default_income_account or frappe.db.get_value(
				"Account", {"account_type": "Income Account", "company": self.company}
			),
			"warehouse": frappe.db.get_value("Warehouse", {"company": self.company})
		})
		si1.insert(ignore_permissions=True)
		si1.submit() # Should succeed (3000 <= 5000)

		# Create a second Sales Invoice that would push the total past the limit (3000 + 3000 = 6000 > 5000)
		si2 = frappe.new_doc("Sales Invoice")
		si2.company = self.company
		si2.customer = self.child_cust.name
		si2.debit_to = si1.debit_to
		si2.currency = si1.currency
		si2.update_stock = 0
		si2.append("items", {
			"item_code": self.item,
			"qty": 1,
			"rate": 3000.0,
			"income_account": si1.items[0].income_account,
			"warehouse": si1.items[0].warehouse
		})
		si2.insert(ignore_permissions=True)

		# Temporarily switch user to a standard user to trigger the credit validation block
		original_user = frappe.session.user
		frappe.set_user("Guest") # Or any non-Accounts/System Manager user
		try:
			with self.assertRaises(frappe.ValidationError):
				si2.submit()
		finally:
			# Restore user
			frappe.set_user(original_user)

		# Administrator has System Manager role, so submitting as Administrator should bypass the limit
		si2.reload()
		si2.submit() # Should succeed due to bypass role

	def test_auto_grn_checklist_on_ci_stuffed_status(self):
		# Create a Commercial Invoice in BOOKED status
		ci = frappe.new_doc("Commercial Invoice")
		ci.company = self.company
		ci.supplier = self.supplier
		ci.ci_number = frappe.generate_hash(length=8)
		ci.ci_date = today()
		ci.status = "BOOKED"
		ci.append("items", {
			"item": self.item,
			"qty": 100,
			"rate": 10.0
		})
		ci.insert(ignore_permissions=True)

		# Verify no GRN checklist exists yet
		self.assertFalse(frappe.db.exists("GRN Checklist", {"commercial_invoice": ci.name}))

		# Transition status to STUFFED
		ci.status = "STUFFED"
		ci.save(ignore_permissions=True)

		# Verify GRN checklist was automatically created via hook
		grn_name = frappe.db.get_value("GRN Checklist", {"commercial_invoice": ci.name})
		self.assertTrue(grn_name)

		grn = frappe.get_doc("GRN Checklist", grn_name)
		self.assertEqual(grn.company, self.company)
		self.assertEqual(grn.supplier, self.supplier)
		self.assertEqual(len(grn.grn_items), 1)
		self.assertEqual(grn.grn_items[0].item_code, self.item)
		self.assertEqual(flt(grn.grn_items[0].expected_total_kg), 100.0)
