"""1C:Enterprise CommerceML file-drop inbound sync.

Watches `frappe.conf.onec_inbox` for *.xml files and upserts Customer /
Item / PriceList / Warehouse using each element's GUID for cross-system
identity (mapped via `1C External Ref`). Processed files are moved into
`<onec_inbox>/processed/` so re-runs are idempotent.

Each file produces one `1C Sync Log` row per object (direction=In).
Parse errors are logged but don't abort the entire batch — one bad file
shouldn't lock out the rest of the queue.

Called from hooks.py scheduler_events.hourly via `scan()`.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import frappe

from stabler.integrations.one_c._common import lookup_by_guid, timed, upsert_external_ref, write_log

# Permissive: CommerceML uses several namespace variants depending on the 1C
# config version. We strip namespaces at parse time rather than enumerate.
_OBJECT_TAGS = {
	"Контрагент": ("Customer", "_upsert_customer"),
	"Counterparty": ("Customer", "_upsert_customer"),
	"Товар": ("Item", "_upsert_item"),
	"Product": ("Item", "_upsert_item"),
	"Склад": ("Warehouse", "_upsert_warehouse"),
	"Warehouse": ("Warehouse", "_upsert_warehouse"),
	"ТипЦен": ("PriceList", "_upsert_price_list"),
	"PriceType": ("PriceList", "_upsert_price_list"),
}


def scan() -> dict[str, Any]:
	inbox = getattr(frappe.conf, "onec_inbox", None)
	if not inbox:
		return {"status": "skipped", "reason": "onec_inbox not configured"}

	root = Path(inbox)
	if not root.exists():
		return {"status": "skipped", "reason": f"inbox missing: {inbox}"}

	processed_dir = root / "processed"
	processed_dir.mkdir(exist_ok=True)

	processed = 0
	errors: list[dict] = []
	for path in sorted(root.glob("*.xml")):
		try:
			process_file(path)
			shutil.move(str(path), str(processed_dir / path.name))
			processed += 1
		except Exception as exc:
			errors.append({"file": path.name, "error": str(exc)})
			write_log(
				direction="In",
				object_type="Customer",  # placeholder; the file didn't classify
				object_name=path.name,
				status="Error",
				message=str(exc),
			)
	return {"status": "ok", "processed": processed, "errors": errors}


def process_file(path: Path) -> None:
	tree = ET.parse(path)
	root = tree.getroot()
	_strip_namespaces(root)
	for element in root.iter():
		handler_info = _OBJECT_TAGS.get(element.tag)
		if not handler_info:
			continue
		object_type, handler_name = handler_info
		handler = globals().get(handler_name)
		if not handler:
			continue
		with timed() as box:
			try:
				name = handler(element)
				write_log(
					direction="In",
					object_type=object_type,
					object_name=name or "",
					status="OK",
					message=f"from {path.name}",
					duration_ms=box["ms"],
				)
			except Exception as exc:
				write_log(
					direction="In",
					object_type=object_type,
					object_name=_text(element, "Наименование") or _text(element, "Name") or "",
					status="Error",
					message=str(exc),
					payload=ET.tostring(element, encoding="unicode"),
					duration_ms=box["ms"],
				)


def _strip_namespaces(elem: ET.Element) -> None:
	for el in elem.iter():
		if "}" in el.tag:
			el.tag = el.tag.split("}", 1)[1]


def _text(element: ET.Element, tag: str) -> str | None:
	child = element.find(tag)
	return child.text.strip() if child is not None and child.text else None


def _guid(element: ET.Element) -> str | None:
	return _text(element, "Ид") or _text(element, "Id") or _text(element, "Guid")


def _upsert_customer(element: ET.Element) -> str | None:
	guid = _guid(element)
	if not guid:
		return None
	customer_name = _text(element, "Наименование") or _text(element, "Name") or f"1C {guid}"
	tax_id = _text(element, "ИНН") or _text(element, "TaxId")

	existing = lookup_by_guid("Customer", guid)
	if existing and frappe.db.exists("Customer", existing):
		doc = frappe.get_doc("Customer", existing)
		doc.customer_name = customer_name
		if tax_id:
			doc.tax_id = tax_id
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("Customer")
		doc.customer_name = customer_name
		doc.customer_type = "Company"
		doc.customer_group = (
			frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
		)
		doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
		if tax_id:
			doc.tax_id = tax_id
		doc.insert(ignore_permissions=True)
	upsert_external_ref("Customer", doc.name, guid)
	return doc.name


def _upsert_item(element: ET.Element) -> str | None:
	guid = _guid(element)
	if not guid:
		return None
	item_name = _text(element, "Наименование") or _text(element, "Name") or f"1C {guid}"
	item_code = _text(element, "Артикул") or _text(element, "Code") or item_name

	existing = lookup_by_guid("Item", guid)
	if existing and frappe.db.exists("Item", existing):
		doc = frappe.get_doc("Item", existing)
		doc.item_name = item_name
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("Item")
		doc.item_code = item_code
		doc.item_name = item_name
		doc.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
		doc.stock_uom = frappe.db.get_value("UOM", {"name": "Nos"}, "name") or "Nos"
		doc.insert(ignore_permissions=True)
	upsert_external_ref("Item", doc.name, guid)
	return doc.name


def _upsert_price_list(element: ET.Element) -> str | None:
	guid = _guid(element)
	if not guid:
		return None
	pl_name = _text(element, "Наименование") or _text(element, "Name") or f"1C {guid}"

	existing = lookup_by_guid("PriceList", guid)
	if existing and frappe.db.exists("Price List", existing):
		return existing
	if frappe.db.exists("Price List", pl_name):
		upsert_external_ref("PriceList", pl_name, guid)
		return pl_name
	doc = frappe.new_doc("Price List")
	doc.price_list_name = pl_name
	doc.currency = "UZS"
	doc.selling = 1
	doc.insert(ignore_permissions=True)
	upsert_external_ref("PriceList", doc.name, guid)
	return doc.name


def _upsert_warehouse(element: ET.Element) -> str | None:
	guid = _guid(element)
	if not guid:
		return None
	wh_name = _text(element, "Наименование") or _text(element, "Name") or f"1C {guid}"

	existing = lookup_by_guid("Warehouse", guid)
	if existing and frappe.db.exists("Warehouse", existing):
		return existing
	if frappe.db.exists("Warehouse", wh_name):
		upsert_external_ref("Warehouse", wh_name, guid)
		return wh_name

	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		raise frappe.ValidationError("No Company configured; cannot create Warehouse from 1C feed")
	doc = frappe.new_doc("Warehouse")
	doc.warehouse_name = wh_name
	doc.company = company
	doc.insert(ignore_permissions=True)
	upsert_external_ref("Warehouse", doc.name, guid)
	return doc.name
