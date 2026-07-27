"""Patch v33: staged remittance fields on Journal Entry (JE-only model).

The remittance module keeps its JE-only design (no dedicated doctype). To support
the register → payout → refund lifecycle with code-only pickup verification, each
stage JE carries:

  - stabler_remittance_id     groups the stage JEs of one transfer (REM-YYYY-#####)
  - stabler_remittance_stage  Register | Payout | Refund
  - stabler_pickup_code       secret set at Register, matched (never displayed) at Payout
  - stabler_sender_name       promoted from the free-text remark for querying
  - stabler_receiver_name     promoted from the free-text remark for querying

Idempotent: guarded by Custom Field existence.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

_FIELDS = [
	{
		"fieldname": "stabler_remittance_id",
		"label": "Remittance ID",
		"fieldtype": "Data",
		"insert_after": "cheque_date",
		"read_only": 1,
		"no_copy": 1,
	},
	{
		"fieldname": "stabler_remittance_stage",
		"label": "Remittance Stage",
		"fieldtype": "Select",
		"options": "\nRegister\nPayout\nRefund",
		"insert_after": "stabler_remittance_id",
		"read_only": 1,
		"no_copy": 1,
	},
	{
		"fieldname": "stabler_pickup_code",
		"label": "Pickup Code",
		"fieldtype": "Data",
		"insert_after": "stabler_remittance_stage",
		"read_only": 1,
		"no_copy": 1,
		"hidden": 1,
	},
	{
		"fieldname": "stabler_sender_name",
		"label": "Sender",
		"fieldtype": "Data",
		"insert_after": "stabler_pickup_code",
		"read_only": 1,
		"no_copy": 1,
	},
	{
		"fieldname": "stabler_receiver_name",
		"label": "Receiver",
		"fieldtype": "Data",
		"insert_after": "stabler_sender_name",
		"read_only": 1,
		"no_copy": 1,
	},
]


def execute():
	todo = [
		f
		for f in _FIELDS
		if not frappe.db.exists("Custom Field", {"dt": "Journal Entry", "fieldname": f["fieldname"]})
	]
	if todo:
		create_custom_fields({"Journal Entry": todo}, ignore_validate=True)
