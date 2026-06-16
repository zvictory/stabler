"""Add `custom_timepay_id` and `custom_timepay_name` Data fields on Employee.

ERPNext employee names collide (multiple "Dilnoza Yusupova"), so attendance must
be matched on the Timepay user id, not the name. These custom fields stamp the
Timepay identity onto the Employee itself:
  - custom_timepay_id   — the reliable match key (the Timepay/device user id).
  - custom_timepay_name — the Timepay-reported full name, kept as a human
                          reference to disambiguate which Employee is which.

Idempotent: guarded by a Custom Field existence check. Pre-sync safe — we only
create Custom Field metadata, we don't read the new columns here.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields_to_add = []

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_timepay_id"}):
		fields_to_add.append(
			{
				"fieldname": "custom_timepay_id",
				"label": "Timepay ID",
				"fieldtype": "Data",
				"insert_after": "attendance_device_id",
				"unique": 0,
				"description": (
					"Timepay / gate device user id — the reliable key for matching "
					"attendance. Set this rather than matching by name."
				),
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_timepay_name"}):
		fields_to_add.append(
			{
				"fieldname": "custom_timepay_name",
				"label": "Timepay Name",
				"fieldtype": "Data",
				"insert_after": "custom_timepay_id",
				"read_only": 0,
				"description": (
					"Full name as reported by Timepay. Reference only — used to tell "
					"apart ERPNext employees that share the same name."
				),
			}
		)

	if fields_to_add:
		create_custom_fields({"Employee": fields_to_add}, ignore_validate=True)
