"""Add custom_landed_charges JSON field to Supplier Quotation.

Mirrors PO landed charges (v68). Stores planned landed costs (freight, customs,
handling) on quotation lines before a PO is raised.

Idempotent: guarded by a Custom Field existence check.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Supplier Quotation"):
		return
	already_installed = {"dt": "Supplier Quotation", "fieldname": "custom_landed_charges"}
	if frappe.db.exists("Custom Field", already_installed):
		return
	create_custom_fields(
		{
			"Supplier Quotation": [
				{
					"fieldname": "custom_landed_charges",
					"label": "Landed Charges JSON",
					"fieldtype": "Long Text",
					"insert_after": "grand_total",
					"no_copy": 1,
					"read_only": 0,
				}
			]
		},
		ignore_validate=True,
	)
