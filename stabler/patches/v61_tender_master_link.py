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
					"insert_after": "custom_deal_type",
					"depends_on": 'eval:doc.custom_deal_type=="Tender"',
					"no_copy": 1,
				}
			]
		},
		ignore_validate=True,
	)
