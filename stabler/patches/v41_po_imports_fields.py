"""Link Purchase Orders (and PO line items) to an Import PI Group.

Adds `custom_import_pi_group` on Purchase Order and Purchase Order Item so a
PO — or an individual PO line — can be grouped under one commercial-invoice
consolidation used by the imports/customs declaration pipeline (MSAERP
migration). Mirrors v34's custom_crm_deal pattern.

Idempotent: guarded by a Custom Field existence check. Skips entirely (and is
safe to re-run later) if the "Import PI Group" doctype does not exist yet —
listed under [post_model_sync] so it can run once that doctype has synced.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Import PI Group"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Purchase Order", "fieldname": "custom_import_pi_group"}):
		return
	create_custom_fields(
		{
			"Purchase Order": [
				{
					"fieldname": "custom_import_pi_group",
					"label": "Import PI Group",
					"fieldtype": "Link",
					"options": "Import PI Group",
					"insert_after": "custom_crm_deal",
				}
			],
			"Purchase Order Item": [
				{
					"fieldname": "custom_import_pi_group",
					"label": "Import PI Group",
					"fieldtype": "Link",
					"options": "Import PI Group",
					"insert_after": "warehouse",
				}
			],
		},
		ignore_validate=True,
	)
