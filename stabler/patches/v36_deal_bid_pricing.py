"""Tender bid-pricing plan (margin → bid price) on CRM Deal.

Adds a single Long Text field `custom_bid_pricing` on CRM Deal holding a JSON
object with the pricing inputs/overrides (mode, margin %, tax %s, extra cost
lines). The sell side is a Sales Order (Договор / bid price) and the cost side is
the deal's Purchase Orders (landed) — this field only stores the pricing plan
overlay; revenue and landed cost are read live from the linked SO/PO.

Deliberately NOT a child DocType: the whole calculator lives in the Stabler SPA;
one JSON field is enough to persist the plan. CRM Deal is not submittable, so no
allow_on_submit needed.

Idempotent: guarded by a Custom Field existence check. Pre-sync safe (only
creates Custom Field metadata; never reads the new column).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return
	if frappe.db.exists("Custom Field", {"dt": "CRM Deal", "fieldname": "custom_bid_pricing"}):
		return
	create_custom_fields(
		{
			"CRM Deal": [
				{
					"fieldname": "custom_bid_pricing",
					"label": "Bid Pricing (plan)",
					"fieldtype": "Long Text",
					"insert_after": "custom_board_stage" if frappe.db.has_column("CRM Deal", "custom_board_stage") else "status",
					"read_only": 1,
					"hidden": 1,
					"description": (
						"JSON pricing plan (margin, tax rates, extra cost lines) for the tender "
						"bid, maintained from the Stabler Tender PO control board."
					),
				}
			]
		},
		ignore_validate=True,
	)
