"""Pure planner for backfilling TimePay names onto Stabler employees from an
anjan-hr export. No frappe import — unit-testable.

anjan-hr stores `timepayId` + `fio` (full name as it appears in TimePay) per
employee. Stabler stores `custom_timepay_id` / `custom_timepay_name` on Employee.

Match strategy (deliberately conservative — TimePay FIOs have Latin/Cyrillic/typo
variants, so we never silently trust a name):
1. By TimePay id: stabler.custom_timepay_id == anjan.timepay_id  → set the name.
   This is the reliable bridge and is safe to auto-apply.
2. By normalized full name (fallback): only for anjan rows whose id didn't match,
   and only when exactly one Stabler employee with that name has no id yet. These
   are returned as suggestions that would fill BOTH id and name — for human review.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_name(s) -> str:
	"""Lowercase, strip accents/punctuation, collapse whitespace. Used only for the
	best-effort name fallback — not for the id match."""
	s = unicodedata.normalize("NFKD", str(s or ""))
	s = "".join(c for c in s if not unicodedata.combining(c))
	s = s.lower()
	s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
	s = re.sub(r"\s+", " ", s).strip()
	return s


def plan_timepay_import(stabler_emps, anjan_rows) -> dict:
	"""Compute what would change. Returns id_updates (safe), name_suggestions
	(review), and unmatched. Never mutates its inputs."""
	by_id: dict = {}
	by_name: dict = {}
	for e in stabler_emps:
		tid = str(e.get("custom_timepay_id") or "").strip()
		if tid:
			by_id[tid] = e
		n = normalize_name(e.get("employee_name"))
		if n:
			by_name.setdefault(n, []).append(e)

	id_updates = []
	name_suggestions = []
	unmatched = []
	for r in anjan_rows:
		tid = str(r.get("timepay_id") or "").strip()
		fio = str(r.get("fio") or "").strip()
		if not fio:
			continue
		emp = by_id.get(tid) if tid else None
		if emp:
			if str(emp.get("custom_timepay_name") or "").strip() != fio:
				id_updates.append(
					{
						"employee": emp["name"],
						"employee_name": emp.get("employee_name"),
						"timepay_id": tid,
						"old_name": str(emp.get("custom_timepay_name") or ""),
						"new_name": fio,
					}
				)
			continue
		# Fallback: unique name match among employees that still lack an id.
		# Also try reversed token order to handle "Familiya Ism" ↔ "Ism Familiya" differences.
		norm_fio = normalize_name(fio)
		cands = by_name.get(norm_fio, [])
		if not cands:
			tokens = norm_fio.split()
			if len(tokens) >= 2:
				cands = by_name.get(" ".join(reversed(tokens)), [])
		uniq = [c for c in cands if not str(c.get("custom_timepay_id") or "").strip()]
		if len(uniq) == 1:
			c = uniq[0]
			name_suggestions.append(
				{
					"employee": c["name"],
					"employee_name": c.get("employee_name"),
					"timepay_id": tid,
					"fio": fio,
				}
			)
		else:
			unmatched.append({"timepay_id": tid, "fio": fio, "candidates": len(cands)})
	return {
		"id_updates": id_updates,
		"name_suggestions": name_suggestions,
		"unmatched": unmatched,
	}
