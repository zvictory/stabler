"""Tender execution links on Sales Order.

Adds the two links that turn a Sales Order into the "single contract" spine:
  - custom_crm_deal    — back-link to the winning CRM Deal (set by F7).
  - custom_board_stage — the manager-defined execution stage (F8 board).

Idempotent: each field guarded by a Custom Field existence check. Pre-sync safe
— only Custom Field metadata is created here; no new column is read.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields = []

	def add(spec):
		if not frappe.db.exists("Custom Field", {"dt": "Sales Order", "fieldname": spec["fieldname"]}):
			fields.append(spec)

	add({
		"fieldname": "custom_crm_deal",
		"label": "CRM Deal",
		"fieldtype": "Link",
		"options": "CRM Deal",
		"insert_after": "customer",
		"read_only": 1,
	})
	add({
		"fieldname": "custom_board_stage",
		"label": "Board Stage",
		"fieldtype": "Link",
		"options": "Stabler SO Stage",
		"insert_after": "custom_crm_deal",
	})

	if fields:
		create_custom_fields({"Sales Order": fields}, ignore_validate=True)
