"""Service module P1 schema.

Adds the ERPNext-native fields used by Stabler's HoReCa Service ticket board.
The patch is intentionally idempotent so it can run on existing tenants and
newly installed Service tenants without changing non-Service behavior.

Design note: frappe.db.commit() is called immediately after create_custom_fields()
because MariaDB DDL (ALTER TABLE ADD COLUMN) auto-commits and cannot be rolled back,
but the matching tabCustom Field DML inserts ARE transactional. Without an early
commit, an exception in the code below could roll back the metadata records while
leaving the physical columns orphaned — causing silent "columns exist but Frappe
doesn't know about them" corruption.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

ISSUE_STATUS_OPTIONS = "\n".join(
	["Open", "Assigned", "In Progress", "On Hold", "Resolved", "Closed", "Cancelled"]
)

ISSUE_TYPES = ("Install", "Inspection", "Maintenance", "Refill", "Repair", "Complaint")
SERVICE_ROLES = ("Support Team", "Maintenance User", "Maintenance Manager")

_REQUIRED_COLUMNS = [
	("Issue", "custom_horeca_id"),
	("Maintenance Visit", "custom_horeca_id"),
	("Maintenance Schedule Item", "custom_interval_days"),
	("Serial No", "custom_horeca_id"),
]


def execute() -> None:
	create_custom_fields(
		{
			"Issue": [
				{
					"fieldname": "custom_serial_no",
					"label": "Serial No",
					"fieldtype": "Link",
					"options": "Serial No",
					"insert_after": "customer",
				},
				{
					"fieldname": "custom_tech_state",
					"label": "Technician State",
					"fieldtype": "Select",
					"options": "\nAccepted\nEn Route\nStarted",
					"insert_after": "status",
				},
				{
					"fieldname": "custom_maintenance_visit",
					"label": "Maintenance Visit",
					"fieldtype": "Link",
					"options": "Maintenance Visit",
					"insert_after": "custom_tech_state",
				},
				{
					"fieldname": "custom_horeca_id",
					"label": "HoReCa ID",
					"fieldtype": "Data",
					"insert_after": "custom_maintenance_visit",
					"unique": 1,
				},
			],
			"Maintenance Visit": [
				{
					"fieldname": "custom_issue",
					"label": "Issue",
					"fieldtype": "Link",
					"options": "Issue",
					"insert_after": "customer",
				},
				{
					"fieldname": "custom_customer_signature",
					"label": "Customer Signature",
					"fieldtype": "Signature",
					"insert_after": "custom_issue",
				},
				{
					"fieldname": "custom_sales_invoice",
					"label": "Sales Invoice",
					"fieldtype": "Link",
					"options": "Sales Invoice",
					"insert_after": "custom_customer_signature",
				},
				{
					"fieldname": "custom_stock_entry",
					"label": "Stock Entry",
					"fieldtype": "Link",
					"options": "Stock Entry",
					"insert_after": "custom_sales_invoice",
				},
				{
					"fieldname": "custom_horeca_id",
					"label": "HoReCa ID",
					"fieldtype": "Data",
					"insert_after": "custom_stock_entry",
					"unique": 1,
				},
			],
			"Maintenance Schedule Item": [
				{
					"fieldname": "custom_interval_days",
					"label": "Interval Days",
					"fieldtype": "Int",
					"insert_after": "end_date",
				},
				{
					"fieldname": "custom_day_of_month",
					"label": "Day of Month",
					"fieldtype": "Int",
					"insert_after": "custom_interval_days",
				},
			],
			"Serial No": [
				{
					"fieldname": "custom_placement",
					"label": "Placement",
					"fieldtype": "Select",
					"options": "\nSold\nLoaned\nIn Stock",
					"insert_after": "warehouse",
				},
				{
					"fieldname": "custom_asset",
					"label": "Asset",
					"fieldtype": "Link",
					"options": "Asset",
					"insert_after": "custom_placement",
				},
				{
					"fieldname": "custom_horeca_id",
					"label": "HoReCa ID",
					"fieldtype": "Data",
					"insert_after": "custom_asset",
					"unique": 1,
				},
			],
		},
		update=True,
	)

	# Commit now so the tabCustom Field DML inserts survive even if anything below raises.
	# (ALTER TABLE ADD COLUMN is DDL and auto-commits regardless — this guards the metadata.)
	frappe.db.commit()

	make_property_setter(
		"Issue",
		"status",
		"options",
		ISSUE_STATUS_OPTIONS,
		"Text",
		for_doctype=False,
	)

	for issue_type in ISSUE_TYPES:
		if frappe.db.exists("Issue Type", issue_type):
			continue
		doc = frappe.new_doc("Issue Type")
		doc.name = issue_type
		doc.issue_type = issue_type
		doc.insert(ignore_permissions=True)

	for role in SERVICE_ROLES:
		if frappe.db.exists("Role", role):
			continue
		doc = frappe.new_doc("Role")
		doc.name = role
		doc.role_name = role
		if hasattr(doc, "desk_access"):
			doc.desk_access = 0
		doc.insert(ignore_permissions=True)

	if frappe.db.has_column("Stabler Company Modules", "enable_service"):
		frappe.db.sql(
			"""UPDATE `tabStabler Company Modules`
			   SET enable_service = 0
			   WHERE enable_service IS NULL"""
		)

	frappe.db.commit()

	# Fail loud if any expected column is still missing after the patch.
	missing = [
		f"{doctype}.{col}"
		for doctype, col in _REQUIRED_COLUMNS
		if not frappe.db.has_column(doctype, col)
	]
	if missing:
		frappe.throw(f"v16 patch: expected columns not found after execute: {missing}")
