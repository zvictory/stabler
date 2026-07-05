"""Planned landed-cost charges for imported Purchase Orders.

Adds a single Long Text field `custom_landed_charges` on Purchase Order that
holds a JSON array of planned cost lines (transport, customs/gümrük,
certification/sertifika, insurance, …) in company (base) currency. This lets
the Tender PO control board compute each vendor's true delivered/landed cost
and compare on that basis — not just the bare grand_total.

Deliberately NOT a child DocType: the whole editing experience lives in the
Stabler SPA; we only need one lightweight JSON field to persist the plan.
`allow_on_submit` so the plan can be maintained after the PO is submitted.

Idempotent: guarded by a Custom Field existence check. Pre-sync safe (we only
create Custom Field metadata here, we never read the new column).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.db.exists("Custom Field", {"dt": "Purchase Order", "fieldname": "custom_landed_charges"}):
		return
	create_custom_fields(
		{
			"Purchase Order": [
				{
					"fieldname": "custom_landed_charges",
					"label": "Landed Charges (plan)",
					"fieldtype": "Long Text",
					"insert_after": "custom_crm_deal",
					"allow_on_submit": 1,
					"read_only": 1,
					"hidden": 1,
					"description": (
						"JSON array of planned landed-cost lines in company currency, "
						"maintained from the Stabler Tender PO control board."
					),
				}
			]
		},
		ignore_validate=True,
	)
