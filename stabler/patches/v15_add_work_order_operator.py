"""Add custom operator field to Work Order.

Links a shop-floor operator (User) to each Work Order so operators can
see only the Work Orders assigned to their manufacturing line.
Idempotent: create_custom_fields with update=True is a no-op if the field
already exists.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> None:
	create_custom_fields(
		{
			"Work Order": [
				{
					"fieldname": "operator",
					"label": "Operator",
					"fieldtype": "Link",
					"options": "User",
					"insert_after": "wip_warehouse",
					"allow_on_submit": 1,
					"description": "Shop-floor operator (line) responsible for this Work Order",
				}
			],
		},
		update=True,
	)
