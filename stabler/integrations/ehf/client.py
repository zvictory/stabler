"""SoliqOnline REST client for signed EHF payloads.

POSTs `{payload, signature}` to `frappe.conf.soliq_endpoint` with a
bearer token from `frappe.conf.soliq_token`. Maps the response onto an
`EHFSubmission` row (status / soliq_uuid / error_message) and increments
`retry_count` on every send (success or failure) so dashboards can
distinguish a clean accept from one that needed N attempts.

Dev shortcut: when `frappe.conf.ehf_stub_signature` is truthy AND
`soliq_endpoint` is unset, we synthesize an Accepted response so the
end-to-end stub flow stays local.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frappe


def send(submission_name: str, payload: dict[str, Any], signature: str) -> dict[str, Any]:
	"""POST to SoliqOnline and persist the outcome onto EHFSubmission."""
	doc = frappe.get_doc("EHF Submission", submission_name)
	doc.retry_count = (doc.retry_count or 0) + 1
	doc.submitted_at = datetime.now()
	doc.soliq_status = "Submitted"
	doc.error_message = None

	conf = frappe.conf
	endpoint = getattr(conf, "soliq_endpoint", None)
	stub = int(getattr(conf, "ehf_stub_signature", 0) or 0)

	try:
		if not endpoint:
			if not stub:
				raise frappe.ValidationError(
					"SoliqOnline endpoint not configured. Set `soliq_endpoint`"
					" or enable `ehf_stub_signature` for development."
				)
			result = {"status": "Accepted", "uuid": f"STUB-{uuid.uuid4()}"}
		else:
			result = _post(endpoint, payload, signature, getattr(conf, "soliq_token", None))

		doc.soliq_status = _normalize_status(result.get("status"))
		doc.soliq_uuid = result.get("uuid") or result.get("id") or doc.soliq_uuid
		if doc.soliq_status == "Rejected":
			doc.error_message = result.get("reason") or json.dumps(result)
	except Exception as exc:  # noqa: BLE001 — funnel into EHFSubmission for ops visibility
		doc.soliq_status = "Error"
		doc.error_message = str(exc)
	finally:
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	return {
		"name": doc.name,
		"status": doc.soliq_status,
		"soliq_uuid": doc.soliq_uuid,
		"retry_count": doc.retry_count,
		"error_message": doc.error_message,
	}


def _normalize_status(value: Any) -> str:
	allowed = {"Pending", "Submitted", "Accepted", "Rejected", "Error"}
	if isinstance(value, str) and value in allowed:
		return value
	if isinstance(value, str):
		title = value.strip().title()
		if title in allowed:
			return title
	return "Submitted"


def _post(
	endpoint: str, payload: dict[str, Any], signature: str, token: str | None
) -> dict[str, Any]:
	body = json.dumps({"payload": payload, "signature": signature}, ensure_ascii=False).encode(
		"utf-8"
	)
	headers = {"Content-Type": "application/json", "Accept": "application/json"}
	if token:
		headers["Authorization"] = f"Bearer {token}"

	req = Request(endpoint, data=body, headers=headers, method="POST")
	try:
		with urlopen(req, timeout=20) as resp:
			text = resp.read().decode("utf-8")
	except HTTPError as e:
		raise frappe.ValidationError(f"SoliqOnline HTTP {e.code}: {e.reason}") from e
	except URLError as e:
		raise frappe.ValidationError(f"SoliqOnline unreachable: {e.reason}") from e

	try:
		return json.loads(text)
	except json.JSONDecodeError as e:
		raise frappe.ValidationError(f"SoliqOnline returned non-JSON: {text[:200]}") from e
