"""A warehouse belongs to the tree of the company it is created for.

`create_warehouse` checked that `parent_warehouse` EXISTS. It did not check
whose it was, and ERPNext does not check either — `Warehouse.validate()` only
warns about multiple warehouse accounts, and the nested-set update happily
files the new node wherever the parent is.

Measured on genesis-test 2026-08-27: a warehouse created for `_Test Company`
under a second company's `All Warehouses` group was accepted, stored with
`company = _Test Company`, and given lft/rgt inside the OTHER company's tree.

That is not cosmetic. Warehouse trees are read by lft/rgt: the owning company's
rollups walk down from its own root and never reach the node, while the other
company's do. Stock exists in a warehouse that its own company's group totals
cannot see.

The SPA's parent picker is fed by `list_parent_warehouses`, which is company
scoped, so this is an API-level hole rather than something an operator can click
into. It is guarded here for the same reason every other company argument in
this module is: the endpoint is whitelisted, and the check belongs where the
write happens.
"""

from __future__ import annotations

import unittest

import frappe

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from stabler.api.inventory import create_warehouse

OTHER_COMPANY = "Warehouse Scope Probe Co"


class TestAWarehouseStaysInItsOwnCompanysTree(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# A second company on the same site: what `_assert_company_scope` exists
		# to separate, and the only way to demonstrate the defect at all.
		if not frappe.db.exists("Company", OTHER_COMPANY):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": OTHER_COMPANY,
					"abbr": "WSPC",
					"default_currency": "UZS",
					"country": "Uzbekistan",
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		if frappe.db.exists("Company", OTHER_COMPANY):
			frappe.delete_doc("Company", OTHER_COMPANY, force=True, ignore_permissions=True)
			frappe.db.commit()

	def setUp(self):
		super().setUp()
		self.company = frappe.db.get_value("Company", {"name": ["!=", OTHER_COMPANY]}, "name")
		self.assertTrue(self.company, "the site needs a second company for this to mean anything")

	def _create(self, **kw):
		out = create_warehouse(company=self.company, **kw)
		self.addCleanup(frappe.delete_doc, "Warehouse", out["name"], force=True, ignore_permissions=True)
		return out

	def test_a_parent_from_another_company_is_refused(self):
		foreign = frappe.db.get_value("Warehouse", {"company": OTHER_COMPANY, "is_group": 1}, "name")
		self.assertTrue(foreign, "the probe company has no group warehouse")

		with self.assertRaises(frappe.ValidationError):
			self._create(warehouse_name="Scope Probe Child", parent_warehouse=foreign)

	def test_a_parent_in_the_same_company_is_still_accepted(self):
		"""The guard must not cost the ordinary case — this is the path the SPA
		actually uses, since its picker only offers parents of the active
		company."""
		own = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 1}, "name")
		self.assertTrue(own, "no group warehouse to nest under")

		out = self._create(warehouse_name="Scope Probe Sibling", parent_warehouse=own)

		parent = frappe.get_doc("Warehouse", own)
		child = frappe.get_doc("Warehouse", out["name"])
		self.assertEqual(child.parent_warehouse, own)
		self.assertTrue(
			parent.lft < child.lft and child.rgt < parent.rgt,
			"the child must sit inside its parent's tree, which is how rollups find it",
		)

	def test_a_warehouse_with_no_parent_is_unaffected(self):
		out = self._create(warehouse_name="Scope Probe Rootless")
		self.assertEqual(frappe.db.get_value("Warehouse", out["name"], "company"), self.company)
