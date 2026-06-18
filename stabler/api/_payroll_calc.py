"""Pure Python payroll calculation — no Frappe dependency.

Faithfully ported from anjan-hr:
  lib/payroll/calculate.ts   — calculatePayroll, getYearsOfService, getSeniorityPercent
  lib/payroll/round.ts       — roundMoney  (ROUND_HALF_UP to 0 dp)
  lib/payroll/schedule.ts    — resolveSchedule
  lib/employees/allowance-config.ts — parseAllowanceConfig

All money arithmetic uses decimal.Decimal.  Float is NEVER used for monetary
values.  round_money() is the ONLY place where a Decimal is reduced to whole
UZS (0 decimal places, ROUND_HALF_UP), and it is called ONLY once — on the
final net — mirroring the single round in calculate.ts.

Input shapes (plain dicts — snake_case equivalents of the TS camelCase types):

employee dict keys:
  base_salary            str | Decimal
  stake_coefficient      str | Decimal   (default "1")
  work_mode              str             (SHIFT_8H | SHIFT_12H | HALF_RATE | FLEXIBLE | REMOTE)
  region                 str             (CITY | DISTRICT | FAR_DISTRICT | NO_TRAVEL)
  heavy_conditions       bool            (default False)
  additional_duties      bool            (default False)
  allowance_config       dict | str | None
  hire_date              str (ISO yyyy-mm-dd) | None

summary dict keys:
  period                 str  "YYYY-MM"
  attended_days          int
  expected_days          int
  night_hours_worked     str | Decimal   (default "0")
  ot_minutes_worked      str | Decimal   (default "0")
  full_days              int | None      (defaults to attended_days)
  half_days              int | None      (default 0)
  fee_uzs                str | Decimal   (default "0")

adjustments list — each item is a dict:
  type    str   — one of: OVERTIME KPI BONUS FINE ALLOWANCE_SENIORITY
                         ALLOWANCE_NIGHT ALLOWANCE_OTHER TRAVEL_ALLOWANCE ADVANCE
  amount  str | Decimal

policies dict | None:
  night:
    night_premium_pct   str | Decimal   (e.g. "10.00")
    ot_multiplier       str | Decimal   (e.g. "1.50")
  kpi:
    kpi_share_pct       str | Decimal   (e.g. "40.00")
  region_rates:
    CITY / DISTRICT / FAR_DISTRICT / NO_TRAVEL  → str | Decimal per-day rate

kpi_performance_pct     str | Decimal | None    (0–100)

duty_supplements list | None — each item:
  id    str
  pct   str | Decimal   (e.g. "25")
  note  str | None

Returns a dict with keys matching PayrollLineInput / PayrollBreakdown:
  base_salary, prorated_base, allowances, overtime, kpi, duty_supplement,
  bonus, fines, advance, net, breakdown (dict of all audit fields).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


# ---------------------------------------------------------------------------
# Work-mode constants (mirror Prisma WorkMode enum)
# ---------------------------------------------------------------------------

SHIFT_8H = "SHIFT_8H"
SHIFT_12H = "SHIFT_12H"
HALF_RATE = "HALF_RATE"
FLEXIBLE = "FLEXIBLE"
REMOTE = "REMOTE"

# Region constants
CITY = "CITY"
DISTRICT = "DISTRICT"
FAR_DISTRICT = "FAR_DISTRICT"
NO_TRAVEL = "NO_TRAVEL"

# Adjustment type constants
ADJ_OVERTIME = "OVERTIME"
ADJ_KPI = "KPI"
ADJ_BONUS = "BONUS"
ADJ_FINE = "FINE"
ADJ_ALLOWANCE_SENIORITY = "ALLOWANCE_SENIORITY"
ADJ_ALLOWANCE_NIGHT = "ALLOWANCE_NIGHT"
ADJ_ALLOWANCE_OTHER = "ALLOWANCE_OTHER"
ADJ_TRAVEL_ALLOWANCE = "TRAVEL_ALLOWANCE"
ADJ_ADVANCE = "ADVANCE"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	"""Convert value to Decimal. Accepts str, int, float, Decimal, None."""
	if value is None:
		return Decimal(0)
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _js_str(value: Decimal) -> str:
	"""Serialize a Decimal to a string matching Decimal.js .toString() behaviour.

	Decimal.js .toString() strips trailing zeros after the decimal point and
	removes the decimal point entirely when there is no fractional part.
	Python's str(Decimal) preserves all digits (including trailing zeros) that
	were accumulated during arithmetic, and may also produce scientific notation
	for zero values (e.g. '0E-29'). Both diverge from Decimal.js.

	Examples:
	  Decimal('3600000.0000') → '3600000'
	  Decimal('0.40')         → '0.4'
	  Decimal('0.10')         → '0.1'
	  Decimal('0.00')         → '0'
	  Decimal('0E-29')        → '0'
	  Decimal('15.00')        → '15'
	  Decimal('54545.454...')  → '54545.454...' (no trailing zeros → unchanged)
	"""
	s = str(value)
	# Python Decimal may produce scientific notation (e.g. '0E-29', '1E+7').
	# Convert to fixed-point first, then strip trailing zeros.
	if 'E' in s or 'e' in s:
		s = format(value, 'f')
	if '.' in s:
		s = s.rstrip('0').rstrip('.')
	return s


# ---------------------------------------------------------------------------
# round_money — mirrors round.ts: ROUND_HALF_UP to 0 decimal places
# ---------------------------------------------------------------------------

def round_money(value: Decimal) -> Decimal:
	"""Round to nearest whole UZS using ROUND_HALF_UP (arithmetic rounding).

	Mirrors roundMoney() in round.ts:
	  value.toDecimalPlaces(0, Prisma.Decimal.ROUND_HALF_UP)

	Python's decimal.ROUND_HALF_UP rounds half away from zero, which matches
	Decimal.js ROUND_HALF_UP (which also rounds half away from zero).

	Examples:
	  1234.50 → 1235
	  1234.49 → 1234
	 -1234.50 → -1235  (away from zero)
	 -1234.49 → -1234
	"""
	return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# parse_allowance_config — mirrors allowance-config.ts parseAllowanceConfig
# ---------------------------------------------------------------------------

def parse_allowance_config(json_val: Any) -> dict:
	"""Parse allowance config JSON into a normalised dict.

	Mirrors parseAllowanceConfig — on any parse error returns {custom: []}.

	Returned shape:
	  {
	    "seniority": Decimal | None,
	    "night": {"per_hour": Decimal} | None,
	    "custom": [{"name": str, "amount": Decimal, "note": str|None}, ...]
	  }
	"""
	_empty = {"seniority": None, "night": None, "custom": []}

	if json_val is None:
		return _empty

	if isinstance(json_val, str):
		try:
			json_val = json.loads(json_val)
		except (json.JSONDecodeError, TypeError):
			return _empty

	if not isinstance(json_val, dict):
		return _empty

	# seniority
	seniority = None
	if "seniority" in json_val and json_val["seniority"] is not None:
		try:
			val = _d(json_val["seniority"])
			if val >= 0:
				seniority = val
		except Exception:
			pass

	# night
	night = None
	night_raw = json_val.get("night")
	if isinstance(night_raw, dict) and "perHour" in night_raw:
		try:
			ph = _d(night_raw["perHour"])
			if ph >= 0:
				night = {"per_hour": ph}
		except Exception:
			pass
	# also accept snake_case per_hour from Python callers
	if night is None and isinstance(night_raw, dict) and "per_hour" in night_raw:
		try:
			ph = _d(night_raw["per_hour"])
			if ph >= 0:
				night = {"per_hour": ph}
		except Exception:
			pass

	# custom
	custom = []
	for item in json_val.get("custom", []):
		if not isinstance(item, dict):
			continue
		name = item.get("name", "")
		if not name:
			continue
		try:
			amount = _d(item.get("amount", 0))
		except Exception:
			continue
		if amount < 0:
			continue
		note = item.get("note") or None
		custom.append({"name": name, "amount": amount, "note": note})

	return {"seniority": seniority, "night": night, "custom": custom}


# ---------------------------------------------------------------------------
# years_of_service — mirrors getYearsOfService in calculate.ts
# ---------------------------------------------------------------------------

def years_of_service(hire_date_iso: str | None, period: str) -> int:
	"""Return completed years of service as of the last day of *period*.

	Mirrors getYearsOfService(hireDate: Date, period: string).

	Args:
		hire_date_iso: ISO date string "yyyy-mm-dd" or None/invalid.
		period:        "YYYY-MM" string.

	Returns:
		int >= 0, or 0 for null/invalid hire_date.
	"""
	if not hire_date_iso:
		return 0

	try:
		hire = date.fromisoformat(str(hire_date_iso)[:10])
	except (ValueError, TypeError):
		return 0

	try:
		period_year, period_month = (int(x) for x in period.split("-"))
	except (ValueError, AttributeError):
		return 0

	# Last day of period month (mirrors new Date(UTC(periodYear, periodMonth, 0)).getUTCDate())
	# In JS: new Date(UTC(year, month, 0)) where month is 1-indexed → last day of that month.
	import calendar
	last_day = calendar.monthrange(period_year, period_month)[1]

	hire_year = hire.year
	hire_month = hire.month  # 1-indexed (same as TS after accounting for getUTCMonth() 0-indexed)
	hire_day = hire.day

	years = period_year - hire_year

	# TS: periodMonth0 = periodMonth - 1 (0-indexed)
	# Adjust if hire month/day is AFTER the period month/last day
	# TS condition: periodMonth0 < hireMonth [0-indexed] OR (equal month AND lastDay < hireDay)
	# In Python (1-indexed months): period_month < hire_month OR (equal month AND last_day < hire_day)
	if period_month < hire_month or (period_month == hire_month and last_day < hire_day):
		years -= 1

	return max(0, years)


# ---------------------------------------------------------------------------
# seniority_percent — mirrors getSeniorityPercent in calculate.ts
# ---------------------------------------------------------------------------

def seniority_percent(years: int) -> Decimal:
	"""Return the seniority rate as a Decimal fraction.

	Brackets (mirroring getSeniorityPercent):
	  >= 11 → 0.50
	  >=  6 → 0.30
	  >=  4 → 0.20
	  >=  1 → 0.10
	       → 0.00
	"""
	if years >= 11:
		return Decimal("0.50")
	if years >= 6:
		return Decimal("0.30")
	if years >= 4:
		return Decimal("0.20")
	if years >= 1:
		return Decimal("0.10")
	return Decimal("0.00")


# ---------------------------------------------------------------------------
# resolve_schedule — mirrors resolveSchedule in schedule.ts
# ---------------------------------------------------------------------------

def resolve_schedule(work_mode: str, stake_coefficient: Decimal) -> dict:
	"""Map work_mode + stake_coefficient to schedule parameters.

	Returns dict:
	  {
	    "hours_per_day": int,
	    "stake": Decimal,
	    "proration": "attendance" | "full",
	    "late_fees_apply": bool,
	  }

	Mirrors ResolvedSchedule / resolveSchedule from schedule.ts.
	"""
	if work_mode == SHIFT_8H:
		return {
			"hours_per_day": 8,
			"stake": Decimal("1"),
			"proration": "attendance",
			"late_fees_apply": True,
		}
	elif work_mode == SHIFT_12H:
		return {
			"hours_per_day": 12,
			"stake": Decimal("1"),
			"proration": "attendance",
			"late_fees_apply": True,
		}
	elif work_mode == HALF_RATE:
		return {
			"hours_per_day": 8,
			"stake": stake_coefficient,
			"proration": "attendance",
			"late_fees_apply": True,
		}
	elif work_mode == FLEXIBLE:
		return {
			"hours_per_day": 8,
			"stake": Decimal("1"),
			"proration": "full",
			"late_fees_apply": False,
		}
	elif work_mode == REMOTE:
		return {
			"hours_per_day": 8,
			"stake": Decimal("1"),
			"proration": "full",
			"late_fees_apply": False,
		}
	else:
		# Default: treat unknown as SHIFT_8H (back-compat invariant)
		return {
			"hours_per_day": 8,
			"stake": Decimal("1"),
			"proration": "attendance",
			"late_fees_apply": True,
		}


# ---------------------------------------------------------------------------
# calculate_payroll — mirrors calculatePayroll in calculate.ts
# ---------------------------------------------------------------------------

def calculate_payroll(inp: dict) -> dict:
	"""Calculate payroll for one employee in one period.

	Args:
		inp: dict with keys:
		  employee       dict
		  summary        dict
		  adjustments    list[dict]
		  policies       dict | None  (optional)
		  kpi_performance_pct  str | Decimal | None  (optional)
		  duty_supplements     list[dict] | None     (optional)

	Returns:
		dict with keys:
		  base_salary, prorated_base, allowances, overtime, kpi,
		  duty_supplement, bonus, fines, advance, net  — all Decimal
		  breakdown — dict of audit fields (all values are str or primitive)
	"""
	employee = inp["employee"]
	summary = inp["summary"]
	adjustments = inp.get("adjustments", [])
	policies = inp.get("policies")
	kpi_performance_pct_raw = inp.get("kpi_performance_pct")
	duty_supplements_raw = inp.get("duty_supplements") or []

	# ------------------------------------------------------------------ #
	# 0. Resolve work schedule
	# ------------------------------------------------------------------ #
	work_mode = employee.get("work_mode") or SHIFT_8H
	stake_coeff = _d(employee.get("stake_coefficient") or "1")
	sched = resolve_schedule(work_mode, stake_coeff)

	base_salary = _d(employee.get("base_salary") or "0")
	effective_base = base_salary * sched["stake"]

	attended_days = int(summary.get("attended_days") or 0)
	expected_days = int(summary.get("expected_days") or 0)

	# Half-day / full-day counts — fall back to full attended_days
	full_days_raw = summary.get("full_days")
	half_days_raw = summary.get("half_days")
	full_days = int(full_days_raw) if full_days_raw is not None else attended_days
	half_days = int(half_days_raw) if half_days_raw is not None else 0

	# ------------------------------------------------------------------ #
	# 1. Attendance Ratio — uses half-day proration
	#    FLEXIBLE/REMOTE: force ratio = 1
	# ------------------------------------------------------------------ #
	effective_days = _d(full_days) + _d(half_days) * Decimal("0.5")

	if sched["proration"] == "full":
		attendance_ratio = Decimal("1")
	elif expected_days > 0:
		attendance_ratio = effective_days / _d(expected_days)
	else:
		attendance_ratio = Decimal("0")

	# isZeroAttended: for FLEXIBLE/REMOTE always False (they still get allowances)
	if sched["proration"] == "full":
		is_zero_attended = False
	else:
		is_zero_attended = (attended_days == 0)

	# ------------------------------------------------------------------ #
	# 2. Prorated Effective Base
	# ------------------------------------------------------------------ #
	prorated_base = effective_base * attendance_ratio

	# Per-employee expected hours: hoursPerDay × expectedDays
	personal_expected_hours = _d(expected_days) * _d(sched["hours_per_day"])

	# ------------------------------------------------------------------ #
	# Parse allowance config
	# ------------------------------------------------------------------ #
	config = parse_allowance_config(employee.get("allowance_config"))

	# ------------------------------------------------------------------ #
	# 3. Base allowances
	# ------------------------------------------------------------------ #
	seniority_allowance = Decimal("0")
	seniority_years_val: int | None = None
	seniority_percent_val: Decimal | None = None

	if not is_zero_attended:
		hire_date_raw = employee.get("hire_date")
		if hire_date_raw:
			yrs = years_of_service(str(hire_date_raw)[:10], summary["period"])
			pct = seniority_percent(yrs)
			seniority_years_val = yrs
			seniority_percent_val = pct
			seniority_allowance = prorated_base * pct
		else:
			# flat config seniority (no hireDate)
			cfg_seniority = config.get("seniority")
			if cfg_seniority is not None:
				seniority_allowance = cfg_seniority
			# seniority_years_val and seniority_percent_val remain None

	# Night premium factor
	if policies and policies.get("night") and policies["night"].get("night_premium_pct") is not None:
		night_premium_factor = _d(policies["night"]["night_premium_pct"]) / Decimal("100")
		night_premium_pct_str = _js_str(_d(policies["night"]["night_premium_pct"]))
	else:
		night_premium_factor = Decimal("0.10")
		night_premium_pct_str = "10"

	if personal_expected_hours > 0:
		night_rate_per_hour = effective_base / personal_expected_hours * night_premium_factor
	else:
		cfg_night = config.get("night")
		night_rate_per_hour = _d(cfg_night["per_hour"]) if cfg_night else Decimal("0")

	night_hours_worked = _d(summary.get("night_hours_worked") or "0")
	if is_zero_attended:
		night_allowance = Decimal("0")
	else:
		night_allowance = night_rate_per_hour * night_hours_worked

	# Region transport allowance — NO_TRAVEL → 0
	region = employee.get("region") or CITY
	if region == NO_TRAVEL:
		region_rate_per_day = Decimal("0")
	elif policies and policies.get("region_rates") and region in policies["region_rates"]:
		region_rate_per_day = _d(policies["region_rates"][region])
	else:
		region_rate_per_day = Decimal("0")

	if is_zero_attended:
		transport = Decimal("0")
	else:
		transport = region_rate_per_day * effective_days

	custom_allowances_list = [] if is_zero_attended else config.get("custom", [])
	custom_allowances_sum = sum(
		(_d(c["amount"]) for c in custom_allowances_list),
		Decimal("0"),
	)

	# ------------------------------------------------------------------ #
	# 4. Manual adjustments
	# ------------------------------------------------------------------ #
	def _sum_adj(adj_type: str) -> Decimal:
		return sum(
			(_d(a["amount"]) for a in adjustments if a.get("type") == adj_type),
			Decimal("0"),
		)

	def _has_adj(adj_type: str) -> bool:
		return any(a.get("type") == adj_type for a in adjustments)

	manual_overtime_rows = [a for a in adjustments if a.get("type") == ADJ_OVERTIME]
	has_manual_overtime = len(manual_overtime_rows) > 0
	manual_overtime_sum = sum((_d(a["amount"]) for a in manual_overtime_rows), Decimal("0"))

	# ------------------------------------------------------------------ #
	# KPI v2: 60/40 split
	# ------------------------------------------------------------------ #
	if policies and policies.get("kpi") and policies["kpi"].get("kpi_share_pct") is not None:
		kpi_share_factor = _d(policies["kpi"]["kpi_share_pct"]) / Decimal("100")
	else:
		kpi_share_factor = Decimal("0")

	fixed_share_factor = Decimal("1") - kpi_share_factor
	fixed_base = prorated_base * fixed_share_factor

	kpi_pool = effective_base * kpi_share_factor  # NOT attendance-prorated
	kpi_performance_pct = _d(kpi_performance_pct_raw) if kpi_performance_pct_raw is not None else Decimal("0")
	performance_factor = kpi_performance_pct / Decimal("100")
	auto_kpi = Decimal("0") if is_zero_attended else kpi_pool * performance_factor

	manual_kpi = _sum_adj(ADJ_KPI)
	kpi = auto_kpi + manual_kpi

	# ------------------------------------------------------------------ #
	# Duty supplements
	# ------------------------------------------------------------------ #
	duty_supplement = sum(
		(effective_base * (_d(d["pct"]) / Decimal("100")) for d in duty_supplements_raw),
		Decimal("0"),
	)

	bonus = _sum_adj(ADJ_BONUS)
	fines_from_adj = _sum_adj(ADJ_FINE)

	# Late fee from attendance (suppressed for FLEXIBLE/REMOTE)
	raw_late_fee = _d(summary.get("fee_uzs") or "0")
	late_fee_uzs = raw_late_fee if sched["late_fees_apply"] else Decimal("0")
	fines = fines_from_adj + late_fee_uzs

	# Manual allowance overrides
	manual_seniority_rows = [a for a in adjustments if a.get("type") == ADJ_ALLOWANCE_SENIORITY]
	has_manual_seniority = len(manual_seniority_rows) > 0
	manual_seniority = sum((_d(a["amount"]) for a in manual_seniority_rows), Decimal("0"))

	manual_night_rows = [a for a in adjustments if a.get("type") == ADJ_ALLOWANCE_NIGHT]
	has_manual_night = len(manual_night_rows) > 0
	manual_night = sum((_d(a["amount"]) for a in manual_night_rows), Decimal("0"))

	manual_other = _sum_adj(ADJ_ALLOWANCE_OTHER)
	manual_travel = _sum_adj(ADJ_TRAVEL_ALLOWANCE)

	# Auto overtime
	if personal_expected_hours > 0:
		ot_hourly = effective_base / personal_expected_hours
	else:
		ot_hourly = Decimal("0")

	if policies and policies.get("night") and policies["night"].get("ot_multiplier") is not None:
		ot_multiplier = _d(policies["night"]["ot_multiplier"])
	else:
		ot_multiplier = Decimal("1")

	ot_minutes = _d(summary.get("ot_minutes_worked") or "0")
	if is_zero_attended:
		auto_overtime = Decimal("0")
	else:
		auto_overtime = ot_hourly / Decimal("60") * ot_minutes * ot_multiplier

	resolved_overtime = manual_overtime_sum if has_manual_overtime else auto_overtime

	# ------------------------------------------------------------------ #
	# 5. Resolved allowances
	# ------------------------------------------------------------------ #
	resolved_seniority = manual_seniority if has_manual_seniority else seniority_allowance
	resolved_night = manual_night if has_manual_night else night_allowance

	# Heavy conditions: 20% of prorated base
	heavy_conditions = employee.get("heavy_conditions") or False
	if (not is_zero_attended) and heavy_conditions:
		heavy_conditions_allowance = prorated_base * Decimal("0.20")
	else:
		heavy_conditions_allowance = Decimal("0")

	# Additional duties: 25% of prorated base
	additional_duties = employee.get("additional_duties") or False
	if (not is_zero_attended) and additional_duties:
		additional_duties_allowance = prorated_base * Decimal("0.25")
	else:
		additional_duties_allowance = Decimal("0")

	allowances_sum = (
		resolved_seniority
		+ resolved_night
		+ transport
		+ custom_allowances_sum
		+ heavy_conditions_allowance
		+ additional_duties_allowance
		+ manual_other
		+ manual_travel
	)

	advance = _sum_adj(ADJ_ADVANCE)

	# ------------------------------------------------------------------ #
	# 6. Gross and Net
	# ------------------------------------------------------------------ #
	gross = fixed_base + allowances_sum + resolved_overtime + kpi + duty_supplement + bonus
	raw_net = gross - fines - advance
	net = round_money(raw_net)

	# ------------------------------------------------------------------ #
	# 7. Breakdown dict (mirrors PayrollBreakdown — all string or primitive)
	# ------------------------------------------------------------------ #
	breakdown = {
		"formula_version": "v2",
		"work_mode": work_mode,
		"stake_coefficient": _js_str(sched["stake"]),
		"hours_per_day": sched["hours_per_day"],
		"proration_mode": sched["proration"],
		"effective_base": _js_str(effective_base),
		"base_salary": _js_str(base_salary),
		"attended_days": attended_days,
		"expected_days": expected_days,
		"full_days": full_days,
		"half_days": half_days,
		"attendance_ratio": _js_str(attendance_ratio),
		"prorated_base": _js_str(prorated_base),
		"seniority_allowance": _js_str(seniority_allowance),
		"seniority_years": seniority_years_val,
		"seniority_percent": _js_str(seniority_percent_val) if seniority_percent_val is not None else None,
		"night_hours_worked": _js_str(night_hours_worked),
		"night_rate_per_hour": _js_str(night_rate_per_hour),
		"night_allowance": _js_str(night_allowance),
		"transport": _js_str(transport),
		"custom_allowances": [
			{"name": c["name"], "amount": _js_str(_d(c["amount"]))}
			for c in custom_allowances_list
		],
		"custom_allowances_sum": _js_str(custom_allowances_sum),
		"manual_seniority": _js_str(manual_seniority) if has_manual_seniority else None,
		"manual_night": _js_str(manual_night) if has_manual_night else None,
		"manual_other": _js_str(manual_other),
		"manual_travel": _js_str(manual_travel),
		"heavy_conditions_allowance": _js_str(heavy_conditions_allowance),
		"additional_duties_allowance": _js_str(additional_duties_allowance),
		"advance": _js_str(advance),
		"allowances_sum": _js_str(allowances_sum),
		"overtime": _js_str(resolved_overtime),
		"overtime_minutes": _js_str(ot_minutes),
		"overtime_rate_per_hour": _js_str(ot_hourly),
		"overtime_multiplier": _js_str(ot_multiplier),
		"manual_overtime": _js_str(manual_overtime_sum) if has_manual_overtime else None,
		"night_premium_pct": night_premium_pct_str,
		"duty_supplement": _js_str(duty_supplement),
		"kpi": _js_str(kpi),
		"kpi_auto": _js_str(auto_kpi),
		"kpi_manual": _js_str(manual_kpi),
		"fixed_share_factor": _js_str(fixed_share_factor),
		"kpi_share_factor": _js_str(kpi_share_factor),
		"fixed_base": _js_str(fixed_base),
		"kpi_pool": _js_str(kpi_pool),
		"performance_pct": _js_str(kpi_performance_pct),
		"bonus": _js_str(bonus),
		"late_fee_uzs": _js_str(late_fee_uzs),
		"fines": _js_str(fines),
		"gross": _js_str(gross),
		"net": _js_str(net),
	}

	return {
		"base_salary": base_salary,
		"prorated_base": prorated_base,
		"allowances": allowances_sum,
		"overtime": resolved_overtime,
		"kpi": kpi,
		"duty_supplement": duty_supplement,
		"bonus": bonus,
		"fines": fines,
		"advance": advance,
		"net": net,
		"breakdown": breakdown,
	}
