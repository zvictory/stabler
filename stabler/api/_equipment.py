"""Pure equipment-coverage helpers — no frappe, no DB (unit-testable).

Equipment in the Service module is an ERPNext Serial No (a fridge/freezer/ice
machine placed at a customer). "Coverage" = whether warranty or AMC is still
active. Used by stabler.api.service to classify and summarise the fleet.
"""

from __future__ import annotations

from datetime import date


def _as_date(value):
	if not value:
		return None
	if isinstance(value, date):
		return value
	try:
		return date.fromisoformat(str(value)[:10])
	except ValueError, TypeError:
		return None


def coverage_state(warranty_expiry, amc_expiry, today=None) -> str:
	"""Return 'covered', 'expired', or 'none'.

	- 'none'    → no warranty and no AMC date on record.
	- 'covered' → the later of warranty/AMC expiry is today or in the future.
	- 'expired' → both dates are in the past.
	"""
	cur = _as_date(today) or date.today()
	dates = [d for d in (_as_date(warranty_expiry), _as_date(amc_expiry)) if d]
	if not dates:
		return "none"
	return "covered" if max(dates) >= cur else "expired"


def summarise_coverage(rows, today=None) -> dict:
	"""Count a list of {warranty_expiry_date, amc_expiry_date} rows by coverage."""
	out = {"total": 0, "covered": 0, "expired": 0, "none": 0}
	for r in rows or []:
		state = coverage_state(r.get("warranty_expiry_date"), r.get("amc_expiry_date"), today)
		out["total"] += 1
		out[state] += 1
	return out
