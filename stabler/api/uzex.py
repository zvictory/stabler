"""UZEX SPA endpoints (WP-304).

Thin whitelisted surface over the read-only UZEX client so the Tender Intake
form can "paste a lot URL → autofill". No company argument: this reads public
portal data, not tenant rows — the guard is CRM Deal read permission (the same
right needed to create the intake it feeds).
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.integrations.uzex import client
from stabler.integrations.uzex._parse import lot_id_from_url, parse_uzex_dt, to_float


@frappe.whitelist()
def fetch_lot(lot: str) -> dict:
	"""Fetch one UZEX lot by pasted URL or id and shape it for the intake form.

	Returns the fields TenderIntake.vue prefills (lot_no, buyer, deadline,
	start_price, status) plus the canonical lot id + url. Raises on a bad id or an
	unreachable portal so the SPA can toast a real error.
	"""
	if not frappe.has_permission("CRM Deal", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	lot_id = lot_id_from_url(lot)
	if not lot_id:
		frappe.throw(_("Could not read a lot number from: {0}").format(lot))

	detail = client.get_trade(lot_id)
	if not detail:
		frappe.throw(_("UZEX lot {0} not found.").format(lot_id))

	return {
		"lot_id": lot_id,
		"url": f"https://etender.uzex.uz/lot/{lot_id}",
		"lot_no": str(detail.get("display_no") or "").strip(),
		"buyer": (detail.get("customer_name") or "").strip() or None,
		"bid_deadline": parse_uzex_dt(detail.get("end_date")),
		"start_price": to_float(detail.get("start_cost")),
		"status": (detail.get("status_name") or "").strip() or None,
		"type_name": (detail.get("type_name") or "").strip() or None,
	}
