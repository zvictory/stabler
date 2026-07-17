"""Link Journal Entries (kassa expenses) to a tender.

Adds `custom_crm_deal` on Journal Entry so cash expenses recorded through
/money/expenses (or the Telegram kassa bot) can be attributed to a tender and
fed into the tender plan-vs-actual P&L. Mirrors v34 (Purchase Order → deal).

Idempotent: guarded by a Custom Field existence check. Post-model-sync safe.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Journal Entry", "fieldname": "custom_crm_deal"}):
		return
	create_custom_fields(
		{
			"Journal Entry": [
				{
					"fieldname": "custom_crm_deal",
					"label": "CRM Deal",
					"fieldtype": "Link",
					"options": "CRM Deal",
					"insert_after": "cheque_date",
				}
			]
		},
		ignore_validate=True,
	)
