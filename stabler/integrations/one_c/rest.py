"""1C:Enterprise REST inbound poll (alternative to file-drop).

Polls `frappe.conf.onec_rest_endpoint` with `frappe.conf.onec_rest_token`.
Each poll requests changes since the last successful watermark
(persisted in Stabler Settings.onec_last_pulled_at) and applies the
same upsert logic as the file-drop path.

The endpoint contract is assumed to return:
  {"changes": [
     {"object_type": "Customer"|"Item"|...,
      "onec_guid": "...",
      "fields": { ... }},
     ...
   ],
   "next_watermark": "ISO-8601"}

Implemented as a pull-based reconciliation so an outage in either side
self-heals on the next poll without needing 1C-side replay.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frappe

from stabler.integrations.one_c._common import (
	lookup_by_guid,
	timed,
	upsert_external_ref,
	write_log,
)


def poll() -> dict[str, Any]:
	conf = frappe.conf
	endpoint = getattr(conf, "onec_rest_endpoint", None)
	if not endpoint:
		return {"status": "skipped", "reason": "onec_rest_endpoint not configured"}

	watermark = (
		frappe.db.get_single_value("Stabler Settings", "onec_last_pulled_at")
		if frappe.db.exists("DocType", "Stabler Settings")
		else None
	)
	url = endpoint
	if watermark:
		separator = "&" if "?" in endpoint else "?"
		url = f"{endpoint}{separator}since={watermark}"

	token = getattr(conf, "onec_rest_token", None)
	headers = {"Accept": "application/json"}
	if token:
		headers["Authorization"] = f"Bearer {token}"

	req = Request(url, headers=headers, method="GET")
	with timed() as box:
		try:
			with urlopen(req, timeout=20) as resp:
				body = resp.read().decode("utf-8")
		except HTTPError as e:
			write_log("In", "Customer", url, "Error", f"HTTP {e.code}: {e.reason}", duration_ms=box["ms"])
			return {"status": "error", "reason": str(e)}
		except URLError as e:
			write_log("In", "Customer", url, "Error", f"unreachable: {e.reason}", duration_ms=box["ms"])
			return {"status": "error", "reason": str(e)}

	try:
		data = json.loads(body)
	except json.JSONDecodeError as e:
		write_log("In", "Customer", url, "Error", f"bad JSON: {e}", payload=body[:1000])
		return {"status": "error", "reason": "bad JSON"}

	applied = 0
	for change in data.get("changes", []) or []:
		try:
			_apply_change(change)
			applied += 1
		except Exception as exc:  # noqa: BLE001
			write_log(
				"In",
				change.get("object_type") or "Customer",
				change.get("onec_guid") or "",
				"Error",
				str(exc),
				payload=change,
			)

	next_watermark = data.get("next_watermark")
	if next_watermark and frappe.db.exists("DocType", "Stabler Settings"):
		frappe.db.set_single_value("Stabler Settings", "onec_last_pulled_at", next_watermark)

	frappe.db.commit()
	return {"status": "ok", "applied": applied, "next_watermark": next_watermark}


def _apply_change(change: dict[str, Any]) -> None:
	object_type = change.get("object_type")
	guid = change.get("onec_guid")
	fields = change.get("fields") or {}
	if not (object_type and guid):
		raise frappe.ValidationError("change missing object_type or onec_guid")

	doctype = _map_doctype(object_type)
	existing = lookup_by_guid(object_type, guid)

	with timed() as box:
		if existing and frappe.db.exists(doctype, existing):
			doc = frappe.get_doc(doctype, existing)
			for key, value in fields.items():
				if hasattr(doc, key):
					setattr(doc, key, value)
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.new_doc(doctype)
			for key, value in fields.items():
				if hasattr(doc, key):
					setattr(doc, key, value)
			doc.insert(ignore_permissions=True)
		upsert_external_ref(object_type, doc.name, guid)
	write_log(
		"In",
		object_type,
		doc.name,
		"OK",
		message=f"REST sync at {datetime.now().isoformat()}",
		duration_ms=box["ms"],
	)


def _map_doctype(object_type: str) -> str:
	return {
		"Customer": "Customer",
		"Item": "Item",
		"PriceList": "Price List",
		"Warehouse": "Warehouse",
		"SalesInvoice": "Sales Invoice",
		"PaymentEntry": "Payment Entry",
		"StockEntry": "Stock Entry",
	}.get(object_type, object_type)
