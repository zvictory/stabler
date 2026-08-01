"""Seed enable_sales_box_uom to 0 for every tenant — close, don't guess open.

The flag decides whether a new sales order line auto-selects the largest
box/case unit of measure (conversion_factor > 1) instead of the stock unit.
Unlike v63 (enable_dimensional_lines), there is no equivalent fact in the
catalogue that says "this tenant sells by the box" — Item carries a
dimension mode, but it carries nothing about packaging preference. Inventing
one here would be a guess dressed up as a migration, so every tenant is
closed to 0 and the owner-tenant (anjan) is opened by hand from Companies
after deploy.

Idempotent: re-running only ever sets rows to 0, so it is always safe to
run again.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_sales_box_uom"):
		return  # Column not created yet — DocType DDL sync hasn't run.

	# NULL must never read as permissive: close everyone.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_sales_box_uom = 0 "
		"WHERE enable_sales_box_uom IS NULL OR enable_sales_box_uom != 0"
	)

	frappe.db.commit()
