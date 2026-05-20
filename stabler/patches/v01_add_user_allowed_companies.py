"""Add `allowed_companies` Table MultiSelect on User → Stabler User Company.

Idempotent: skips creation if the custom field already exists.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "allowed_companies"}):
		return

	create_custom_fields(
		{
			"User": [
				{
					"fieldname": "allowed_companies_section",
					"fieldtype": "Section Break",
					"label": "Stabler Access",
					"insert_after": "language",
				},
				{
					"fieldname": "allowed_companies",
					"label": "Allowed Companies",
					"fieldtype": "Table MultiSelect",
					"options": "Stabler User Company",
					"insert_after": "allowed_companies_section",
					"description": "Limit Stabler access to these companies. Empty = all companies.",
				},
			]
		},
		ignore_validate=True,
	)
	frappe.db.commit()
