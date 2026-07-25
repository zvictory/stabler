"""Agreement master links for contract-level receivables.

The native Contract DocType remains the agreement master. These links let one
contract connect to many quotations, sales orders, and sales invoices without
duplicating financial truth outside ERPNext.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields = {
		"Contract": [
			{
				"fieldname": "custom_agreement_no",
				"label": "Agreement No",
				"fieldtype": "Data",
				"insert_after": "party_name",
				"unique": 0,
			},
			{
				"fieldname": "custom_original_currency",
				"label": "Original Currency",
				"fieldtype": "Link",
				"options": "Currency",
				"insert_after": "custom_agreement_no",
			},
			{
				"fieldname": "custom_original_total",
				"label": "Original Contract Total",
				"fieldtype": "Currency",
				"insert_after": "custom_original_currency",
			},
		],
		"Quotation": [
			{
				"fieldname": "custom_agreement",
				"label": "Agreement",
				"fieldtype": "Link",
				"options": "Contract",
				"insert_after": "customer_name",
			},
		],
		"Sales Order": [
			{
				"fieldname": "custom_agreement",
				"label": "Agreement",
				"fieldtype": "Link",
				"options": "Contract",
				"insert_after": "customer_name",
			},
		],
		"Sales Invoice": [
			{
				"fieldname": "custom_agreement",
				"label": "Agreement",
				"fieldtype": "Link",
				"options": "Contract",
				"insert_after": "customer_name",
			},
		],
	}
	create_custom_fields(fields, ignore_validate=True)
