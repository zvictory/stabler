"""Patch v33: staged remittance fields on Journal Entry (JE-only model).

The remittance module keeps its JE-only design (no dedicated doctype). To support
the register → payout → refund lifecycle with code-only pickup verification, each
stage JE carries:

  - stabler_remittance_id     groups the stage JEs of one transfer (REM-YYYY-#####)
  - stabler_remittance_stage  Register | Payout | Refund
  - stabler_pickup_code       secret set at Register, matched (never displayed) at Payout
  - stabler_sender_name       promoted from the free-text remark for querying
  - stabler_receiver_name     promoted from the free-text remark for querying

`stabler_pickup_code` sits at permlevel 1. It shipped at permlevel 0 behind
`hidden: 1`, which hides nothing from a reader: `frappe/model/meta.py` builds the
permitted field list from permlevel access and never consults `hidden`, so any
role with `read` on Journal Entry — Accounts User, Accounts Manager, Auditor, none
of which is a remittance role — could pull the value off `/api/resource`. Since
v86 that value is `scheme$salt$digest` over an 8-character draw from a 32-glyph
alphabet: a bounded offline crack whose plaintext is the bearer token for the cash.
v89 closed exactly this door on `Remittance Transfer.pickup_code_hash`; this is the
same secret's third name. Writes are unaffected — `create_remittance` inserts with
`ignore_permissions=True`, which returns from `validate_higher_perm_levels` before
it can silently reset the field, and the payout comparison reads the document
server-side, where field-level read permissions are not applied.

Idempotent: guarded by Custom Field existence. Because `execute()` skips fields
that already exist, editing the dict below does NOT change a site that already ran
this patch — `v91_je_pickup_code_permlevel` is what raises the permlevel there.
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
		# Not decoration. `hidden` is a form hint; this is the read gate. See the
		# module docstring — Journal Entry carries no permlevel-1 permission row, so
		# permlevel 1 means nobody but Administrator reads it through the API.
		"permlevel": 1,
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
