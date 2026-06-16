"""Pure decision logic for approvals and audit — no Frappe, no I/O.

Everything here is a deterministic function of its arguments, so it can be unit
tested without a bench or a database. The Frappe-facing modules
(``stabler.api.approvals`` and ``stabler.api.audit``) own all the I/O and call
into these helpers for the actual rules. Keeping the rules pure is what makes
the maker-checker control and the audit parser testable at all.

Multi-level (tiered) approval
------------------------------
A tier config is a list of dicts with keys:

  {
      "threshold": <number>,      # minimum base_amount that activates this tier
      "approver_role": <str>,     # Frappe role whose holders can approve at this level
      "level": <int>,             # 1-based ordering; level 1 is reviewed first
  }

``resolve_required_tiers(base_amount, tiers)``
    Returns the ordered list of tiers (dicts) that must approve a document of
    this amount. A tier is required if ``base_amount >= tier["threshold"]``.
    Always returned sorted by ascending level.

``is_fully_approved(required_tiers, approvals_so_far)``
    ``approvals_so_far`` is a list of dicts ``{"level": int, "approver": str}``.
    Returns True when every required level has at least one approval.

``next_required_level(required_tiers, approvals_so_far)``
    Returns the level int of the lowest required tier that has not yet been
    approved, or None when fully approved.

``approval_is_in_sequence(level, required_tiers, approvals_so_far)``
    Returns True only if all levels below ``level`` in the required set already
    have an approval — i.e., the given level is the correct next step. Prevents
    level-N approvers from jumping ahead.

``would_be_double_approve(level, approver, approvals_so_far)``
    Returns True if ``approver`` has already recorded an approval at ``level``.
    This is the pure half of the race-prevention guard; the Frappe wrapper must
    also hold a DB-level row-lock or recheck after acquiring it.
"""

from __future__ import annotations

# Fields that are never worth showing as a "change" in the audit trail.
IGNORE_FIELDS = frozenset(
	{
		"modified",
		"modified_by",
		"_user_tags",
		"_comments",
		"_assign",
		"_liked_by",
		"idx",
		"naming_series",
		"lft",
		"rgt",
	}
)


def _to_float(value) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0


def _clean_tiers(tiers) -> list:
	"""Validate and normalise a tier config list.

	Each entry must be a dict with at minimum ``threshold``, ``approver_role``,
	and ``level``. Bad/incomplete entries are silently dropped so garbage input
	never raises — the caller receives an empty list and falls back to
	single-level behaviour.
	"""
	if not tiers:
		return []
	cleaned = []
	for t in tiers:
		if not isinstance(t, dict):
			continue
		try:
			level = int(t["level"])
			role = str(t["approver_role"]).strip()
			thr = _to_float(t.get("threshold", 0))
		except (KeyError, TypeError, ValueError):
			continue
		if not role or level < 1:
			continue
		cleaned.append({"threshold": thr, "approver_role": role, "level": level})
	# Stable sort by level; duplicate levels are preserved (harmless — both must
	# be satisfied, which is unusual but valid for a "dual-control" setup).
	cleaned.sort(key=lambda x: x["level"])
	return cleaned


def resolve_required_tiers(base_amount, tiers) -> list:
	"""Return the ordered list of tier dicts that must approve a document.

	A tier is required when ``base_amount >= tier["threshold"]``.  A threshold
	of 0 / None / negative always activates the tier (secure default: every
	document needs that level). The returned list is sorted by ascending level
	and is a fresh copy — callers may mutate it freely.

	Returns [] when no tiers are configured or none are triggered, which the
	Frappe layer treats as "no multi-level tiers → fall back to single-level".
	"""
	cleaned = _clean_tiers(tiers)
	amount = _to_float(base_amount)
	return [t.copy() for t in cleaned if amount >= (t["threshold"] if t["threshold"] > 0 else 0) or t["threshold"] <= 0]


def is_fully_approved(required_tiers, approvals_so_far) -> bool:
	"""True when every required level has at least one approval entry.

	``approvals_so_far`` is a list of ``{"level": int, "approver": str}`` dicts.
	Missing or malformed entries in ``approvals_so_far`` are silently ignored.
	"""
	if not required_tiers:
		return True  # No tiers configured → not this function's concern.
	approved_levels = set()
	for a in (approvals_so_far or []):
		try:
			approved_levels.add(int(a["level"]))
		except (KeyError, TypeError, ValueError):
			continue
	return all(t["level"] in approved_levels for t in required_tiers)


def next_required_level(required_tiers, approvals_so_far) -> int | None:
	"""Return the level int of the lowest required tier not yet approved.

	Returns None when all required tiers are satisfied (fully approved).
	"""
	if not required_tiers:
		return None
	approved_levels = set()
	for a in (approvals_so_far or []):
		try:
			approved_levels.add(int(a["level"]))
		except (KeyError, TypeError, ValueError):
			continue
	for t in required_tiers:  # already sorted by level
		if t["level"] not in approved_levels:
			return t["level"]
	return None


def approval_is_in_sequence(level: int, required_tiers, approvals_so_far) -> bool:
	"""True only if all lower required levels are already approved.

	Prevents a level-N approver from skipping ahead of level-(N-1). If
	``level`` is not in the required tiers at all, returns False — the caller
	should reject an approval for an unsolicited level.
	"""
	required_levels = [t["level"] for t in (required_tiers or [])]
	if level not in required_levels:
		return False
	approved_levels = set()
	for a in (approvals_so_far or []):
		try:
			approved_levels.add(int(a["level"]))
		except (KeyError, TypeError, ValueError):
			continue
	# All required levels strictly below ``level`` must be approved.
	return all(lvl in approved_levels for lvl in required_levels if lvl < level)


def would_be_double_approve(level: int, approver: str, approvals_so_far) -> bool:
	"""True if ``approver`` already has an approval recorded at ``level``.

	Pure half of the race-prevention guard. The Frappe layer must re-check this
	after acquiring a DB row-lock to close the TOCTOU window.
	"""
	if not approver or not approvals_so_far:
		return False
	for a in approvals_so_far:
		try:
			if int(a["level"]) == level and str(a.get("approver", "")) == approver:
				return True
		except (TypeError, ValueError):
			continue
	return False


def threshold_requires(base_amount, *, enabled: bool, threshold) -> bool:
	"""Does a money-movement document need approval?

	- ``enabled`` False  → never (control switched off).
	- ``threshold`` > 0  → only when base_amount >= threshold.
	- ``threshold`` 0/None/negative → every controlled document (secure default).
	"""
	if not enabled:
		return False
	thr = _to_float(threshold)
	if thr > 0:
		return _to_float(base_amount) >= thr
	return True


def is_self_approval(requested_by, reviewed_by) -> bool:
	"""True when the same user raised and reviewed the request (SoD violation)."""
	if not requested_by or not reviewed_by:
		return False
	return requested_by == reviewed_by


def docstatus_kind(changed_rows) -> str | None:
	"""Map a Version ``changed`` list to a lifecycle kind, if it flips docstatus.

	Returns "submit" (→1), "cancel" (→2), or None (no docstatus change).
	``changed_rows`` is the list of ``[fieldname, old, new]`` triples.
	"""
	for row in changed_rows or []:
		if len(row) >= 3 and row[0] == "docstatus":
			try:
				new_i = int(row[2])
			except (TypeError, ValueError):
				continue
			if new_i == 1:
				return "submit"
			if new_i == 2:
				return "cancel"
	return None


def extract_field_changes(changed_rows, ignore_fields=IGNORE_FIELDS):
	"""Visible field changes from a Version ``changed`` list.

	Drops noise fields and ``docstatus`` (rendered separately as submit/cancel).
	Returns a list of ``{"field", "old", "new"}`` dicts (labels are added later
	by the Frappe layer, which has the doctype meta).
	"""
	out = []
	for row in changed_rows or []:
		if len(row) < 3:
			continue
		field = row[0]
		if field in ignore_fields or field == "docstatus":
			continue
		out.append({"field": field, "old": row[1], "new": row[2]})
	return out


def summarize_version(data: dict, ignore_fields=IGNORE_FIELDS) -> dict:
	"""Pure summary of one parsed Version ``data`` dict.

	Returns:
	  {
	    "kind": "create|edit|submit|cancel",   # 'create' is never produced here
	    "field_changes": [ {field, old, new}, ... ],
	    "child_changes": int,                   # added + removed + row_changed
	    "meaningful": bool,                     # False = only-noise, drop it
	  }
	"""
	changed = data.get("changed") or []
	added = data.get("added") or []
	removed = data.get("removed") or []
	row_changed = data.get("row_changed") or []

	kind = docstatus_kind(changed) or "edit"
	field_changes = extract_field_changes(changed, ignore_fields)
	child_changes = len(added) + len(removed) + len(row_changed)

	# A docstatus flip (submit/cancel) is always meaningful even with no visible
	# field changes. An "edit" with neither field nor child changes is just a
	# timestamp bump and should be dropped.
	meaningful = kind in ("submit", "cancel") or bool(field_changes) or child_changes > 0

	return {
		"kind": kind,
		"field_changes": field_changes,
		"child_changes": child_changes,
		"meaningful": meaningful,
	}
