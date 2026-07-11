"""Vendor-traceability reference fields on Purchase Invoice / Payment Entry (WP7).

The imports pipeline books several DRAFT Purchase Invoices (goods, cross-border
transport, non-transport Import Expenses) and a 70% advance Payment Entry, but
nothing on those accounting documents said WHICH container / commercial invoice
/ truck / expense they belonged to. Without that back-link the container cost
ledger cannot answer "hangi fatura hangi konteynere ait, ödendi mi" — so this
patch stamps four read-only Link fields on Purchase Invoice and one on Payment
Entry. The imports hooks (payment_math payload builders) fill them at creation;
here we only ensure the columns exist.

All fields are read_only=1 (set by automation, never hand-edited) and permlevel
0 (they are traceability links, not cost figures — the money stays masked at
permlevel 1 elsewhere).

Field-by-field idempotent: each Custom Field is created only when missing and an
existing field is never rewritten, so a partial prior run is completed rather
than skipped and a re-run is a no-op. Listed under [post_model_sync]; Purchase
Invoice / Payment Entry are core doctypes so the upsert is safe post-sync.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

_FIELDS = {
	"Purchase Invoice": [
		{
			"fieldname": "custom_commercial_invoice",
			"label": "Commercial Invoice",
			"fieldtype": "Link",
			"options": "Commercial Invoice",
			"insert_after": "bill_no",
			"read_only": 1,
			"description": "Import traceability — the Commercial Invoice this bill belongs to.",
		},
		{
			"fieldname": "custom_import_container",
			"label": "Import Container",
			"fieldtype": "Link",
			"options": "Import Container",
			"insert_after": "custom_commercial_invoice",
			"read_only": 1,
			"description": "Import traceability — the Import Container this bill belongs to.",
		},
		{
			"fieldname": "custom_import_truck",
			"label": "Import Truck",
			"fieldtype": "Link",
			"options": "Import Truck",
			"insert_after": "custom_import_container",
			"read_only": 1,
			"description": "Import traceability — the Import Truck this transport bill belongs to.",
		},
		{
			"fieldname": "custom_import_expense",
			"label": "Import Expense",
			"fieldtype": "Link",
			"options": "Import Expense",
			"insert_after": "custom_import_truck",
			"read_only": 1,
			"description": "Import traceability — the Import Expense this bill was raised from.",
		},
	],
	"Payment Entry": [
		{
			"fieldname": "custom_import_container",
			"label": "Import Container",
			"fieldtype": "Link",
			"options": "Import Container",
			"insert_after": "reference_no",
			"read_only": 1,
			"description": "Import traceability — the Import Container this advance belongs to.",
		},
	],
}


def execute() -> None:
	for doctype, fields in _FIELDS.items():
		for field in fields:
			if frappe.db.exists("Custom Field", f"{doctype}-{field['fieldname']}"):
				# Never rewrite an existing field's properties (idempotent re-run).
				continue
			create_custom_field(doctype, field)
	frappe.db.commit()
