"""Unit tests for the pure attendance day-processor (Phase 3)."""

from __future__ import annotations

import unittest

from stabler.api._attendance_processor import (
	build_daily_record,
	detect_exceptions,
	late_minutes,
	summarize_day,
)


def p(ts, direction="UNKNOWN"):
	return {"timestamp": ts, "direction": direction}


class BuildDailyRecordTest(unittest.TestCase):
	def test_first_in_last_out(self):
		r = build_daily_record([
			p("2026-05-10T09:01:00", "IN"),
			p("2026-05-10T13:00:00", "OUT"),
			p("2026-05-10T13:45:00", "IN"),
			p("2026-05-10T18:05:00", "OUT"),
		])
		self.assertEqual(r["entry"], "09:01")
		self.assertEqual(r["exit"], "18:05")
		self.assertEqual(r["punch_count"], 4)

	def test_no_direction_uses_earliest_latest(self):
		r = build_daily_record([p("2026-05-10T08:30:00"), p("2026-05-10T17:30:00")])
		self.assertEqual((r["entry"], r["exit"]), ("08:30", "17:30"))

	def test_single_punch_no_exit(self):
		r = build_daily_record([p("2026-05-10T09:00:00", "IN")])
		self.assertEqual(r["entry"], "09:00")
		self.assertIsNone(r["exit"])

	def test_empty(self):
		r = build_daily_record([])
		self.assertEqual(r["punch_count"], 0)


class ExceptionsTest(unittest.TestCase):
	def test_no_punch_missing_checkin(self):
		self.assertIn("missing_check_in", detect_exceptions({"punch_count": 0, "exit": None}, []))

	def test_single_punch_flags(self):
		exc = detect_exceptions({"punch_count": 1, "exit": None}, [p("2026-05-10T09:00:00", "IN")])
		self.assertIn("missing_check_out", exc)
		self.assertIn("single_punch", exc)

	def test_excess_punches(self):
		punches = [p(f"2026-05-10T0{i}:00:00") for i in range(1, 9)]
		self.assertIn("excess_punches", detect_exceptions({"punch_count": 8, "exit": "08:00"}, punches))


class LateMinutesTest(unittest.TestCase):
	def test_late(self):
		self.assertEqual(late_minutes("09:25", "09:00"), 25)

	def test_on_time(self):
		self.assertEqual(late_minutes("08:55", "09:00"), 0)

	def test_missing(self):
		self.assertEqual(late_minutes(None, "09:00"), 0)


class SummarizeDayTest(unittest.TestCase):
	def test_present_clean_day(self):
		s = summarize_day(
			[p("2026-05-10T09:00:00", "IN"), p("2026-05-10T18:00:00", "OUT")],
			shift="DAY", shift_start_hm="09:00", date_str="2026-05-10", hire_date="2026-01-01")
		self.assertEqual(s["status"], "present")
		self.assertEqual(s["worked_min"], 540)
		self.assertEqual(s["overtime_min"], 0)
		self.assertEqual(s["exceptions"], [])
		self.assertFalse(s["payroll_impacting"])

	def test_late_day_charges_fee(self):
		s = summarize_day(
			[p("2026-05-10T09:25:00", "IN"), p("2026-05-10T18:00:00", "OUT")],
			shift="DAY", shift_start_hm="09:00", date_str="2026-05-10", hire_date="2026-01-01")
		self.assertEqual(s["status"], "late_step")   # 25 > grace+step(20)
		self.assertEqual(s["late_min"], 25)
		self.assertEqual(s["late_fee_uzs"], 20000)
		self.assertTrue(s["payroll_impacting"])

	def test_overtime_day(self):
		s = summarize_day(
			[p("2026-05-10T09:00:00", "IN"), p("2026-05-10T22:00:00", "OUT")],
			shift="DAY", shift_start_hm="09:00", date_str="2026-05-10", hire_date="2026-01-01")
		self.assertEqual(s["overtime_min"], 120)
		self.assertTrue(s["payroll_impacting"])

	def test_missing_checkout_exception(self):
		s = summarize_day(
			[p("2026-05-10T09:00:00", "IN")],
			shift="DAY", shift_start_hm="09:00", date_str="2026-05-10", hire_date="2026-01-01")
		self.assertIn("missing_check_out", s["exceptions"])
		# single IN punch -> no exit -> classified absent (no worked time)
		self.assertEqual(s["status"], "absent")

	def test_device_late_min_override(self):
		s = summarize_day(
			[p("2026-05-10T09:00:00", "IN"), p("2026-05-10T18:00:00", "OUT")],
			shift="DAY", shift_start_hm="09:00", date_str="2026-05-10", hire_date="2026-01-01",
			device_late_min=15)
		self.assertEqual(s["late_min"], 15)
		self.assertEqual(s["status"], "late_flat")  # 15 > grace(10), <= grace+step(20)

	def test_holiday(self):
		s = summarize_day(
			[p("2026-05-09T10:00:00", "IN"), p("2026-05-09T16:00:00", "OUT")],
			shift="DAY", is_holiday=True, date_str="2026-05-09", hire_date="2026-01-01")
		self.assertEqual(s["status"], "holiday")


if __name__ == "__main__":
	unittest.main()
