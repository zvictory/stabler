"""Add custom_triage_status and unique custom_idempotency_key fields to Communication doctype."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Communication"):
		return

	create_custom_fields(
		{
			"Communication": [
				{
					"fieldname": "custom_triage_status",
					"label": "Triage Status",
					"fieldtype": "Select",
					"options": "\nPending\nUnmatched\nLinked",
					"default": "Pending",
					"insert_after": "status",
				},
				{
					"fieldname": "custom_idempotency_key",
					"label": "Idempotency Key",
					"fieldtype": "Data",
					"unique": 1,
					"insert_after": "custom_triage_status",
				},
			]
		},
		ignore_validate=True,
	)
