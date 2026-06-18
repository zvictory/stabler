"""ARCA payment webhook handler.

Verifies HMAC SHA-256 over the raw request body using
`frappe.conf.arca_webhook_secret`, then idempotently materializes an
ARCAPaymentEvent + Payment Entry against the referenced Sales Invoice.

Idempotency: enforced by the UNIQUE index on
ARCAPaymentEvent.arca_transaction_id at the DB level. A repeat POST
returns 200 with `{processed: True, duplicate: True}` and no new
Payment Entry.

Endpoint: POST /api/method/stabler.integrations.arca.webhook.handle_payment_webhook
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit


_SIGNATURE_HEADER = "X-ARCA-Signature"


def _raw_body() -> bytes:
	# frappe.request is a werkzeug Request when called via web; .get_data
	# returns the raw bytes used by the HMAC verification on the sender side.
	req = getattr(frappe, "request", None)
	if req is None:
		return b""
	return req.get_data(cache=True, as_text=False) or b""


def _verify_signature(secret: str, body: bytes, signature: str) -> bool:
	if not signature:
		return False
	expected = hmac.new(
		secret.encode("utf-8"),
		body,
		hashlib.sha256,
	).hexdigest()
	# constant-time compare; also tolerate the "sha256=..." prefix some
	# gateways add.
	sent = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
	return hmac.compare_digest(expected, sent.strip())


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=600, seconds=60)
def handle_payment_webhook() -> dict[str, Any]:
	secret = getattr(frappe.conf, "arca_webhook_secret", None)
	if not secret:
		frappe.local.response.http_status_code = 503
		return {"ok": False, "reason": "arca_webhook_secret not configured"}

	body = _raw_body()
	signature = (
		frappe.get_request_header(_SIGNATURE_HEADER)
		or frappe.get_request_header(_SIGNATURE_HEADER.lower())
		or ""
	)
	if not _verify_signature(secret, body, signature):
		frappe.local.response.http_status_code = 401
		return {"ok": False, "reason": "invalid signature"}

	try:
		payload = json.loads(body.decode("utf-8") or "{}")
	except json.JSONDecodeError:
		frappe.local.response.http_status_code = 400
		return {"ok": False, "reason": "bad JSON"}

	txn_id = (payload.get("transaction_id") or payload.get("arca_transaction_id") or "").strip()
	invoice = (payload.get("sales_invoice") or payload.get("invoice") or "").strip()
	amount = payload.get("amount")
	if not (txn_id and invoice and amount is not None):
		frappe.local.response.http_status_code = 400
		return {"ok": False, "reason": "missing transaction_id / sales_invoice / amount"}

	existing = frappe.db.get_value(
		"ARCA Payment Event",
		{"arca_transaction_id": txn_id},
		["name", "processed", "payment_entry"],
		as_dict=True,
	)
	if existing:
		return {
			"ok": True,
			"duplicate": True,
			"event": existing["name"],
			"payment_entry": existing.get("payment_entry"),
			"processed": bool(existing.get("processed")),
		}

	event = frappe.new_doc("ARCA Payment Event")
	event.arca_transaction_id = txn_id
	event.sales_invoice = invoice
	event.amount = float(amount)
	event.received_at = datetime.now()
	event.payload = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
	event.processed = 0
	event.insert(ignore_permissions=True)

	try:
		pe_name = _create_payment_entry(invoice, float(amount), txn_id)
		event.payment_entry = pe_name
		event.processed = 1
		event.save(ignore_permissions=True)
		frappe.db.commit()
		return {"ok": True, "event": event.name, "payment_entry": pe_name, "processed": True}
	except Exception as exc:  # noqa: BLE001
		frappe.db.rollback()
		# preserve the event row; mark as un-processed so a Retry can re-link
		event.payload = (event.payload or "") + f"\n\n# error: {exc}"
		event.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.local.response.http_status_code = 500
		return {"ok": False, "event": event.name, "reason": str(exc)}


def _create_payment_entry(invoice: str, amount: float, reference: str) -> str:
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry("Sales Invoice", invoice)
	pe.paid_amount = amount
	pe.received_amount = amount
	pe.reference_no = reference
	pe.reference_date = datetime.now().date()
	for ref in pe.references or []:
		ref.allocated_amount = amount
	pe.insert(ignore_permissions=True)
	# Bank-initiated (ARCA) auto-reconciliation — no human maker, so it
	# bypasses the maker-checker approval gate.
	pe.flags.ignore_approval_gate = True
	pe.submit()
	return pe.name
