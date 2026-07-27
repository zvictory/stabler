"""Unit tests for the pure gate-event ingestion logic (Phase 2).

No Frappe — runs under plain `python -m unittest`. Locks down the two
guarantees: idempotent dedupe and explicit (no-fuzzy) employee resolution.
"""

from __future__ import annotations

import unittest
from typing import ClassVar

from stabler.api._attendance_ingest import (
	decide_event_action,
	dedupe_key,
	is_mapping_active,
	mapping_rows_from_reconciliation,
	resolve_employee,
)


def ev(**kw):
	base = {
		"device_id": "DEV1",
		"device_user_id": "10783",
		"timestamp": "2026-05-10T09:01:00",
		"direction": "IN",
	}
	base.update(kw)
	return base


class DedupeTest(unittest.TestCase):
	def test_external_id_is_the_key(self):
		self.assertEqual(dedupe_key(ev(external_event_id="abc")), "ext:abc")

	def test_same_punch_same_hash_key(self):
		self.assertEqual(dedupe_key(ev()), dedupe_key(ev()))

	def test_different_punch_different_key(self):
		self.assertNotEqual(dedupe_key(ev(timestamp="2026-05-10T09:02:00")), dedupe_key(ev()))

	def test_decide_action_idempotent(self):
		seen = set()
		e = ev(external_event_id="x1")
		self.assertEqual(decide_event_action(e, seen), "new")
		seen.add(dedupe_key(e))
		# replay -> duplicate, no second record
		self.assertEqual(decide_event_action(e, seen), "duplicate")

	def test_offline_event_imported_later_still_new(self):
		seen = {dedupe_key(ev(external_event_id="online"))}
		offline = ev(external_event_id="offline", timestamp="2026-05-09T22:00:00")
		self.assertEqual(decide_event_action(offline, seen), "new")


class MappingActiveTest(unittest.TestCase):
	def test_open_ended_active(self):
		self.assertTrue(is_mapping_active({"active_from": "2026-01-01", "active_to": ""}, "2026-05-10"))

	def test_before_start_inactive(self):
		self.assertFalse(is_mapping_active({"active_from": "2026-06-01"}, "2026-05-10"))

	def test_after_end_inactive(self):
		self.assertFalse(is_mapping_active({"active_to": "2026-04-30"}, "2026-05-10"))

	def test_status_inactive(self):
		self.assertFalse(is_mapping_active({"status": "Inactive"}, "2026-05-10"))

	def test_blank_date_inactive(self):
		self.assertFalse(is_mapping_active({}, ""))


class ResolveEmployeeTest(unittest.TestCase):
	MAP: ClassVar[list[dict]] = [
		{"device_user_id": "10783", "employee": "HR-EMP-0001", "active_from": "2026-01-01"},
		{
			"device_user_id": "10784",
			"employee": "HR-EMP-0002",
			"device_id": "DEV2",
			"active_from": "2026-01-01",
		},
	]

	def test_resolves_active_mapping(self):
		self.assertEqual(resolve_employee(ev(device_user_id="10783"), self.MAP), "HR-EMP-0001")

	def test_unmatched_returns_none(self):
		self.assertIsNone(resolve_employee(ev(device_user_id="99999"), self.MAP))

	def test_device_scoped_mapping_other_device_no_match(self):
		# mapping for 10784 is scoped to DEV2; event from DEV1 must not match
		self.assertIsNone(resolve_employee(ev(device_user_id="10784", device_id="DEV1"), self.MAP))

	def test_device_scoped_mapping_correct_device_matches(self):
		self.assertEqual(
			resolve_employee(ev(device_user_id="10784", device_id="DEV2"), self.MAP), "HR-EMP-0002"
		)

	def test_ambiguous_mapping_unresolved(self):
		dupmap = [
			{"device_user_id": "10783", "employee": "HR-EMP-0001", "active_from": "2026-01-01"},
			{"device_user_id": "10783", "employee": "HR-EMP-0009", "active_from": "2026-01-01"},
		]
		self.assertIsNone(resolve_employee(ev(device_user_id="10783"), dupmap))

	def test_blank_device_user_unresolved(self):
		self.assertIsNone(resolve_employee(ev(device_user_id=""), self.MAP))


class ReconciliationSeedTest(unittest.TestCase):
	def test_transforms_matched_rows(self):
		rows = [
			{"timepay_id": "10783", "erpnext_employee": "HR-EMP-0001", "phone": "+998901112233"},
			{"timepay_id": "10784", "erpnext_employee": "HR-EMP-0002", "phone": ""},
		]
		out = mapping_rows_from_reconciliation(rows)
		self.assertEqual(len(out), 2)
		self.assertEqual(out[0]["device_user_id"], "10783")
		self.assertEqual(out[0]["employee"], "HR-EMP-0001")
		self.assertEqual(out[0]["status"], "Active")

	def test_skips_incomplete_rows(self):
		rows = [
			{"timepay_id": "", "erpnext_employee": "HR-EMP-0001"},
			{"timepay_id": "10785", "erpnext_employee": ""},
		]
		self.assertEqual(mapping_rows_from_reconciliation(rows), [])


if __name__ == "__main__":
	unittest.main()
