"""Thorough unit tests for stabler.api._payroll_summary.

Run with:
    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_payroll_summary -v
"""

from __future__ import annotations

import unittest

from stabler.api._payroll_summary import (
	can_lock,
	is_correction_payroll_impacting,
	night_premium_amount,
	overtime_amount,
	period_blockers,
	rollup_month,
)

# ---------------------------------------------------------------------------
# Helpers to build realistic per-day dicts (mirrors summarize_day output)
# ---------------------------------------------------------------------------


def _day(
	status,
	late_min=0,
	late_fee_uzs=0.0,
	overtime_min=0,
	is_night=False,
	worked_min=480,
	exceptions=None,
	early_leave_min=0,
):
	return {
		"status": status,
		"late_min": late_min,
		"late_fee_uzs": late_fee_uzs,
		"overtime_min": overtime_min,
		"is_night": is_night,
		"worked_min": worked_min,
		"exceptions": exceptions or [],
		"early_leave_min": early_leave_min,
	}


# ---------------------------------------------------------------------------
# rollup_month
# ---------------------------------------------------------------------------


class TestRollupMonthEmpty(unittest.TestCase):
	def test_empty_list_returns_zeros(self):
		r = rollup_month([])
		self.assertEqual(r["present_days"], 0)
		self.assertEqual(r["half_days"], 0)
		self.assertEqual(r["absent_days"], 0)
		self.assertEqual(r["holiday_days"], 0)
		self.assertEqual(r["night_days"], 0)
		self.assertEqual(r["late_count"], 0)
		self.assertEqual(r["late_minutes"], 0)
		self.assertEqual(r["late_deduction_amount"], 0.0)
		self.assertEqual(r["early_leave_minutes"], 0)
		self.assertEqual(r["overtime_minutes"], 0)
		self.assertEqual(r["night_minutes"], 0)
		self.assertEqual(r["exceptions_count"], 0)

	def test_all_expected_keys_present(self):
		r = rollup_month([])
		expected_keys = {
			"present_days",
			"half_days",
			"absent_days",
			"holiday_days",
			"night_days",
			"late_count",
			"late_minutes",
			"late_deduction_amount",
			"early_leave_minutes",
			"overtime_minutes",
			"night_minutes",
			"exceptions_count",
		}
		self.assertEqual(set(r.keys()), expected_keys)


class TestRollupMonthMixedMonth(unittest.TestCase):
	"""Simulate a realistic working month with various day types."""

	@classmethod
	def setUpClass(cls):
		# Build a 22-working-day month:
		# 12 present days (normal)
		# 3 late_flat days (late_min=15, fee=15000 each)
		# 2 late_step days (late_min=35, fee=25000 each)
		# 2 half days
		# 2 absent days
		# 1 holiday
		# + 3 night shifts (present, attended, is_night=True, worked_min=500)
		# + 4 overtime days (overtime_min=60 each)
		# + 2 days with exceptions (1 exception each)
		# + 3 days with early_leave_min=30
		cls.days = (
			# 12 present (includes 4 OT days, 3 early-leave)
			[_day("present", overtime_min=60, early_leave_min=30) for _ in range(3)]
			+ [_day("present", overtime_min=60) for _ in range(1)]
			+ [_day("present") for _ in range(8)]
			# 3 late_flat
			+ [_day("late_flat", late_min=15, late_fee_uzs=15000.0) for _ in range(3)]
			# 2 late_step
			+ [_day("late_step", late_min=35, late_fee_uzs=25000.0) for _ in range(2)]
			# 2 half_day
			+ [_day("half_day") for _ in range(2)]
			# 2 absent
			+ [_day("absent", worked_min=0) for _ in range(2)]
			# 1 holiday
			+ [_day("holiday", worked_min=0)]
			# 3 night shifts (present + is_night, worked_min=500)
			+ [_day("present", is_night=True, worked_min=500) for _ in range(3)]
			# 2 days with exceptions
			+ [_day("present", exceptions=["missing_check_out"]) for _ in range(2)]
		)

	def test_present_days_count(self):
		r = rollup_month(self.days)
		# present_days = 12 present (no is_night) + 3 late_flat + 2 late_step
		# night present days are also counted as present_days
		# The 3 night present days have is_night=True; they still have status "present"
		# so they add to present_days too.
		# 3 present (early OT) + 1 present (OT) + 8 present + 3 late_flat + 2 late_step
		#   + 3 night present + 2 present (exceptions) = 22
		self.assertEqual(r["present_days"], 22)

	def test_half_days(self):
		r = rollup_month(self.days)
		self.assertEqual(r["half_days"], 2)

	def test_absent_days(self):
		r = rollup_month(self.days)
		self.assertEqual(r["absent_days"], 2)

	def test_holiday_days(self):
		r = rollup_month(self.days)
		self.assertEqual(r["holiday_days"], 1)

	def test_night_days(self):
		r = rollup_month(self.days)
		# Only the 3 present+is_night days qualify
		self.assertEqual(r["night_days"], 3)

	def test_late_count(self):
		r = rollup_month(self.days)
		# 3 late_flat (late_min=15) + 2 late_step (late_min=35) = 5
		self.assertEqual(r["late_count"], 5)

	def test_late_minutes(self):
		r = rollup_month(self.days)
		# 3*15 + 2*35 = 45 + 70 = 115
		self.assertEqual(r["late_minutes"], 115)

	def test_late_deduction_amount(self):
		r = rollup_month(self.days)
		# 3*15000 + 2*25000 = 45000 + 50000 = 95000
		self.assertAlmostEqual(r["late_deduction_amount"], 95000.0)

	def test_early_leave_minutes(self):
		r = rollup_month(self.days)
		# 3 days * 30 min = 90
		self.assertEqual(r["early_leave_minutes"], 90)

	def test_overtime_minutes(self):
		r = rollup_month(self.days)
		# 4 days * 60 min = 240
		self.assertEqual(r["overtime_minutes"], 240)

	def test_night_minutes(self):
		r = rollup_month(self.days)
		# 3 night days * 500 worked_min = 1500
		self.assertEqual(r["night_minutes"], 1500)

	def test_exceptions_count(self):
		r = rollup_month(self.days)
		# 2 days with 1 exception each = 2
		self.assertEqual(r["exceptions_count"], 2)

	def test_garbage_days_ignored(self):
		"""Non-dict items in the list must not cause errors."""
		days = [_day("present"), None, "bad", 42, _day("absent", worked_min=0)]
		r = rollup_month(days)
		self.assertEqual(r["present_days"], 1)
		self.assertEqual(r["absent_days"], 1)

	def test_missing_keys_default_to_zero(self):
		"""Days with missing optional keys must not raise."""
		days = [{"status": "present"}, {"status": "late_flat"}]
		r = rollup_month(days)
		self.assertEqual(r["present_days"], 2)
		self.assertEqual(r["late_deduction_amount"], 0.0)
		self.assertEqual(r["exceptions_count"], 0)
		self.assertEqual(r["early_leave_minutes"], 0)


class TestRollupNightHalfDayNotCountedTwice(unittest.TestCase):
	def test_night_half_day_not_in_present_days(self):
		"""A half_day + is_night should count as half_day, not present_day."""
		days = [_day("half_day", is_night=True, worked_min=300)]
		r = rollup_month(days)
		self.assertEqual(r["half_days"], 1)
		self.assertEqual(r["present_days"], 0)
		# half_day + is_night = attended + night -> night_days counts it
		self.assertEqual(r["night_days"], 1)


# ---------------------------------------------------------------------------
# period_blockers
# ---------------------------------------------------------------------------


class TestPeriodBlockersClean(unittest.TestCase):
	def test_clean_ctx_returns_empty(self):
		ctx = {
			"open_punch_days": 0,
			"unresolved_exceptions": 0,
			"pending_corrections": 0,
			"employees_without_summary": 0,
			"already_locked": False,
		}
		self.assertEqual(period_blockers(ctx), [])

	def test_empty_ctx_returns_empty(self):
		self.assertEqual(period_blockers({}), [])

	def test_none_ctx_returns_empty(self):
		self.assertEqual(period_blockers(None), [])


class TestPeriodBlockersEachBlocker(unittest.TestCase):
	def _codes(self, ctx):
		return [b["code"] for b in period_blockers(ctx)]

	def test_open_punches_blocker(self):
		codes = self._codes({"open_punch_days": 3})
		self.assertIn("open_punches", codes)

	def test_open_punches_count_propagated(self):
		bs = period_blockers({"open_punch_days": 5})
		b = next(x for x in bs if x["code"] == "open_punches")
		self.assertEqual(b["count"], 5)

	def test_unresolved_exceptions_blocker(self):
		codes = self._codes({"unresolved_exceptions": 7})
		self.assertIn("unresolved_exceptions", codes)

	def test_unapproved_corrections_blocker(self):
		codes = self._codes({"pending_corrections": 2})
		self.assertIn("unapproved_corrections", codes)

	def test_missing_summaries_blocker(self):
		codes = self._codes({"employees_without_summary": 10})
		self.assertIn("missing_summaries", codes)

	def test_already_locked_blocker(self):
		codes = self._codes({"already_locked": True})
		self.assertIn("already_locked", codes)

	def test_already_locked_count_is_one(self):
		bs = period_blockers({"already_locked": True})
		b = next(x for x in bs if x["code"] == "already_locked")
		self.assertEqual(b["count"], 1)

	def test_multiple_blockers_all_returned(self):
		ctx = {
			"open_punch_days": 2,
			"unresolved_exceptions": 1,
			"pending_corrections": 3,
			"employees_without_summary": 5,
			"already_locked": True,
		}
		codes = self._codes(ctx)
		self.assertIn("open_punches", codes)
		self.assertIn("unresolved_exceptions", codes)
		self.assertIn("unapproved_corrections", codes)
		self.assertIn("missing_summaries", codes)
		self.assertIn("already_locked", codes)
		self.assertEqual(len(codes), 5)

	def test_blocker_has_required_keys(self):
		bs = period_blockers({"open_punch_days": 1})
		self.assertIn("code", bs[0])
		self.assertIn("message", bs[0])
		self.assertIn("count", bs[0])
		self.assertIsInstance(bs[0]["message"], str)
		self.assertGreater(len(bs[0]["message"]), 0)

	def test_zero_value_does_not_trigger_blocker(self):
		ctx = {"open_punch_days": 0, "unresolved_exceptions": 0}
		self.assertEqual(period_blockers(ctx), [])

	def test_missing_key_treated_as_zero(self):
		# No "open_punch_days" key at all — should not add blocker
		self.assertEqual(period_blockers({"pending_corrections": 0}), [])

	def test_none_values_treated_as_zero(self):
		ctx = {"open_punch_days": None, "unresolved_exceptions": None}
		self.assertEqual(period_blockers(ctx), [])


# ---------------------------------------------------------------------------
# can_lock
# ---------------------------------------------------------------------------


class TestCanLock(unittest.TestCase):
	def test_clean_ctx_can_lock(self):
		self.assertTrue(can_lock({}))

	def test_open_punch_blocks_lock(self):
		self.assertFalse(can_lock({"open_punch_days": 1}))

	def test_already_locked_blocks_relock(self):
		self.assertFalse(can_lock({"already_locked": True}))

	def test_all_clean_can_lock(self):
		ctx = {
			"open_punch_days": 0,
			"unresolved_exceptions": 0,
			"pending_corrections": 0,
			"employees_without_summary": 0,
			"already_locked": False,
		}
		self.assertTrue(can_lock(ctx))

	def test_any_single_issue_blocks(self):
		for key, value in [
			("open_punch_days", 1),
			("unresolved_exceptions", 1),
			("pending_corrections", 1),
			("employees_without_summary", 1),
			("already_locked", True),
		]:
			with self.subTest(key=key):
				self.assertFalse(can_lock({key: value}))


# ---------------------------------------------------------------------------
# is_correction_payroll_impacting
# ---------------------------------------------------------------------------


class TestIsCorrectionPayrollImpacting(unittest.TestCase):
	# Impacting types with real changes
	def test_check_in_change_is_impacting(self):
		self.assertTrue(is_correction_payroll_impacting("check_in", "09:05", "08:55"))

	def test_check_out_change_is_impacting(self):
		self.assertTrue(is_correction_payroll_impacting("check_out", "17:00", "18:30"))

	def test_status_change_is_impacting(self):
		self.assertTrue(is_correction_payroll_impacting("status", "absent", "present"))

	def test_add_attendance_is_impacting(self):
		self.assertTrue(is_correction_payroll_impacting("add_attendance", None, "2026-05-12"))

	def test_remove_attendance_is_impacting(self):
		self.assertTrue(is_correction_payroll_impacting("remove_attendance", "2026-05-12", None))

	def test_late_excuse_is_impacting(self):
		self.assertTrue(is_correction_payroll_impacting("late_excuse", False, True))

	def test_overtime_adjust_is_impacting(self):
		self.assertTrue(is_correction_payroll_impacting("overtime_adjust", 0, 30))

	# Non-impacting types
	def test_note_is_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("note", "", "Added context"))

	def test_remark_is_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("remark", "old", "new"))

	def test_comment_is_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("comment", None, "A comment"))

	def test_unknown_type_is_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("unknown_field", "a", "b"))

	# No-op: before == after
	def test_no_change_check_in_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("check_in", "09:00", "09:00"))

	def test_no_change_status_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("status", "present", "present"))

	def test_no_change_none_none_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("overtime_adjust", None, None))

	def test_no_change_zero_zero_not_impacting(self):
		self.assertFalse(is_correction_payroll_impacting("overtime_adjust", 0, 0))

	# Edge: type in impacting set but values equal
	def test_impacting_type_same_value_returns_false(self):
		self.assertFalse(is_correction_payroll_impacting("late_excuse", True, True))


# ---------------------------------------------------------------------------
# night_premium_amount
# ---------------------------------------------------------------------------


class TestNightPremiumAmount(unittest.TestCase):
	def test_basic_calculation(self):
		# 120 min night * 60000 UZS/hr * 10% = 120/60 * 60000 * 0.10 = 12000
		result = night_premium_amount(120, 60000, 10.0)
		self.assertEqual(result, 12000.0)

	def test_zero_minutes_returns_zero(self):
		self.assertEqual(night_premium_amount(0, 60000, 10.0), 0.0)

	def test_zero_rate_returns_zero(self):
		self.assertEqual(night_premium_amount(480, 0, 10.0), 0.0)

	def test_zero_premium_returns_zero(self):
		self.assertEqual(night_premium_amount(480, 60000, 0.0), 0.0)

	def test_rounds_to_whole_uzs(self):
		# 70 min / 60 * 60000 UZS/hr * 10% = 7000 UZS exactly
		result = night_premium_amount(70, 60000, 10.0)
		self.assertEqual(result, 7000.0)
		self.assertEqual(result, int(result))  # whole UZS

	def test_rounds_up_fractional_uzs(self):
		# 1 min * 1 UZS/hr * 50% = 1/60 * 1 * 0.5 ≈ 0.00833 -> rounds to 0 (floor-half-up)
		# But 61 min * 120 UZS/hr * 100% = 61/60 * 120 = 122.0 exactly
		result = night_premium_amount(61, 120, 100.0)
		self.assertEqual(result, 122.0)

	def test_none_values_safe(self):
		self.assertEqual(night_premium_amount(None, 60000, 10.0), 0.0)
		self.assertEqual(night_premium_amount(120, None, 10.0), 0.0)

	def test_large_values(self):
		# 480 min (8h) * 2_000_000 UZS/hr * 15% = 8 * 2_000_000 * 0.15 = 2_400_000
		result = night_premium_amount(480, 2_000_000, 15.0)
		self.assertEqual(result, 2_400_000.0)

	def test_result_is_whole_number(self):
		"""The UZS amount must always be a whole number (no fractional units)."""
		# Fractional result scenario: 100 min * 37000 * 10% = 100/60 * 37000 * 0.1
		result = night_premium_amount(100, 37000, 10.0)
		self.assertEqual(result, int(result))


# ---------------------------------------------------------------------------
# overtime_amount
# ---------------------------------------------------------------------------


class TestOvertimeAmount(unittest.TestCase):
	def test_basic_no_multiplier(self):
		# 60 min * 60000 UZS/hr * 1.0 = 60000
		result = overtime_amount(60, 60000, 1.0)
		self.assertEqual(result, 60000.0)

	def test_time_and_a_half(self):
		# 60 min * 60000 * 1.5 = 90000
		result = overtime_amount(60, 60000, 1.5)
		self.assertEqual(result, 90000.0)

	def test_default_multiplier_is_one(self):
		result = overtime_amount(60, 60000)
		self.assertEqual(result, 60000.0)

	def test_zero_minutes_returns_zero(self):
		self.assertEqual(overtime_amount(0, 60000, 1.5), 0.0)

	def test_zero_rate_returns_zero(self):
		self.assertEqual(overtime_amount(120, 0, 2.0), 0.0)

	def test_rounds_to_whole_uzs(self):
		# 90 min * 40000 * 1.5 = 90000.0 exactly
		result = overtime_amount(90, 40000, 1.5)
		self.assertEqual(result, 90000.0)
		self.assertEqual(result, int(result))

	def test_fractional_result_rounds_whole(self):
		# 100 min * 37000 * 1.0 = 61666.67 -> rounds to 61667
		result = overtime_amount(100, 37000, 1.0)
		self.assertEqual(result, int(result))
		self.assertAlmostEqual(result, 61667.0, places=0)

	def test_none_values_safe(self):
		self.assertEqual(overtime_amount(None, 60000), 0.0)
		self.assertEqual(overtime_amount(60, None), 0.0)

	def test_large_values(self):
		# 240 min (4h) OT * 3_000_000 UZS/hr * 2.0 = 24_000_000
		result = overtime_amount(240, 3_000_000, 2.0)
		self.assertEqual(result, 24_000_000.0)

	def test_result_is_whole_number(self):
		"""The UZS amount must always be a whole number."""
		result = overtime_amount(100, 37000, 1.5)
		self.assertEqual(result, int(result))


if __name__ == "__main__":
	unittest.main()
