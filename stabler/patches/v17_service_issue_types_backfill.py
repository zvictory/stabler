"""Backfill Service setup records after the P1 schema patch."""

import frappe

ISSUE_TYPES = ("Install", "Inspection", "Maintenance", "Refill", "Repair", "Complaint")
SERVICE_ROLES = ("Support Team", "Maintenance User", "Maintenance Manager")


def execute() -> None:
	for issue_type in ISSUE_TYPES:
		if frappe.db.exists("Issue Type", issue_type):
			continue
		doc = frappe.new_doc("Issue Type")
		doc.name = issue_type
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

	frappe.db.commit()
