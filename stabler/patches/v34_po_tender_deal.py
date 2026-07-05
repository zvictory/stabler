"""Link Purchase Orders to a tender (PO control board).

Adds `custom_crm_deal` on Purchase Order so all POs raised to vendors for one
tender can be grouped, counted and compared on the Tender PO control board.
Mirrors v30 (Supplier Quotation → deal).

Idempotent: guarded by a Custom Field existence check. Pre-sync safe.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.db.exists("Custom Field", {"dt": "Purchase Order", "fieldname": "custom_crm_deal"}):
		return
	create_custom_fields(
		{
			"Purchase Order": [
				{
					"fieldname": "custom_crm_deal",
					"label": "CRM Deal",
					"fieldtype": "Link",
					"options": "CRM Deal",
					"insert_after": "supplier",
				}
			]
		},
		ignore_validate=True,
	)
