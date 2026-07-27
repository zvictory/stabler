"""Exchange-rate staleness controls on Accounts Settings.

The Posting Window admin page and validate_exchange_rate both rely on two
settings that gate back-dated multi-currency entries:
  - allow_stale — bypass the "CBU rate must be within N days" check entirely.
  - stale_days  — widen the default 3-day staleness window.

These are stored on Accounts Settings. Add them as custom fields so the admin
toggle persists and the validator can read real values. Idempotent + pre-sync
safe (only Custom Field metadata).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields = []

	def add(spec):
		if not frappe.db.exists("Custom Field", {"dt": "Accounts Settings", "fieldname": spec["fieldname"]}):
			fields.append(spec)

	add(
		{
			"fieldname": "allow_stale",
			"label": "Allow Stale Exchange Rate",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "frozen_accounts_modifier",
			"description": "Bypass the CBU staleness check for back-dated multi-currency entries.",
		}
	)
	add(
		{
			"fieldname": "stale_days",
			"label": "Exchange Rate Staleness Window (days)",
			"fieldtype": "Int",
			"default": "3",
			"insert_after": "allow_stale",
			"description": "Max age (days) of the nearest CBU rate before an entry is blocked. 0 = use default (3).",
		}
	)

	if fields:
		create_custom_fields({"Accounts Settings": fields}, ignore_validate=True)
