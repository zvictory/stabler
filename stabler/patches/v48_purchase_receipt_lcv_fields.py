import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
	if not frappe.db.exists("DocType", "Purchase Receipt"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Purchase Receipt", "fieldname": "custom_landed_cost_vouchered"}):
		return

	create_custom_fields(
		{
			"Purchase Receipt": [
				{
					"fieldname": "custom_landed_cost_vouchered",
					"label": "Landed Cost Vouchered",
					"fieldtype": "Check",
					"insert_after": "status",
					"read_only": 1,
					"hidden": 1,
				},
				{
					"fieldname": "custom_landed_cost_settings",
					"label": "Landed Cost Settings",
					"fieldtype": "Code",
					"options": "JSON",
					"insert_after": "custom_landed_cost_vouchered",
					"read_only": 1,
					"hidden": 1,
				},
			]
		},
		ignore_validate=True,
	)
