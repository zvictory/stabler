"""Link Supplier Quotations to a tender (F3 sourcing).

Adds `custom_crm_deal` on Supplier Quotation so the ≥5-quotation / 2-country
sourcing comparison can group all quotes collected for one tender.

Idempotent: guarded by a Custom Field existence check. Pre-sync safe.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Supplier Quotation", "fieldname": "custom_crm_deal"}):
		return
	create_custom_fields(
		{
			"Supplier Quotation": [
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
