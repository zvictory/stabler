"""Add compensation and attendance-rule custom fields on Employee.

These fields drive the anjan-hr payroll / attendance engine that runs alongside
Stabler. Each field is salary-sensitive (base_salary, allowance_config) or
controls the rule engine (shift_class, region, work_mode, stake_coefficient,
heavy_conditions, additional_duties). They are stored as ERPNext Custom Fields
so the Employee doctype needs no schema fork.

Field order (insert_after chain, appears after the v21 Timepay fields):
  custom_timepay_name
    → custom_base_salary
      → custom_shift_class
        → custom_region
          → custom_work_mode
            → custom_stake_coefficient
              → custom_heavy_conditions
                → custom_additional_duties
                  → custom_allowance_config

Idempotent: each field is guarded by a Custom Field existence check so the
patch is safe to re-run and safe to run before the doctype DDL sync (pre-sync
safe — we create metadata only, we do not read the new columns here).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields_to_add = []

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_base_salary"}):
		fields_to_add.append(
			{
				"fieldname": "custom_base_salary",
				"label": "Base Salary",
				"fieldtype": "Currency",
				"insert_after": "custom_timepay_name",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_shift_class"}):
		fields_to_add.append(
			{
				"fieldname": "custom_shift_class",
				"label": "Shift Class",
				"fieldtype": "Select",
				"options": "DAY\nNIGHT\nOFFICE\nLIGHT",
				"default": "DAY",
				"insert_after": "custom_base_salary",
				"description": "Drives the attendance rule engine (anchors, OT, night).",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_region"}):
		fields_to_add.append(
			{
				"fieldname": "custom_region",
				"label": "Region",
				"fieldtype": "Select",
				"options": "CITY\nDISTRICT\nFAR_DISTRICT\nNO_TRAVEL",
				"default": "CITY",
				"insert_after": "custom_shift_class",
				"description": "Transport allowance / region rate band.",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_work_mode"}):
		fields_to_add.append(
			{
				"fieldname": "custom_work_mode",
				"label": "Work Mode",
				"fieldtype": "Select",
				"options": "SHIFT_8H\nSHIFT_12H\nHALF_RATE\nFLEXIBLE\nREMOTE",
				"default": "SHIFT_8H",
				"insert_after": "custom_region",
				"description": "FLEXIBLE/REMOTE suppress auto late fees; HALF_RATE prorates by stake.",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_stake_coefficient"}):
		fields_to_add.append(
			{
				"fieldname": "custom_stake_coefficient",
				"label": "Stake Coefficient",
				"fieldtype": "Float",
				"default": "1.0",
				"insert_after": "custom_work_mode",
				"description": "Only meaningful when Work Mode = HALF_RATE (0.1–2.0); forced to 1 otherwise.",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_heavy_conditions"}):
		fields_to_add.append(
			{
				"fieldname": "custom_heavy_conditions",
				"label": "Heavy Conditions",
				"fieldtype": "Check",
				"default": "0",
				"insert_after": "custom_stake_coefficient",
				"description": "Adds the heavy-conditions supplement (+20%).",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_additional_duties"}):
		fields_to_add.append(
			{
				"fieldname": "custom_additional_duties",
				"label": "Additional Duties",
				"fieldtype": "Check",
				"default": "0",
				"insert_after": "custom_heavy_conditions",
				"description": "Adds the additional-duties supplement (+25%).",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_allowance_config"}):
		fields_to_add.append(
			{
				"fieldname": "custom_allowance_config",
				"label": "Allowance Config (JSON)",
				"fieldtype": "Long Text",
				"insert_after": "custom_additional_duties",
				"description": (
					"JSON: {seniority?, night?:{perHour}, custom?:[{label,amount,type}]}. Salary-sensitive."
				),
			}
		)

	if fields_to_add:
		create_custom_fields({"Employee": fields_to_add}, ignore_validate=True)
