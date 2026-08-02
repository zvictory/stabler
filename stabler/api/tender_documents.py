"""API Endpoints for Tender Document Center (B2).

Provides list, upload, waive, and gated download endpoints for tender/lot documents:
- list_tender_documents
- upload_tender_document
- waive_tender_document
- download_tender_document
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now

from stabler.api._tender_documents import docs_summary, parse_doc_requirements
from stabler.api.permissions import (
	_assert_company_scope,
	_require_tender,
	_require_tender_view,
)


def _get_deal_and_master(deal_name: str, company: str | None = None, ptype: str = "read"):
	"""Load CRM Deal and linked Tender Master with company scope checks."""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_tender_view("sourcing", selected_company)

	if not frappe.db.exists("CRM Deal", deal_name):
		frappe.throw(_("Tender Deal {0} not found.").format(deal_name), frappe.DoesNotExistError)

	deal_doc = frappe.get_doc("CRM Deal", deal_name)
	if deal_doc.company != selected_company:
		frappe.throw(_("Deal does not belong to the selected company."), frappe.PermissionError)

	if not frappe.has_permission("CRM Deal", ptype=ptype, doc=deal_doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	master_doc = None
	master_name = getattr(deal_doc, "custom_tender_master", None)
	if master_name and frappe.db.exists("Tender Master", master_name):
		master_doc = frappe.get_doc("Tender Master", master_name)

	return deal_doc, master_doc, selected_company


@frappe.whitelist()
def list_tender_documents(deal: str, company: str | None = None) -> dict[str, Any]:
	"""Return merged tender and lot document requirements with derived completion."""
	deal_doc, master_doc, selected_company = _get_deal_and_master(deal, company, "read")

	lot_raw = deal_doc.get("custom_tender_intake") if hasattr(deal_doc, "custom_tender_intake") else None
	if isinstance(lot_raw, str) and lot_raw.strip():
		try:
			lot_intake = json.loads(lot_raw)
		except Exception:
			lot_intake = {}
	elif isinstance(lot_raw, dict):
		lot_intake = lot_raw
	else:
		lot_intake = {}

	lot_reqs = parse_doc_requirements(lot_intake.get("documents") or [])

	master_reqs = []
	if master_doc and hasattr(master_doc, "custom_tender_documents") and master_doc.custom_tender_documents:
		master_reqs = parse_doc_requirements(master_doc.custom_tender_documents)
		for m in master_reqs:
			m["scope"] = "tender"

	all_reqs = master_reqs + lot_reqs
	summary = docs_summary(all_reqs)

	return {
		"deal": deal_doc.name,
		"tender_master": master_doc.name if master_doc else None,
		"company": selected_company,
		"requirements": all_reqs,
		"summary": summary,
	}


@frappe.whitelist()
def upload_tender_document(
	deal: str, requirement_key: str, file_name: str, file_url: str, company: str | None = None
) -> dict[str, Any]:
	"""Attach a document file to a document requirement (lot or tender scoped)."""
	deal_doc, master_doc, selected_company = _get_deal_and_master(deal, company, "write")

	if not file_name or not file_url:
		frappe.throw(_("File name and file URL are required."), frappe.ValidationError)

	key = str(requirement_key or "").strip().lower().replace(" ", "_")

	# Check if requirement is on master
	is_master_req = False
	if master_doc and hasattr(master_doc, "custom_tender_documents") and master_doc.custom_tender_documents:
		master_reqs = parse_doc_requirements(master_doc.custom_tender_documents)
		if any(r["key"] == key for r in master_reqs):
			is_master_req = True

	target_doc = master_doc if (is_master_req and master_doc) else deal_doc
	target_fieldname = "custom_tender_documents" if (is_master_req and master_doc) else "custom_tender_intake"

	raw = target_doc.get(target_fieldname)
	if is_master_req:
		reqs = parse_doc_requirements(raw)
		found = False
		for r in reqs:
			if r["key"] == key:
				found = True
				r["files"].append(
					{
						"file_name": file_name,
						"file_url": file_url,
						"uploaded_by": frappe.session.user,
						"uploaded_at": now(),
					}
				)
				r["done"] = True
				r["unverified"] = False
				r["waiver_reason"] = None
		if not found:
			frappe.throw(_("Requirement {0} not found.").format(requirement_key), frappe.DoesNotExistError)
		target_doc.db_set("custom_tender_documents", json.dumps(reqs, ensure_ascii=False))

	else:
		intake = (
			json.loads(raw)
			if (isinstance(raw, str) and raw.strip())
			else (raw if isinstance(raw, dict) else {})
		)
		reqs = parse_doc_requirements(intake.get("documents") or [])
		found = False
		for r in reqs:
			if r["key"] == key:
				found = True
				r["files"].append(
					{
						"file_name": file_name,
						"file_url": file_url,
						"uploaded_by": frappe.session.user,
						"uploaded_at": now(),
					}
				)
				r["done"] = True
				r["unverified"] = False
				r["waiver_reason"] = None
		if not found:
			frappe.throw(_("Requirement {0} not found.").format(requirement_key), frappe.DoesNotExistError)
		intake["documents"] = reqs
		target_doc.db_set("custom_tender_intake", json.dumps(intake, ensure_ascii=False))

	return list_tender_documents(deal, company=selected_company)


@frappe.whitelist()
def waive_tender_document(
	deal: str, requirement_key: str, reason: str, company: str | None = None
) -> dict[str, Any]:
	"""Waive a document requirement with a required written justification."""
	deal_doc, master_doc, selected_company = _get_deal_and_master(deal, company, "write")

	reason_clean = str(reason or "").strip()
	if not reason_clean:
		frappe.throw(_("Waiver reason is mandatory."), frappe.ValidationError)

	key = str(requirement_key or "").strip().lower().replace(" ", "_")

	is_master_req = False
	if master_doc and hasattr(master_doc, "custom_tender_documents") and master_doc.custom_tender_documents:
		master_reqs = parse_doc_requirements(master_doc.custom_tender_documents)
		if any(r["key"] == key for r in master_reqs):
			is_master_req = True

	target_doc = master_doc if (is_master_req and master_doc) else deal_doc
	target_fieldname = "custom_tender_documents" if (is_master_req and master_doc) else "custom_tender_intake"

	raw = target_doc.get(target_fieldname)
	if is_master_req:
		reqs = parse_doc_requirements(raw)
		found = False
		for r in reqs:
			if r["key"] == key:
				found = True
				r["waiver_reason"] = reason_clean
				r["waived_by"] = frappe.session.user
				r["waived_at"] = now()
				r["done"] = True
				r["unverified"] = False
		if not found:
			frappe.throw(_("Requirement {0} not found.").format(requirement_key), frappe.DoesNotExistError)
		target_doc.db_set("custom_tender_documents", json.dumps(reqs, ensure_ascii=False))
	else:
		intake = (
			json.loads(raw)
			if (isinstance(raw, str) and raw.strip())
			else (raw if isinstance(raw, dict) else {})
		)
		reqs = parse_doc_requirements(intake.get("documents") or [])
		found = False
		for r in reqs:
			if r["key"] == key:
				found = True
				r["waiver_reason"] = reason_clean
				r["waived_by"] = frappe.session.user
				r["waived_at"] = now()
				r["done"] = True
				r["unverified"] = False
		if not found:
			frappe.throw(_("Requirement {0} not found.").format(requirement_key), frappe.DoesNotExistError)
		intake["documents"] = reqs
		target_doc.db_set("custom_tender_intake", json.dumps(intake, ensure_ascii=False))

	return list_tender_documents(deal, company=selected_company)


@frappe.whitelist()
def download_tender_document(deal: str, requirement_key: str, file_url: str, company: str | None = None):
	"""Gated download endpoint enforcing company scope and requirement attachment validation."""
	_deal_doc, _master_doc, selected_company = _get_deal_and_master(deal, company, "read")

	key = str(requirement_key or "").strip().lower().replace(" ", "_")

	res = list_tender_documents(deal, company=selected_company)
	matched_req = next((r for r in res["requirements"] if r["key"] == key), None)
	if not matched_req:
		frappe.throw(
			_("Requirement {0} not found for this tender.").format(requirement_key), frappe.DoesNotExistError
		)

	matched_file = next((f for f in matched_req["files"] if f["file_url"] == file_url), None)
	if not matched_file:
		frappe.throw(
			_("Requested file URL does not belong to requirement {0}.").format(requirement_key),
			frappe.PermissionError,
		)

	# Direct stream/redirect authorization
	frappe.response["type"] = "redirect"
	frappe.response["location"] = file_url
