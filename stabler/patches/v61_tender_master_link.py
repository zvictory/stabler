"""Link CRM Deal records to their Tender Master parent."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return

	create_custom_fields(
		{
			"CRM Deal": [
				{
					"fieldname": "custom_parent_tender",
					"label": "Parent Tender",
					"fieldtype": "Link",
					"options": "Tender Master",
					# v60 creates this field as plain `deal_type` (no custom_ prefix —
					# frappe only auto-prefixes when fieldname is left empty), so the
					# field must be referenced by that exact name or the Desk form
					# hides Parent Tender forever on an eval that can't be true.
					"insert_after": "deal_type",
					"depends_on": 'eval:doc.deal_type=="Tender"',
					"no_copy": 1,
				}
			]
		},
		ignore_validate=True,
	)
