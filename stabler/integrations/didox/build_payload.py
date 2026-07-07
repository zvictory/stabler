"""Serialize a Sales Invoice to the Didox.uz EDO (ЭСФ) JSON envelope.

Didox is a separate EDO operator from SoliqOnline (see ``integrations/ehf``);
this module builds the invoice payload their partner API expects. The exact
field names are best-effort pending confirmed Didox partner API docs (see
Faz 0 in the Didox integration plan) — adjust once a real sandbox response
is available to diff against.

Unlike ``ehf/build_payload.py``, this payload is never signed on the server:
it is sent to the browser unsigned, signed there via the user's own E-IMZO
key (PKCS#7), and only the signed envelope + signature travel back through
``stabler.api.edo.didox_send``.
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
		ikpu_code = frappe.db.get_value("Item", row.item_code, "custom_ikpu_code") or ""
		items.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"ikpu_code": ikpu_code,
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
		"doc_type": "002",  # ЭСФ (hisob-faktura)
		"invoice_no": si.name,
		"posting_date": str(si.posting_date) if si.posting_date else None,
		"due_date": str(si.due_date) if si.due_date else None,
		"currency": si.currency,
		"conversion_rate": flt(si.conversion_rate),
		"seller": {"company": si.company, "tin": company_tin},
		"buyer": {"customer": si.customer, "customer_name": si.customer_name, "tin": customer_tin},
		"items": items,
		"taxes": taxes,
		"totals": {
			"net_total": flt(si.net_total),
			"total_taxes_and_charges": flt(si.total_taxes_and_charges),
			"grand_total": flt(si.grand_total),
		},
	}
