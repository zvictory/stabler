"""Cash/bank payment earmark on Commercial Invoice (WP-I3b).

The real agreement (`agreed_total`) is split by HOW it will be settled:
  custom_bank_agreed — the portion paid from a Bank account (official),
  custom_cash_agreed — the portion paid from the Cash (Kassa) account.
Both are fully financial (every kuruş hits GL, just from different asset
accounts). Identity: custom_bank_agreed + custom_cash_agreed == agreed_total.

`docs_total` stays a customs-only figure and is unrelated to this split.

Cost-sensitive → permlevel 1 (same as docs_total / cash_difference), so only
cost-visible roles see/edit them. Listed under [post_model_sync]. Idempotent:
sentinel Custom Field guard.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Commercial Invoice"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Commercial Invoice", "fieldname": "custom_bank_agreed"}):
		return

	after = "agreed_total" if frappe.db.has_column("Commercial Invoice", "agreed_total") else "supplier"
	create_custom_fields(
		{
			"Commercial Invoice": [
				{
					"fieldname": "custom_bank_agreed",
					"label": "Bank Agreed",
					"fieldtype": "Currency",
					"options": "currency",
					"insert_after": after,
					"permlevel": 1,
					"description": "Portion of agreed_total settled from a Bank account (official).",
				},
				{
					"fieldname": "custom_cash_agreed",
					"label": "Cash Agreed",
					"fieldtype": "Currency",
					"options": "currency",
					"insert_after": "custom_bank_agreed",
					"permlevel": 1,
					"description": "Portion of agreed_total settled from the Cash (Kassa) account.",
				},
			]
		},
		ignore_validate=True,
	)
