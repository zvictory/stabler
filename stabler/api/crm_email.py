"""Two-Way Email and Triage Queue API for CRM Deals.

Enforces CRM module permissions, company scoping, record-level authorization,
thread matching, ambiguous email triage queue, durable DB idempotency, and send failure retry.
"""

from __future__ import annotations

import re

import frappe
from frappe import _

from stabler.api._common import _assert_can_write
from stabler.api.crm import _assert_crm_record_company, _require_crm, _require_crm_company


def _assert_communication_company(comm_doc: dict | object, company: str) -> None:
	"""Verify Communication record company matches the selected company."""
	comm_company = getattr(comm_doc, "company", None) or (
		comm_doc.get("company") if isinstance(comm_doc, dict) else None
	)
	if comm_company and comm_company != company:
		frappe.throw(
			_("Not permitted for company {0}.").format(company),
			frappe.PermissionError,
		)


def _set_http_failure_status(code: int = 500) -> None:
	"""Set HTTP status code on frappe.local.response if running under web request context."""
	if hasattr(frappe, "local") and hasattr(frappe.local, "response"):
		frappe.local.response["http_status_code"] = code


@frappe.whitelist()
def send_deal_email(
	deal: str,
	subject: str,
	content: str,
	company: str,
	recipients: str | None = None,
	idempotency_key: str | None = None,
) -> dict:
	"""Send email linked to a CRM Deal with durable DB idempotency guard and delivery retry support.

	Creates a Communication record linked to the CRM Deal and sends via frappe.sendmail.
	If mail delivery fails, records Failed status & error durably in DB transaction without rollback,
	returning a non-2xx status response to allow subsequent retries via the same idempotency key.
	"""
	_require_crm()
	_require_crm_company(company)
	if not frappe.has_permission("Communication", "create"):
		frappe.throw(_("Not permitted for Communication"), frappe.PermissionError)

	_assert_crm_record_company("CRM Deal", deal, company, "write")

	deal_doc = frappe.get_doc("CRM Deal", deal)
	raw_key = (idempotency_key or "").strip()
	key = f"comm:{company}:{raw_key}" if raw_key else ""

	# Durable DB Idempotency lookup
	if key:
		existing = frappe.get_list(
			"Communication",
			filters={"custom_idempotency_key": key, "company": company},
			fields=["name", "custom_execution_status", "custom_attempts"],
			limit_page_length=1,
		)
		if existing:
			ext = existing[0]
			status = ext.get("custom_execution_status")
			if status != "Failed":
				return {
					"name": ext["name"],
					"deal": deal,
					"deduped": True,
					"status": status,
				}
			# Retry previous failed email delivery
			comm_name = ext["name"]
			to_email = recipients or deal_doc.get("email_id") or deal_doc.get("email")
			if hasattr(frappe, "sendmail"):
				try:
					frappe.sendmail(
						recipients=to_email,
						subject=subject,
						message=content,
						reference_doctype="CRM Deal",
						reference_name=deal,
					)
					new_attempts = (ext.get("custom_attempts") or 1) + 1
					if hasattr(frappe, "db") and hasattr(frappe.db, "set_value"):
						frappe.db.set_value(
							"Communication",
							comm_name,
							{
								"custom_execution_status": "Retried",
								"custom_attempts": new_attempts,
								"custom_last_error": None,
							},
						)
						if hasattr(frappe.db, "commit"):
							frappe.db.commit()
					return {
						"name": comm_name,
						"deal": deal,
						"retried": True,
						"deduped": False,
						"status": "Retried",
						"attempts": new_attempts,
					}
				except Exception as err:
					safe_err = str(err)[:255]
					new_attempts = (ext.get("custom_attempts") or 1) + 1
					if hasattr(frappe, "db") and hasattr(frappe.db, "set_value"):
						frappe.db.set_value(
							"Communication",
							comm_name,
							{
								"custom_execution_status": "Failed",
								"custom_attempts": new_attempts,
								"custom_last_error": safe_err,
							},
						)
						if hasattr(frappe.db, "commit"):
							frappe.db.commit()
					_set_http_failure_status(500)
					user_msg = _("Email delivery failed. Please check mail server settings.")
					return {
						"name": comm_name,
						"deal": deal,
						"status": "Failed",
						"attempts": new_attempts,
						"error": user_msg,
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
		comm.custom_idempotency_key = key or None
		comm.custom_execution_status = "Executed"
		comm.custom_attempts = 1
		comm.custom_last_error = None

	if hasattr(comm, "insert"):
		dup_errs = (
			getattr(frappe, "UniqueValidationError", type("UniqueValidationError", (Exception,), {})),
			getattr(frappe, "DuplicateEntryError", type("DuplicateEntryError", (Exception,), {})),
		)
		try:
			comm.insert()
		except dup_errs:
			# Catch ONLY duplicate key exceptions on insertion
			existing_comm = frappe.get_list(
				"Communication",
				filters={"custom_idempotency_key": key, "company": company},
				fields=["name"],
				limit_page_length=1,
			)
			if existing_comm:
				return {
					"name": existing_comm[0]["name"],
					"deal": deal,
					"deduped": True,
				}
			raise

	comm_name = getattr(comm, "name", f"COMM-{deal}")

	# Send email with durable error audit logging
	if hasattr(frappe, "sendmail"):
		try:
			frappe.sendmail(
				recipients=to_email,
				subject=subject,
				message=content,
				reference_doctype="CRM Deal",
				reference_name=deal,
			)
		except Exception as err:
			safe_err = str(err)[:255]
			if hasattr(comm, "custom_execution_status"):
				comm.custom_execution_status = "Failed"
				comm.custom_last_error = safe_err
				if hasattr(comm, "save"):
					comm.save()
			if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
				frappe.db.commit()
			_set_http_failure_status(500)
			user_msg = _("Email delivery failed. Please check mail server settings.")
			return {
				"name": comm_name,
				"deal": deal,
				"status": "Failed",
				"attempts": 1,
				"error": user_msg,
			}

	return {
		"name": comm_name,
		"deal": deal,
		"deduped": False,
		"status": "Executed",
	}


def match_incoming_email_to_deal(communication_name: str, company: str | None = None) -> dict:
	"""Thread-match incoming email to a CRM Deal.

	Matching hierarchy:
	 1. Explicit [DEAL-<name>] pattern in subject.
	 2. Matching sender email address to CRM Deal `email_id`.
	 3. Unambiguous match with matching company -> links reference_doctype & reference_name.
	 4. Ambiguous / cross-company / no match -> tags custom_triage_status="Unmatched".
	"""
	comm = frappe.get_doc("Communication", communication_name)
	subject = (getattr(comm, "subject", "") or comm.get("subject") or "").strip()
	sender = (getattr(comm, "sender", "") or comm.get("sender") or "").strip()
	comm_company = (
		company or getattr(comm, "company", None) or (comm.get("company") if isinstance(comm, dict) else None)
	)

	# Pattern 1: subject tag [DEAL-123]
	match = re.search(r"\[(DEAL-[^\]]+)\]", subject, re.IGNORECASE)
	matched_deal = None

	if match:
		candidate_deal = match.group(1).strip()
		# Validate candidate deal exists and belongs to same company
		if frappe.db.exists("CRM Deal", candidate_deal):
			deal_company = frappe.db.get_value("CRM Deal", candidate_deal, "company")
			if not comm_company or deal_company == comm_company:
				matched_deal = candidate_deal

	elif sender:
		# Pattern 2: sender email match
		filters = {"email_id": sender}
		if comm_company:
			filters["company"] = comm_company
		deals = frappe.get_list(
			"CRM Deal",
			filters=filters,
			fields=["name"],
			limit_page_length=2,
		)
		if len(deals) == 1:
			matched_deal = deals[0]["name"]

	if matched_deal:
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
	_require_crm()
	_require_crm_company(company)
	if not frappe.has_permission("Communication", "read"):
		frappe.throw(_("Not permitted for Communication"), frappe.PermissionError)

	rows = frappe.get_list(
		"Communication",
		filters={"custom_triage_status": "Unmatched", "company": company},
		fields=["name", "subject", "sender", "recipients", "creation", "content", "company"],
		order_by="creation desc",
		limit_page_length=50,
	)
	return {"rows": rows, "count": len(rows)}


@frappe.whitelist()
def link_triage_email(communication_name: str, deal: str, company: str) -> dict:
	"""Manually link an unassigned triage email to a selected CRM Deal."""
	_require_crm()
	_require_crm_company(company)
	_assert_can_write("Communication", communication_name)
	_assert_crm_record_company("CRM Deal", deal, company, "write")

	comm = frappe.get_doc("Communication", communication_name)
	_assert_communication_company(comm, company)

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
