"""Factura.uz inbound stub.

Parses a placeholder XML at `path` and upserts a draft Purchase Invoice
with header fields only. Full schema lands in Phase 1.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import frappe


def import_invoice(path: str) -> dict[str, Any]:
	p = Path(path)
	if not p.exists():
		return {"status": "error", "reason": f"missing file: {path}"}

	try:
		root = ET.parse(p).getroot()
	except ET.ParseError as exc:
		return {"status": "error", "reason": f"bad XML: {exc}"}

	supplier = _text(root, "Supplier") or _text(root, "Customer")
	posting_date = _text(root, "PostingDate")
	grand_total = _text(root, "GrandTotal")
	if not supplier:
		return {"status": "error", "reason": "missing Supplier"}

	if not frappe.db.exists("Supplier", supplier):
		return {"status": "error", "reason": f"unknown Supplier: {supplier}"}

	doc = frappe.new_doc("Purchase Invoice")
	doc.supplier = supplier
	if posting_date:
		doc.set_posting_time = 1
		doc.posting_date = posting_date
	# Header-only stub — full line items in Phase 1.
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "ok", "purchase_invoice": doc.name, "grand_total_seen": grand_total}


def _text(element: ET.Element, tag: str) -> str | None:
	child = element.find(tag)
	return child.text.strip() if child is not None and child.text else None
