"""Link an asset-purchase Journal Entry line to a specific ERPNext Asset.

Asset-purchase expenses (Money → Expenses, "Asset purchase" mode) debit a
Fixed-Asset GL account. This custom field on the Journal Entry Account child
lets each debit line also point at the concrete Asset record (the ones the
company maintains manually), so purchases are traceable to — and totalled
against — a specific asset.

Only created when the ERPNext Asset doctype is installed (some benches don't
carry the assets app). Idempotent: create_custom_fields update=True.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> None:
	if not frappe.db.exists("DocType", "Asset"):
		return
	create_custom_fields(
		{
			"Journal Entry Account": [
				{
					"fieldname": "custom_asset",
					"label": "Asset",
					"fieldtype": "Link",
					"options": "Asset",
					"insert_after": "reference_name",
					"allow_on_submit": 1,
					"description": "Asset this purchase line is capitalised against",
				}
			],
		},
		update=True,
	)
