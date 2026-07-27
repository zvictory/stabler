"""Unit tests for the pure attendance rule engine.

Imports only stabler.api._attendance_rules (no Frappe), so it runs under plain
`python -m unittest` and under `bench run-tests`. The overtime cases are the
exact oracles from anjan-hr `lib/timesheet/overtime.test.ts`; the late-fee cases
are derived from `totals.ts:computeLateFeeNumber` with the Prisma defaults.
"""

from __future__ import annotations

import unittest

from stabler.api._attendance_rules import (
	HalfDayPolicy,
	LateFeePolicy,
	NightPolicy,
	classify_day,
	compute_late_fee,
	compute_overtime_minutes,
	compute_row_totals,
	is_overnight,
	policies_from_ruleset,
	record_worked_min,
)

NIGHT = NightPolicy(start_hour=20, end_hour=8, ot_method="CLOCK_CUTOFF", ot_threshold_min=0)
LATE = LateFeePolicy(grace_min=10, step_min=10, flat_fee=15000, step_fee=5000, daily_cap=50000)
HALF = HalfDayPolicy(min_worked_min=240, anchor_day_h=12, anchor_night_h=12, anchor_office_h=12, anchor_light_h=12)


def rec(entry=None, exit=None, late_min=0, early_leave_min=0, late_excused=False):
	return {"entry": entry, "exit": exit, "late_min": late_min,
		"early_leave_min": early_leave_min, "late_excused": late_excused}


class OvertimeOracleTest(unittest.TestCase):
	"""Exact numbers from anjan-hr overtime.test.ts."""

	def test_day_normal_zero(self):
		self.assertEqual(compute_overtime_minutes(rec("09:00", "18:00"), "DAY", NIGHT), 0)

	def test_day_stayed_late_120(self):
		self.assertEqual(compute_overtime_minutes(rec("09:00", "22:00"), "DAY", NIGHT), 120)

	def test_day_crossed_midnight_360(self):
		self.assertEqual(compute_overtime_minutes(rec("13:00", "02:00"), "DAY", NIGHT), 360)

	def test_night_normal_zero(self):
		self.assertEqual(compute_overtime_minutes(rec("20:00", "08:00"), "NIGHT", NIGHT), 0)

	def test_night_stayed_late_90(self):
		self.assertEqual(compute_overtime_minutes(rec("20:00", "09:30"), "NIGHT", NIGHT), 90)

	def test_missing_punch_zero(self):
		self.assertEqual(compute_overtime_minutes(rec(None, None), "DAY", NIGHT), 0)

	def test_daily_hours_method(self):
		p = NightPolicy(ot_method="DAILY_HOURS", ot_threshold_min=480)
		# worked 09:00->20:00 = 660 min; 660-480 = 180
		self.assertEqual(compute_overtime_minutes(rec("09:00", "20:00"), "DAY", p), 180)


class LateFeeTest(unittest.TestCase):
	def test_within_grace_zero(self):
		self.assertEqual(compute_late_fee(5, LATE), 0.0)
		self.assertEqual(compute_late_fee(10, LATE), 0.0)

	def test_first_step_flat(self):
		# grace<late<=grace+step  -> flat
		self.assertEqual(compute_late_fee(15, LATE), 15000)
		self.assertEqual(compute_late_fee(20, LATE), 15000)

	def test_one_block_over(self):
		# late 25: blocksOver = ceil((25-20)/10)=1 -> 15000 + 5000
		self.assertEqual(compute_late_fee(25, LATE), 20000)

	def test_three_blocks_over(self):
		# late 45: ceil((45-20)/10)=3 -> 15000 + 15000
		self.assertEqual(compute_late_fee(45, LATE), 30000)

	def test_capped(self):
		# late 200: ceil(180/10)=18 -> 15000+90000=105000 capped to 50000
		self.assertEqual(compute_late_fee(200, LATE), 50000)

	def test_garbage_safe(self):
		self.assertEqual(compute_late_fee("nan", LATE), 0.0)


class WorkedMinTest(unittest.TestCase):
	def test_normal(self):
		self.assertEqual(record_worked_min(rec("09:00", "18:00")), 540)

	def test_overnight(self):
		# 19:21 -> 07:58 : (1440-1161)+478 = 757
		self.assertEqual(record_worked_min(rec("19:21", "07:58")), 757)
		self.assertTrue(is_overnight(rec("19:21", "07:58")))

	def test_missing(self):
		self.assertEqual(record_worked_min(rec(None, "18:00")), 0)


class ClassifyTest(unittest.TestCase):
	def test_out_of_employment_pre_hire(self):
		self.assertEqual(classify_day(rec("09:00", "18:00"), "DAY", False, LATE, HALF, NIGHT,
			"2026-04-01", "2026-05-01", None), "out_of_employment")

	def test_out_of_employment_post_termination(self):
		self.assertEqual(classify_day(rec("09:00", "18:00"), "DAY", False, LATE, HALF, NIGHT,
			"2026-06-10", "2026-01-01", "2026-06-01"), "out_of_employment")

	def test_holiday(self):
		self.assertEqual(classify_day(rec("09:00", "18:00"), "DAY", True, LATE, HALF, NIGHT,
			"2026-05-09", "2026-01-01", None), "holiday")

	def test_absent_no_punch(self):
		self.assertEqual(classify_day(rec(None, None), "DAY", False, LATE, HALF, NIGHT,
			"2026-05-10", "2026-01-01", None), "absent")

	def test_absent_under_4h(self):
		# 09:00->12:30 = 210 min < 240
		self.assertEqual(classify_day(rec("09:00", "12:30"), "DAY", False, LATE, HALF, NIGHT,
			"2026-05-10", "2026-01-01", None), "absent")

	def test_present(self):
		self.assertEqual(classify_day(rec("09:00", "18:00", late_min=0), "DAY", False, LATE, HALF, NIGHT,
			"2026-05-10", "2026-01-01", None), "present")

	def test_late_flat(self):
		# late_min 15 (>grace 10, <=grace+step 20)
		self.assertEqual(classify_day(rec("09:15", "18:00", late_min=15), "DAY", False, LATE, HALF, NIGHT,
			"2026-05-10", "2026-01-01", None), "late_flat")

	def test_late_step(self):
		self.assertEqual(classify_day(rec("09:40", "18:00", late_min=40), "DAY", False, LATE, HALF, NIGHT,
			"2026-05-10", "2026-01-01", None), "late_step")

	def test_half_day_entry_after_anchor(self):
		# entry hour 13 >= anchor 12, worked >= min_worked -> half_day
		self.assertEqual(classify_day(rec("13:00", "18:00"), "DAY", False, LATE, HALF, NIGHT,
			"2026-05-10", "2026-01-01", None), "half_day")


class RowTotalsTest(unittest.TestCase):
	def test_partition_invariant(self):
		statuses = ["present", "late_flat", "absent", "holiday", "present"]
		night_flags = [False, False, False, False, True]
		ot = [0, 0, 0, 0, 90]
		records = [rec("09:00", "18:00", late_min=0), rec("09:15", "18:00", late_min=15),
			rec("20:00", "09:30", late_min=0)]
		t = compute_row_totals(records, statuses, night_flags, ot, calendar_days=5, late=LATE)
		# days_worked(present+late_flat, non-night) = 2; night_days(present+night) = 1
		self.assertEqual(t["days_worked"], 2)
		self.assertEqual(t["night_days"], 1)
		self.assertEqual(t["days_worked"] + t["night_days"] + t["absent_days"], 5)
		self.assertEqual(t["late_count"], 1)
		self.assertEqual(t["overtime_min"], 90)
		self.assertEqual(t["fee_uzs"], 15000)  # only the late_min=15 record


class PoliciesFromRuleSetTest(unittest.TestCase):
	def test_maps_fields(self):
		late, night, _half, mwp = policies_from_ruleset({
			"grace_min": 15, "flat_fee_uzs": 20000, "night_start_hour": 21,
			"ot_method": "DAILY_HOURS", "min_worked_for_present_min": 200,
		})
		self.assertEqual(late.grace_min, 15)
		self.assertEqual(late.flat_fee, 20000)
		self.assertEqual(night.start_hour, 21)
		self.assertEqual(night.ot_method, "DAILY_HOURS")
		self.assertEqual(mwp, 200)

	def test_defaults_on_empty(self):
		late, night, half, mwp = policies_from_ruleset({})
		self.assertEqual(late.grace_min, 10)
		self.assertEqual(night.start_hour, 20)
		self.assertEqual(half.anchor_day_h, 12)
		self.assertEqual(mwp, 240)

	def test_garbage_falls_back(self):
		late, night, _, _ = policies_from_ruleset({"grace_min": "x", "ot_method": "WAT"})
		self.assertEqual(late.grace_min, 10)
		self.assertEqual(night.ot_method, "CLOCK_CUTOFF")


if __name__ == "__main__":
	unittest.main()
