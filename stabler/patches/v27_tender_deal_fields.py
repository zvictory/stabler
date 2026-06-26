"""Tender extensions on CRM Deal.

Adds the pre-win tender fields used by the tender funnel (F1):
  - tender_no        — the tender / lot reference number.
  - tender_deadline  — submission / bid deadline (red when overdue on the card).
  - bid_value        — our submitted bid amount.
  - tender_source    — acquisition channel (Telegram / Web / Portal / Direct).

Prefixed `tender_*` to avoid colliding with any native CRM Deal / Lead field
(`source` exists on Lead). Idempotent: each field guarded by a Custom Field
existence check. Pre-sync safe — only Custom Field metadata is created here.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields = []

	def add(spec):
		if not frappe.db.exists("Custom Field", {"dt": "CRM Deal", "fieldname": spec["fieldname"]}):
			fields.append(spec)

	add({
		"fieldname": "tender_no",
		"label": "Tender No",
		"fieldtype": "Data",
		"insert_after": "deal_value",
	})
	add({
		"fieldname": "tender_deadline",
		"label": "Tender Deadline",
		"fieldtype": "Date",
		"insert_after": "tender_no",
	})
	add({
		"fieldname": "bid_value",
		"label": "Bid Value",
		"fieldtype": "Currency",
		"insert_after": "tender_deadline",
	})
	add({
		"fieldname": "tender_source",
		"label": "Tender Source",
		"fieldtype": "Select",
		"options": "\nTelegram\nWeb\nPortal\nDirect",
		"insert_after": "bid_value",
	})

	if fields:
		create_custom_fields({"CRM Deal": fields}, ignore_validate=True)
