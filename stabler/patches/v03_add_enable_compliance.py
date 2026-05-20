"""Backfill the per-Company enable_compliance toggle to ON for existing rows.

The column is declared on Stabler Company Modules with default=1, but rows
created before this patch landed have NULL — normalise to 1 so
module_map_for() reports True.

Idempotent: skips work that's already been done.
"""

import frappe


def execute():
	if frappe.db.has_column("Stabler Company Modules", "enable_compliance"):
		frappe.db.sql(
			"""
			UPDATE `tabStabler Company Modules`
			SET enable_compliance = 1
			WHERE enable_compliance IS NULL
			"""
		)
	frappe.db.commit()
