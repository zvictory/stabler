"""Link Journal Entries (kassa/bank expenses) to an import Commercial Invoice.

Adds `custom_commercial_invoice`, `custom_import_truck`, `custom_import_container`
on Journal Entry so direct expenses recorded through /money/expenses can be
attributed to an import and fed into the CI landed cost review.

Idempotent: guarded by Custom Field existence checks. Post-model-sync safe.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields_to_create = []

	if not frappe.db.exists(
		"Custom Field", {"dt": "Journal Entry", "fieldname": "custom_commercial_invoice"}
	):
		fields_to_create.append(
			{
				"fieldname": "custom_commercial_invoice",
				"label": "Commercial Invoice",
				"fieldtype": "Link",
				"options": "Commercial Invoice",
				"insert_after": "cheque_date",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Journal Entry", "fieldname": "custom_import_truck"}):
		fields_to_create.append(
			{
				"fieldname": "custom_import_truck",
				"label": "Import Truck",
				"fieldtype": "Link",
				"options": "Import Truck",
				"insert_after": "custom_commercial_invoice",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Journal Entry", "fieldname": "custom_import_container"}):
		fields_to_create.append(
			{
				"fieldname": "custom_import_container",
				"label": "Import Container",
				"fieldtype": "Link",
				"options": "Import Container",
				"insert_after": "custom_import_truck",
			}
		)

	if fields_to_create:
		create_custom_fields({"Journal Entry": fields_to_create}, ignore_validate=True)
