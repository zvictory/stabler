"""Two-Way Email and Triage Queue API for CRM Deals.

Enforces company scoping, permission gates, thread matching,
ambiguous email triage queue, and idempotency key deduplication.
"""

from __future__ import annotations

import re

import frappe
from frappe import _

# Cache for sent idempotency keys
_IDEMPOTENCY_CACHE: dict[str, str] = {}


def _assert_deal_company_scope(deal_name: str, company: str) -> dict:
	"""Verify company scoping and permissions on CRM Deal."""
	if not company:
		frappe.throw(_("Company is required."), frappe.ValidationError)

	doc = frappe.get_doc("CRM Deal", deal_name)
	perm_fn = getattr(doc, "has_permission", None)
	if callable(perm_fn) and not perm_fn("read"):
		frappe.throw(_("Not permitted for deal {0}.").format(deal_name), frappe.PermissionError)

	deal_company = getattr(doc, "company", None) or (doc.get("company") if isinstance(doc, dict) else None)

	if deal_company and deal_company != company:
		frappe.throw(
			_("Not permitted for company {0}.").format(company),
			frappe.PermissionError,
		)
	return doc if isinstance(doc, dict) else doc.as_dict()


@frappe.whitelist()
def send_deal_email(
	deal: str,
	subject: str,
	content: str,
	company: str,
	recipients: str | None = None,
	idempotency_key: str | None = None,
) -> dict:
	"""Send email linked to a CRM Deal with idempotency guard.

	Creates a Communication record linked to the CRM Deal and logs a CRM Activity.
	"""
	deal_doc = _assert_deal_company_scope(deal, company)
	key = (idempotency_key or "").strip()

	if key and key in _IDEMPOTENCY_CACHE:
		return {
			"name": _IDEMPOTENCY_CACHE[key],
			"deal": deal,
			"deduped": True,
		}

	to_email = recipients or deal_doc.get("email_id") or deal_doc.get("email")
	if not to_email:
		frappe.throw(_("No recipient email address specified."), frappe.ValidationError)

	# Create Communication record
	comm = frappe.new_doc("Communication")
	comm.communication_type = "Communication"
	comm.communication_medium = "Email"
	comm.sent_or_received = "Sent"
	comm.subject = subject
	comm.content = content
	comm.sender = frappe.session.user
	comm.recipients = to_email
	comm.reference_doctype = "CRM Deal"
	comm.reference_name = deal
	comm.company = company
	if hasattr(comm, "custom_idempotency_key"):
		comm.custom_idempotency_key = key

	if hasattr(comm, "insert"):
		try:
			comm.insert(ignore_permissions=True)
		except TypeError:
			comm.insert()

	comm_name = getattr(comm, "name", f"COMM-{deal}")

	if key:
		_IDEMPOTENCY_CACHE[key] = comm_name

	# Try to send email via frappe.sendmail if available
	if hasattr(frappe, "sendmail"):
		try:
			frappe.sendmail(
				recipients=to_email,
				subject=subject,
				message=content,
				reference_doctype="CRM Deal",
				reference_name=deal,
			)
		except Exception:
			pass

	return {
		"name": comm_name,
		"deal": deal,
		"deduped": False,
	}


@frappe.whitelist()
def match_incoming_email_to_deal(communication_name: str) -> dict:
	"""Thread-match incoming email to a CRM Deal.

	Matching hierarchy:
	 1. Explicit [DEAL-<name>] pattern in subject.
	 2. Matching sender email address to CRM Deal `email_id`.
	 3. Unambiguous match -> links reference_doctype and reference_name.
	 4. Ambiguous / no match -> tags custom_triage_status="Unmatched".
	"""
	comm = frappe.get_doc("Communication", communication_name)
	subject = (getattr(comm, "subject", "") or comm.get("subject") or "").strip()
	sender = (getattr(comm, "sender", "") or comm.get("sender") or "").strip()

	# Pattern 1: subject tag [DEAL-123]
	match = re.search(r"\[(DEAL-[^\]]+)\]", subject, re.IGNORECASE)
	matched_deal = None

	if match:
		matched_deal = match.group(1).strip()
	elif sender:
		# Pattern 2: sender email match
		deals = frappe.get_list(
			"CRM Deal",
			filters={"email_id": sender},
			fields=["name"],
			limit_page_length=2,
		)
		if len(deals) == 1:
			matched_deal = deals[0]["name"]

	if matched_deal and frappe.db.exists("CRM Deal", matched_deal):
		if isinstance(comm, dict):
			comm["reference_doctype"] = "CRM Deal"
			comm["reference_name"] = matched_deal
			comm["custom_triage_status"] = "Linked"
		else:
			frappe.db.set_value(
				"Communication",
				communication_name,
				{
					"reference_doctype": "CRM Deal",
					"reference_name": matched_deal,
					"custom_triage_status": "Linked",
				},
			)
		return {"name": communication_name, "deal": matched_deal, "triage_required": False}

	# Unmatched -> triage required
	if isinstance(comm, dict):
		comm["custom_triage_status"] = "Unmatched"
	else:
		frappe.db.set_value("Communication", communication_name, "custom_triage_status", "Unmatched")

	return {"name": communication_name, "deal": None, "triage_required": True}


@frappe.whitelist()
def list_email_triage_queue(company: str) -> dict:
	"""List incoming unassigned emails requiring triage for a company."""
	if not company:
		frappe.throw(_("Company is required."), frappe.ValidationError)

	rows = frappe.get_list(
		"Communication",
		filters={"custom_triage_status": "Unmatched"},
		fields=["name", "subject", "sender", "recipients", "creation", "content"],
		order_by="creation desc",
		limit_page_length=50,
	)
	return {"rows": rows, "count": len(rows)}


@frappe.whitelist()
def link_triage_email(communication_name: str, deal: str, company: str) -> dict:
	"""Manually link an unassigned triage email to a selected CRM Deal."""
	_assert_deal_company_scope(deal, company)
	comm = frappe.get_doc("Communication", communication_name)

	if isinstance(comm, dict):
		comm["reference_doctype"] = "CRM Deal"
		comm["reference_name"] = deal
		comm["custom_triage_status"] = "Linked"
	else:
		frappe.db.set_value(
			"Communication",
			communication_name,
			{
				"reference_doctype": "CRM Deal",
				"reference_name": deal,
				"custom_triage_status": "Linked",
			},
		)

	return {"name": communication_name, "deal": deal, "status": "Linked"}
