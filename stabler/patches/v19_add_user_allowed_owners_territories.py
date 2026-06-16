"""Add `allowed_owners` and `allowed_territories` Table fields on User.

Gap #46 — master scoping by owner / territory for Customer and Supplier.

Idempotent: each block is guarded by a Custom Field existence check.
No frappe.db.has_column guard needed — we are not reading a new column here,
only creating the Custom Field metadata (pre-sync safe).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields_to_add = []

	if not frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "allowed_owners"}):
		fields_to_add.append(
			{
				"fieldname": "allowed_owners",
				"label": "Allowed Owners",
				"fieldtype": "Table",
				"options": "Stabler User Allowed Owner",
				"insert_after": "allowed_modules",
				"description": (
					"Restrict this user to Customer/Supplier records owned by these users. "
					"Empty = no restriction. Admins always see all records."
				),
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "allowed_territories"}):
		fields_to_add.append(
			{
				"fieldname": "allowed_territories",
				"label": "Allowed Territories",
				"fieldtype": "Table",
				"options": "Stabler User Allowed Territory",
				"insert_after": "allowed_owners",
				"description": (
					"Restrict this user to Customer/Supplier records in these territories. "
					"Empty = no restriction. Admins always see all records."
				),
			}
		)

	if fields_to_add:
		create_custom_fields({"User": fields_to_add}, ignore_validate=True)
		frappe.db.commit()
