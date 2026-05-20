"""Shared helpers for the 1C:Enterprise integration: ref lookup + log."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

import frappe


_VALID_TYPES = {
	"Customer",
	"Item",
	"PriceList",
	"Warehouse",
	"SalesInvoice",
	"PaymentEntry",
	"StockEntry",
}


def upsert_external_ref(doctype: str, name: str, onec_guid: str) -> None:
	"""Bind a Frappe (doctype, name) to a 1C GUID. Idempotent."""
	existing = frappe.db.get_value(
		"One C External Ref",
		{"onec_guid": onec_guid},
		["name", "doctype_ref", "name_ref"],
		as_dict=True,
	)
	if existing:
		if existing["doctype_ref"] == doctype and existing["name_ref"] == name:
			frappe.db.set_value("One C External Ref", existing["name"], "last_synced", datetime.now())
			return
		# GUID re-used for a new object — update the mapping.
		frappe.db.set_value(
			"One C External Ref",
			existing["name"],
			{"doctype_ref": doctype, "name_ref": name, "last_synced": datetime.now()},
		)
		return

	doc = frappe.new_doc("One C External Ref")
	doc.doctype_ref = doctype
	doc.name_ref = name
	doc.onec_guid = onec_guid
	doc.last_synced = datetime.now()
	doc.insert(ignore_permissions=True)


def lookup_by_guid(doctype: str, onec_guid: str) -> str | None:
	row = frappe.db.get_value(
		"One C External Ref",
		{"onec_guid": onec_guid, "doctype_ref": doctype},
		"name_ref",
	)
	return row or None


def write_log(
	direction: str,
	object_type: str,
	object_name: str,
	status: str,
	message: str = "",
	payload: Any = None,
	duration_ms: int = 0,
) -> str:
	doc = frappe.new_doc("One C Sync Log")
	doc.direction = direction
	doc.object_type = object_type if object_type in _VALID_TYPES else "Customer"
	doc.object_name = object_name or ""
	doc.status = status
	doc.duration_ms = int(duration_ms)
	doc.message = (message or "")[:2000]
	if payload is not None:
		doc.payload = (
			json.dumps(payload, ensure_ascii=False, indent=2, default=str)
			if not isinstance(payload, str)
			else payload
		)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


@contextmanager
def timed() -> Iterator[dict]:
	"""Context manager exposing elapsed ms via `box['ms']` on exit."""
	t0 = time.monotonic()
	box: dict = {"ms": 0}
	try:
		yield box
	finally:
		box["ms"] = int((time.monotonic() - t0) * 1000)
