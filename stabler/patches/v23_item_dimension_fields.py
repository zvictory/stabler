"""Dimensional-pricing custom fields (Sales).

Lets one tenant sell ice cream by the box while another sells industrial belt /
pipe / foam by measured size. Driven by a per-ITEM mode (so no per-tenant code —
ice-cream items simply leave the mode blank):

  Item.custom_dimension_mode  Select ""/Linear/Area/Volume
  Sales Order Item   + custom_length/_width/_height/_pieces (Float)
  Sales Invoice Item + custom_length/_width/_height/_pieces (Float)

The line's billable `qty` (in the item's stock UOM = m / m² / m³) is computed from
these by stabler.api._dimensions.dimensional_qty; rate is per stock UOM, so amount
= qty × rate and ERPNext stock/valuation/GL stay consistent.

Idempotent + pre-sync safe: each field guarded by a Custom Field existence check;
we create metadata only (no reads of the new columns).
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

	if not frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": "custom_dimension_mode"}):
		plan["Item"] = [
			{
				"fieldname": "custom_dimension_mode",
				"label": "Dimension Mode",
				"fieldtype": "Select",
				"options": "\nLinear\nArea\nVolume",
				"default": "",
				"insert_after": "stock_uom",
				"description": (
					"Blank = normal item (qty as entered). Linear → qty = length×pieces (m); "
					"Area → length×width×pieces (m²); Volume → length×width×height×pieces (m³). "
					"Set the item's stock UOM to the matching measure."
				),
			}
		]

	for dt, anchor in (("Sales Order Item", "qty"), ("Sales Invoice Item", "qty")):
		if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": "custom_length"}):
			plan[dt] = _line_fields(anchor)

	if plan:
		create_custom_fields(plan, ignore_validate=True)
