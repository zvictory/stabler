"""The stop log's arithmetic and its seed catalogue. No frappe import on purpose.

Why this exists at all, measured on anjan 2026-08-28, read-only:

    Downtime Entry rows                                     0
    Work Orders with `process_loss_qty` set                  0
    Work Orders with a `scrap_warehouse`                     0
    `BOM Scrap Item` rows                                    0
    Stock Entry rows flagged `is_scrap_item`                 0
    Manufacture entries those zeros are measured against  3757

Nothing on this floor has ever recorded why a line stopped or what it lost.
ERPNext's own `Downtime Entry` cannot record it either: all three of its
required fields are unmet here — `workstation` links to Workstation (0 records),
`operator` links to Employee (439 exist, 0 carry a `user_id`, so no kiosk
operator can be named), and `stop_reason` is a fixed seven-option Select written
for a machine shop (`On-machine press checks`, `Excessive machine set up time`).

So the log is Stabler-side, keyed on the dimensions this floor actually has:
`wip_warehouse` for the line — the same column 1a filters and 1c plans on — and
the signed-in user for who reported it.
"""

from __future__ import annotations

from datetime import datetime

#: A stop longer than this is almost certainly a forgotten timer rather than a
#: stop. The floor runs shifts, not days, and the failure it guards is specific:
#: an operator opens a stop, goes home, and closes it the next morning. Recorded
#: as-is that single row outweighs a month of real stops in any total, and the
#: number that comes out of it is worse than no number.
MAX_STOP_MINUTES = 12 * 60

#: The first catalogue, written to be corrected rather than to be right. Reasons
#: are seeded in English so they can be translated through the same `t()` catalogue
#: as the rest of the UI; anything Zafar adds later is his own words, untranslated,
#: which is correct — a reason nobody on this floor uses the words for is a reason
#: that gets logged as "Other".
#:
#: `kind` splits the two questions the catalogue answers. A line waiting on
#: material is a stop and never a loss; a batch that came out off-spec is a loss
#: and not necessarily a stop. Reasons that are genuinely both carry "Both".
SEED_REASONS = (
	# --- the line is stopped -------------------------------------------------
	("Waiting for material", "Downtime"),
	("Waiting for packaging material", "Downtime"),
	("Filling machine setup or changeover", "Downtime"),
	("Filling machine breakdown", "Downtime"),
	("Freezer or compressor fault", "Both"),
	("Cleaning or CIP", "Downtime"),
	("Power cut", "Both"),
	("Water or steam supply", "Downtime"),
	("Shift handover", "Downtime"),
	("No operator available", "Downtime"),
	("Waiting for quality check", "Downtime"),
	("Planned maintenance", "Downtime"),
	# --- product was lost ----------------------------------------------------
	("Off-spec batch", "Loss"),
	("Melted or thawed product", "Loss"),
	("Packaging damaged", "Loss"),
	("Weight out of tolerance", "Loss"),
	("Spillage", "Loss"),
	("Line start-up and flush", "Loss"),
	("Expired or unusable raw material", "Loss"),
	# --- the escape hatch, last on purpose -----------------------------------
	("Other", "Both"),
)

REASON_KINDS = ("Downtime", "Loss", "Both")


def _as_datetime(value) -> datetime | None:
	if isinstance(value, datetime):
		return value
	text = str(value or "").strip()
	if not text:
		return None
	for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
		try:
			return datetime.strptime(text, fmt)
		except ValueError:
			continue
	return None


def stop_minutes(from_time, to_time) -> float:
	"""Minutes between two stamps, or 0.0 when the pair says nothing.

	Zero rather than a throw: this is the number a screen renders beside a row it
	has already accepted, and a display helper that raises turns one bad row into
	a blank page. `validate_stop` is where a bad pair is refused.
	"""
	start, end = _as_datetime(from_time), _as_datetime(to_time)
	if start is None or end is None or end <= start:
		return 0.0
	return round((end - start).total_seconds() / 60.0, 1)


def validate_stop(from_time, to_time) -> tuple[bool, str]:
	"""Whether this pair of stamps may be written, and why not.

	Returns a reason key rather than a sentence so the caller decides how loud to
	be — the kiosk shows it under the field, the API throws it.
	"""
	start, end = _as_datetime(from_time), _as_datetime(to_time)
	if start is None:
		return False, "missing_start"
	if end is None:
		return False, "missing_end"
	if end == start:
		# A zero-length stop is the double-tap, not an event. Recorded, it inflates
		# the count of stops while adding no minutes — the shape that makes a
		# "stops per shift" figure quietly wrong.
		return False, "zero_length"
	if end < start:
		return False, "ends_before_it_starts"
	if (end - start).total_seconds() / 60.0 > MAX_STOP_MINUTES:
		return False, "too_long"
	return True, ""
