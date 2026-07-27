"""Pure attendance rule engine for Stabler HR.

A faithful, frappe-free reimplementation of the anjan-hr attendance rules
(`lib/timesheet/{overtime,classify,totals}.ts` and
`components/timesheet/night-policy.ts`). No Frappe, no Decimal, no I/O — so it
runs under plain `python -m unittest` as well as `bench run-tests`, and the
anjan-hr `*.test.ts` cases are used as the test oracles.

Design rule (per the migration DECISIONS): every threshold is *configuration*,
passed in via the policy dataclasses below. Nothing is hardcoded — the values
here are only defaults that mirror the anjan-hr Prisma defaults and will live on
the `Stabler Attendance Rule Set` doctype.

A "record" is a dict with at least: entry, exit (HH:MM strings or None),
late_min, early_leave_min (ints). This mirrors the ERPNext/Timepay daily shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

# Worked-minutes floor below which a day with a punch still counts as absent.
# anjan-hr: classify uses `worked < 240` (4h). Configurable via AttendanceRuleSet.
DEFAULT_MIN_WORKED_FOR_PRESENT = 240


@dataclass(frozen=True)
class LateFeePolicy:
	grace_min: int = 10
	step_min: int = 10
	flat_fee: float = 15000.0
	step_fee: float = 5000.0
	daily_cap: float = 50000.0


@dataclass(frozen=True)
class NightPolicy:
	start_hour: int = 20  # OT clock-cutoff for day shifts
	end_hour: int = 8  # OT clock-cutoff for night shifts (next day)
	ot_method: str = "CLOCK_CUTOFF"  # or "DAILY_HOURS"
	ot_threshold_min: int = 0
	night_premium_pct: float = 10.0


@dataclass(frozen=True)
class HalfDayPolicy:
	min_worked_min: int = 240
	anchor_day_h: int = 12
	anchor_night_h: int = 12
	anchor_office_h: int = 12
	anchor_light_h: int = 12


_SHIFTS = ("DAY", "NIGHT", "OFFICE", "LIGHT")


def parse_hm(s):
	"""'HH:MM' -> minutes since midnight, or None. Garbage-safe."""
	if not s or not isinstance(s, str):
		return None
	parts = s.split(":")
	if len(parts) < 2:
		return None
	try:
		h, m = int(parts[0]), int(parts[1])
	except TypeError, ValueError:
		return None
	return h * 60 + m


def record_worked_min(record) -> int:
	"""Minutes worked; overnight (exit < entry) adds the remainder of day 1."""
	a, b = parse_hm(record.get("entry")), parse_hm(record.get("exit"))
	if a is None or b is None:
		return 0
	return (1440 - a) + b if b < a else b - a


def is_overnight(record) -> bool:
	a, b = parse_hm(record.get("entry")), parse_hm(record.get("exit"))
	return a is not None and b is not None and b < a


def effective_late_min(record, night: NightPolicy) -> int:
	"""Timepay reports late vs the daytime anchor; recompute vs NightPolicy for
	overnight records, else pass through the raw late_min."""
	if not is_overnight(record):
		return int(record.get("late_min") or 0)
	a = parse_hm(record.get("entry"))
	if a is None:
		return 0
	return max(0, a - night.start_hour * 60)


def effective_early_leave_min(record, night: NightPolicy) -> int:
	if not is_overnight(record):
		return int(record.get("early_leave_min") or 0)
	b = parse_hm(record.get("exit"))
	if b is None:
		return 0
	return max(0, night.end_hour * 60 - b)


def compute_overtime_minutes(record, shift: str, night: NightPolicy) -> int:
	"""OT minutes for one day. Mirrors lib/timesheet/overtime.ts."""
	a, b = parse_hm(record.get("entry")), parse_hm(record.get("exit"))
	if a is None or b is None:
		return 0

	if night.ot_method == "DAILY_HOURS":
		return max(0, record_worked_min(record) - night.ot_threshold_min)

	# CLOCK_CUTOFF
	worked = (1440 - a) + b if b < a else b - a
	exit_timeline = a + worked
	if shift == "NIGHT":
		end_min = night.end_hour * 60
		cutoff = (1440 + end_min) if a >= end_min else end_min
	else:
		start_min = night.start_hour * 60
		cutoff = a if a >= start_min else start_min
	cutoff += night.ot_threshold_min
	return max(0, exit_timeline - cutoff)


def compute_late_fee(late_min: int, policy: LateFeePolicy) -> float:
	"""UZS late fee for one day. Mirrors totals.ts:computeLateFeeNumber."""
	try:
		late_min = int(late_min)
	except TypeError, ValueError:
		return 0.0
	if late_min <= policy.grace_min:
		return 0.0
	if late_min <= policy.grace_min + policy.step_min:
		return min(policy.flat_fee, policy.daily_cap)
	blocks_over = ceil((late_min - policy.grace_min - policy.step_min) / policy.step_min)
	total = policy.flat_fee + policy.step_fee * blocks_over
	return min(total, policy.daily_cap)


def _anchor_hour(shift: str, half: HalfDayPolicy) -> int:
	return {
		"DAY": half.anchor_day_h,
		"NIGHT": half.anchor_night_h,
		"OFFICE": half.anchor_office_h,
		"LIGHT": half.anchor_light_h,
	}.get(shift, half.anchor_day_h)


def _entry_hour(entry: str):
	m = parse_hm(entry)
	return None if m is None else m // 60


def classify_day(
	record,
	shift: str,
	is_holiday: bool,
	late: LateFeePolicy,
	half: HalfDayPolicy,
	night: NightPolicy,
	date_str: str,
	hire_date: str,
	termination_date=None,
	min_worked_present: int = DEFAULT_MIN_WORKED_FOR_PRESENT,
) -> str:
	"""Day status. Mirrors lib/timesheet/classify.ts:classifyDayClient.

	Returns one of: present, late_flat, late_step, half_day, absent, holiday,
	out_of_employment.
	"""
	if hire_date and date_str < hire_date:
		return "out_of_employment"
	if termination_date and date_str > termination_date:
		return "out_of_employment"
	if is_holiday:
		return "holiday"
	if not record:
		return "absent"
	if record.get("entry") is None or record.get("exit") is None:
		return "absent"

	worked = record_worked_min(record)
	if worked < min_worked_present:
		return "absent"

	if is_overnight(record):
		eff = effective_late_min(record, night)
		if eff > late.grace_min + late.step_min:
			return "late_step"
		if eff > late.grace_min:
			return "late_flat"
		return "present"

	eh = _entry_hour(record.get("entry"))
	if eh is None:
		return "absent"
	if eh >= _anchor_hour(shift, half):
		return "half_day" if worked >= half.min_worked_min else "absent"

	late_min = int(record.get("late_min") or 0)
	if late_min > late.grace_min + late.step_min:
		return "late_step"
	if late_min > late.grace_min:
		return "late_flat"
	return "present"


def _num(d, key, default):
	"""Coerce a Rule Set field to a number, falling back to the default."""
	v = d.get(key)
	if v in (None, ""):
		return default
	try:
		return type(default)(v)
	except TypeError, ValueError:
		return default


def policies_from_ruleset(d) -> tuple:
	"""Map a `Stabler Attendance Rule Set` dict (doc.as_dict()) onto the three
	pure policy objects + the presence threshold. Pure and garbage-safe so the
	Frappe API layer is a thin pass-through.

	Returns (LateFeePolicy, NightPolicy, HalfDayPolicy, min_worked_present).
	"""
	d = d or {}
	late = LateFeePolicy(
		grace_min=_num(d, "grace_min", 10),
		step_min=_num(d, "step_min", 10),
		flat_fee=_num(d, "flat_fee_uzs", 15000.0),
		step_fee=_num(d, "step_fee_uzs", 5000.0),
		daily_cap=_num(d, "daily_cap_uzs", 50000.0),
	)
	otm = d.get("ot_method") or "CLOCK_CUTOFF"
	night = NightPolicy(
		start_hour=_num(d, "night_start_hour", 20),
		end_hour=_num(d, "night_end_hour", 8),
		ot_method=otm if otm in ("CLOCK_CUTOFF", "DAILY_HOURS") else "CLOCK_CUTOFF",
		ot_threshold_min=_num(d, "ot_threshold_min", 0),
		night_premium_pct=_num(d, "night_premium_pct", 10.0),
	)
	half = HalfDayPolicy(
		min_worked_min=_num(d, "half_day_min_worked_min", 240),
		anchor_day_h=_num(d, "anchor_day_h", 12),
		anchor_night_h=_num(d, "anchor_night_h", 12),
		anchor_office_h=_num(d, "anchor_office_h", 12),
		anchor_light_h=_num(d, "anchor_light_h", 12),
	)
	return late, night, half, _num(d, "min_worked_for_present_min", 240)


_ATTENDED = frozenset({"present", "late_flat", "late_step", "half_day"})


def compute_row_totals(records, statuses, night_flags, overtime_minutes, calendar_days, late=None) -> dict:
	"""Per-employee monthly totals. Mirrors totals.ts:computeRowTotals.

	daysWorked + nightDays + absentDays == calendarDays (invariant).
	"""
	days_worked = night_days = 0
	for i, s in enumerate(statuses):
		if s not in _ATTENDED:
			continue
		if i < len(night_flags) and night_flags[i]:
			night_days += 1
		else:
			days_worked += 1
	absent_days = max(0, calendar_days - days_worked - night_days)
	late_count = sum(1 for r in records if int(r.get("late_min") or 0) > 0)
	total_minutes = sum(record_worked_min(r) for r in records)
	worked_hours = round((total_minutes / 60) * 10) / 10
	overtime_min = sum(overtime_minutes)
	if late:
		fee = sum(
			0.0 if r.get("late_excused") else compute_late_fee(int(r.get("late_min") or 0), late)
			for r in records
		)
	else:
		fee = 0.0
	return {
		"days_worked": days_worked,
		"night_days": night_days,
		"absent_days": absent_days,
		"late_count": late_count,
		"worked_hours": worked_hours,
		"overtime_min": overtime_min,
		"fee_uzs": fee,
	}
