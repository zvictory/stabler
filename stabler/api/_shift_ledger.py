"""Arithmetic for the Work Order register's header strip. No frappe import.

The strip's other tiles are derived in the SPA from the rows the table is already
showing, so the header can never disagree with the list under it. Downtime cannot
be derived that way, and the reason is in the doctype: `Stabler Line Stop
.work_order` is optional — a line can be stopped with no order on it, and those
are exactly the stops a shift lead cares about. Scoping downtime to the orders on
screen would drop them. So that tile is a company-and-window figure, labelled as
such rather than pretending to belong to the filtered list.
"""

from __future__ import annotations


def _minutes(value) -> float:
	"""`minutes` is not a required field — a stop that is still open has none."""
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def top_stop_contributor(rows) -> dict | None:
	"""The (line, reason) pair that cost the shift the most minutes.

	Grouped and summed, never "the single longest stop". Eight four-minute film
	jams on one line are a line that is not running; one twelve-minute changeover
	on another is a line that is. Naming the changeover because it is the longest
	single row sends the supervisor to the wrong machine.

	Grouped by line AND reason: "Line 2 lost 50 minutes" is true and useless,
	because the reason is the only part anybody can act on.

	Returns None when nothing stopped — the strip renders the context line only
	when there is one, and `— · — · 0 мин` is furniture.
	"""
	totals: dict[tuple[str, str | None], float] = {}
	for row in rows or []:
		line = (row.get("line") or "").strip()
		# `line` is required on the doctype, so a blank one is corrupt data, not
		# a case to model. Naming it would point at a machine nobody can walk to.
		if not line:
			continue
		key = (line, row.get("reason") or None)
		totals[key] = totals.get(key, 0.0) + _minutes(row.get("minutes"))

	if not totals:
		return None

	# Walked in name order and taken on a STRICT improvement, so two lines that
	# lost the same minutes always resolve to the same one and the tile does not
	# flicker between page loads. `reason` is optional, so the sort key coerces
	# it — Python will not compare a str against None.
	best_key: tuple[str, str | None] | None = None
	best_minutes = 0.0
	for key in sorted(totals, key=lambda k: (k[0], k[1] or "")):
		if best_key is None or totals[key] > best_minutes:
			best_key, best_minutes = key, totals[key]

	return {"line": best_key[0], "reason": best_key[1], "minutes": best_minutes}
