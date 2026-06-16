"""Pure gate-event ingestion logic for Stabler HR (Phase 2).

Frappe-free so it runs under plain `python -m unittest`. Implements the two
guarantees the migration DECISIONS require:
  - idempotent processing: an event is keyed by a stable external id; replaying
    a sync never creates a second record for the same punch.
  - explicit employee resolution: a device user maps to an Employee only via the
    effective-dated `Stabler Employee Device Mapping` (no fuzzy FIO fallback);
    unmatched events are routed to the exception queue.

A "raw event" here is a dict with at least: device_id, device_user_id,
timestamp (ISO 'YYYY-MM-DDTHH:MM:SS'), direction ('IN'/'OUT'), and optionally
external_event_id.
"""

from __future__ import annotations

import hashlib


def dedupe_key(event) -> str:
	"""Stable key for an event. Prefer the device's own external id; otherwise
	derive a deterministic hash from the identifying fields so the same physical
	punch always collapses to one key."""
	ext = (event.get("external_event_id") or "").strip()
	if ext:
		return f"ext:{ext}"
	basis = "|".join(str(event.get(k, "")) for k in ("device_id", "device_user_id", "timestamp", "direction"))
	return "h:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def decide_event_action(event, seen_keys) -> str:
	"""'new' if this event's key is unseen, else 'duplicate'. `seen_keys` is any
	container of already-ingested keys (set/dict/list)."""
	return "duplicate" if dedupe_key(event) in seen_keys else "new"


def _date_of(ts: str) -> str:
	"""ISO date portion of a timestamp; '' if unparseable."""
	if not ts or not isinstance(ts, str):
		return ""
	return ts[:10] if len(ts) >= 10 else ""


def is_mapping_active(mapping_row, on_date: str) -> bool:
	"""Effective-dated check: active_from <= on_date <= active_to (open-ended ok),
	and status not explicitly inactive."""
	if not on_date:
		return False
	if str(mapping_row.get("status", "Active")).lower() in ("inactive", "disabled", "0"):
		return False
	af = mapping_row.get("active_from") or ""
	at = mapping_row.get("active_to") or ""
	if af and on_date < af:
		return False
	if at and on_date > at:
		return False
	return True


def resolve_employee(event, mappings) -> str | None:
	"""Return the ERPNext Employee for this event, or None (→ exception queue).

	`mappings` is a list of dicts: {device_id?, device_user_id, employee,
	active_from?, active_to?, status?}. Match on device_user_id (the Timepay/
	device user), honouring device scoping when the mapping specifies a device,
	and effective dates. No name matching here — that belongs to the one-time
	reconciliation, not the hot path."""
	duid = str(event.get("device_user_id", "")).strip()
	if not duid:
		return None
	on_date = _date_of(event.get("timestamp", ""))
	dev = str(event.get("device_id", "")).strip()
	candidates = []
	for m in mappings:
		if str(m.get("device_user_id", "")).strip() != duid:
			continue
		mdev = str(m.get("device_id", "")).strip()
		if mdev and dev and mdev != dev:
			continue  # mapping is scoped to a different device
		if is_mapping_active(m, on_date):
			candidates.append(m)
	if len(candidates) == 1:
		return candidates[0].get("employee") or None
	# 0 candidates -> unmatched; >1 -> ambiguous mapping (also unresolved, flag it)
	return None


def mapping_rows_from_reconciliation(matched_rows):
	"""Transform confirmed reconciliation rows (timepay_id, erpnext_employee[,
	phone]) into Stabler Employee Device Mapping seed rows. The Timepay employee
	id IS the device user id."""
	out = []
	for r in matched_rows:
		duid = str(r.get("timepay_id") or r.get("device_user_id") or "").strip()
		emp = str(r.get("erpnext_employee") or r.get("employee") or "").strip()
		if not duid or not emp:
			continue
		out.append({
			"device_user_id": duid,
			"employee": emp,
			"phone": (r.get("phone") or "").strip(),
			"status": "Active",
			"active_from": (r.get("active_from") or "").strip(),
			"active_to": "",
		})
	return out
