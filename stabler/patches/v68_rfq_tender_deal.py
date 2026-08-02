"""Link Request for Quotation records to the tender lot they were asked for.

Mirrors v30 (`custom_crm_deal` on Supplier Quotation). Until now the SPA could
only READ quotations someone had tagged elsewhere — there was no record of WHOM
we asked, only of who answered. This field is the other half: the request side
of the same conversation, hanging off the same CRM Deal.

Idempotent: guarded by a Custom Field existence check, and by a DocType check
for the four sites that carry no purchase stack at all. `patches.txt` has no
`[post_model_sync]` marker, so this runs BEFORE the doctype sync on every
migrate — it must therefore never assume a schema it did not itself create.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Request for Quotation"):
		return
	if not frappe.db.exists("DocType", "CRM Deal"):
		return
	already_installed = {"dt": "Request for Quotation", "fieldname": "custom_crm_deal"}
	if frappe.db.exists("Custom Field", already_installed):
		return
	create_custom_fields(
		{
			"Request for Quotation": [
				{
					"fieldname": "custom_crm_deal",
					"label": "CRM Deal",
					"fieldtype": "Link",
					"options": "CRM Deal",
					# `transaction_date` is a core RFQ field present on every
					# ERPNext version this bench has carried, unlike the naming
					# series block which moved between v14 and v16. An
					# `insert_after` that points at nothing installs quietly with
					# `ignore_validate=True` and drops the field at an arbitrary
					# idx — see the v61 note.
					"insert_after": "transaction_date",
					"no_copy": 1,
				}
			]
		},
		ignore_validate=True,
	)
