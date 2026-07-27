"""Tests for pure Timepay processor planning helpers."""

from __future__ import annotations

import unittest

from stabler.api._attendance_processor import summarize_day
from stabler.api._attendance_rules import policies_from_ruleset
from stabler.api._timepay_processor import (
	attendance_status_from_summary,
	plan_raw_event_groups,
	raw_event_to_punch,
)


def raw(**kw):
	base = {
		"name": "RAW-1",
		"device": "Timepay API",
		"device_user_id": "10783",
		"timestamp": "2026-06-15 09:01:00",
		"direction": "IN",
		"external_event_id": "timepay:2026-06-15:10783:in",
	}
	base.update(kw)
	return base


class StatusMappingTest(unittest.TestCase):
	def test_late_statuses_are_present_in_erpnext(self):
		self.assertEqual(attendance_status_from_summary({"status": "late_step"}), "Present")
		self.assertEqual(attendance_status_from_summary({"status": "late_flat"}), "Present")

	def test_absent_half_day_and_holiday_map_to_native_statuses(self):
		self.assertEqual(attendance_status_from_summary({"status": "absent"}), "Absent")
		self.assertEqual(attendance_status_from_summary({"status": "half_day"}), "Half Day")
		self.assertEqual(attendance_status_from_summary({"status": "holiday"}), "On Leave")


class RawEventToPunchTest(unittest.TestCase):
	def test_naive_frappe_datetime_is_not_shifted(self):
		self.assertEqual(
			raw_event_to_punch(raw())["timestamp"],
			"2026-06-15T09:01:00",
		)

	def test_policies_from_ruleset_feed_summarize_day_in_processor_order(self):
		late, night, half, min_worked = policies_from_ruleset({})

		summary = summarize_day(
			[
				raw_event_to_punch(raw()),
				raw_event_to_punch(raw(name="RAW-OUT", timestamp="2026-06-15 18:02:00", direction="OUT")),
			],
			shift="DAY",
			shift_start_hm="09:00",
			is_holiday=False,
			date_str="2026-06-15",
			hire_date="2026-01-01",
			late=late,
			half=half,
			night=night,
			min_worked_present=min_worked,
		)

		self.assertEqual(summary["status"], "present")


class PlanRawEventGroupsTest(unittest.TestCase):
	def test_groups_resolved_events_by_employee_and_date(self):
		events = [
			raw(name="RAW-IN"),
			raw(name="RAW-OUT", timestamp="2026-06-15 18:02:00", direction="OUT"),
		]
		mappings = [{"device_user_id": "10783", "employee": "HR-EMP-0001", "active_from": "2026-01-01"}]

		plan = plan_raw_event_groups(events, mappings)

		self.assertEqual(plan["unmatched"], [])
		self.assertEqual(len(plan["groups"]), 1)
		group = plan["groups"][0]
		self.assertEqual(group["employee"], "HR-EMP-0001")
		self.assertEqual(group["date"], "2026-06-15")
		self.assertEqual([e["name"] for e in group["events"]], ["RAW-IN", "RAW-OUT"])

	def test_unresolved_events_are_separated(self):
		plan = plan_raw_event_groups([raw(device_user_id="99999")], [])

		self.assertEqual(plan["groups"], [])
		self.assertEqual(plan["unmatched"][0]["name"], "RAW-1")

	def test_falls_back_to_unique_employee_custom_timepay_id(self):
		plan = plan_raw_event_groups([raw(device_user_id="TP-42")], [], {"TP-42": ["HR-EMP-0002"]})

		self.assertEqual(plan["unmatched"], [])
		self.assertEqual(len(plan["groups"]), 1)
		self.assertEqual(plan["groups"][0]["employee"], "HR-EMP-0002")

	def test_ambiguous_employee_custom_timepay_id_stays_unmatched(self):
		plan = plan_raw_event_groups(
			[raw(device_user_id="TP-42")], [], {"TP-42": ["HR-EMP-0002", "HR-EMP-0003"]}
		)

		self.assertEqual(plan["groups"], [])
		self.assertEqual(plan["unmatched"][0]["name"], "RAW-1")


if __name__ == "__main__":
	unittest.main()
