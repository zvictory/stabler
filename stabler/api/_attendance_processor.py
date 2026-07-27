"""Pure attendance day-processor for Stabler HR (Phase 3).

Turns a single employee-day's raw punches into a classified attendance record.
Frappe-free, so it runs under `python -m unittest`. The Frappe service layer
will: group `Stabler Raw Attendance Event` rows by (employee, date), call
`summarize_day` here, then write ERPNext Employee Checkin / Attendance and any
`Stabler Attendance Exception` rows.

Mirrors anjan-hr's "first-in / last-out daily summary" (Timepay collapses many
gate punches into one entry/exit per day) and feeds the rule engine in
`_attendance_rules`.
"""

from __future__ import annotations

from stabler.api._attendance_rules import (
	HalfDayPolicy,
	LateFeePolicy,
	NightPolicy,
	classify_day,
	compute_late_fee,
	compute_overtime_minutes,
	is_overnight,
	record_worked_min,
)


def _hm(ts: str):
	"""'YYYY-MM-DDTHH:MM[:SS]' -> 'HH:MM', or None."""
	if not ts or not isinstance(ts, str) or "T" not in ts:
		return None
	t = ts.split("T", 1)[1]
	parts = t.split(":")
	if len(parts) < 2:
		return None
	return f"{parts[0]}:{parts[1]}"


def build_daily_record(punches) -> dict:
	"""Collapse a day's punches into {entry, exit, punch_count}.

	entry = time of the first IN (or the earliest punch if no direction);
	exit  = time of the last OUT (or the latest punch). Single punch -> exit None.
	`punches` = list of {timestamp, direction}.
	"""
	rows = [p for p in punches if p.get("timestamp")]
	rows.sort(key=lambda p: p["timestamp"])
	if not rows:
		return {"entry": None, "exit": None, "punch_count": 0}

	ins = [p for p in rows if str(p.get("direction", "")).upper() == "IN"]
	outs = [p for p in rows if str(p.get("direction", "")).upper() == "OUT"]
	entry = _hm(ins[0]["timestamp"]) if ins else _hm(rows[0]["timestamp"])
	exit_ = _hm(outs[-1]["timestamp"]) if outs else (_hm(rows[-1]["timestamp"]) if len(rows) > 1 else None)
	return {"entry": entry, "exit": exit_, "punch_count": len(rows)}


def detect_exceptions(daily, punches) -> list[str]:
	"""Operational anomalies that route a day to the exception queue."""
	out = []
	n = daily.get("punch_count", 0)
	if n == 0:
		out.append("missing_check_in")
		return out
	if daily.get("exit") is None:
		out.append("missing_check_out")
	if n == 1:
		out.append("single_punch")
	if n > 6:
		out.append("excess_punches")  # likely double-swipes; worth a look
	return out


def late_minutes(entry, shift_start_hm, grace_already_applied=False) -> int:
	"""Late minutes = entry - shift start, floored at 0. If the device already
	reports late_min, pass it straight to summarize_day instead."""
	if not entry or not shift_start_hm:
		return 0

	def m(s):
		h, mm = s.split(":")[:2]
		return int(h) * 60 + int(mm)

	try:
		return max(0, m(entry) - m(shift_start_hm))
	except (TypeError, ValueError):
		return 0


def summarize_day(
	punches,
	*,
	shift: str = "DAY",
	shift_start_hm: str | None = "09:00",
	is_holiday: bool = False,
	date_str: str,
	hire_date: str,
	termination_date=None,
	late: LateFeePolicy | None = None,
	half: HalfDayPolicy | None = None,
	night: NightPolicy | None = None,
	min_worked_present: int = 240,
	device_late_min=None,
) -> dict:
	"""Full day summary: entry/exit, worked minutes, status, late fee, overtime,
	night flag, and exception flags. `device_late_min` overrides the computed
	late minutes when the gate already provides it (Timepay does)."""
	late = late or LateFeePolicy()
	half = half or HalfDayPolicy()
	night = night or NightPolicy()

	daily = build_daily_record(punches)
	lm = int(device_late_min) if device_late_min is not None else late_minutes(daily["entry"], shift_start_hm)
	record = {"entry": daily["entry"], "exit": daily["exit"], "late_min": lm, "early_leave_min": 0}

	worked = record_worked_min(record)
	status = classify_day(
		record,
		shift,
		is_holiday,
		late,
		half,
		night,
		date_str,
		hire_date,
		termination_date,
		min_worked_present,
	)
	overtime = compute_overtime_minutes(record, shift, night)
	fee = compute_late_fee(lm, late) if status in ("late_flat", "late_step") else 0.0
	exceptions = detect_exceptions(daily, punches)
	if status == "absent" and daily["punch_count"] > 0:
		exceptions.append("present_but_under_threshold")

	return {
		"date": date_str,
		"entry": daily["entry"],
		"exit": daily["exit"],
		"punch_count": daily["punch_count"],
		"worked_min": worked,
		"status": status,
		"late_min": lm,
		"late_fee_uzs": fee,
		"overtime_min": overtime,
		"is_night": is_overnight(record),
		"exceptions": exceptions,
		"payroll_impacting": status in ("late_flat", "late_step", "half_day", "absent") or overtime > 0,
	}
