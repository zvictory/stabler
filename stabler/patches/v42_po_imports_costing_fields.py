"""Add the remaining imports-costing custom fields on Purchase Order / Purchase Order Item.

Per docs/plans/2026-07-09-msaerp-to-stabler-migration-plan.md §3.1, the imports
pipeline needs advance/prepayment and docs-cost tracking on the PO header, and
per-line docs-rate/box-count tracking on PO Item. These mirror the sensitive
cost fields already added to Commercial Invoice (docs_total, cash_difference)
and are kept at permlevel=1 for the same reason: only roles with write access
to level-1 fields (see stabler/api/organization.py role map) can edit them.

Idempotent: guarded field-by-field via a Custom Field existence check per
(doctype, fieldname), so a partial prior run is completed rather than skipped
outright. Skips entirely if the "Import PI Group" doctype does not exist yet —
listed under [post_model_sync] so it can run once that doctype has synced.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

_FIELD_DEFS = {
	"Purchase Order": [
		{
			"fieldname": "custom_advance_percentage",
			"label": "Advance Percentage",
			"fieldtype": "Percent",
			"insert_after": "custom_import_pi_group",
			"permlevel": 1,
		},
		{
			"fieldname": "custom_prepayment_type",
			"label": "Prepayment Type",
			"fieldtype": "Select",
			"options": "\nAdvance\nLC\nOpen Account",
			"insert_after": "custom_advance_percentage",
			"permlevel": 1,
		},
		{
			"fieldname": "custom_docs_total",
			"label": "Docs Total",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "custom_prepayment_type",
			"permlevel": 1,
		},
		{
			"fieldname": "custom_cash_difference",
			"label": "Cash Difference",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "custom_docs_total",
			"permlevel": 1,
		},
		{
			"fieldname": "custom_stage",
			"label": "Stage",
			"fieldtype": "Data",
			"insert_after": "custom_cash_difference",
			"permlevel": 1,
		},
	],
	"Purchase Order Item": [
		{
			"fieldname": "custom_docs_rate",
			"label": "Docs Rate",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "custom_import_pi_group",
			"permlevel": 1,
		},
		{
			"fieldname": "custom_docs_amount",
			"label": "Docs Amount",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "custom_docs_rate",
			"permlevel": 1,
		},
		{
			"fieldname": "custom_boxes",
			"label": "Boxes",
			"fieldtype": "Int",
			"insert_after": "custom_docs_amount",
			"permlevel": 1,
		},
		{
			"fieldname": "custom_box_weight_kg",
			"label": "Box Weight (kg)",
			"fieldtype": "Float",
			"insert_after": "custom_boxes",
			"permlevel": 1,
		},
	],
}


def execute():
	if not frappe.db.exists("DocType", "Import PI Group"):
		return
	fields_to_create = {}
	for doctype, dfs in _FIELD_DEFS.items():
		missing = [
			df
			for df in dfs
			if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": df["fieldname"]})
		]
		if missing:
			fields_to_create[doctype] = missing
	if not fields_to_create:
		return
	create_custom_fields(fields_to_create, ignore_validate=True)
