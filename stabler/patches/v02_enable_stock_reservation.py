"""Enable ERPNext Stock Reservation Engine + add per-Company toggle.

- Flip `Stock Settings.enable_stock_reservation` to 1 if it's currently off.
  We intentionally leave `auto_reserve_serial_and_batch` alone; SRE for
  serial/batch is a separate UX decision and the default behaves fine for
  non-serialised items.
- Backfill the per-Company `enable_stock_reservation` column on Stabler
  Company Modules child rows so the boot() payload always carries a value.

Idempotent: skips work that's already been done.
"""

import frappe


def execute():
	if frappe.db.exists("DocType", "Stock Settings"):
		current = frappe.db.get_single_value("Stock Settings", "enable_stock_reservation")
		if not current:
			frappe.db.set_single_value("Stock Settings", "enable_stock_reservation", 1)

	# Backfill the per-Company toggle column. The schema lives in the doctype
	# JSON (declared with default=1), but rows created before this patch
	# landed have NULL — normalise to 1 so module_map_for() reports True.
	if frappe.db.has_column("Stabler Company Modules", "enable_stock_reservation"):
		frappe.db.sql(
			"""
			UPDATE `tabStabler Company Modules`
			SET enable_stock_reservation = 1
			WHERE enable_stock_reservation IS NULL
			"""
		)

	frappe.db.commit()
