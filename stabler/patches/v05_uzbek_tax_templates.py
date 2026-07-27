"""Uzbek NDS 12% tax plumbing.

For each existing Company, ensure two Sales Taxes and Charges Templates
exist (created with the company's `abbr` suffix per ERPNext naming):
  - "Uzbekistan NDS 12% - <ABBR>"     → 12% VAT line on Net Total
  - "Uzbekistan NDS Exempt - <ABBR>"  → empty taxes table (reverse-charge)

Also bootstraps a Custom Field on Customer: `is_tax_exempt` (Check).

Idempotent:
  - Templates: skipped if a row with the same `name` already exists.
  - Custom Field: `create_custom_fields(update=True)` upserts.
  - Tax-account discovery: walks a short list of conventional names, then
    falls back to any `account_type=Tax` leaf under the Company. If nothing
    is found, that Company is logged and skipped (no half-built template).
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

_NDS_RATE = 12.0


def _find_tax_account(company: str, abbr: str) -> str | None:
	for candidate in (
		f"VAT - {abbr}",
		f"NDS - {abbr}",
		f"NDS 12% - {abbr}",
		f"Output VAT - {abbr}",
	):
		if frappe.db.exists("Account", candidate):
			return candidate
	leaf = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": "Tax", "is_group": 0, "disabled": 0},
		fields=["name"],
		limit=1,
	)
	return leaf[0]["name"] if leaf else None


def _ensure_template(
	title: str,
	company: str,
	abbr: str,
	tax_account: str | None,
	rate: float,
) -> None:
	template_name = f"{title} - {abbr}"
	if frappe.db.exists("Sales Taxes and Charges Template", template_name):
		return

	doc = frappe.new_doc("Sales Taxes and Charges Template")
	doc.title = title
	doc.company = company
	doc.disabled = 0
	if rate > 0 and tax_account:
		doc.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": tax_account,
				"description": f"NDS {rate:g}%",
				"rate": rate,
				"included_in_print_rate": 0,
			},
		)
	doc.insert(ignore_permissions=True)


def execute():
	if not frappe.db.exists("DocType", "Sales Taxes and Charges Template"):
		return

	create_custom_fields(
		{
			"Customer": [
				{
					"fieldname": "is_tax_exempt",
					"label": "Tax Exempt (Uzbekistan NDS)",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "tax_id",
					"description": (
						"If checked, sales transactions for this customer default to"
						" the Uzbekistan NDS Exempt template instead of NDS 12%."
					),
				}
			]
		},
		update=True,
	)

	for company in frappe.get_all("Company", fields=["name", "abbr"]):
		tax_account = _find_tax_account(company["name"], company["abbr"])
		if not tax_account:
			frappe.logger().warning(
				f"[v05_uzbek_tax_templates] No tax account for {company['name']};"
				" skipping NDS template creation."
			)
			continue
		_ensure_template("Uzbekistan NDS 12%", company["name"], company["abbr"], tax_account, _NDS_RATE)
		_ensure_template("Uzbekistan NDS Exempt", company["name"], company["abbr"], None, 0.0)

	frappe.db.commit()
