"""Asl Belgisi (mandatory product marking) custom fields.

Bootstraps:
  - Item.asl_belgisi_enabled (Check) — flag goods that require scanning
  - Stock Entry Detail.asl_belgisi_code (Data) — captured at receipt/issue
  - Sales Invoice Item.asl_belgisi_code (Data, read-only) — surfaced for
    audit; populated by the scan API when a SI is materialized from a
    flagged Stock Entry row.

Uses `create_custom_fields(update=True)` so it's idempotent — the second
run is a no-op.
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> None:
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "asl_belgisi_enabled",
					"label": "Asl Belgisi Required",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "is_stock_item",
					"description": "Item requires Asl Belgisi mandatory marking scan",
				},
			],
			"Stock Entry Detail": [
				{
					"fieldname": "asl_belgisi_code",
					"label": "Asl Belgisi Code",
					"fieldtype": "Data",
					"insert_after": "serial_no",
					"in_list_view": 0,
				},
			],
			"Sales Invoice Item": [
				{
					"fieldname": "asl_belgisi_code",
					"label": "Asl Belgisi Code",
					"fieldtype": "Data",
					"read_only": 1,
					"insert_after": "serial_no",
				},
			],
		},
		update=True,
	)
