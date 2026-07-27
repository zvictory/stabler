"""Didox.uz REST client for already-signed EDO payloads.

Unlike ``ehf/client.py``, the signature here is produced entirely in the
user's browser via their own E-IMZO key (see ``public/js/lib/eimzo.js``) —
this module never signs anything, it only relays the signed PKCS#7 envelope
to Didox and persists the outcome onto a ``Didox Submission`` row.

POSTs `{payload, signature}` to `frappe.conf.didox_endpoint` with a bearer
token from `frappe.conf.didox_token`. Maps the response onto the submission
row (status / didox_doc_id / error_message) and increments `retry_count` on
every send (success or failure), matching the EHF client's accounting so
retries stay auditable.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frappe


def send(submission_name: str, payload: dict[str, Any], signed_pkcs7: str) -> dict[str, Any]:
	"""POST to Didox and persist the outcome onto Didox Submission."""
	conf = frappe.conf
	endpoint = getattr(conf, "didox_endpoint", None)

	# Validate deployment config BEFORE touching the row: a missing/plaintext
	# endpoint is an ops misconfiguration, not a real send attempt — recording
	# it as a failed try (retry_count++/submitted_at/status=Error) would pollute
	# the audit trail and leave the submission out of its recoverable "Signed"
	# state. The caller (submit.py) has already persisted status="Signed", so
	# throwing here keeps the signature retryable.
	if not endpoint:
		frappe.throw(
			"Didox endpoint not configured. Set `didox_endpoint` (and"
			" `didox_token`) in site_config.json before sending."
		)
	if not str(endpoint).lower().startswith("https://"):
		# Never transmit the bearer token over plaintext HTTP.
		frappe.throw("Didox endpoint must use HTTPS.")

	doc = frappe.get_doc("Didox Submission", submission_name)
	doc.retry_count = (doc.retry_count or 0) + 1
	doc.submitted_at = datetime.now()
	doc.status = "Sent"
	doc.error_message = None

	try:
		result = _post(endpoint, payload, signed_pkcs7, getattr(conf, "didox_token", None))

		doc.status = _normalize_status(result.get("status"))
		doc.didox_doc_id = result.get("doc_id") or result.get("id") or doc.didox_doc_id
		if doc.status == "Rejected":
			doc.error_message = result.get("reason") or json.dumps(result)
	except Exception as exc:  # funnel into Didox Submission for ops visibility
		doc.status = "Error"
		doc.error_message = str(exc)
	finally:
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	return {
		"name": doc.name,
		"status": doc.status,
		"didox_doc_id": doc.didox_doc_id,
		"retry_count": doc.retry_count,
		"error_message": doc.error_message,
	}


_TERMINAL_STATUSES = {"Accepted", "Rejected"}


def poll_status(submission_name: str) -> dict[str, Any]:
	"""GET the current Didox status for one submission and persist it.

	Read-only counterpart to :func:`send`: it fetches the counterparty-side
	state of an already-sent document (has the buyer signed/accepted/rejected
	the ЭСФ yet?) and folds it back onto the row. Unlike ``send`` this does
	**not** bump ``retry_count`` — a status poll is not a send attempt — and it
	never re-POSTs the signature, so it is safe to run on a schedule.

	No-ops when the submission is not yet ``Sent`` (nothing to poll) or is
	already in a terminal state (``Accepted``/``Rejected`` — a legally binding
	ЭСФ never flips back). Config problems throw rather than mutate the row,
	mirroring ``send``.
	"""
	doc = frappe.get_doc("Didox Submission", submission_name)

	if doc.status in _TERMINAL_STATUSES:
		return _poll_result(doc, changed=False)
	if doc.status != "Sent":
		# Draft/Signed = never left our side; Error = a send failure, not a
		# remote state we can poll. Only "Sent" has a live Didox counterpart.
		return _poll_result(doc, changed=False)
	if not doc.didox_doc_id:
		# Sent but no doc id means the send response never returned one —
		# nothing addressable to query.
		return _poll_result(doc, changed=False)

	conf = frappe.conf
	endpoint = getattr(conf, "didox_endpoint", None)
	if not endpoint:
		frappe.throw(
			"Didox endpoint not configured. Set `didox_endpoint` (and"
			" `didox_token`) in site_config.json before polling."
		)
	if not str(endpoint).lower().startswith("https://"):
		frappe.throw("Didox endpoint must use HTTPS.")

	before = doc.status
	try:
		result = _get_status(endpoint, doc.didox_doc_id, getattr(conf, "didox_token", None))
		doc.status = _normalize_status(result.get("status"))
		if doc.status == "Rejected":
			doc.error_message = result.get("reason") or json.dumps(result)
		elif doc.status in ("Accepted", "Sent"):
			doc.error_message = None
	except Exception as exc:  # surface poll failure on the row
		doc.status = "Error"
		doc.error_message = str(exc)

	changed = doc.status != before
	if changed:
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	return _poll_result(doc, changed=changed)


def _poll_result(doc: Any, changed: bool) -> dict[str, Any]:
	return {
		"name": doc.name,
		"status": doc.status,
		"didox_doc_id": doc.didox_doc_id,
		"error_message": doc.error_message,
		"changed": changed,
	}


def _normalize_status(value: Any) -> str:
	allowed = {"Draft", "Signed", "Sent", "Accepted", "Rejected", "Error"}
	if isinstance(value, str) and value in allowed:
		return value
	if isinstance(value, str):
		title = value.strip().title()
		if title in allowed:
			return title
	return "Sent"


def _post(
	endpoint: str, payload: dict[str, Any], signed_pkcs7: str, token: str | None
) -> dict[str, Any]:
	body = json.dumps(
		{"payload": payload, "signature": signed_pkcs7}, ensure_ascii=False
	).encode("utf-8")
	headers = {"Content-Type": "application/json", "Accept": "application/json"}
	if token:
		headers["Authorization"] = f"Bearer {token}"

	req = Request(endpoint, data=body, headers=headers, method="POST")
	try:
		with urlopen(req, timeout=20) as resp:
			text = resp.read().decode("utf-8")
	except HTTPError as e:
		raise frappe.ValidationError(f"Didox HTTP {e.code}: {e.reason}") from e
	except URLError as e:
		raise frappe.ValidationError(f"Didox unreachable: {e.reason}") from e

	try:
		return json.loads(text)
	except json.JSONDecodeError as e:
		raise frappe.ValidationError(f"Didox returned non-JSON: {text[:200]}") from e


def _get_status(endpoint: str, doc_id: str, token: str | None) -> dict[str, Any]:
	# Best-effort status URL pending real Didox partner docs (Faz 0/B0): query
	# the document by id under the configured base. When the real endpoint shape
	# lands, only this join needs adjusting — callers stay unchanged.
	url = f"{endpoint.rstrip('/')}/{doc_id}"
	headers = {"Accept": "application/json"}
	if token:
		headers["Authorization"] = f"Bearer {token}"

	req = Request(url, headers=headers, method="GET")
	try:
		with urlopen(req, timeout=20) as resp:
			text = resp.read().decode("utf-8")
	except HTTPError as e:
		raise frappe.ValidationError(f"Didox HTTP {e.code}: {e.reason}") from e
	except URLError as e:
		raise frappe.ValidationError(f"Didox unreachable: {e.reason}") from e

	try:
		return json.loads(text)
	except json.JSONDecodeError as e:
		raise frappe.ValidationError(f"Didox returned non-JSON: {text[:200]}") from e
