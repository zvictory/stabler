"""Pure Python logic for Tender Document Requirements & Verification (B1).

Enforces derived completion (K2), legacy unverified tagging (K3),
and document summary metrics for CRM Deals and Tender Masters.
"""

from __future__ import annotations

import json
from typing import Any


def parse_doc_requirements(raw: Any) -> list[dict[str, Any]]:
	"""Parse and clean a raw document requirements payload or JSON string."""
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

	cleaned = []
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

		waiver_reason = item.get("waiver_reason")
		waiver_reason_str = str(waiver_reason).strip() if waiver_reason else None
		waived_by = str(item.get("waived_by") or "").strip() or None
		waived_at = str(item.get("waived_at") or "").strip() or None

		files = item.get("files") if isinstance(item.get("files"), list) else []
		clean_files = []
		for f in files:
			if isinstance(f, dict) and (f.get("file_name") or f.get("file_url") or f.get("name")):
				clean_files.append(
					{
						"file_name": str(f.get("file_name") or f.get("name") or ""),
						"file_url": str(f.get("file_url") or ""),
						"uploaded_by": str(f.get("uploaded_by") or f.get("owner") or ""),
						"uploaded_at": str(f.get("uploaded_at") or f.get("creation") or ""),
					}
				)

		file_count = len(clean_files)
		is_waived = bool(waiver_reason_str)

		# K2: done is derived (at least one file OR explicitly waived with reason)
		is_done = (file_count > 0) or is_waived

		# K3: Legacy manually ticked items without files or waivers become unverified
		legacy_done = bool(item.get("done", False))
		unverified = legacy_done and not is_done

		cleaned.append(
			{
				"key": key,
				"label": label,
				"required": required,
				"scope": scope,
				"done": is_done,
				"unverified": unverified,
				"waiver_reason": waiver_reason_str,
				"waived_by": waived_by,
				"waived_at": waived_at,
				"files": clean_files,
				"file_count": file_count,
				"latest_file": clean_files[-1] if clean_files else None,
			}
		)

	return cleaned


def docs_summary(requirements: list[dict[str, Any]]) -> dict[str, Any]:
	"""Compute documents summary metrics based on derived completion."""
	total = len(requirements)
	required = 0
	done_required = 0
	unverified_count = 0
	missing = []

	for r in requirements:
		if r.get("unverified"):
			unverified_count += 1

		if r.get("required"):
			required += 1
			if r.get("done"):
				done_required += 1
			else:
				missing.append(r.get("label", ""))

	readiness_pct = int(round((done_required / required * 100))) if required > 0 else 100

	return {
		"total": total,
		"required": required,
		"done_required": done_required,
		"unverified": unverified_count,
		"missing": missing,
		"readiness_pct": readiness_pct,
	}
