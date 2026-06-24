"""Dimensional-pricing custom fields for the Purchasing side.

Mirrors v23 (Sales) on the buy side so a tenant can purchase belt / pipe / foam by
measured size:

  Purchase Order Item   + custom_length/_width/_height/_pieces (Float)
  Purchase Invoice Item + custom_length/_width/_height/_pieces (Float)

The per-ITEM mode (Item.custom_dimension_mode) and the qty math are shared with
Sales — only the line custom fields are doctype-specific, so we add them here.
The apply_dimensional_qty before_validate hook (registered on PO + PI) recomputes
qty in the item's stock UOM (m / m² / m³).

Idempotent + pre-sync safe: each field guarded by a Custom Field existence check.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _line_fields(insert_anchor: str) -> list:
	return [
		{"fieldname": "custom_length", "label": "Length", "fieldtype": "Float", "insert_after": insert_anchor},
		{"fieldname": "custom_width", "label": "Width", "fieldtype": "Float", "insert_after": "custom_length"},
		{"fieldname": "custom_height", "label": "Height", "fieldtype": "Float", "insert_after": "custom_width"},
		{"fieldname": "custom_pieces", "label": "Pieces", "fieldtype": "Float", "insert_after": "custom_height"},
	]


def execute():
	plan: dict = {}
	for dt in ("Purchase Order Item", "Purchase Invoice Item"):
		if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": "custom_length"}):
			plan[dt] = _line_fields("qty")
	if plan:
		create_custom_fields(plan, ignore_validate=True)
