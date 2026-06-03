"""Add `allowed_modules` Table field on User → Stabler User Module.

Idempotent: skips creation if the custom field already exists.

Note: uses plain Table (not Table MultiSelect) because module keys are Data
strings, not Link options. All editing is done via the SPA admin drawer; the
field is never edited directly in Frappe Desk.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "allowed_modules"}):
		return

	create_custom_fields(
		{
			"User": [
				{
					"fieldname": "allowed_modules",
					"label": "Allowed Modules",
					"fieldtype": "Table",
					"options": "Stabler User Module",
					"insert_after": "allowed_companies",
					"description": "Per-user module override. Empty = derive from roles. Non-empty = exactly these modules (grants and restricts). Admins always see all.",
				},
			]
		},
		ignore_validate=True,
	)
	frappe.db.commit()
