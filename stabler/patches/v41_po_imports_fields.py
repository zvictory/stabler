"""Link Purchase Orders (and PO line items) to an Import PI Group.

Adds `custom_import_pi_group` on Purchase Order and Purchase Order Item so a
PO — or an individual PO line — can be grouped under one commercial-invoice
consolidation used by the imports/customs declaration pipeline (MSAERP
migration). Mirrors v34's custom_crm_deal pattern.

Idempotent: guarded field-by-field via a Custom Field existence check per
doctype, so a partial prior run (e.g. Purchase Order got the field but
Purchase Order Item didn't) is completed rather than skipped outright. Skips
entirely if the "Import PI Group" doctype does not exist yet — listed under
[post_model_sync] so it can run once that doctype has synced.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

_FIELD_DEFS = {
	"Purchase Order": {
		"fieldname": "custom_import_pi_group",
		"label": "Import PI Group",
		"fieldtype": "Link",
		"options": "Import PI Group",
		"insert_after": "custom_crm_deal",
	},
	"Purchase Order Item": {
		"fieldname": "custom_import_pi_group",
		"label": "Import PI Group",
		"fieldtype": "Link",
		"options": "Import PI Group",
		"insert_after": "warehouse",
	},
}


def execute():
	if not frappe.db.exists("DocType", "Import PI Group"):
		return
	fields_to_create = {}
	for doctype, df in _FIELD_DEFS.items():
		if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": df["fieldname"]}):
			continue
		fields_to_create[doctype] = [df]
	if not fields_to_create:
		return
	create_custom_fields(fields_to_create, ignore_validate=True)
