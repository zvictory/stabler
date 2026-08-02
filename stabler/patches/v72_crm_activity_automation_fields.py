"""Add automation audit custom fields with unique idempotency index to CRM Activity doctype."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Activity"):
		return

	create_custom_fields(
		{
			"CRM Activity": [
				{
					"fieldname": "custom_idempotency_key",
					"label": "Idempotency Key",
					"fieldtype": "Data",
					"unique": 1,
					"insert_after": "status",
				},
				{
					"fieldname": "custom_rule_name",
					"label": "Automation Rule Name",
					"fieldtype": "Data",
					"insert_after": "custom_idempotency_key",
				},
				{
					"fieldname": "custom_execution_status",
					"label": "Execution Status",
					"fieldtype": "Select",
					"options": "\nExecuted\nRetried\nFailed",
					"default": "Executed",
					"insert_after": "custom_rule_name",
				},
				{
					"fieldname": "custom_attempts",
					"label": "Execution Attempts",
					"fieldtype": "Int",
					"default": 1,
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
