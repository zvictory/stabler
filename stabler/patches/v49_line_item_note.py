"""Per-line material note on transactional item rows (WP-310 phase 2).

Adds ``custom_line_note`` (Small Text) to the five item child tables the SPA
edits — Sales Order Item, Sales Invoice Item, Purchase Order Item, Purchase
Invoice Item and Stock Entry Detail — so a user can attach a short note to a
material right where they pick it (sales, purchase and transfers alike).

Not no_copy: ERPNext's get_mapped_doc then carries the note along the document
chain automatically (SO Item → SI Item, PO Item → PI Item). allow_on_submit=1 —
a note is non-financial and may be corrected after submit.

Listed under [post_model_sync]. Idempotent: sentinel Custom Field guard on the
Sales Order Item field, so a re-run adds nothing.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

_CHILD_DOCTYPES = (
	"Sales Order Item",
	"Sales Invoice Item",
	"Purchase Order Item",
	"Purchase Invoice Item",
	"Stock Entry Detail",
)


def execute():
	if not frappe.db.exists("DocType", "Sales Order Item"):
		return
	# Sentinel guard: if the first table already has the field, the set was added.
	if frappe.db.exists("Custom Field", {"dt": "Sales Order Item", "fieldname": "custom_line_note"}):
		return

	fields = {}
	for dt in _CHILD_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		fields[dt] = [
			{
				"fieldname": "custom_line_note",
				"label": "Line Note",
				"fieldtype": "Small Text",
				"insert_after": "item_name",
				"allow_on_submit": 1,
				"print_hide": 0,
				"description": "Free-form note for this material line (shown in the Stabler SPA).",
			}
		]
	if fields:
		create_custom_fields(fields, ignore_validate=True)
