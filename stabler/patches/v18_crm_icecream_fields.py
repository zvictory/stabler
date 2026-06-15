"""Ice-cream (FMCG) CRM Deal extensions.

Adds the outlet-acquisition fields to CRM Deal (recurring monthly volume,
freezer, credit, region/route, outlet type, win/loss reason, linked customer)
and seeds the FMCG pipeline stages. All operations are idempotent:
`create_custom_field` upserts, and statuses are created only when missing and
appended after the existing columns so an operator's current board is undisturbed.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

_FIELDS = [
	{
		"fieldname": "outlet_type",
		"label": "Outlet Type",
		"fieldtype": "Select",
		"options": "\nShop\nSupermarket\nKiosk\nHoReCa\nDistributor\nWholesaler",
		"insert_after": "deal_value",
	},
	{
		"fieldname": "region",
		"label": "Region / Route",
		"fieldtype": "Data",
		"insert_after": "outlet_type",
		"description": "Sales route / territory this outlet belongs to.",
	},
	{
		"fieldname": "expected_monthly_volume",
		"label": "Expected Monthly Volume",
		"fieldtype": "Currency",
		"insert_after": "region",
		"description": "Recurring monthly run-rate (UZS) — the pipeline forecast metric.",
	},
	{
		"fieldname": "expected_cases_week",
		"label": "Cases / Week",
		"fieldtype": "Int",
		"insert_after": "expected_monthly_volume",
	},
	{
		"fieldname": "price_tier",
		"label": "Price Tier",
		"fieldtype": "Select",
		"options": "\nWholesale\nRetail\nHoReCa",
		"insert_after": "expected_cases_week",
	},
	{
		"fieldname": "needs_freezer",
		"label": "Needs Freezer",
		"fieldtype": "Check",
		"insert_after": "price_tier",
	},
	{
		"fieldname": "freezer_asset",
		"label": "Placed Freezer",
		"fieldtype": "Link",
		"options": "Asset",
		"insert_after": "needs_freezer",
		"description": "Branded freezer placed at this outlet (set once installed).",
	},
	{
		"fieldname": "credit_terms_days",
		"label": "Credit Terms (days)",
		"fieldtype": "Int",
		"insert_after": "freezer_asset",
	},
	{
		"fieldname": "win_loss_reason",
		"label": "Win/Loss Reason",
		"fieldtype": "Select",
		"options": "\nNo freezer space\nCompetitor exclusivity\nCredit terms\nPrice\nQuality\nOther",
		"insert_after": "credit_terms_days",
	},
	{
		"fieldname": "linked_customer",
		"label": "Customer",
		"fieldtype": "Link",
		"options": "Customer",
		"insert_after": "win_loss_reason",
		"description": "Customer created/linked when the deal is Won.",
	},
]

# (name, color, type). type is best-effort; if the CRM build rejects the value
# we retry without it so migrate never aborts.
_STAGES = [
	("New", "gray", "Ongoing"),
	("Contacted", "blue", "Ongoing"),
	("Sampling", "cyan", "Ongoing"),
	("Terms", "yellow", "Ongoing"),
	("Won", "green", "Won"),
	("Active", "teal", "Ongoing"),
	("At-risk", "orange", "Ongoing"),
	("Reactivation", "purple", "Ongoing"),
	("Lost", "red", "Lost"),
]


def _seed_stages() -> None:
	if not frappe.db.exists("DocType", "CRM Deal Status"):
		return
	existing = {s.lower() for s in frappe.get_all("CRM Deal Status", pluck="name")}
	base = (frappe.db.sql("SELECT COALESCE(MAX(position), 0) FROM `tabCRM Deal Status`") or [[0]])[0][0] or 0
	pos = int(base)
	for name, color, type_ in _STAGES:
		if name.lower() in existing:
			continue
		pos += 1
		# Mirror the proven shape used by api.crm.save_deal_status.
		payload = {"doctype": "CRM Deal Status", "name": name, "color": color, "position": pos, "type": type_}
		try:
			doc = frappe.new_doc("CRM Deal Status")
			doc.update(payload)
			doc.insert(ignore_permissions=True)
		except Exception:
			payload.pop("type", None)
			try:
				doc = frappe.new_doc("CRM Deal Status")
				doc.update(payload)
				doc.insert(ignore_permissions=True)
			except Exception:
				frappe.clear_last_message()


def execute() -> None:
	if not frappe.db.exists("DocType", "CRM Deal"):
		return
	for field in _FIELDS:
		create_custom_field("CRM Deal", field)
	_seed_stages()
	frappe.db.commit()
