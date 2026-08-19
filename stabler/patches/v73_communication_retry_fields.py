"""Add custom_execution_status, custom_attempts, and custom_last_error fields to Communication doctype."""

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
					"fieldname": "custom_execution_status",
					"label": "Execution Status",
					"fieldtype": "Select",
					"options": "\nExecuted\nRetried\nFailed",
					"default": "Executed",
					"insert_after": "custom_idempotency_key",
				},
				{
					"fieldname": "custom_attempts",
					"label": "Execution Attempts",
					"fieldtype": "Int",
					"default": "1",
					"insert_after": "custom_execution_status",
				},
				{
					"fieldname": "custom_last_error",
					"label": "Last Error Message",
					"fieldtype": "Small Text",
					"insert_after": "custom_attempts",
				},
			]
		},
		ignore_validate=True,
	)
