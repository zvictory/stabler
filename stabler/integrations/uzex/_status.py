"""Central UZEX portal-status → outcome mapping (WP-303, Frappe-free).

One place decides how a raw portal status becomes an intake result
(won / lost / pending) and which CRM Deal Status it maps to — no per-page or
inline mapping (mirrors the SPA's getStatusBadgeClass discipline on the backend).

Portal statuses are matched first by numeric ``status_id`` (stable), then by a
substring of the localized ``status_name`` (uz/ru) as a fallback for ids we have
not catalogued yet. Anything unrecognised is ``pending`` — we never guess a
terminal outcome.
"""

from __future__ import annotations

from datetime import datetime

WON = "won"
LOST = "lost"
PENDING = "pending"

# Known status_id → outcome (extend as new ids are catalogued from GetTrade).
# id 5 observed = "Буюртмачи томонидан бекор қилинган" (cancelled by customer).
_ID_MAP: dict[int, str] = {
	5: LOST,
}

# Localized name substrings (lower-cased) → outcome, fallback when id is unknown.
_NAME_LOST = ("bekor", "бекор", "rad etil", "отклон", "otkaz", "bekor qiling", "yutqaz")
_NAME_WON = ("g'olib", "ғолиб", "golib", "yutdi", "победит", "won", "awarded", "tanlandi g'olib")


def map_result(status_id=None, status_name: str | None = None) -> str:
	"""Return 'won' | 'lost' | 'pending' for a portal status."""
	try:
		sid = int(status_id) if status_id is not None and str(status_id).strip() != "" else None
	except TypeError, ValueError:
		sid = None
	if sid is not None and sid in _ID_MAP:
		return _ID_MAP[sid]

	name = (status_name or "").strip().lower()
	if name:
		if any(tok in name for tok in _NAME_WON):
			return WON
		if any(tok in name for tok in _NAME_LOST):
			return LOST
	return PENDING


def is_terminal(result: str) -> bool:
	"""won/lost are terminal (a legally-closed lot); pending is not."""
	return result in (WON, LOST)


def deal_status_for(result: str) -> str | None:
	"""CRM Deal Status name for a terminal result, or None for pending.

	Returns the canonical 'Won'/'Lost' status names; None means "leave the deal's
	pipeline status untouched" (an open lot must not be forced backwards).
	"""
	if result == WON:
		return "Won"
	if result == LOST:
		return "Lost"
	return None


def _parse(dt) -> datetime | None:
	if isinstance(dt, datetime):
		return dt
	if not dt or not isinstance(dt, str):
		return None
	for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
		try:
			return datetime.strptime(dt.strip(), fmt)
		except ValueError:
			continue
	return None


def hours_until(deadline, now: datetime) -> float | None:
	"""Hours from ``now`` to ``deadline`` (negative = already passed). None if unparseable."""
	d = _parse(deadline)
	if d is None:
		return None
	return (d - now).total_seconds() / 3600.0


def is_deadline_soon(deadline, now: datetime, threshold_h: float = 48.0) -> bool:
	"""True only for a still-future deadline within ``threshold_h`` hours."""
	h = hours_until(deadline, now)
	if h is None:
		return False
	return 0 < h <= threshold_h
