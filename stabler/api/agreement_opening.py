"""Safe preview endpoint for agreement-level opening receivables imports.

The preview deliberately has no insert/update/submit calls. Posting opening
balances is a separate, explicitly approved operation after customer and
Contract mapping has been reviewed.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate

from stabler.api._common import _require_company
from stabler.api.approvals import _assert_company_scope
from stabler.api.organization import module_map_for


OPENING_DATE = "2026-07-20"


def _rows(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except json.JSONDecodeError as exc:
			frappe.throw(_("Invalid opening balance rows JSON: {0}").format(exc))
	if not isinstance(value, list):
		frappe.throw(_("Opening balance rows must be a list."), frappe.ValidationError)
	return value


@frappe.whitelist()
def preview_agreement_opening(
	company: str,
	rows,
	as_of_date: str = OPENING_DATE,
	currency: str = "UZS",
) -> dict:
	"""Validate Excel-normalized rows without creating financial documents."""
	_require_company(company)
	_assert_company_scope(company)
	if not module_map_for(company).get("agreements"):
		frappe.throw(_("Agreement management is not enabled for {0}.").format(company), frappe.PermissionError)
	if currency.upper() != "UZS":
		frappe.throw(_("Opening balance preview currently requires UZS."), frappe.ValidationError)
	if str(getdate(as_of_date)) != OPENING_DATE:
		frappe.throw(_("Opening balance date must be {0}.").format(OPENING_DATE), frappe.ValidationError)
	if not frappe.has_permission("Customer", "read") or not frappe.has_permission("Contract", "read"):
		frappe.throw(_("You are not permitted to preview agreement balances."), frappe.PermissionError)

	contract_no_field = frappe.db.has_column("Contract", "custom_agreement_no")
	items = []
	missing_customers = set()
	missing_agreements = set()
	total = 0.0
	for index, raw in enumerate(_rows(rows), start=1):
		if not isinstance(raw, dict):
			frappe.throw(_("Row {0} must be an object.").format(index), frappe.ValidationError)
		organization = str(raw.get("organization") or raw.get("customer") or "").strip()
		agreement = str(raw.get("agreement") or "").strip()
		amount = flt(raw.get("amount"))
		if not organization:
			frappe.throw(_("Row {0} requires organization.").format(index), frappe.ValidationError)
		customer = frappe.db.get_value(
			"Customer", {"customer_name": organization, "disabled": 0}, ["name", "customer_name"], as_dict=True
		)
		if not customer:
			customer = frappe.db.get_value("Customer", {"name": organization, "disabled": 0}, ["name", "customer_name"], as_dict=True)
		if not customer:
			missing_customers.add(organization)

		contract = None
		if agreement and frappe.db.exists("Contract", agreement):
			contract = frappe.db.get_value("Contract", agreement, ["name", "party_name"], as_dict=True)
		elif agreement and contract_no_field:
			contract = frappe.db.get_value(
				"Contract", {"custom_agreement_no": agreement}, ["name", "party_name"], as_dict=True
			)
		if not contract:
			missing_agreements.add(agreement or "<blank agreement>")
		elif customer and contract.party_name and contract.party_name != customer.name:
			missing_agreements.add(agreement)

		status = "ready" if customer and contract and agreement not in missing_agreements else "needs_mapping"
		items.append({
			"row": index,
			"organization": organization,
			"agreement": agreement,
			"amount": amount,
			"currency": "UZS",
			"as_of_date": OPENING_DATE,
			"customer": customer.name if customer else None,
			"contract": contract.name if contract else None,
			"status": status,
		})
		total += amount

	return {
		"company": company,
		"currency": "UZS",
		"as_of_date": OPENING_DATE,
		"financial_mutation": False,
		"row_count": len(items),
		"total": flt(total),
		"ready_count": sum(1 for item in items if item["status"] == "ready"),
		"needs_mapping_count": sum(1 for item in items if item["status"] != "ready"),
		"missing_customers": sorted(missing_customers),
		"missing_agreements": sorted(missing_agreements),
		"rows": items,
	}
