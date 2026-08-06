"""Pure Python logic for Tender Document Requirements & Verification (B1).

Enforces derived completion (K2), legacy unverified tagging (K3),
and document summary metrics for CRM Deals and Tender Masters.

Reconstructed from the compiled bytecode that had lost its source. The
normalizer is the single source of truth for the per-requirement shape used
by both the lot intake (``CRM Deal.custom_tender_intake.documents``) and the
tender-level requirements (``Tender Master.custom_tender_documents``).
"""
from __future__ import annotations

import json
from typing import Any

# A requirement may be owned by one of these functional roles, so the document
# center can render per-role queues (customs desk, logistics desk, finance desk).
VALID_DOC_ROLES = ("customs", "logistics", "finance", "general")


def parse_doc_requirements(raw: Any) -> list[dict[str, Any]]:
	"""Parse and clean a raw document requirements payload or JSON string.

	Derived completion (K2): a requirement is ``done`` when it carries at least
	one file or has a written waiver. A hand-set ``done`` with no file and no
	waiver is preserved as ``unverified`` (K3) so legacy data stays visible but
	no longer silently satisfies the ready-gate.
	"""
	if not raw:
		return []
	if isinstance(raw, str):
		try:
			parsed = json.loads(raw)
		except Exception:
			return []
	elif isinstance(raw, list):
		parsed = raw
	else:
		return []

	cleaned: list[dict[str, Any]] = []
	for item in parsed:
		if not isinstance(item, dict):
			continue
		key = str(item.get("key") or item.get("label") or "").strip().lower().replace(" ", "_")
		label = str(item.get("label") or item.get("key") or "").strip()
		if not label:
			continue
		required = bool(item.get("required", True))
		scope = str(item.get("scope") or "lot").strip().lower()
		if scope not in ("lot", "tender"):
			scope = "lot"
		role = str(item.get("role") or "general").strip().lower()
		if role not in VALID_DOC_ROLES:
			role = "general"
		# `date` is the legacy per-checklist-item date from the intake editor; kept
		# for backward compatibility with existing CRM Deal intake payloads.
		date = str(item.get("date") or "").strip()[:20]
		waiver_reason = item.get("waiver_reason")
		waiver_reason_str = str(waiver_reason).strip() if waiver_reason else None
		waived_by = str(item.get("waived_by") or "").strip() or None
		waived_at = str(item.get("waived_at") or "").strip() or None
		files = item.get("files") if isinstance(item.get("files"), list) else []
		clean_files: list[dict[str, Any]] = []
		for f in files:
			if not isinstance(f, dict):
				continue
			if not (f.get("file_name") or f.get("file_url") or f.get("name")):
				continue
			clean_files.append({
				"file_name": str(f.get("file_name") or f.get("name") or ""),
				"file_url": str(f.get("file_url") or ""),
				"uploaded_by": str(f.get("uploaded_by") or f.get("owner") or ""),
				"uploaded_at": str(f.get("uploaded_at") or f.get("creation") or ""),
			})
		file_count = len(clean_files)
		is_waived = bool(waiver_reason_str)
		is_done = file_count > 0 or is_waived
		legacy_done = bool(item.get("done", False))
		unverified = legacy_done and not is_done
		cleaned.append({
			"key": key,
			"label": label,
			"required": required,
			"scope": scope,
			"role": role,
			"date": date,
			"done": is_done,
			"unverified": unverified,
			"waiver_reason": waiver_reason_str,
			"waived_by": waived_by,
			"waived_at": waived_at,
			"files": clean_files,
			"file_count": file_count,
			"latest_file": clean_files[-1] if clean_files else None,
		})
	return cleaned


def docs_summary(requirements: list[dict[str, Any]], role: str | None = None) -> dict[str, Any]:
	"""Compute documents summary metrics based on derived completion, optionally filtered by role."""
	if role is not None:
		target_role = str(role).strip().lower()
		target_reqs = [r for r in requirements if r.get("role") == target_role]
	else:
		target_reqs = requirements
	total = len(target_reqs)
	required = 0
	done_required = 0
	unverified_count = 0
	missing: list[str] = []
	for r in target_reqs:
		if r.get("unverified"):
			unverified_count += 1
		if r.get("required"):
			required += 1
			if r.get("done"):
				done_required += 1
			else:
				missing.append(r.get("label", ""))
	readiness_pct = round(done_required / required * 100) if required > 0 else 100
	return {
		"total": total,
		"required": required,
		"done_required": done_required,
		"unverified": unverified_count,
		"missing": missing,
		"readiness_pct": readiness_pct,
	}


def default_doc_requirements() -> list[dict[str, Any]]:
	"""Standard document requirements seeded with explicit role assignments."""
	raw = [
		{"key": "gtd", "label": "ГТД / Gümrük beyannamesi", "required": True, "scope": "lot", "role": "customs"},
		{"key": "origin_cert", "label": "Kelib chiqish sertifikati", "required": False, "scope": "lot", "role": "customs"},
		{"key": "cmr", "label": "CMR / Transport nakladnoyasi", "required": True, "scope": "lot", "role": "logistics"},
		{"key": "packing_list", "label": "Qadoqlash varaqasi", "required": False, "scope": "lot", "role": "logistics"},
		{"key": "invoice", "label": "Invoys / Commercial Invoice", "required": True, "scope": "lot", "role": "finance"},
		{"key": "tech_spec", "label": "Texnik spetsifikatsiya", "required": True, "scope": "lot", "role": "general"},
		{"key": "price_offer", "label": "Narx taklifi", "required": True, "scope": "lot", "role": "general"},
	]
	return parse_doc_requirements(raw)
