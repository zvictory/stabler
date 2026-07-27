"""Custom fields on Attendance for the inline grid editor.

The month-matrix cell editor lets HR record arrival/departure plus the late /
early-leave / overtime minutes for a day. ERPNext Attendance has in_time/out_time
+ late_entry/early_exit checks but no minute fields — add them here so the values
persist and can feed payroll.

Idempotent + pre-sync safe: each field guarded by a Custom Field existence check.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields = [
		{
			"fieldname": "custom_late_minutes",
			"label": "Late (min)",
			"fieldtype": "Int",
			"insert_after": "late_entry",
			"non_negative": 1,
		},
		{
			"fieldname": "custom_early_minutes",
			"label": "Early leave (min)",
			"fieldtype": "Int",
			"insert_after": "custom_late_minutes",
			"non_negative": 1,
		},
		{
			"fieldname": "custom_overtime_minutes",
			"label": "Overtime (min)",
			"fieldtype": "Int",
			"insert_after": "custom_early_minutes",
			"non_negative": 1,
		},
	]
	pending = [
		f
		for f in fields
		if not frappe.db.exists("Custom Field", {"dt": "Attendance", "fieldname": f["fieldname"]})
	]
	if pending:
		create_custom_fields({"Attendance": pending}, ignore_validate=True)
