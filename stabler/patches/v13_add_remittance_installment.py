"""Patch v13: Add enable_remittance + enable_installment module toggles.

Also:
- Backfills both columns to 1 for existing Stabler Company Modules rows.
- Creates a custom Check field `stabler_installment_plan` on Sales Invoice
  and Purchase Invoice so list_contracts/calendar_events can filter on it.
- Ensures a USDT Currency record exists (non-ISO, used by remittance module).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# 1. Backfill enable_remittance on existing rows
	if frappe.db.has_column("Stabler Company Modules", "enable_remittance"):
		frappe.db.sql(
			"""UPDATE `tabStabler Company Modules`
               SET enable_remittance = 1
               WHERE enable_remittance IS NULL"""
		)

	# 2. Backfill enable_installment on existing rows
	if frappe.db.has_column("Stabler Company Modules", "enable_installment"):
		frappe.db.sql(
			"""UPDATE `tabStabler Company Modules`
               SET enable_installment = 1
               WHERE enable_installment IS NULL"""
		)

	# 3. Custom field: stabler_installment_plan on Sales Invoice
	for dt in ("Sales Invoice", "Purchase Invoice"):
		if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": "stabler_installment_plan"}):
			create_custom_fields(
				{
					dt: [
						{
							"fieldname": "stabler_installment_plan",
							"label": "Stabler Installment Plan",
							"fieldtype": "Check",
							"default": "0",
							"insert_after": "remarks",
							"hidden": 1,
							"no_copy": 1,
						}
					]
				},
				ignore_validate=True,
			)

	# 4. Ensure USDT Currency record exists
	if not frappe.db.exists("Currency", "USDT"):
		frappe.get_doc(
			{
				"doctype": "Currency",
				"currency_name": "USDT",
				"enabled": 1,
				"fraction": "Cent",
				"fraction_units": 100,
				"smallest_currency_fraction_value": 0.01,
				"symbol": "₮",
				"number_format": "#,###.##",
			}
		).insert(ignore_permissions=True)

	frappe.db.commit()
