"""Seed enable_sales_box_uom to 0 for every tenant — close, don't guess open.

The flag decides whether a new sales order line auto-selects the largest
box/case unit of measure (conversion_factor > 1) instead of the stock unit.
Unlike v63 (enable_dimensional_lines), there is no equivalent fact in the
catalogue that says "this tenant sells by the box" — Item carries a
dimension mode, but it carries nothing about packaging preference. Inventing
one here would be a guess dressed up as a migration, so every tenant is
closed to 0 and the owner-tenant (anjan) is opened by hand from Companies
after deploy.

Idempotent, and the reason is the WHERE clause, not the value: only a row with
no answer yet (NULL) is written. "Re-running only ever sets rows to 0, so it is
always safe" was the old claim and it was backwards — setting a row to 0 is the
damage, and the only row the old `OR <flag> != 0` clause could match was one a
human had deliberately set to 1.
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_sales_box_uom"):
		return  # Column not created yet — DocType DDL sync hasn't run.

	# NULL must never read as permissive: close the rows that hold no answer.
	# Only those: `OR enable_sales_box_uom != 0` used to be here, and the only row it could
	# ever match was one a human had set to 1 — which the docstring above says
	# is exactly how the owner tenant gets this feature.
	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_sales_box_uom = 0 WHERE enable_sales_box_uom IS NULL"
	)

	frappe.db.commit()
