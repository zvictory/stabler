"""Unit tests for the pure attendance→payroll-engine adapter (no frappe)."""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.api._payroll_adapter import build_calc_input
from stabler.api._payroll_calc import calculate_payroll


def _emp(**kw):
	base = {"base_salary": "10000000", "work_mode": "SHIFT_8H", "region": "NO_TRAVEL"}
	base.update(kw)
	return base


class TestAdapterMapping(unittest.TestCase):
	def test_full_attendance_no_kpi_split_pays_full_base(self):
		# 22/22 days, kpi_share default 0 → net == base, no allowances.
		inp = build_calc_input(
			_emp(),
			{"payroll_period": "2026-06", "present_days": 22, "absent_days": 0, "half_days": 0,
			 "overtime_minutes": 0, "night_minutes": 0, "late_deduction_amount": 0},
			{},
		)
		self.assertEqual(inp["summary"]["attended_days"], 22)
		self.assertEqual(inp["summary"]["expected_days"], 22)
		self.assertEqual(inp["policies"]["kpi"]["kpi_share_pct"], "0")
		out = calculate_payroll(inp)
		self.assertEqual(Decimal(out["net"]), Decimal("10000000"))

	def test_half_attendance_prorates_base(self):
		# 11 present, 11 absent of 22 → ratio 0.5 → ~half base.
		inp = build_calc_input(
			_emp(),
			{"payroll_period": "2026-06", "present_days": 11, "absent_days": 11, "half_days": 0,
			 "overtime_minutes": 0, "night_minutes": 0, "late_deduction_amount": 0},
			{},
		)
		self.assertEqual(inp["summary"]["expected_days"], 22)
		out = calculate_payroll(inp)
		self.assertEqual(Decimal(out["net"]), Decimal("5000000"))

	def test_night_minutes_to_hours_and_fee_to_fines(self):
		inp = build_calc_input(
			_emp(),
			{"payroll_period": "2026-06", "present_days": 22, "absent_days": 0, "half_days": 0,
			 "overtime_minutes": 90, "night_minutes": 120, "late_deduction_amount": 15000},
			{"night_premium_pct": "10"},
		)
		self.assertEqual(inp["summary"]["night_hours_worked"], "2.0")
		self.assertEqual(inp["summary"]["ot_minutes_worked"], "90")
		self.assertEqual(inp["summary"]["fee_uzs"], "15000")
		out = calculate_payroll(inp)
		# late fee flows to fines
		self.assertEqual(Decimal(out["fines"]), Decimal("15000"))

	def test_expected_days_override_respected(self):
		inp = build_calc_input(
			_emp(),
			{"payroll_period": "2026-06", "present_days": 20, "absent_days": 0, "half_days": 0,
			 "expected_days": 25, "overtime_minutes": 0, "night_minutes": 0, "late_deduction_amount": 0},
			{},
		)
		self.assertEqual(inp["summary"]["expected_days"], 25)
		out = calculate_payroll(inp)
		# 20/25 = 0.8 of base
		self.assertEqual(Decimal(out["net"]), Decimal("8000000"))

	def test_kpi_share_withholds_base_when_configured(self):
		# kpi_share 40, no performance → only 60% fixed base flows.
		inp = build_calc_input(
			_emp(),
			{"payroll_period": "2026-06", "present_days": 22, "absent_days": 0, "half_days": 0,
			 "overtime_minutes": 0, "night_minutes": 0, "late_deduction_amount": 0},
			{"kpi_share_pct": "40"},
		)
		out = calculate_payroll(inp)
		self.assertEqual(Decimal(out["net"]), Decimal("6000000"))

	def test_region_rate_adds_per_day_transport(self):
		# CITY band, 10000/day, 22 present → transport 220000 on top of base.
		inp = build_calc_input(
			_emp(region="CITY"),
			{"payroll_period": "2026-06", "present_days": 22, "absent_days": 0, "half_days": 0,
			 "overtime_minutes": 0, "night_minutes": 0, "late_deduction_amount": 0},
			{"region_rates": {"CITY": "10000"}},
		)
		out = calculate_payroll(inp)
		self.assertEqual(Decimal(out["allowances"]), Decimal("220000"))
		self.assertEqual(Decimal(out["net"]), Decimal("10220000"))

	def test_duty_supplement_pct_adds_to_pay(self):
		# 25% of effective base on full attendance → +2 500 000.
		inp = build_calc_input(
			_emp(),
			{"payroll_period": "2026-06", "present_days": 22, "absent_days": 0, "half_days": 0,
			 "overtime_minutes": 0, "night_minutes": 0, "late_deduction_amount": 0},
			{},
			duty_supplements=[{"pct": 25}],
		)
		out = calculate_payroll(inp)
		self.assertEqual(Decimal(out["duty_supplement"]), Decimal("2500000"))
		self.assertEqual(Decimal(out["net"]), Decimal("12500000"))

	def test_kpi_performance_pays_out_pool(self):
		# kpi_share 40 + performance 50 → fixed 6M + KPI pool 4M × 50% = 2M → 8M.
		inp = build_calc_input(
			_emp(),
			{"payroll_period": "2026-06", "present_days": 22, "absent_days": 0, "half_days": 0,
			 "overtime_minutes": 0, "night_minutes": 0, "late_deduction_amount": 0},
			{"kpi_share_pct": "40"},
			kpi_performance_pct=50,
		)
		out = calculate_payroll(inp)
		self.assertEqual(Decimal(out["kpi"]), Decimal("2000000"))
		self.assertEqual(Decimal(out["net"]), Decimal("8000000"))


if __name__ == "__main__":
	unittest.main()
