"""Pure period-close decision logic — no Frappe, no I/O.

All functions are deterministic given their arguments so they can be tested
with plain ``python -m unittest`` and no bench.  The Frappe layer lives in
``stabler.api.period_close``, which reads config from Stabler Settings and
delegates every rule decision to this module.

Rules
-----
* ``close_date`` blank / None  →  period is never closed (feature is off or
  not yet configured; safe default = always open).
* ``posting_date`` <= ``close_date``  →  closed (boundary is *inclusive*).
* ``has_override=True``  →  posting is allowed regardless of close date
  (used when the caller has confirmed the user holds the override role).
* Garbage / unparseable dates are treated as "no date" (open); the function
  never raises on malformed input.
"""

from __future__ import annotations

import datetime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_date(value) -> datetime.date | None:
	"""Coerce *value* to a ``datetime.date``.

	Accepts:
	  * ``datetime.date`` / ``datetime.datetime``  →  returned as-is (date part).
	  * ISO-8601 string ``"YYYY-MM-DD"``  →  parsed.
	  * Anything else (None, "", garbage)  →  ``None`` (safe).
	"""
	if value is None or value == "":
		return None
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	if isinstance(value, str):
		stripped = value.strip()
		if not stripped:
			return None
		try:
			return datetime.date.fromisoformat(stripped)
		except ValueError:
			return None
	# int, float, unknown objects — treat as no date
	return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_closed(posting_date, close_date) -> bool:
	"""Return ``True`` when *posting_date* falls inside the closed period.

	Parameters
	----------
	posting_date : date-like
	    The date of the transaction being created or edited.
	close_date : date-like
	    The period-close boundary stored in Stabler Settings.  Dates on or
	    before this value are considered closed.

	Returns ``False`` when either date cannot be parsed (safe default = open).
	"""
	cd = _to_date(close_date)
	if cd is None:
		return False		# no close date configured → always open
	pd = _to_date(posting_date)
	if pd is None:
		return False		# unparseable posting date → don't block
	return pd <= cd


def assert_posting_allowed(
	posting_date,
	close_date,
	*,
	has_override: bool = False,
) -> None:
	"""Raise ``ValueError`` when posting into a closed period is not allowed.

	Parameters
	----------
	posting_date : date-like
	    The date of the transaction.
	close_date : date-like
	    The period-close boundary.  Blank / None means the feature is off.
	has_override : bool, keyword-only
	    When ``True`` the caller holds the override role; the guard is
	    bypassed and the function returns silently.

	Raises
	------
	ValueError
	    Human-readable message (the Frappe wrapper translates this to
	    ``frappe.throw``).  Never raised on garbage dates (open by default).
	"""
	if has_override:
		return
	if is_closed(posting_date, close_date):
		cd = _to_date(close_date)
		pd = _to_date(posting_date)
		raise ValueError(
			"Posting into a closed period is not allowed. "
			"Posting date {pd} is on or before the period-close date {cd}. "
			"Ask your administrator to reopen the period or grant you the "
			"Period Close Override role.".format(pd=pd, cd=cd)
		)
