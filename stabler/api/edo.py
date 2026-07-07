"""Whitelisted endpoints for the Didox.uz EDO (e-invoicing) manual send flow.

Sales Invoice -> Didox ESF (hisob-faktura), signed client-side via the
user's own E-IMZO key (PKCS#7); the server never sees the private key.
Mirrors the EHF admin endpoints in stabler/api/compliance.py, but scoped to
whichever Sales Invoice the caller can read/write — this is a per-invoice
action a company user triggers manually, not an admin-only tool.
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.api._common import _assert_can_read, _assert_can_write
from stabler.api.approvals import _assert_company_scope
from stabler.integrations.didox import submit as didox_submit

_DIDOX_STATUSES = ("Draft", "Signed", "Sent", "Accepted", "Rejected", "Error")


def _assert_invoice_scope(invoice_name: str, ptype: str = "read") -> None:
	if ptype == "read":
		_assert_can_read("Sales Invoice", invoice_name)
	else:
		_assert_can_write("Sales Invoice", invoice_name, ptype)
	company = frappe.db.get_value("Sales Invoice", invoice_name, "company")
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg


def _submission_invoice(submission: str) -> str:
	reference_invoice = frappe.db.get_value("Didox Submission", submission, "reference_invoice")
	if not reference_invoice:
		frappe.throw(_("Unknown Didox Submission"))
	return reference_invoice


@frappe.whitelist()
def didox_prepare(name: str) -> dict:
	"""Create a Draft Didox Submission for a submitted Sales Invoice; return the unsigned payload for browser preview + E-IMZO signing."""
	_assert_invoice_scope(name, "read")
	if frappe.db.get_value("Sales Invoice", name, "docstatus") != 1:
		frappe.throw(_("Sales Invoice must be submitted before sending to Didox"))
	return didox_submit.prepare_for_invoice(name)


@frappe.whitelist()
def didox_send(name: str, signed_pkcs7: str) -> dict:
	"""Accept a browser-signed PKCS#7 envelope for a Didox Submission and forward it to Didox."""
	invoice = _submission_invoice(name)
	_assert_invoice_scope(invoice, "write")
	# Re-check submitted state here, not only at prepare time: the invoice could
	# have been cancelled between preparing/signing and sending. A cancelled ЭСФ
	# must never reach Didox.
	if frappe.db.get_value("Sales Invoice", invoice, "docstatus") != 1:
		frappe.throw(_("Sales Invoice must be submitted before sending to Didox"))

	signed_pkcs7 = (signed_pkcs7 or "").strip()
	if not signed_pkcs7:
		frappe.throw(_("Signed document (PKCS#7) is required"))

	return didox_submit.send_signed(name, signed_pkcs7)


@frappe.whitelist()
def didox_retry(name: str) -> dict:
	"""Resend an already-signed Didox Submission after a transient failure (network/Didox downtime)."""
	invoice = _submission_invoice(name)
	_assert_invoice_scope(invoice, "write")
	if frappe.db.get_value("Sales Invoice", invoice, "docstatus") != 1:
		frappe.throw(_("Sales Invoice must be submitted before sending to Didox"))
	return didox_submit.retry(name)


@frappe.whitelist()
def didox_status(name: str) -> dict:
	"""Latest Didox Submission status for a Sales Invoice, or {} if never sent."""
	_assert_invoice_scope(name, "read")
	rows = frappe.get_all(
		"Didox Submission",
		filters={"reference_invoice": name},
		fields=["name", "doc_type", "status", "didox_doc_id", "submitted_at", "retry_count", "error_message"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else {}


def _is_admin() -> bool:
	from stabler.api.organization import _ADMIN_ROLES

	return any(r in frappe.get_roles() for r in _ADMIN_ROLES)


@frappe.whitelist()
def list_didox_submissions(
	status: str | None = None,
	reference_invoice: str | None = None,
	limit: int = 50,
) -> list[dict]:
	"""List Didox Submissions, optionally filtered by status / invoice.

	Without an explicit reference_invoice, only admins may browse across
	invoices — otherwise this would leak submission data for invoices the
	caller cannot read.
	"""
	try:
		limit = max(1, min(int(limit), 500))
	except (TypeError, ValueError):
		limit = 50

	filters: dict = {}
	if status and status in _DIDOX_STATUSES:
		filters["status"] = status
	if reference_invoice:
		_assert_invoice_scope(reference_invoice, "read")
		filters["reference_invoice"] = reference_invoice
	elif not _is_admin():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	return frappe.get_all(
		"Didox Submission",
		filters=filters,
		fields=[
			"name",
			"reference_invoice",
			"doc_type",
			"status",
			"didox_doc_id",
			"submitted_at",
			"retry_count",
			"error_message",
			"creation",
		],
		order_by="creation desc",
		limit=limit,
	)
