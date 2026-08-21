"""convert_ci_to_purchase_invoice's warehouse guard, proved live (bench-only).

`test_ci_conversion_moves_stock.py` proves the guard's THREE checks exist in
source: unknown warehouse, warehouse group, warehouse from another company.
Source-regex can only prove the tokens are present, not that the function
actually refuses anything -- and needing a real second Company (WP-I5's own
comment: "the converter is company-scoped end to end... a warehouse from
another company would be the one hole left in it") is exactly why nothing
behavioral existed for any of the three: msa.erpstable.com, where this
shipped, carries exactly one Company (measured 2026-08-20), so no site it was
ever exercised on could supply a warehouse that fails the company comparison.
The branch has shipped unexercised since it was written.

It matters because `warehouse` is what turns `update_stock` on: passing one
makes this Purchase Invoice receive real goods into that warehouse's stock
ledger and value them on the invoicing company's books, on the same document
that opens the payable. A warehouse from another company would move stock and
money across a legal-entity boundary in one call, and nothing downstream
re-checks it -- ERPNext's own shared `_validate_invoice_inputs`
(purchasing.py) only checks that `set_warehouse` exists, never whose company
it belongs to. This file is the only place that comparison is made, so it is
the only place a regression in it could be caught.

genesis-test.local carries exactly one Company at the time this was written
(also measured, not assumed -- see setUp), so proving the guard needs a real
second Company and a real non-group Warehouse under it, built here and torn
down after.

    cd ~/frappe-bench-local && bench --site <test-site> run-tests \\
        --module stabler.tests.test_ci_conversion_moves_stock_integration
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api.imports import convert_ci_to_purchase_invoice


class TheConverterRefusesAWarehouseFromAnotherCompany(FrappeTestCase):
	def setUp(self):
		self.company_a = frappe.db.get_value("Company", {}, "name")
		self.supplier = frappe.db.get_value("Supplier", {}, "name")
		if not (self.company_a and self.supplier):
			self.skipTest("no Company / Supplier fixture available")
		if not frappe.db.exists("DocType", "Stabler Settings"):
			self.skipTest("Stabler Settings doctype not present")

		# convert_ci_to_purchase_invoice calls _assert_imports_access(company)
		# before it ever looks at the warehouse; without this the call throws
		# on module access and never reaches guard 3 at all.
		settings = frappe.get_single("Stabler Settings")
		row = next((r for r in settings.company_modules or [] if r.company == self.company_a), None)
		row = row or settings.append("company_modules", {"company": self.company_a})
		row.enable_imports = 1
		settings.save(ignore_permissions=True)

		source = frappe.get_doc("Company", self.company_a)
		suffix = frappe.generate_hash(length=6)
		self.company_b = frappe.new_doc("Company")
		self.company_b.update(
			{
				"company_name": f"Warehouse Guard Test {suffix}",
				"abbr": suffix[:5].upper(),
				"default_currency": source.default_currency,
				"country": source.country,
				"create_chart_of_accounts_based_on": "Standard Template",
			}
		)
		self.company_b.insert(ignore_permissions=True)

		# Company.insert() builds the default warehouse tree itself (Stores,
		# Work In Progress, Finished Goods, ...) -- a real one of those is
		# enough to prove the guard is about *company*, not a fixture shape
		# invented for this test.
		self.warehouse_b = frappe.db.get_value(
			"Warehouse", {"company": self.company_b.name, "is_group": 0}, "name"
		)
		if not self.warehouse_b:
			self.skipTest("Company creation did not produce a non-group warehouse")

		self.ci = frappe.new_doc("Commercial Invoice")
		self.ci.update(
			{
				"company": self.company_a,
				"supplier": self.supplier,
				"ci_number": frappe.generate_hash(length=10),
				"ci_date": frappe.utils.today(),
			}
		)
		self.ci.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		# Company.insert() commits its chart-of-accounts setup as it goes, so
		# the rollback above cannot undo it -- explicit delete or a
		# "Warehouse Guard Test *" company accumulates on the site every run.
		name = getattr(getattr(self, "company_b", None), "name", None)
		if not name:
			return
		frappe.db.delete("Stabler Company Modules", {"parent": "Stabler Settings", "company": name})
		if frappe.db.exists("Company", name):
			frappe.delete_doc("Company", name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_a_warehouse_from_another_company_is_refused_naming_both_companies(self):
		# dry_run defaults to 1 (preview, never writes) and the warehouse block
		# runs unconditionally ahead of the `if cint(dry_run):` return, so the
		# guard is reachable -- and this call stays a pure read -- without
		# building a full reconciled invoice.
		with self.assertRaises(frappe.ValidationError) as ctx:
			convert_ci_to_purchase_invoice(
				commercial_invoice=self.ci.name,
				company=self.company_a,
				dry_run=1,
				warehouse=self.warehouse_b,
			)
		message = str(ctx.exception)
		self.assertIn(
			self.company_b.name,
			message,
			"the refusal did not name the warehouse's own company",
		)
		self.assertIn(
			self.company_a,
			message,
			"the refusal did not name the company being invoiced",
		)


if __name__ == "__main__":
	import unittest

	unittest.main()
