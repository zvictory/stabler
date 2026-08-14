"""Link Supplier Quotation records to the specific RFQ they answer.

Mirrors v68 (custom_crm_deal on Request for Quotation) and v30 (custom_crm_deal
on Supplier Quotation). This provides round-based response tracking so that
an RFQ can distinguish responses to a specific request round from quotations
submitted in other rounds of the same lot.

Idempotent: guarded by a Custom Field existence check, and by a DocType check.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Supplier Quotation"):
		return
	if not frappe.db.exists("DocType", "Request for Quotation"):
		return
	already_installed = {"dt": "Supplier Quotation", "fieldname": "custom_rfq"}
	if frappe.db.exists("Custom Field", already_installed):
		return
	create_custom_fields(
		{
			"Supplier Quotation": [
				{
					"fieldname": "custom_rfq",
					"label": "RFQ",
					"fieldtype": "Link",
					"options": "Request for Quotation",
					"insert_after": "custom_crm_deal",
					"no_copy": 1,
					"in_list_view": 1,
				}
			]
		},
		ignore_validate=True,
	)
