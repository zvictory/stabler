"""Tender intake + deadline data on CRM Deal.

Adds a single Long Text field `custom_tender_intake` on CRM Deal holding a JSON
object with the pre-bid intake and deadline fields: lot no, buyer, volume/unit,
bid deadline, delivery deadline, guarantee (amount + return date), certificate
requirement, penalty %/day, go/no-go decision, notes.

Deadlines drive the "muddat nazorati" timeline (days-left + risk) across the
tender. Deliberately NOT a child DocType — one JSON field, edited entirely in the
Stabler SPA. CRM Deal is not submittable, so no allow_on_submit needed.

Idempotent: guarded by a Custom Field existence check. Pre-sync safe.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return
	if frappe.db.exists("Custom Field", {"dt": "CRM Deal", "fieldname": "custom_tender_intake"}):
		return
	create_custom_fields(
		{
			"CRM Deal": [
				{
					"fieldname": "custom_tender_intake",
					"label": "Tender Intake (plan)",
					"fieldtype": "Long Text",
					"insert_after": "custom_bid_pricing" if frappe.db.has_column("CRM Deal", "custom_bid_pricing") else "status",
					"read_only": 1,
					"hidden": 1,
					"description": (
						"JSON intake + deadline plan (lot, deadlines, guarantee, certificate, "
						"go/no-go) maintained from the Stabler Tender PO control board."
					),
				}
			]
		},
		ignore_validate=True,
	)
