"""v70 patch: Add custom_tender_documents (Long Text) to Tender Master.

Stores tender-scoped document requirements JSON on the master tender record,
allowing all child lots to share high-level tender documents once.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.table_exists("Tender Master"):
		return

	fields = {
		"Tender Master": [
			{
				"fieldname": "custom_tender_documents",
				"label": "Tender Document Requirements",
				"fieldtype": "Long Text",
				"insert_after": "tender_type",
				"read_only": 0,
				"description": "JSON requirement array for tender-scoped documents shared across child lots",
			}
		]
	}
	create_custom_fields(fields, update=True)
