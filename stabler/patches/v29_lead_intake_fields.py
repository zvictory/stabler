"""Multi-channel intake fields on CRM Lead (F2).

Stamps where an inbound lead came from so the intake log and funnel can show
channel + the raw message + an optional tender reference:
  - custom_intake_channel  — Telegram / Web / Portal / Direct.
  - custom_intake_message  — the free-text body the prospect submitted.
  - custom_intake_tender_no — tender/lot number if the lead quoted one.

Idempotent: each field guarded by a Custom Field existence check. Pre-sync safe
— only Custom Field metadata is created here.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields = []

	def add(spec):
		if not frappe.db.exists("Custom Field", {"dt": "CRM Lead", "fieldname": spec["fieldname"]}):
			fields.append(spec)

	add({
		"fieldname": "custom_intake_channel",
		"label": "Intake Channel",
		"fieldtype": "Data",
		"insert_after": "source",
		"read_only": 1,
	})
	add({
		"fieldname": "custom_intake_message",
		"label": "Intake Message",
		"fieldtype": "Small Text",
		"insert_after": "custom_intake_channel",
		"read_only": 1,
	})
	add({
		"fieldname": "custom_intake_tender_no",
		"label": "Intake Tender No",
		"fieldtype": "Data",
		"insert_after": "custom_intake_message",
		"read_only": 1,
	})

	if fields:
		create_custom_fields({"CRM Lead": fields}, ignore_validate=True)
