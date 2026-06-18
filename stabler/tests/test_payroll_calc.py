"""Oracle test suite for stabler.api._payroll_calc.

Ported verbatim from anjan-hr/lib/payroll/calculate.test.ts.
Every expected number is taken directly from the TS test file — no invented values.

Run:
    cd /path/to/stabler
    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_payroll_calc -v

Key translation notes
---------------------
* TS camelCase keys → Python snake_case dict keys.
* Prisma.Decimal("...") → decimal.Decimal("...").
* Breakdown string comparisons use Python-computed Decimal values (not TS
  literal strings) for intermediate values that accumulate more precision in
  Python (28 sig digits) than Decimal.js (~20). The *net* (rounded) is always
  compared as an exact integer string.
* Decimal.js .toString() strips trailing zeros; _payroll_calc._js_str() mirrors
  this — all breakdown string fields go through _js_str() since the port bug fix.
"""

from __future__ import annotations

import unittest
from decimal import Decimal, ROUND_HALF_UP

from stabler.api._payroll_calc import (
	calculate_payroll,
	parse_allowance_config,
	resolve_schedule,
	round_money,
	seniority_percent,
	years_of_service,
)


# ---------------------------------------------------------------------------
# Shared fixtures (mirrors fixtures.ts)
# ---------------------------------------------------------------------------

MOCK_EMPLOYEE = {
	"base_salary": "6000000.00",
	"allowance_config": {
		"seniority": 500000,
		"night": {"perHour": 15000},
		"custom": [
			{"name": "Meal allowance", "amount": 300000},
			{"name": "Transport allowance", "amount": 200000},
		],
	},
	"hire_date": None,
	"region": "CITY",
	"work_mode": "SHIFT_8H",
	"stake_coefficient": "1",
}

MOCK_SUMMARY_PERFECT = {
	"period": "2026-05",
	"attended_days": 22,
	"expected_days": 22,
	"night_hours_worked": "0",
	"ot_minutes_worked": "0.00",
	"full_days": 22,
	"half_days": 0,
	"fee_uzs": "0",
}

# Policies with kpiSharePct=0 (back-compat — same as no policies for KPI)
MOCK_POLICIES = {
	"night": {
		"night_premium_pct": "10.00",
		"ot_multiplier": "1.50",
	},
	"kpi": {
		"kpi_share_pct": "0.00",
	},
	"region_rates": {
		"CITY": "5000",
		"DISTRICT": "8000",
		"FAR_DISTRICT": "12000",
		"NO_TRAVEL": "0",
	},
}

# KPI v2 policies — 40% KPI share
KPI_V2_POLICIES = {
	**MOCK_POLICIES,
	"kpi": {
		"kpi_share_pct": "40.00",
	},
}

# ---------------------------------------------------------------------------
# Fixture helpers (mirrors fixtures.ts named exports)
# ---------------------------------------------------------------------------

def _perfect_attendance_fixture():
	return {
		"employee": MOCK_EMPLOYEE,
		"summary": MOCK_SUMMARY_PERFECT,
		"adjustments": [],
	}


def _partial_month_fixture():
	return {
		"employee": MOCK_EMPLOYEE,
		"summary": {
			**MOCK_SUMMARY_PERFECT,
			"attended_days": 15,
			"expected_days": 22,
			"full_days": 15,
			"half_days": 0,
		},
		"adjustments": [],
	}


def _heavy_adjustments_fixture():
	return {
		"employee": MOCK_EMPLOYEE,
		"summary": MOCK_SUMMARY_PERFECT,
		"adjustments": [
			{"type": "BONUS", "amount": "1200000.00"},
			{"type": "KPI",   "amount": "800000.00"},
			{"type": "FINE",  "amount": "300000.00"},
			{"type": "FINE",  "amount": "150000.00"},
			{"type": "FINE",  "amount": "50000.00"},
		],
	}


def _manual_seniority_override_fixture():
	return {
		"employee": MOCK_EMPLOYEE,
		"summary": MOCK_SUMMARY_PERFECT,
		"adjustments": [
			{"type": "ALLOWANCE_SENIORITY", "amount": "800000.00"},
		],
	}


def _zero_attended_fixture():
	return {
		"employee": MOCK_EMPLOYEE,
		"summary": {
			**MOCK_SUMMARY_PERFECT,
			"attended_days": 0,
			"expected_days": 22,
			"full_days": 0,
			"half_days": 0,
		},
		"adjustments": [
			{"type": "BONUS", "amount": "1500000.00"},
			{"type": "KPI",   "amount": "500000.00"},
			{"type": "FINE",  "amount": "200000.00"},
		],
	}


def _night_shift_fixture():
	return {
		"employee": MOCK_EMPLOYEE,
		"summary": {
			**MOCK_SUMMARY_PERFECT,
			"night_hours_worked": "16",
		},
		"adjustments": [],
	}


def _empty_allowance_config_fixture():
	return {
		"employee": {**MOCK_EMPLOYEE, "allowance_config": {"custom": []}},
		"summary": MOCK_SUMMARY_PERFECT,
		"adjustments": [],
	}


def _negative_net_fixture():
	return {
		"employee": MOCK_EMPLOYEE,
		"summary": MOCK_SUMMARY_PERFECT,
		"adjustments": [
			{"type": "FINE", "amount": "8000000.00"},
		],
	}


# ---------------------------------------------------------------------------
# Helper: run calculate_payroll and return (result_dict, breakdown_dict)
# ---------------------------------------------------------------------------

def _run(inp: dict):
	res = calculate_payroll(inp)
	return res, res["breakdown"]


# ===========================================================================
# Case 1: Full month perfect attendance — base + standard allowances
# ===========================================================================

class TestCase01PerfectAttendance(unittest.TestCase):
	"""Mirrors TS: 'computes full month perfect attendance with standard config'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_perfect_attendance_fixture())

	def test_base_salary(self):
		self.assertEqual(self.res["base_salary"], Decimal("6000000"))

	def test_prorated_base(self):
		self.assertEqual(self.res["prorated_base"], Decimal("6000000"))

	def test_allowances(self):
		self.assertEqual(self.res["allowances"], Decimal("1000000"))

	def test_overtime_zero(self):
		self.assertEqual(self.res["overtime"], Decimal("0"))

	def test_kpi_zero(self):
		self.assertEqual(self.res["kpi"], Decimal("0"))

	def test_bonus_zero(self):
		self.assertEqual(self.res["bonus"], Decimal("0"))

	def test_fines_zero(self):
		self.assertEqual(self.res["fines"], Decimal("0"))

	def test_net(self):
		self.assertEqual(self.res["net"], Decimal("7000000"))

	def test_breakdown_gross(self):
		self.assertEqual(self.bd["gross"], "7000000")

	def test_breakdown_formula_version(self):
		self.assertEqual(self.bd["formula_version"], "v2")

	def test_breakdown_seniority_years_null(self):
		self.assertIsNone(self.bd["seniority_years"])

	def test_breakdown_seniority_percent_null(self):
		self.assertIsNone(self.bd["seniority_percent"])


# ===========================================================================
# Case 2: Partial month (15/22) — prorated base
# ===========================================================================

class TestCase02PartialMonth(unittest.TestCase):
	"""Mirrors TS: 'prorates base salary for a partial month attendance'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_partial_month_fixture())

	def test_prorated_base_value(self):
		# proratedBase = 6,000,000 * 15 / 22
		expected = Decimal("6000000") * Decimal("15") / Decimal("22")
		self.assertEqual(self.res["prorated_base"], expected)

	def test_allowances(self):
		self.assertEqual(self.res["allowances"], Decimal("1000000"))

	def test_net(self):
		# net = round(proratedBase + 1,000,000)
		expected_gross = Decimal("6000000") * Decimal("15") / Decimal("22") + Decimal("1000000")
		expected_net = expected_gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		self.assertEqual(self.res["net"], expected_net)
		# TS oracle value
		self.assertEqual(str(self.res["net"]), "5090909")


# ===========================================================================
# Case 3: Heavy adjustments — bonus + KPI + 3 fines
# ===========================================================================

class TestCase03HeavyAdjustments(unittest.TestCase):
	"""Mirrors TS: 'calcules heavy adjustments correctly'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_heavy_adjustments_fixture())

	def test_bonus(self):
		self.assertEqual(self.res["bonus"], Decimal("1200000"))

	def test_kpi(self):
		self.assertEqual(self.res["kpi"], Decimal("800000"))

	def test_fines(self):
		self.assertEqual(self.res["fines"], Decimal("500000"))

	def test_net(self):
		# gross = 6M + 1M + 800k + 1.2M = 9M; fines = 500k; net = 8.5M
		self.assertEqual(self.res["net"], Decimal("8500000"))


# ===========================================================================
# Case 4: Manual seniority override beats config
# ===========================================================================

class TestCase04ManualSeniorityOverride(unittest.TestCase):
	"""Mirrors TS: 'prefers manual seniority allowance override over standard config seniority'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_manual_seniority_override_fixture())

	def test_allowances(self):
		# manual seniority (800k) + meal (300k) + transport (200k) = 1,300,000
		self.assertEqual(self.res["allowances"], Decimal("1300000"))

	def test_breakdown_manual_seniority(self):
		self.assertEqual(self.bd["manual_seniority"], "800000")

	def test_net(self):
		self.assertEqual(self.res["net"], Decimal("7300000"))


# ===========================================================================
# Case 5: Zero attended — net from manual entries only
# ===========================================================================

class TestCase05ZeroAttended(unittest.TestCase):
	"""Mirrors TS: 'calculates zero attended days to be derived from manual entries only'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_zero_attended_fixture())

	def test_prorated_base_zero(self):
		self.assertEqual(self.res["prorated_base"], Decimal("0"))

	def test_allowances_zero(self):
		self.assertEqual(self.res["allowances"], Decimal("0"))

	def test_bonus(self):
		self.assertEqual(self.res["bonus"], Decimal("1500000"))

	def test_kpi(self):
		self.assertEqual(self.res["kpi"], Decimal("500000"))

	def test_fines(self):
		self.assertEqual(self.res["fines"], Decimal("200000"))

	def test_net(self):
		self.assertEqual(self.res["net"], Decimal("1800000"))


# ===========================================================================
# Case 6: Night allowance with night hours worked
# ===========================================================================

class TestCase06NightShift(unittest.TestCase):
	"""Mirrors TS: 'incorporates night hours allowance from config'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_night_shift_fixture())
		# nightRatePerHour = 6,000,000 / 176 * 0.10
		# nightAllowance = 16 * nightRatePerHour
		cls.expected_night = (
			Decimal("6000000") / Decimal("176") * Decimal("0.10") * Decimal("16")
		)

	def test_breakdown_night_allowance(self):
		# Compare as Decimal (Python has more precision than Decimal.js 20-digit repr)
		actual = Decimal(self.bd["night_allowance"])
		self.assertEqual(actual, self.expected_night)

	def test_allowances(self):
		expected_allowances = Decimal("500000") + self.expected_night + Decimal("500000")
		self.assertEqual(self.res["allowances"], expected_allowances)

	def test_net(self):
		# TS oracle: 7054545
		self.assertEqual(str(self.res["net"]), "7054545")


# ===========================================================================
# Case 7: Empty allowance config
# ===========================================================================

class TestCase07EmptyAllowanceConfig(unittest.TestCase):
	"""Mirrors TS: 'handles empty allowance configurations gracefully'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_empty_allowance_config_fixture())

	def test_allowances_zero(self):
		self.assertEqual(self.res["allowances"], Decimal("0"))

	def test_net(self):
		self.assertEqual(self.res["net"], Decimal("6000000"))


# ===========================================================================
# Case 8: Net would be negative
# ===========================================================================

class TestCase08NegativeNet(unittest.TestCase):
	"""Mirrors TS: 'allows negative net and records it in breakdown'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run(_negative_net_fixture())

	def test_net(self):
		self.assertEqual(self.res["net"], Decimal("-1000000"))

	def test_breakdown_net(self):
		self.assertEqual(self.bd["net"], "-1000000")


# ===========================================================================
# Case 9: round_money utility (ROUND_HALF_UP)
# ===========================================================================

class TestCase09RoundMoney(unittest.TestCase):
	"""Mirrors TS roundingMoney utility tests."""

	def test_half_rounds_up(self):
		self.assertEqual(round_money(Decimal("1234.50")), Decimal("1235"))

	def test_below_half_rounds_down(self):
		self.assertEqual(round_money(Decimal("1234.49")), Decimal("1234"))

	def test_just_above_half_rounds_up(self):
		self.assertEqual(round_money(Decimal("1234.5000001")), Decimal("1235"))

	def test_negative_half_rounds_away_from_zero(self):
		# -1234.50 → -1235 (ROUND_HALF_UP rounds half away from zero)
		self.assertEqual(round_money(Decimal("-1234.50")), Decimal("-1235"))

	def test_negative_below_half_rounds_toward_zero(self):
		self.assertEqual(round_money(Decimal("-1234.49")), Decimal("-1234"))


# ===========================================================================
# Case 11-NEW: Half-day proration (10 full + 4 half, expected 22)
# ===========================================================================

class TestCase11HalfDayProration(unittest.TestCase):
	"""Mirrors TS: 'prorates base using half-day weight: (10 + 4*0.5)/22'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {
				**MOCK_SUMMARY_PERFECT,
				"attended_days": 14,
				"full_days": 10,
				"half_days": 4,
				"expected_days": 22,
			},
			"adjustments": [],
		})

	def test_prorated_base(self):
		# effectiveDays = 10 + 4*0.5 = 12; ratio = 12/22
		expected_ratio = Decimal("12") / Decimal("22")
		expected_prorated = Decimal("6000000") * expected_ratio
		self.assertEqual(self.res["prorated_base"], expected_prorated)

	def test_breakdown_full_days(self):
		self.assertEqual(self.bd["full_days"], 10)

	def test_breakdown_half_days(self):
		self.assertEqual(self.bd["half_days"], 4)

	def test_net(self):
		# net = round(proratedBase + 1,000,000 allowances)
		self.assertEqual(str(self.res["net"]), "4272727")


# ===========================================================================
# Case 12-NEW: Region transport CITY with policies (5000/day × effectiveDays)
# ===========================================================================

class TestCase12CityTransport(unittest.TestCase):
	"""Mirrors TS: 'adds region transport allowance for CITY at 5000/day × effectiveDays'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": {**MOCK_EMPLOYEE, "region": "CITY"},
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": MOCK_POLICIES,
		})

	def test_breakdown_transport(self):
		# transport = 5000 * 22 = 110,000
		self.assertEqual(self.bd["transport"], "110000")

	def test_allowances(self):
		# seniority 500k + night 0 + transport 110k + custom 500k = 1,110,000
		self.assertEqual(self.res["allowances"], Decimal("1110000"))

	def test_net(self):
		self.assertEqual(str(self.res["net"]), "7110000")


# ===========================================================================
# Case 13-NEW: feeUZS summed into fines + breakdown.lateFeeUZS
# ===========================================================================

class TestCase13LateFeeUZS(unittest.TestCase):
	"""Mirrors TS: 'includes feeUZS in fines and surfaces lateFeeUZS in breakdown'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {
				**MOCK_SUMMARY_PERFECT,
				"fee_uzs": "30000",
			},
			"adjustments": [
				{"type": "FINE", "amount": "50000"},
			],
		})

	def test_breakdown_late_fee_uzs(self):
		self.assertEqual(self.bd["late_fee_uzs"], "30000")

	def test_fines(self):
		self.assertEqual(self.res["fines"], Decimal("80000"))

	def test_net(self):
		self.assertEqual(str(self.res["net"]), "6920000")


# ===========================================================================
# Case 14: Dynamic seniority brackets from hireDate
# ===========================================================================

class TestCase14SeniorityBrackets(unittest.TestCase):
	"""Mirrors TS: 'calculates dynamic seniority allowance brackets correctly'"""

	def _run_hire(self, hire_date_str):
		return _run({
			"employee": {**MOCK_EMPLOYEE, "hire_date": hire_date_str},
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
		})

	def test_bracket1_2_years_10pct(self):
		# Hired 2024-05-15, period 2026-05 → 2 years → 10%
		# seniorityAllowance = 6,000,000 * 0.10 = 600,000
		res, bd = self._run_hire("2024-05-15")
		self.assertEqual(bd["seniority_allowance"], "600000")
		self.assertEqual(bd["seniority_years"], 2)
		self.assertEqual(bd["seniority_percent"], "0.1")
		self.assertEqual(self.res_allowances(res), Decimal("1100000"))
		self.assertEqual(str(res["net"]), "7100000")

	def res_allowances(self, res):
		return res["allowances"]

	def test_bracket2_4_years_20pct(self):
		# Hired 2022-05-15, period 2026-05 → 4 years → 20%
		# seniorityAllowance = 6,000,000 * 0.20 = 1,200,000
		res, bd = self._run_hire("2022-05-15")
		self.assertEqual(bd["seniority_allowance"], "1200000")

	def test_bracket3_8_years_30pct(self):
		# Hired 2018-05-15, period 2026-05 → 8 years → 30%
		# seniorityAllowance = 6,000,000 * 0.30 = 1,800,000
		res, bd = self._run_hire("2018-05-15")
		self.assertEqual(bd["seniority_allowance"], "1800000")

	def test_bracket4_14_years_50pct(self):
		# Hired 2012-05-15, period 2026-05 → 14 years → 50%
		# seniorityAllowance = 6,000,000 * 0.50 = 3,000,000
		res, bd = self._run_hire("2012-05-15")
		self.assertEqual(bd["seniority_allowance"], "3000000")
		self.assertEqual(bd["seniority_years"], 14)
		self.assertEqual(bd["seniority_percent"], "0.5")

	def test_bracket5_less_than_1_year_0pct(self):
		# Hired 2025-06-15, period 2026-05 → 0 years → 0%
		res, bd = self._run_hire("2025-06-15")
		self.assertEqual(bd["seniority_allowance"], "0")
		# hireDate provided → years=0 (not null), percent='0' (not null)
		self.assertEqual(bd["seniority_years"], 0)
		self.assertEqual(bd["seniority_percent"], "0")


# ===========================================================================
# Case 15: Auto OT = baseSalary/expectedHours/60 × otMinutes × otMultiplier
# ===========================================================================

class TestCase15AutoOvertime(unittest.TestCase):
	"""Mirrors TS: 'auto overtime = baseSalary/expectedHours/60 × otMinutes × otMultiplier'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {**MOCK_SUMMARY_PERFECT, "ot_minutes_worked": "120"},
			"adjustments": [],
			"policies": MOCK_POLICIES,
		})
		# expected = 6,000,000 / 176 / 60 * 120 * 1.50
		cls.expected_ot = (
			Decimal("6000000") / Decimal("176") / Decimal("60")
			* Decimal("120") * Decimal("1.50")
		)

	def test_overtime_value(self):
		self.assertEqual(self.res["overtime"], self.expected_ot)

	def test_breakdown_overtime_minutes(self):
		self.assertEqual(self.bd["overtime_minutes"], "120")

	def test_breakdown_manual_overtime_null(self):
		self.assertIsNone(self.bd["manual_overtime"])


# ===========================================================================
# Case 16: Manual OVERTIME overrides auto OT — no double-count
# ===========================================================================

class TestCase16ManualOvertimeOverride(unittest.TestCase):
	"""Mirrors TS: 'manual OVERTIME adjustment overrides auto OT — no double-count'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {**MOCK_SUMMARY_PERFECT, "ot_minutes_worked": "120"},
			"adjustments": [{"type": "OVERTIME", "amount": "500000"}],
			"policies": MOCK_POLICIES,
		})

	def test_overtime_is_manual(self):
		self.assertEqual(self.res["overtime"], Decimal("500000"))

	def test_breakdown_manual_overtime(self):
		self.assertEqual(self.bd["manual_overtime"], "500000")

	def test_net(self):
		# net = 6M fixed + allowances(1M seniority+custom + 110k CITY transport) + 500k OT
		# = 6M + 1110k + 500k = 7,610,000
		self.assertEqual(str(self.res["net"]), "7610000")


# ===========================================================================
# Case 17: nightPremiumPct drives night allowance (not hardcoded 10%)
# ===========================================================================

class TestCase17NightPremiumPct15(unittest.TestCase):
	"""Mirrors TS: 'nightPremiumPct=15 yields 15% night premium, not hardcoded 10%'"""

	@classmethod
	def setUpClass(cls):
		policies_15 = {
			**MOCK_POLICIES,
			"night": {**MOCK_POLICIES["night"], "night_premium_pct": "15.00"},
		}
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {**MOCK_SUMMARY_PERFECT, "night_hours_worked": "16"},
			"adjustments": [],
			"policies": policies_15,
		})
		# nightAllowance = 6,000,000 / 176 * 0.15 * 16
		cls.expected_night = (
			Decimal("6000000") / Decimal("176") * Decimal("0.15") * Decimal("16")
		)

	def test_breakdown_night_allowance(self):
		actual = Decimal(self.bd["night_allowance"])
		self.assertEqual(actual, self.expected_night)

	def test_breakdown_night_premium_pct(self):
		# Decimal.js strips trailing zeros: '15.00' → '15'
		self.assertEqual(self.bd["night_premium_pct"], "15")


# ===========================================================================
# Case 18: otMinutesWorked=0 → overtime=0 in breakdown
# ===========================================================================

class TestCase18OtMinutesZero(unittest.TestCase):
	"""Mirrors TS: 'otMinutesWorked=0 produces overtime=0 in breakdown'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {**MOCK_SUMMARY_PERFECT, "ot_minutes_worked": "0"},
			"adjustments": [],
			"policies": MOCK_POLICIES,
		})

	def test_overtime_zero(self):
		self.assertEqual(self.res["overtime"], Decimal("0"))

	def test_breakdown_overtime_zero(self):
		self.assertEqual(self.bd["overtime"], "0")

	def test_breakdown_overtime_minutes_zero(self):
		self.assertEqual(self.bd["overtime_minutes"], "0")

	def test_breakdown_manual_overtime_null(self):
		self.assertIsNone(self.bd["manual_overtime"])


# ===========================================================================
# Case 19: TRAVEL_ALLOWANCE adjustment is additive to allowancesSum
# ===========================================================================

class TestCase19TravelAllowance(unittest.TestCase):
	"""Mirrors TS: 'includes TRAVEL_ALLOWANCE adjustment in allowancesSum'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [{"type": "TRAVEL_ALLOWANCE", "amount": "300000"}],
		})

	def test_breakdown_manual_travel(self):
		self.assertEqual(self.bd["manual_travel"], "300000")

	def test_allowances(self):
		# seniority 500k + night 0 + custom 500k + manualTravel 300k = 1,300,000
		self.assertEqual(self.res["allowances"], Decimal("1300000"))

	def test_net(self):
		self.assertEqual(str(self.res["net"]), "7300000")


# ===========================================================================
# Case 20-NEW (v2): 100% attendance + 40% share + 100% perf → invariant
# ===========================================================================

class TestCase20KpiV2Perfect(unittest.TestCase):
	"""Mirrors TS: 'v2: 100% attendance + 40% share + 100% perf → fixedBase + autoKpi = baseSalary'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": KPI_V2_POLICIES,
			"kpi_performance_pct": "100",
		})

	def test_fixed_base(self):
		self.assertEqual(self.bd["fixed_base"], "3600000")

	def test_kpi_pool(self):
		self.assertEqual(self.bd["kpi_pool"], "2400000")

	def test_kpi_auto(self):
		self.assertEqual(self.bd["kpi_auto"], "2400000")

	def test_performance_pct(self):
		self.assertEqual(self.bd["performance_pct"], "100")

	def test_perfect_month_invariant(self):
		# fixedBase + autoKpi = baseSalary
		fixed = Decimal(self.bd["fixed_base"])
		auto_kpi = Decimal(self.bd["kpi_auto"])
		self.assertEqual(fixed + auto_kpi, Decimal("6000000"))

	def test_net(self):
		# gross = 3.6M fixed + 1.11M allowances + 2.4M autoKpi = 7.11M
		self.assertEqual(str(self.res["net"]), "7110000")


# ===========================================================================
# Case 21-NEW (v2): partial performance — share 40%, perf 80%
# ===========================================================================

class TestCase21KpiV2PartialPerf(unittest.TestCase):
	"""Mirrors TS: 'v2: share 40% + perf 80% → correct fixedBase and autoKpi'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": KPI_V2_POLICIES,
			"kpi_performance_pct": "80",
		})

	def test_fixed_base(self):
		self.assertEqual(self.bd["fixed_base"], "3600000")

	def test_kpi_auto(self):
		# kpiPool(2400k) * 0.80 = 1,920,000
		self.assertEqual(self.bd["kpi_auto"], "1920000")

	def test_kpi_share_factor(self):
		# Decimal.js strips trailing zeros: '0.40' → '0.4'
		self.assertEqual(self.bd["kpi_share_factor"], "0.4")

	def test_fixed_share_factor(self):
		self.assertEqual(self.bd["fixed_share_factor"], "0.6")


# ===========================================================================
# Case 22-NEW (v2): partial attendance prorates fixed but not KPI pool
# ===========================================================================

class TestCase22KpiV2PartialAttendance(unittest.TestCase):
	"""Mirrors TS: 'v2: partial attendance prorates fixed but not the KPI pool'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {
				**MOCK_SUMMARY_PERFECT,
				"attended_days": 11,
				"full_days": 11,
				"half_days": 0,
			},
			"adjustments": [],
			"policies": KPI_V2_POLICIES,
			"kpi_performance_pct": "80",
		})

	def test_prorated_base(self):
		self.assertEqual(self.res["prorated_base"], Decimal("3000000"))

	def test_fixed_base_scaled_with_attendance(self):
		# fixedBase = proratedBase(3M) * 0.6 = 1,800,000
		self.assertEqual(self.bd["fixed_base"], "1800000")

	def test_kpi_pool_not_attendance_prorated(self):
		# kpiPool = baseSalary(6M) * 0.4 = 2,400,000 (NOT 3M * 0.4)
		self.assertEqual(self.bd["kpi_pool"], "2400000")

	def test_kpi_auto(self):
		# 2,400,000 * 0.80 = 1,920,000
		self.assertEqual(self.bd["kpi_auto"], "1920000")


# ===========================================================================
# Case 23-NEW (v2): isZeroAttended blocks autoKpi
# ===========================================================================

class TestCase23KpiV2ZeroAttended(unittest.TestCase):
	"""Mirrors TS: 'v2: isZeroAttended blocks autoKpi even with share 40 + perf 100'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": {
				**MOCK_SUMMARY_PERFECT,
				"attended_days": 0,
				"full_days": 0,
				"half_days": 0,
			},
			"adjustments": [],
			"policies": KPI_V2_POLICIES,
			"kpi_performance_pct": "100",
		})

	def test_kpi_zero(self):
		self.assertEqual(self.res["kpi"], Decimal("0"))

	def test_kpi_auto_zero(self):
		self.assertEqual(self.bd["kpi_auto"], "0")

	def test_kpi_manual_zero(self):
		self.assertEqual(self.bd["kpi_manual"], "0")


# ===========================================================================
# Case 24-NEW (v2): absent kpiPerformancePct → autoKpi = 0
# ===========================================================================

class TestCase24KpiV2AbsentPerf(unittest.TestCase):
	"""Mirrors TS: 'v2: absent kpiPerformancePct → autoKpi = 0, only fixedBase flows to gross'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": KPI_V2_POLICIES,
			# kpi_performance_pct omitted
		})

	def test_kpi_auto_zero(self):
		self.assertEqual(self.bd["kpi_auto"], "0")

	def test_kpi_manual_zero(self):
		self.assertEqual(self.bd["kpi_manual"], "0")

	def test_fixed_base(self):
		self.assertEqual(self.bd["fixed_base"], "3600000")

	def test_kpi_zero(self):
		self.assertEqual(self.res["kpi"], Decimal("0"))


# ===========================================================================
# Case 25-NEW (v2): manual KPI adjustment adds on top of autoKpi
# ===========================================================================

class TestCase25KpiV2ManualAdditive(unittest.TestCase):
	"""Mirrors TS: 'v2: manual KPI adjustment adds on top of performance-based autoKpi'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [{"type": "KPI", "amount": "300000"}],
			"policies": KPI_V2_POLICIES,
			"kpi_performance_pct": "80",
		})

	def test_kpi_auto(self):
		# 2400000 * 0.80 = 1,920,000
		self.assertEqual(self.bd["kpi_auto"], "1920000")

	def test_kpi_manual(self):
		self.assertEqual(self.bd["kpi_manual"], "300000")

	def test_kpi_total(self):
		self.assertEqual(self.res["kpi"], Decimal("2220000"))


# ===========================================================================
# Case 26-NEW (v2): absent policies → kpiShareFactor=0 → back-compat
# ===========================================================================

class TestCase26NoPolicesBackCompat(unittest.TestCase):
	"""Mirrors TS: 'v2: absent policies → kpiShareFactor=0 → fixedBase=proratedBase'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [{"type": "KPI", "amount": "400000"}],
			# policies omitted
		})

	def test_kpi_share_factor_zero(self):
		self.assertEqual(self.bd["kpi_share_factor"], "0")

	def test_fixed_base_equals_prorated_base(self):
		self.assertEqual(self.bd["fixed_base"], self.bd["prorated_base"])

	def test_kpi_auto_zero(self):
		self.assertEqual(self.bd["kpi_auto"], "0")

	def test_kpi_manual(self):
		self.assertEqual(self.bd["kpi_manual"], "400000")

	def test_kpi_total(self):
		self.assertEqual(self.res["kpi"], Decimal("400000"))


# ===========================================================================
# Work mode tests
# ===========================================================================

class TestWorkModes(unittest.TestCase):
	"""Mirrors TS describe('work modes') block."""

	# WM1: SHIFT_8H regression
	def test_wm1_shift_8h_same_as_baseline(self):
		"""SHIFT_8H: same result as baseline (no workMode set)."""
		baseline = calculate_payroll({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
		})
		with_mode = calculate_payroll({
			"employee": {
				**MOCK_EMPLOYEE,
				"work_mode": "SHIFT_8H",
				"stake_coefficient": "1",
			},
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
		})
		self.assertEqual(with_mode["net"], baseline["net"])
		self.assertEqual(with_mode["prorated_base"], baseline["prorated_base"])

	# WM2: HALF_RATE stake=0.5
	def test_wm2_half_rate_stake_05(self):
		"""HALF_RATE stake=0.5: effectiveBase and proratedBase are halved."""
		res, bd = _run({
			"employee": {
				**MOCK_EMPLOYEE,
				"base_salary": "6000000",
				"work_mode": "HALF_RATE",
				"stake_coefficient": "0.5",
			},
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
		})
		# effectiveBase = 6,000,000 × 0.5 = 3,000,000
		self.assertEqual(bd["effective_base"], "3000000")
		self.assertEqual(bd["prorated_base"], "3000000")
		self.assertEqual(res["prorated_base"], Decimal("3000000"))

	# WM3: REMOTE zero attendance → full base, lateFeeUZS = 0
	def test_wm3_remote_zero_attendance(self):
		"""REMOTE: zero attendance → proratedBase = full base, lateFeeUZS = 0."""
		res, bd = _run({
			"employee": {
				**MOCK_EMPLOYEE,
				"base_salary": "4000000",
				"allowance_config": {"custom": []},
				"work_mode": "REMOTE",
				"stake_coefficient": "1",
			},
			"summary": {
				**MOCK_SUMMARY_PERFECT,
				"attended_days": 0,
				"full_days": 0,
				"half_days": 0,
				"fee_uzs": "30000",
			},
			"adjustments": [],
		})
		# REMOTE forces attendanceRatio = 1 and isZeroAttended = False
		self.assertEqual(bd["proration_mode"], "full")
		self.assertEqual(bd["prorated_base"], "4000000")
		self.assertEqual(bd["late_fee_uzs"], "0")

	# WM4: FLEXIBLE with late fee suppressed, manual FINE still applies
	def test_wm4_flexible_late_fee_suppressed(self):
		"""FLEXIBLE: auto lateFeeUZS suppressed, manual FINE still deducted."""
		res, bd = _run({
			"employee": {
				**MOCK_EMPLOYEE,
				"work_mode": "FLEXIBLE",
				"stake_coefficient": "1",
			},
			"summary": {
				**MOCK_SUMMARY_PERFECT,
				"fee_uzs": "50000",
			},
			"adjustments": [{"type": "FINE", "amount": "100000"}],
		})
		# Auto late fee suppressed for FLEXIBLE
		self.assertEqual(bd["late_fee_uzs"], "0")
		self.assertEqual(bd["fines"], "100000")
		self.assertEqual(res["fines"], Decimal("100000"))

	# WM5: SHIFT_12H uses 22*12=264 as personalExpectedHours for nightRatePerHour
	def test_wm5_shift_12h_night_rate_basis(self):
		"""SHIFT_12H: nightRatePerHour uses 264h basis (22 days × 12h)."""
		res, bd = _run({
			"employee": {
				**MOCK_EMPLOYEE,
				"base_salary": "6000000",
				"work_mode": "SHIFT_12H",
				"stake_coefficient": "1",
			},
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
		})
		# personalExpectedHours = 22 × 12 = 264
		# nightRatePerHour = 6,000,000 / 264 × 0.10
		expected_nrph = Decimal("6000000") / Decimal("264") * Decimal("0.10")
		actual_nrph = Decimal(bd["night_rate_per_hour"])
		# Compare to 2 decimal places (mirrors TS .toFixed(2) comparison)
		self.assertEqual(
			actual_nrph.quantize(Decimal("0.01")),
			expected_nrph.quantize(Decimal("0.01")),
		)


# ===========================================================================
# Duty supplement tests
# ===========================================================================

class TestDutySupplements(unittest.TestCase):
	"""Mirrors TS describe('dutySupplement') block."""

	def test_ds1_single_25pct(self):
		"""25% of effectiveBase added to gross."""
		# effectiveBase = 6,000,000 × 1 = 6,000,000
		# dutySupplement = 6,000,000 × 0.25 = 1,500,000
		res, bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": MOCK_POLICIES,
			"duty_supplements": [{"id": "ds-1", "pct": "25", "note": "Acting head"}],
		})
		self.assertEqual(bd["duty_supplement"], "1500000")
		# baseline net = 6M + 1.11M (seniority 500k+custom 500k+transport 5k×22=110k) = 7.11M
		# + 1.5M duty = 8,610,000
		self.assertEqual(str(res["net"]), "8610000")

	def test_ds2_multiple_supplements_summed(self):
		"""Multiple duty supplements are summed."""
		# duty1 = 6M × 0.25 = 1.5M; duty2 = 6M × 0.10 = 600k; total = 2.1M
		res, bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": MOCK_POLICIES,
			"duty_supplements": [
				{"id": "ds-1", "pct": "25", "note": None},
				{"id": "ds-2", "pct": "10", "note": None},
			],
		})
		self.assertEqual(bd["duty_supplement"], "2100000")

	def test_ds3_empty_list_returns_zero(self):
		"""No supplements → dutySupplement = 0."""
		res, bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": MOCK_POLICIES,
			"duty_supplements": [],
		})
		self.assertEqual(bd["duty_supplement"], "0")

	def test_ds4_omitted_backward_compat(self):
		"""Omitting duty_supplements (pre-F5 callers) equals empty array."""
		res, bd = _run({
			"employee": MOCK_EMPLOYEE,
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": MOCK_POLICIES,
			# duty_supplements omitted
		})
		self.assertEqual(bd["duty_supplement"], "0")


# ===========================================================================
# NO_TRAVEL region test
# ===========================================================================

class TestNoTravelRegion(unittest.TestCase):
	"""Mirrors TS: 'sets transport to 0 for NO_TRAVEL region regardless of policies'"""

	@classmethod
	def setUpClass(cls):
		cls.res, cls.bd = _run({
			"employee": {**MOCK_EMPLOYEE, "region": "NO_TRAVEL"},
			"summary": MOCK_SUMMARY_PERFECT,
			"adjustments": [],
			"policies": MOCK_POLICIES,
		})

	def test_transport_zero(self):
		self.assertEqual(self.bd["transport"], "0")

	def test_allowances(self):
		# seniority 500k + custom 500k + transport 0 = 1,000,000
		self.assertEqual(self.res["allowances"], Decimal("1000000"))

	def test_net(self):
		self.assertEqual(str(self.res["net"]), "7000000")


# ===========================================================================
# Unit tests for years_of_service, seniority_percent, resolve_schedule
# ===========================================================================

class TestYearsOfService(unittest.TestCase):
	"""Direct unit tests for years_of_service() helper."""

	def test_2_years(self):
		self.assertEqual(years_of_service("2024-05-15", "2026-05"), 2)

	def test_4_years(self):
		self.assertEqual(years_of_service("2022-05-15", "2026-05"), 4)

	def test_8_years(self):
		self.assertEqual(years_of_service("2018-05-15", "2026-05"), 8)

	def test_14_years(self):
		self.assertEqual(years_of_service("2012-05-15", "2026-05"), 14)

	def test_less_than_1_year(self):
		self.assertEqual(years_of_service("2025-06-15", "2026-05"), 0)

	def test_none_returns_zero(self):
		self.assertEqual(years_of_service(None, "2026-05"), 0)

	def test_invalid_iso_returns_zero(self):
		self.assertEqual(years_of_service("not-a-date", "2026-05"), 0)


class TestSeniorityPercent(unittest.TestCase):
	"""Direct unit tests for seniority_percent() helper."""

	def test_0_years(self):
		self.assertEqual(seniority_percent(0), Decimal("0.00"))

	def test_1_year(self):
		self.assertEqual(seniority_percent(1), Decimal("0.10"))

	def test_3_years(self):
		self.assertEqual(seniority_percent(3), Decimal("0.10"))

	def test_4_years(self):
		self.assertEqual(seniority_percent(4), Decimal("0.20"))

	def test_5_years(self):
		self.assertEqual(seniority_percent(5), Decimal("0.20"))

	def test_6_years(self):
		self.assertEqual(seniority_percent(6), Decimal("0.30"))

	def test_10_years(self):
		self.assertEqual(seniority_percent(10), Decimal("0.30"))

	def test_11_years(self):
		self.assertEqual(seniority_percent(11), Decimal("0.50"))

	def test_20_years(self):
		self.assertEqual(seniority_percent(20), Decimal("0.50"))


class TestResolveSchedule(unittest.TestCase):
	"""Direct unit tests for resolve_schedule() helper."""

	def test_shift_8h(self):
		s = resolve_schedule("SHIFT_8H", Decimal("1"))
		self.assertEqual(s["hours_per_day"], 8)
		self.assertEqual(s["stake"], Decimal("1"))
		self.assertEqual(s["proration"], "attendance")
		self.assertTrue(s["late_fees_apply"])

	def test_shift_12h(self):
		s = resolve_schedule("SHIFT_12H", Decimal("1"))
		self.assertEqual(s["hours_per_day"], 12)
		self.assertEqual(s["stake"], Decimal("1"))
		self.assertEqual(s["proration"], "attendance")
		self.assertTrue(s["late_fees_apply"])

	def test_half_rate_uses_stake(self):
		s = resolve_schedule("HALF_RATE", Decimal("0.5"))
		self.assertEqual(s["hours_per_day"], 8)
		self.assertEqual(s["stake"], Decimal("0.5"))
		self.assertEqual(s["proration"], "attendance")
		self.assertTrue(s["late_fees_apply"])

	def test_flexible(self):
		s = resolve_schedule("FLEXIBLE", Decimal("1"))
		self.assertEqual(s["hours_per_day"], 8)
		self.assertEqual(s["proration"], "full")
		self.assertFalse(s["late_fees_apply"])

	def test_remote(self):
		s = resolve_schedule("REMOTE", Decimal("1"))
		self.assertEqual(s["hours_per_day"], 8)
		self.assertEqual(s["proration"], "full")
		self.assertFalse(s["late_fees_apply"])


if __name__ == "__main__":
	unittest.main()
