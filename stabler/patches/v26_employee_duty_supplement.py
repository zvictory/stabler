"""Add a per-employee duty-supplement percentage custom field on Employee.

The payroll engine (`_payroll_calc.calculate_payroll`) accepts a list of duty
supplements, each a percentage of the effective base. Stabler exposes a single
per-employee supplement here; `hr_pay._compute` maps a non-zero value onto the
engine's `duty_supplements=[{"pct": ...}]` input.

Idempotent + pre-sync safe: we only create Custom Field *metadata* (no read of
the new column), guarded by an existence check, so the patch is safe to re-run
and safe to run before the doctype DDL sync.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields_to_add = []

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_duty_supplement_pct"}):
		fields_to_add.append(
			{
				"fieldname": "custom_duty_supplement_pct",
				"label": "Duty Supplement %",
				"fieldtype": "Percent",
				"default": "0",
				"insert_after": "custom_additional_duties",
				"description": (
					"Extra duty supplement as a percentage of the effective base "
					"(e.g. acting-role pay). 0 = none."
				),
			}
		)

	if fields_to_add:
		create_custom_fields({"Employee": fields_to_add}, ignore_validate=True)
