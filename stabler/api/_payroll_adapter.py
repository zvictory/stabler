"""Pure mapping from Stabler attendance/employee/rule-set data onto the
`calculate_payroll` input contract — no Frappe dependency, unit-testable.

This is the bridge between Stabler's `Stabler Payroll Attendance Summary` /
`Employee` custom fields / `Stabler Attendance Rule Set` and the ported anjan-hr
payroll engine in `_payroll_calc.calculate_payroll`.

Conservative defaults so a tenant that has not configured the optional payroll
policy (region rates, KPI split) gets sensible numbers:
  - kpi_share_pct defaults to 0  → NO base withholding (full base flows to gross);
    a tenant using the KPI-pool model sets it on the rule set later.
  - region_rates defaults to {}  → region allowance 0 until rates are configured.
  - ot_multiplier defaults to "1".
"""

from __future__ import annotations


def build_calc_input(
	employee: dict,
	summary: dict,
	ruleset: dict | None = None,
	*,
	adjustments=None,
	kpi_performance_pct=None,
	duty_supplements=None,
) -> dict:
	"""Assemble the dict that `_payroll_calc.calculate_payroll` expects.

	employee — already-normalized pay fields (base_salary, stake_coefficient,
	  work_mode, region, heavy_conditions, additional_duties, allowance_config,
	  hire_date).
	summary  — Stabler Payroll Attendance Summary fields (present_days, absent_days,
	  half_days, overtime_minutes, night_minutes, late_deduction_amount,
	  payroll_period; optional expected_days / night_hours_worked overrides).
	ruleset  — `Stabler Attendance Rule Set` as_dict (or None).
	"""
	rs = ruleset or {}
	present = int(summary.get("present_days") or 0)
	half = int(summary.get("half_days") or 0)
	absent = int(summary.get("absent_days") or 0)
	expected = summary.get("expected_days")
	if not expected:
		expected = present + half + absent

	if summary.get("night_hours_worked") is not None:
		night_hours = str(summary["night_hours_worked"])
	else:
		night_hours = str(float(summary.get("night_minutes") or 0) / 60.0)

	emp = {
		"base_salary": employee.get("base_salary") or "0",
		"stake_coefficient": employee.get("stake_coefficient") or "1",
		"work_mode": employee.get("work_mode") or "SHIFT_8H",
		"region": employee.get("region") or "NO_TRAVEL",
		"heavy_conditions": bool(employee.get("heavy_conditions")),
		"additional_duties": bool(employee.get("additional_duties")),
		"allowance_config": employee.get("allowance_config"),
		"hire_date": employee.get("hire_date"),
	}
	summ = {
		"period": summary.get("period") or summary.get("payroll_period"),
		"attended_days": present + half,
		"expected_days": int(expected),
		"full_days": present,
		"half_days": half,
		"night_hours_worked": night_hours,
		"ot_minutes_worked": str(summary.get("overtime_minutes") or 0),
		"fee_uzs": str(summary.get("late_deduction_amount") or 0),
	}
	night_premium = rs.get("night_premium_pct")
	policies = {
		"night": {
			"night_premium_pct": night_premium if night_premium is not None else "10",
			"ot_multiplier": rs.get("ot_multiplier") or "1",
		},
		"kpi": {"kpi_share_pct": rs.get("kpi_share_pct") or "0"},
		"region_rates": rs.get("region_rates") or {},
	}
	return {
		"employee": emp,
		"summary": summ,
		"policies": policies,
		"adjustments": adjustments or [],
		"kpi_performance_pct": kpi_performance_pct,
		"duty_supplements": duty_supplements or [],
	}
