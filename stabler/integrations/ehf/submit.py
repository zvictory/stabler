"""End-to-end EHF submission pipeline.

submit_for_invoice(name):
  1. Build EHFSubmission row tied to the Sales Invoice (status=Pending).
  2. Build payload (pure function).
  3. Sign via EIMZO (stub or real per frappe.conf.ehf_stub_signature).
  4. POST to SoliqOnline and persist response onto the row.

Called from hooks.py via frappe.enqueue on Sales Invoice.on_submit so the
SI submit transaction never blocks on an external network call.

Safe to call multiple times for the same invoice — every call creates a
fresh EHFSubmission row, which preserves an audit trail of retries.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from stabler.integrations.ehf.build_payload import build_payload
from stabler.integrations.ehf.client import send
from stabler.integrations.ehf.sign import sign


def submit_for_invoice(name: str) -> dict[str, Any]:
	if not frappe.db.exists("Sales Invoice", name):
		frappe.logger().warning(f"[ehf.submit] missing Sales Invoice {name}")
		return {"status": "skipped", "reason": "missing invoice"}

	submission = frappe.new_doc("EHF Submission")
	submission.reference_invoice = name
	submission.soliq_status = "Pending"
	submission.insert(ignore_permissions=True)

	try:
		payload = build_payload(name)
		submission.payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
		signature = sign(payload)
		submission.signature = signature
		submission.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001
		submission.soliq_status = "Error"
		submission.error_message = f"build/sign failed: {exc}"
		submission.save(ignore_permissions=True)
		frappe.db.commit()
		return {"name": submission.name, "status": "Error", "error_message": str(exc)}

	return send(submission.name, payload, signature)


def retry(submission_name: str) -> dict[str, Any]:
	"""Re-run sign + send for an existing EHFSubmission row.

	Reuses the stored payload_json if present so callers can edit it
	through the admin UI before retrying. Increments retry_count via the
	client's normal accounting.
	"""
	submission = frappe.get_doc("EHF Submission", submission_name)
	if submission.payload_json:
		payload = json.loads(submission.payload_json)
	else:
		payload = build_payload(submission.reference_invoice)
		submission.payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

	signature = sign(payload)
	submission.signature = signature
	submission.save(ignore_permissions=True)
	frappe.db.commit()

	return send(submission.name, payload, signature)
