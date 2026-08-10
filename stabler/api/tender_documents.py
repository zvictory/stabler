"""API Endpoints for Tender Document Center (B2).

Provides list, upload, waive, and gated download endpoints for tender/lot documents:
- list_tender_documents
- upload_tender_document
- waive_tender_document
- download_tender_document

Reconstructed from compiled bytecode whose source had been lost. The two-level
design merges requirements defined at the Tender Master (parent tender) level
with those carried on each lot (CRM Deal intake), giving one document center
per lot with derived completion and optional written waivers.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now

from stabler.api._tender_documents import (
	DOC_ROLE_WRITER_VIEWS,
	apply_ready_audit,
	docs_summary,
	parse_doc_requirements,
)
from stabler.api.tender import (
	_deal_label,
	_require_any_tender_view,
	_require_tender,
	_require_tender_view,
	_tender_deal_names,
)
from stabler.api.tender_master import _assert_company_scope


def _get_deal_and_master(deal_name: str, company: str | None, ptype: str):
	"""Load CRM Deal and linked Tender Master with company scope checks.

	Okuma dört tender görünümünden herhangi birine açık (director/sourcing/
	declarant/logist) — karar "Okuma dört tender görünümüne de açıktır" dedi.
	Yazma kapısı satırın ``role`` alanına göre ayrıca uygulanır
	(``_require_doc_role_write``).
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_any_tender_view(("director", "sourcing", "declarant", "logist"), selected_company)
	if not frappe.db.exists("CRM Deal", deal_name):
		frappe.throw(_("Tender Deal {0} not found.").format(deal_name), frappe.DoesNotExistError)
	deal_doc = frappe.get_doc("CRM Deal", deal_name)
	if deal_doc.company != selected_company:
		frappe.throw(_("Deal does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("CRM Deal", ptype=ptype, doc=deal_doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	master_doc = None
	master_name = getattr(deal_doc, "custom_parent_tender", None) or getattr(
		deal_doc, "custom_tender_master", None
	)
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
	master_reqs: list[dict[str, Any]] = []
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


def _normalize_key(requirement_key: str) -> str:
	"""Slugged requirement key — the single canonical form for matching."""
	return str(requirement_key or "").strip().lower().replace(" ", "_")


def _assert_local_file_url(file_url: str) -> str:
	"""Reject anything that is not a site-local file path.

	The stored ``file_url`` is handed straight to ``frappe.response["location"]``
	by the download endpoint, so an absolute (``https://evil.example/x``) or
	protocol-relative (``//evil.example``) value would turn a trusted-origin
	endpoint into an open redirect. Requiring the ``/files/`` prefix also rules
	out protocol-relative URLs; ``..`` blocks path traversal and CR/LF blocks
	response-header injection.
	"""
	url = str(file_url or "").strip()
	if (
		not url.startswith(("/files/", "/private/files/"))
		or "://" in url
		or ".." in url
		or "\r" in url
		or "\n" in url
	):
		frappe.throw(
			_("File URL must be a site file path starting with /files/ or /private/files/."),
			frappe.ValidationError,
		)
	return url


def _resolve_target(deal_doc, master_doc, key: str):
	"""Pick (target_doc, fieldname, is_master) for a requirement key.

	Master requirements live on ``Tender Master.custom_tender_documents``; lot
	requirements on ``CRM Deal.custom_tender_intake.documents``. Decided by where
	the key actually exists, so an upload/waive/remove lands on the right layer.
	"""
	is_master_req = False
	if master_doc and hasattr(master_doc, "custom_tender_documents") and master_doc.custom_tender_documents:
		master_reqs = parse_doc_requirements(master_doc.custom_tender_documents)
		if any(r.get("key") == key for r in master_reqs):
			is_master_req = True
	if is_master_req and master_doc:
		return master_doc, "custom_tender_documents", True
	return deal_doc, "custom_tender_intake", False


def _resolve_target_with_role(deal_doc, master_doc, key: str):
	"""Like ``_resolve_target`` but also returns the requirement row's ``role``.

	Used by the write endpoints (upload/waive/remove) to apply the row-role
	write gate — "kim yükler" sorusunun cevabı satırın rolünde.
	"""
	target_doc, fieldname, is_master_req = _resolve_target(deal_doc, master_doc, key)
	raw = target_doc.get(fieldname)
	reqs = parse_doc_requirements(raw if is_master_req else _intake_documents(raw))
	row = next((r for r in reqs if r.get("key") == key), None)
	return target_doc, fieldname, is_master_req, row


def _require_doc_role_write(row: dict | None, company: str) -> None:
	"""Write gate keyed on the requirement row's ``role`` field.

	``director`` is the universal writer.  Other roles may write only rows whose
	``role`` maps to a view they hold::

	    customs    → declarant + director
	    logistics  → logist + director
	    general    → sourcing + director
	    finance    → sourcing + director
	"""
	if row is None:
		return
	role = str(row.get("role") or "general").strip().lower()
	allowed = DOC_ROLE_WRITER_VIEWS.get(role, DOC_ROLE_WRITER_VIEWS["general"])
	_require_any_tender_view(allowed, company)


def _save_requirements(target_doc, fieldname: str, reqs: list, is_master_req: bool) -> None:
	"""Persist a normalized requirements list back to its owner document."""
	if is_master_req:
		target_doc.db_set(fieldname, json.dumps(reqs, ensure_ascii=False))
	else:
		raw = target_doc.get(fieldname)
		intake = (
			json.loads(raw)
			if (isinstance(raw, str) and raw.strip())
			else (raw if isinstance(raw, dict) else {})
		)
		intake["documents"] = reqs
		# Attaching the last required file is a lifecycle transition, not just a
		# file write: without this the lot satisfies the ready gate but carries
		# no ready_at, so _has_ready_evidence reads it as not ready and it never
		# reaches the acquisition funnel's ready bucket.
		apply_ready_audit(intake, reqs, frappe.session.user, now())
		target_doc.db_set(fieldname, json.dumps(intake, ensure_ascii=False))


@frappe.whitelist()
def upload_tender_document(
	deal: str,
	requirement_key: str,
	file_name: str,
	file_url: str,
	company: str | None = None,
) -> dict[str, Any]:
	"""Attach a document file to a document requirement (lot or tender scoped)."""
	deal_doc, master_doc, selected_company = _get_deal_and_master(deal, company, "write")
	if not (file_name and file_url):
		frappe.throw(_("File name and file URL are required."), frappe.ValidationError)
	file_url = _assert_local_file_url(file_url)
	if not frappe.db.exists("File", {"file_url": file_url}):
		frappe.throw(_("No uploaded file found for {0}.").format(file_url), frappe.ValidationError)
	key = _normalize_key(requirement_key)
	target_doc, fieldname, is_master_req, row = _resolve_target_with_role(deal_doc, master_doc, key)
	_require_doc_role_write(row, selected_company)
	raw = target_doc.get(fieldname)
	reqs = parse_doc_requirements(raw if is_master_req else _intake_documents(raw))
	found = False
	for r in reqs:
		if r["key"] != key:
			continue
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
		# A file does not void a written waiver — they are independent satisfiers.
		# Removing the file later must not leave the requirement open because the
		# waiver was quietly cleared, so we leave waiver_reason/waived_* untouched.
	if not found:
		frappe.throw(_("Requirement {0} not found.").format(requirement_key), frappe.DoesNotExistError)
	_save_requirements(target_doc, fieldname, reqs, is_master_req)
	return list_tender_documents(deal=deal, company=selected_company)


def _intake_documents(raw):
	"""Return the parsed ``documents`` list from a lot intake blob (str or dict)."""
	intake = (
		json.loads(raw) if (isinstance(raw, str) and raw.strip()) else (raw if isinstance(raw, dict) else {})
	)
	return intake.get("documents") or []


@frappe.whitelist()
def waive_tender_document(
	deal: str,
	requirement_key: str,
	reason: str,
	company: str | None = None,
) -> dict[str, Any]:
	"""Waive a document requirement with a required written justification."""
	deal_doc, master_doc, selected_company = _get_deal_and_master(deal, company, "write")
	reason_clean = str(reason or "").strip()
	if not reason_clean:
		frappe.throw(_("Waiver reason is mandatory."), frappe.ValidationError)
	key = _normalize_key(requirement_key)
	target_doc, fieldname, is_master_req, row = _resolve_target_with_role(deal_doc, master_doc, key)
	_require_doc_role_write(row, selected_company)
	raw = target_doc.get(fieldname)
	reqs = parse_doc_requirements(raw if is_master_req else _intake_documents(raw))
	found = False
	for r in reqs:
		if r["key"] != key:
			continue
		found = True
		r["waiver_reason"] = reason_clean
		r["waived_by"] = frappe.session.user
		r["waived_at"] = now()
		r["done"] = True
		r["unverified"] = False
	if not found:
		frappe.throw(_("Requirement {0} not found.").format(requirement_key), frappe.DoesNotExistError)
	_save_requirements(target_doc, fieldname, reqs, is_master_req)
	return list_tender_documents(deal=deal, company=selected_company)


@frappe.whitelist()
def remove_tender_document(
	deal: str,
	requirement_key: str,
	file_url: str | None = None,
	company: str | None = None,
) -> dict[str, Any]:
	"""Detach a file (or all files) from a document requirement.

	With ``file_url`` only that file is removed (so a multi-file requirement can
	shed a wrong upload without losing the rest); without it every file on the
	requirement is cleared. Re-derives ``done``/``unverified`` from whatever
	remains, so removing the last file re-opens the requirement instead of
	leaving a satisfied-looking slot with nothing behind it. This is the only
	path that legitimately removes files — the intake editor cannot, because its
	save is reconciled server-side (file/waiver facts are preserved, not trusted
	from the browser).
	"""
	deal_doc, master_doc, selected_company = _get_deal_and_master(deal, company, "write")
	key = _normalize_key(requirement_key)
	target_doc, fieldname, is_master_req, row = _resolve_target_with_role(deal_doc, master_doc, key)
	_require_doc_role_write(row, selected_company)
	raw = target_doc.get(fieldname)
	reqs = parse_doc_requirements(raw if is_master_req else _intake_documents(raw))
	found = False
	changed = False
	for r in reqs:
		if r["key"] != key:
			continue
		found = True
		if file_url:
			before = len(r["files"])
			r["files"] = [f for f in r["files"] if f.get("file_url") != file_url]
			changed = changed or len(r["files"]) != before
		else:
			changed = changed or bool(r["files"])
			r["files"] = []
		# Re-derive completion from the remaining files + any waiver.
		has_files = bool(r["files"])
		is_waived = bool(r.get("waiver_reason"))
		r["done"] = has_files or is_waived
		r["unverified"] = False  # never silently re-stick the legacy flag
	if not found:
		frappe.throw(_("Requirement {0} not found.").format(requirement_key), frappe.DoesNotExistError)
	if changed:
		_save_requirements(target_doc, fieldname, reqs, is_master_req)
	return list_tender_documents(deal=deal, company=selected_company)


@frappe.whitelist()
def download_tender_document(
	deal: str,
	requirement_key: str,
	file_url: str,
	company: str | None = None,
):
	"""Gated download endpoint enforcing company scope and requirement attachment validation."""
	_get_deal_and_master(deal, company, "read")
	key = _normalize_key(requirement_key)
	res = list_tender_documents(deal=deal, company=company)
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
	# Re-validated here, not only on upload: rows written before the upload-side
	# check existed may still carry an external URL, and those must be refused
	# rather than redirected to.
	frappe.response["type"] = "redirect"
	frappe.response["location"] = _assert_local_file_url(file_url)
	return None


@frappe.whitelist()
def tender_document_targets(company: str | None = None) -> dict:
	"""Selectable lot list for the document center's lot picker.

	When the user arrives at ``/tender/documents`` with no ``?deal=`` selected,
	this endpoint feeds the picker.  Returns the company's tender deals with
	missing-required-document counts so the user can see at a glance which lot
	needs attention.

	Company + module gated (never branches on tenant name — CLAUDE.md hard rule).
	"""
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	_require_any_tender_view(("director", "sourcing", "declarant", "logist"), selected_company)

	deal_names = _tender_deal_names(selected_company)
	targets: list[dict] = []
	for deal in sorted(deal_names):
		if not frappe.has_permission("CRM Deal", "read", doc=deal):
			continue
		# Read the merged requirements to count missing required docs.
		try:
			res = list_tender_documents(deal=deal, company=selected_company)
			summary = res.get("summary", {})
		except Exception:
			summary = {}
		targets.append(
			{
				"deal": deal,
				"label": _deal_label(deal),
				"parent_tender": frappe.db.get_value("CRM Deal", deal, "custom_parent_tender") or "",
				"stage": frappe.db.get_value("CRM Deal", deal, "status") or "",
				"missing_required": len(summary.get("missing", [])),
				"readiness_pct": summary.get("readiness_pct", 0),
			}
		)
	targets.sort(key=lambda r: (r["missing_required"], r["readiness_pct"]))
	return {"targets": targets}
