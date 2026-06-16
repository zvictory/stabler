"""Pure backup/DR decision logic — no Frappe, no filesystem, no I/O.

Frappe writes backup files named like::

    20260615_120000-anjan_erpstable_com-database.sql.gz
    20260615_120000-anjan_erpstable_com-files.tar
    20260615_120000-anjan_erpstable_com-private-files.tar
    20260615_120000-anjan_erpstable_com-site_config_backup.json

This module turns lists of such names + sizes into the decisions the backup
API needs (group into sets, pick which to delete for retention, decide whether
a restore test is overdue). Keeping it pure makes those rules unit-testable
without a bench — and the retention rule is exactly the kind of thing you do
NOT want to get wrong silently.

Phase 2 additions:
  - ``prune_by_policy``: keep-N-daily + M-weekly retention, returning the set
    keys to delete (complement of the sets to keep).
  - ``restore_test_schedule``: given the last test date and an interval,
    return the next due date (yyyy-mm-dd) and whether it is overdue.
  - ``verify_checksum``: pure pass/fail given expected vs actual hash strings.
"""
from __future__ import annotations

import re

# 14-digit timestamp prefix Frappe uses: YYYYMMDD_HHMMSS
_TS_RE = re.compile(r"^(\d{8}_\d{6})-")

_KIND_SUFFIXES = (
	("database", (".sql.gz", "-database.sql.gz", ".sql")),
	("private-files", ("-private-files.tar",)),
	("files", ("-files.tar",)),
	("config", ("-site_config_backup.json", "site_config_backup.json")),
)


def parse_backup_timestamp(filename: str) -> str | None:
	"""Return the ``YYYYMMDD_HHMMSS`` set key for a backup file, or None."""
	m = _TS_RE.match(filename or "")
	return m.group(1) if m else None


def classify_backup_file(filename: str) -> str:
	"""Coarse kind of a backup file: database / files / private-files / config / other."""
	name = filename or ""
	if name.endswith("-private-files.tar"):
		return "private-files"
	if name.endswith("-files.tar"):
		return "files"
	if name.endswith("-database.sql.gz") or name.endswith(".sql.gz") or name.endswith(".sql"):
		return "database"
	if "site_config_backup" in name:
		return "config"
	return "other"


def human_size(num_bytes) -> str:
	"""Bytes → human string (e.g. '12.3 MB'). Pure, locale-free."""
	try:
		n = float(num_bytes)
	except (TypeError, ValueError):
		return "—"
	for unit in ("B", "KB", "MB", "GB", "TB"):
		if abs(n) < 1024.0:
			return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
		n /= 1024.0
	return f"{n:.1f} PB"


def group_backup_sets(files: list[dict]) -> list[dict]:
	"""Group flat backup files into one entry per timestamp.

	``files``: ``[{"name": str, "size": int, "modified": str}, ...]``.
	Returns sets newest-first::

	    [{"key", "has_database", "has_files", "total_size", "modified", "files": [...]}, ...]
	"""
	sets: dict[str, dict] = {}
	for f in files:
		key = parse_backup_timestamp(f.get("name", ""))
		if not key:
			continue
		entry = sets.setdefault(
			key,
			{
				"key": key,
				"has_database": False,
				"has_files": False,
				"total_size": 0,
				"modified": f.get("modified") or "",
				"files": [],
			},
		)
		kind = classify_backup_file(f["name"])
		if kind == "database":
			entry["has_database"] = True
		if kind in ("files", "private-files"):
			entry["has_files"] = True
		entry["total_size"] += int(f.get("size") or 0)
		entry["modified"] = max(entry["modified"], f.get("modified") or "")
		entry["files"].append(f["name"])
	return sorted(sets.values(), key=lambda s: s["key"], reverse=True)


def select_for_retention(
	set_keys: list[str], *, keep_days: int, keep_min: int, now_ts: str
) -> list[str]:
	"""Which backup-set keys to DELETE.

	Always keep the newest ``keep_min`` sets, whatever their age (so you are
	never left with zero backups). Beyond that, delete sets older than
	``keep_days`` days. ``now_ts`` / keys are ``YYYYMMDD_HHMMSS`` strings.

	keep_days <= 0 disables age-based deletion (keep everything).
	"""
	keys = sorted(set_keys, reverse=True)  # newest first
	protected = set(keys[: max(keep_min, 0)])
	if keep_days is None or keep_days <= 0:
		return []
	cutoff = _shift_days(now_ts, -keep_days)
	to_delete = []
	for k in keys:
		if k in protected:
			continue
		if k < cutoff:
			to_delete.append(k)
	return to_delete


def restore_test_overdue(last_test_date: str | None, *, interval_days: int, today: str) -> bool:
	"""True if the last successful restore test is older than ``interval_days``.

	Dates are ``YYYY-MM-DD``. A never-tested backup (no date) is overdue — an
	untested backup is not a backup you can trust.
	"""
	if interval_days is None or interval_days <= 0:
		return False
	if not last_test_date:
		return True
	return _days_between(last_test_date, today) > interval_days


# ---------------------------------------------------------------------------
# Phase 2: prune_by_policy
# ---------------------------------------------------------------------------

def prune_by_policy(
	set_keys: list[str],
	*,
	keep_daily: int,
	keep_weekly: int,
	now_ts: str,
) -> list[str]:
	"""Return set keys to DELETE under a daily + weekly retention policy.

	Policy:
	  - Keep the newest ``keep_daily`` sets unconditionally (the daily window).
	  - Among older sets, keep one set per ISO calendar week for the newest
	    ``keep_weekly`` distinct weeks.  The *newest* set within each week is
	    kept; the rest may be deleted.
	  - Everything outside both windows is scheduled for deletion.

	``set_keys`` are ``YYYYMMDD_HHMMSS`` strings (the timestamp prefix used by
	Frappe backups).  ``now_ts`` is a ``YYYYMMDD_HHMMSS`` reference time (not
	used in this implementation but kept for API symmetry with
	``select_for_retention`` so callers can supply it consistently).

	``keep_daily`` or ``keep_weekly`` <= 0 disables that tier (keeps nothing
	extra from it — the other tier still applies).

	Returns the list of set_keys to delete (the complement of what to keep).
	"""
	if not set_keys:
		return []

	sorted_keys = sorted(set_keys, reverse=True)  # newest first

	keep: set[str] = set()

	# Tier 1: keep the newest keep_daily sets.
	daily_n = max(int(keep_daily), 0)
	for k in sorted_keys[:daily_n]:
		keep.add(k)

	# Tier 2: among the remainder, keep one set per ISO week for keep_weekly weeks.
	weekly_n = max(int(keep_weekly), 0)
	if weekly_n > 0:
		seen_weeks: dict[tuple, str] = {}  # (year, week) -> best key in that week
		for k in sorted_keys:
			if k in keep:
				continue
			try:
				d = _key_to_date(k)
				iso = d.isocalendar()  # (year, week, weekday)
				yw = (iso[0], iso[1])
				if yw not in seen_weeks:
					seen_weeks[yw] = k
				# Keep only the newest (first encountered in newest-first order).
			except (ValueError, AttributeError):
				continue

		# Take the keep_weekly most-recent ISO weeks.
		recent_weeks = sorted(seen_weeks.keys(), reverse=True)[:weekly_n]
		for yw in recent_weeks:
			keep.add(seen_weeks[yw])

	to_delete = [k for k in sorted_keys if k not in keep]
	return to_delete


# ---------------------------------------------------------------------------
# Phase 2: restore_test_schedule
# ---------------------------------------------------------------------------

def restore_test_schedule(
	last_test_date: str | None,
	*,
	interval_days: int,
	today: str,
) -> dict:
	"""Return scheduling info for the next restore-test.

	Returns a dict::

	    {
	        "next_due": "YYYY-MM-DD",   # date when a restore test is due
	        "overdue": bool,            # True if today >= next_due
	        "days_until_due": int,      # negative when overdue
	        "interval_days": int,
	        "last_test_date": str | None,
	    }

	If ``interval_days`` <= 0 scheduling is disabled:
	``next_due`` is None and ``overdue`` is False.

	If no test has ever been performed (``last_test_date`` is None or empty),
	``next_due`` is ``today`` (i.e. overdue immediately).
	"""
	import datetime as _dt

	iv = int(interval_days) if interval_days is not None else 0
	if iv <= 0:
		return {
			"next_due": None,
			"overdue": False,
			"days_until_due": None,
			"interval_days": iv,
			"last_test_date": last_test_date or None,
		}

	today_d = _dt.datetime.strptime(today, "%Y-%m-%d").date()

	if not last_test_date:
		next_due_d = today_d
	else:
		last_d = _dt.datetime.strptime(last_test_date, "%Y-%m-%d").date()
		next_due_d = last_d + _dt.timedelta(days=iv)

	days_until = (next_due_d - today_d).days
	overdue = days_until <= 0

	return {
		"next_due": next_due_d.strftime("%Y-%m-%d"),
		"overdue": overdue,
		"days_until_due": days_until,
		"interval_days": iv,
		"last_test_date": last_test_date or None,
	}


# ---------------------------------------------------------------------------
# Phase 2: verify_checksum
# ---------------------------------------------------------------------------

def verify_checksum(
	expected: str | None,
	actual: str | None,
	*,
	algorithm: str = "sha256",
) -> dict:
	"""Decide pass/fail for a backup file checksum comparison.

	Returns::

	    {
	        "ok": bool,
	        "algorithm": str,
	        "expected": str | None,
	        "actual": str | None,
	        "reason": str,       # human-readable, e.g. "match", "mismatch", "missing expected"
	    }

	Both values are normalised to lower-case before comparison so hex digests
	from different tools (openssl vs sha256sum) compare correctly.

	Edge cases:
	  - ``expected`` is None/empty → fail with reason "missing expected"
	  - ``actual`` is None/empty → fail with reason "missing actual"
	  - Values equal after normalisation → pass
	  - Values differ → fail with reason "mismatch"
	"""
	algo = (algorithm or "sha256").strip().lower()

	def _norm(v: str | None) -> str:
		return (v or "").strip().lower()

	exp = _norm(expected)
	act = _norm(actual)

	if not exp:
		return {"ok": False, "algorithm": algo, "expected": expected, "actual": actual, "reason": "missing expected"}
	if not act:
		return {"ok": False, "algorithm": algo, "expected": expected, "actual": actual, "reason": "missing actual"}
	if exp == act:
		return {"ok": True, "algorithm": algo, "expected": expected, "actual": actual, "reason": "match"}
	return {"ok": False, "algorithm": algo, "expected": expected, "actual": actual, "reason": "mismatch"}


# ---------------------------------------------------------------------------
# Tiny date helpers (string in / string or int out). Kept dependency-free.
# ---------------------------------------------------------------------------
def _shift_days(now_ts: str, delta_days: int) -> str:
	"""Shift a YYYYMMDD_HHMMSS timestamp by whole days, return same format."""
	import datetime as _dt

	d = _dt.datetime.strptime(now_ts, "%Y%m%d_%H%M%S") + _dt.timedelta(days=delta_days)
	return d.strftime("%Y%m%d_%H%M%S")


def _days_between(start_ymd: str, end_ymd: str) -> int:
	import datetime as _dt

	a = _dt.datetime.strptime(start_ymd, "%Y-%m-%d").date()
	b = _dt.datetime.strptime(end_ymd, "%Y-%m-%d").date()
	return (b - a).days


def _key_to_date(key: str):
	"""Parse a YYYYMMDD_HHMMSS key to a datetime.date."""
	import datetime as _dt
	return _dt.datetime.strptime(key, "%Y%m%d_%H%M%S").date()
