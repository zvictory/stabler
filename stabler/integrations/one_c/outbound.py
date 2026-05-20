"""1C:Enterprise outbound push.

Serializes a Frappe doc (Sales Invoice / Payment Entry / Stock Entry) and
emits it to 1C via REST (`frappe.conf.onec_rest_endpoint`) OR file-drop
(`frappe.conf.onec_outbox`), depending on Stabler Settings.onec_mode.

Wired from hooks.py doc_events on_submit → enqueue (queue="long"), so a
1C outage never blocks a Frappe submission.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frappe

from stabler.integrations.one_c._common import timed, upsert_external_ref, write_log


_OBJECT_TYPE_MAP = {
	"Sales Invoice": "SalesInvoice",
	"Payment Entry": "PaymentEntry",
	"Stock Entry": "StockEntry",
}


def push(doctype: str, name: str) -> dict[str, Any]:
	"""Push a Frappe doc to 1C. Idempotent on (doctype, name)."""
	object_type = _OBJECT_TYPE_MAP.get(doctype, doctype.replace(" ", ""))
	mode = (
		frappe.db.get_single_value("Stabler Settings", "onec_mode")
		if frappe.db.exists("DocType", "Stabler Settings")
		else "file"
	) or "file"

	try:
		payload = _serialize(doctype, name)
	except Exception as exc:  # noqa: BLE001
		write_log("Out", object_type, name, "Error", f"serialize failed: {exc}")
		return {"status": "error", "reason": str(exc)}

	with timed() as box:
		if mode == "rest":
			result = _push_rest(payload)
		else:
			result = _push_file(doctype, name, payload)

	status = "OK" if result.get("ok") else "Error"
	write_log(
		"Out",
		object_type,
		name,
		status,
		message=result.get("message", ""),
		payload=payload,
		duration_ms=box["ms"],
	)
	if result.get("ok") and result.get("onec_guid"):
		upsert_external_ref(object_type, name, result["onec_guid"])
	return result


def _serialize(doctype: str, name: str) -> dict[str, Any]:
	doc = frappe.get_doc(doctype, name)
	return {
		"object_type": _OBJECT_TYPE_MAP.get(doctype, doctype),
		"name": doc.name,
		"docstatus": doc.docstatus,
		"timestamp": datetime.now().isoformat(),
		"data": doc.as_dict(no_nulls=True),
	}


def _push_rest(payload: dict[str, Any]) -> dict[str, Any]:
	endpoint = getattr(frappe.conf, "onec_rest_endpoint", None)
	if not endpoint:
		return {"ok": False, "message": "onec_rest_endpoint not configured"}

	headers = {"Content-Type": "application/json", "Accept": "application/json"}
	token = getattr(frappe.conf, "onec_rest_token", None)
	if token:
		headers["Authorization"] = f"Bearer {token}"

	body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
	req = Request(endpoint, data=body, headers=headers, method="POST")
	try:
		with urlopen(req, timeout=20) as resp:
			data = json.loads(resp.read().decode("utf-8") or "{}")
	except HTTPError as e:
		return {"ok": False, "message": f"HTTP {e.code}: {e.reason}"}
	except URLError as e:
		return {"ok": False, "message": f"unreachable: {e.reason}"}
	except json.JSONDecodeError:
		return {"ok": True, "message": "posted (non-JSON response)"}
	return {
		"ok": True,
		"message": data.get("message", "posted"),
		"onec_guid": data.get("onec_guid"),
	}


def _push_file(doctype: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
	outbox = getattr(frappe.conf, "onec_outbox", None)
	if not outbox:
		return {"ok": False, "message": "onec_outbox not configured"}

	root = Path(outbox)
	root.mkdir(parents=True, exist_ok=True)
	safe_name = name.replace("/", "_").replace(" ", "_")
	target = root / f"{doctype.replace(' ', '_')}-{safe_name}.json"
	target.write_text(
		json.dumps(payload, ensure_ascii=False, indent=2, default=str),
		encoding="utf-8",
	)
	return {"ok": True, "message": f"written to {target.name}"}
