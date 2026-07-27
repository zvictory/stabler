"""Didox submission pipeline (browser-signed variant of ehf/submit.py).

Splits the EHF single-shot submit_for_invoice() into two steps because
signing happens in the browser, not on the server:

  prepare_for_invoice(name):
    1. Create a Didox Submission row (status=Draft) tied to the invoice.
    2. Build the unsigned payload (pure function) and store it on the row
       so the frontend can preview it before signing.
    Returns the submission name + unsigned payload for stabler.api.edo.didox_prepare.

  send_signed(submission_name, signed_pkcs7):
    3. Persist the signature the browser produced.
    4. POST to Didox and record the outcome.
    Called from stabler.api.edo.didox_send once the user has signed with
    their own E-IMZO key.

retry(submission_name) resends the already-signed payload stored on an
existing row — it cannot re-sign (the private key never left the browser),
so it only helps recover from a transient network/API failure after a
successful sign.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from stabler.integrations.didox.build_payload import build_payload
from stabler.integrations.didox.client import send


def prepare_for_invoice(name: str) -> dict[str, Any]:
	if not frappe.db.exists("Sales Invoice", name):
		frappe.logger().warning(f"[didox.submit] missing Sales Invoice {name}")
		return {"status": "skipped", "reason": "missing invoice"}

	payload = build_payload(name)

	submission = frappe.new_doc("Didox Submission")
	submission.reference_invoice = name
	submission.doc_type = "ESF"
	submission.status = "Draft"
	submission.payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
	submission.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"name": submission.name, "status": submission.status, "payload": payload}


def send_signed(submission_name: str, signed_pkcs7: str) -> dict[str, Any]:
	submission = frappe.get_doc("Didox Submission", submission_name)
	# A sent/accepted ЭСФ is a legally-binding tax document — never re-post it,
	# or Didox ends up with a duplicate for the same invoice.
	if submission.status in ("Sent", "Accepted"):
		frappe.throw(f"This document was already sent to Didox (status: {submission.status}).")
	payload = (
		json.loads(submission.payload_json)
		if submission.payload_json
		else build_payload(submission.reference_invoice)
	)

	submission.signature = signed_pkcs7
	submission.status = "Signed"
	submission.save(ignore_permissions=True)
	frappe.db.commit()

	return send(submission.name, payload, signed_pkcs7)


def retry(submission_name: str) -> dict[str, Any]:
	"""Resend an already-signed submission after a transient failure.

	Cannot re-sign — the E-IMZO private key lives only in the user's
	browser — so this only helps when send() itself failed (network,
	Didox downtime) after a successful sign.
	"""
	submission = frappe.get_doc("Didox Submission", submission_name)
	if not submission.signature:
		frappe.throw("Cannot retry an unsigned submission — sign it again via the SPA first.")
	if submission.status == "Accepted":
		frappe.throw("This document was already accepted by Didox — nothing to retry.")

	payload = (
		json.loads(submission.payload_json)
		if submission.payload_json
		else build_payload(submission.reference_invoice)
	)
	return send(submission.name, payload, submission.signature)
