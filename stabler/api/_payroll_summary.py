"""Pure payroll-readiness and monthly rollup helpers for Stabler HR.

No Frappe dependency — runs under plain ``python -m unittest``.

This module closes the gap identified in the anjan-hr migration: payroll
``approve_run`` had zero pre-lock blockers, so open punches, unresolved
exceptions, and unapproved corrections flowed straight into salary. Every
function here is a pure computation over plain dicts/lists; the Frappe
service layer is responsible for hydrating the inputs from doctypes and
persisting the outputs.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# 1. Monthly rollup
# ---------------------------------------------------------------------------

_PRESENT_STATUSES = frozenset({"present", "late_flat", "late_step"})


def rollup_month(daily_summaries) -> dict:
	"""Aggregate a list of per-day ``summarize_day`` dicts into monthly totals.

	All keys are guaranteed present in the output (defaulting to 0).  The
	function is garbage-safe: missing or ``None`` values in a day dict are
	treated as 0 / empty list.

	Args:
		daily_summaries: iterable of dicts as returned by
			``_attendance_processor.summarize_day``.

	Returns a dict with keys:
		present_days, half_days, absent_days, holiday_days, night_days,
		late_count, late_minutes, late_deduction_amount,
		early_leave_minutes, overtime_minutes,
		night_minutes, exceptions_count.
	"""
	present_days = 0
	half_days = 0
	absent_days = 0
	holiday_days = 0
	night_days = 0
	late_count = 0
	late_minutes_total = 0
	late_deduction_amount = 0.0
	early_leave_minutes = 0
	overtime_minutes = 0
	night_minutes = 0
	exceptions_count = 0

	for day in daily_summaries:
		if not isinstance(day, dict):
			continue
		status = day.get("status") or ""
		is_night = bool(day.get("is_night"))
		worked = int(day.get("worked_min") or 0)

		if status in _PRESENT_STATUSES:
			present_days += 1
		elif status == "half_day":
			half_days += 1
		elif status == "absent":
			absent_days += 1
		elif status == "holiday":
			holiday_days += 1

		# night_days = attended AND is_night
		attended = status in _PRESENT_STATUSES or status == "half_day"
		if is_night and attended:
			night_days += 1
			night_minutes += worked

		lm = int(day.get("late_min") or 0)
		if lm > 0:
			late_count += 1
			late_minutes_total += lm

		late_deduction_amount += float(day.get("late_fee_uzs") or 0)
		early_leave_minutes += int(day.get("early_leave_min") or 0)
		overtime_minutes += int(day.get("overtime_min") or 0)
		exceptions_count += len(day.get("exceptions") or [])

	return {
		"present_days": present_days,
		"half_days": half_days,
		"absent_days": absent_days,
		"holiday_days": holiday_days,
		"night_days": night_days,
		"late_count": late_count,
		"late_minutes": late_minutes_total,
		"late_deduction_amount": late_deduction_amount,
		"early_leave_minutes": early_leave_minutes,
		"overtime_minutes": overtime_minutes,
		"night_minutes": night_minutes,
		"exceptions_count": exceptions_count,
	}


# ---------------------------------------------------------------------------
# 2. Period-lock blockers
# ---------------------------------------------------------------------------


def period_blockers(ctx) -> list[dict]:
	"""Return a list of reasons a payroll period MUST NOT be locked.

	Each blocker is ``{code: str, message: str, count: int}``.  An empty list
	means the period is clean and ``can_lock`` will return ``True``.

	Tolerates missing keys in *ctx* (treats them as 0 / False).

	Args:
		ctx: dict with optional keys:
			open_punch_days (int), unresolved_exceptions (int),
			pending_corrections (int), employees_without_summary (int),
			already_locked (bool).
	"""
	if not isinstance(ctx, dict):
		ctx = {}

	blockers = []

	open_punch_days = int(ctx.get("open_punch_days") or 0)
	if open_punch_days > 0:
		blockers.append(
			{
				"code": "open_punches",
				"message": (
					f"{open_punch_days} day(s) have a punch but are missing a check-out. "
					"Resolve before locking."
				),
				"count": open_punch_days,
			}
		)

	unresolved = int(ctx.get("unresolved_exceptions") or 0)
	if unresolved > 0:
		blockers.append(
			{
				"code": "unresolved_exceptions",
				"message": (
					f"{unresolved} attendance exception(s) are still open. Approve or dismiss before locking."
				),
				"count": unresolved,
			}
		)

	pending_corr = int(ctx.get("pending_corrections") or 0)
	if pending_corr > 0:
		blockers.append(
			{
				"code": "unapproved_corrections",
				"message": (
					f"{pending_corr} attendance correction(s) are pending approval. "
					"Approve or reject before locking."
				),
				"count": pending_corr,
			}
		)

	missing = int(ctx.get("employees_without_summary") or 0)
	if missing > 0:
		blockers.append(
			{
				"code": "missing_summaries",
				"message": (
					f"{missing} employee(s) have no attendance summary for this period. "
					"Generate summaries before locking."
				),
				"count": missing,
			}
		)

	already_locked = bool(ctx.get("already_locked"))
	if already_locked:
		blockers.append(
			{
				"code": "already_locked",
				"message": "This period is already locked. Unlock it before re-locking.",
				"count": 1,
			}
		)

	return blockers


# ---------------------------------------------------------------------------
# 3. Lock gate
# ---------------------------------------------------------------------------


def can_lock(ctx) -> bool:
	"""Return ``True`` only when ``period_blockers(ctx)`` is empty."""
	return len(period_blockers(ctx)) == 0


# ---------------------------------------------------------------------------
# 4. Correction payroll-impact classifier
# ---------------------------------------------------------------------------

_PAYROLL_IMPACTING_TYPES = frozenset(
	{
		"check_in",
		"check_out",
		"status",
		"add_attendance",
		"remove_attendance",
		"late_excuse",
		"overtime_adjust",
	}
)


def is_correction_payroll_impacting(
	correction_type: str,
	before_value,
	after_value,
) -> bool:
	"""Return ``True`` when a correction changes a payroll-affecting fact.

	Rules:
	- ``correction_type`` must be in the payroll-impacting set; otherwise
	  returns ``False`` (covers note/remark/comment edits).
	- Returns ``False`` when ``before_value == after_value`` (no real change).
	- String comparison is case-sensitive.
	"""
	if correction_type not in _PAYROLL_IMPACTING_TYPES:
		return False
	if before_value == after_value:
		return False
	return True


# ---------------------------------------------------------------------------
# 5. Salary-component amount helpers
# ---------------------------------------------------------------------------


def night_premium_amount(
	night_minutes: float,
	hourly_rate: float,
	night_premium_pct: float,
) -> float:
	"""UZS premium for time worked on night shifts.

	``night_premium_pct`` is a percentage, e.g. 10.0 means 10 %.
	Result is rounded to the nearest whole UZS (UZS has no fractional units).

	Args:
		night_minutes: total minutes of night work in the period.
		hourly_rate: employee's hourly wage in UZS.
		night_premium_pct: premium percentage (e.g. 10.0 for 10 %).
	"""
	night_minutes = float(night_minutes or 0)
	hourly_rate = float(hourly_rate or 0)
	night_premium_pct = float(night_premium_pct or 0)
	if night_minutes <= 0 or hourly_rate <= 0:
		return 0.0
	raw = (night_minutes / 60.0) * hourly_rate * (night_premium_pct / 100.0)
	return float(math.floor(raw + 0.5))  # round half-up to whole UZS


def overtime_amount(
	overtime_minutes: float,
	hourly_rate: float,
	ot_multiplier: float = 1.0,
) -> float:
	"""UZS payment for overtime minutes.

	Result is rounded to the nearest whole UZS.

	Args:
		overtime_minutes: total OT minutes in the period.
		hourly_rate: employee's hourly wage in UZS.
		ot_multiplier: e.g. 1.5 for time-and-a-half (default 1.0).
	"""
	overtime_minutes = float(overtime_minutes or 0)
	hourly_rate = float(hourly_rate or 0)
	ot_multiplier = float(ot_multiplier if ot_multiplier is not None else 1.0)
	if overtime_minutes <= 0 or hourly_rate <= 0:
		return 0.0
	raw = (overtime_minutes / 60.0) * hourly_rate * ot_multiplier
	return float(math.floor(raw + 0.5))  # round half-up to whole UZS
