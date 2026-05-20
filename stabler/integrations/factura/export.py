"""Factura.uz outbound stub.

Writes a minimal placeholder XML per Sales Invoice into
`frappe.conf.factura_outbox`. Full schema lands in Phase 1; here we only
prove the gating + hook wiring.

Gated by Stabler Settings.factura_export_enabled — when 0, the export
is a no-op (returns skipped).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import frappe


def _enabled() -> bool:
	if not frappe.db.exists("DocType", "Stabler Settings"):
		return False
	return bool(frappe.db.get_single_value("Stabler Settings", "factura_export_enabled"))


def export_invoice(name: str) -> dict[str, Any]:
	if not _enabled():
		return {"status": "skipped", "reason": "factura_export_enabled is off"}

	outbox = getattr(frappe.conf, "factura_outbox", None)
	if not outbox:
		return {"status": "skipped", "reason": "factura_outbox not configured"}

	doc = frappe.get_doc("Sales Invoice", name)
	root = ET.Element("FacturaInvoice")
	ET.SubElement(root, "Name").text = doc.name
	ET.SubElement(root, "Customer").text = doc.customer
	ET.SubElement(root, "PostingDate").text = str(doc.posting_date)
	ET.SubElement(root, "GrandTotal").text = str(doc.grand_total or 0)
	ET.SubElement(root, "Currency").text = doc.currency or ""

	path = Path(outbox)
	path.mkdir(parents=True, exist_ok=True)
	target = path / f"{doc.name.replace('/', '_')}.xml"
	ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
	return {"status": "ok", "path": str(target)}


def enqueue_export(doc, method=None) -> None:
	if getattr(doc, "docstatus", 0) != 1:
		return
	if not _enabled():
		return
	frappe.enqueue(
		"stabler.integrations.factura.export.export_invoice",
		queue="long",
		name=doc.name,
	)
