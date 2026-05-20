"""Serialize a Sales Invoice to the SoliqOnline EHF JSON envelope.

Pure function — no I/O, no global state. Easy to unit-test by constructing
a frappe.get_doc("Sales Invoice", name) and asserting on the dict shape.

The schema here is a representative shape: SoliqOnline (and the EIMZO
wrapper) expects a header block with seller/buyer TINs, line items, and
tax rollups. Production deployments will likely need to adjust field
names and add facsimile fields per the per-vendor EHF spec, but the
mapping from ERPNext concepts → EHF concepts is captured here.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt


def build_payload(sales_invoice_name: str) -> dict[str, Any]:
	si = frappe.get_doc("Sales Invoice", sales_invoice_name)
	company_tin = frappe.db.get_value("Company", si.company, "tax_id") or ""
	customer_tin = frappe.db.get_value("Customer", si.customer, "tax_id") or si.tax_id or ""

	items: list[dict[str, Any]] = []
	for row in si.items or []:
		items.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"uom": row.uom,
				"rate": flt(row.rate),
				"amount": flt(row.amount),
				"net_amount": flt(row.net_amount),
			}
		)

	taxes: list[dict[str, Any]] = []
	for row in si.taxes or []:
		taxes.append(
			{
				"description": row.description,
				"rate": flt(row.rate),
				"tax_amount": flt(row.tax_amount),
				"total": flt(row.total),
			}
		)

	return {
		"invoice_no": si.name,
		"posting_date": str(si.posting_date) if si.posting_date else None,
		"due_date": str(si.due_date) if si.due_date else None,
		"currency": si.currency,
		"conversion_rate": flt(si.conversion_rate),
		"seller": {
			"company": si.company,
			"tin": company_tin,
		},
		"buyer": {
			"customer": si.customer,
			"customer_name": si.customer_name,
			"tin": customer_tin,
		},
		"items": items,
		"taxes": taxes,
		"totals": {
			"net_total": flt(si.net_total),
			"total_taxes_and_charges": flt(si.total_taxes_and_charges),
			"grand_total": flt(si.grand_total),
		},
	}
