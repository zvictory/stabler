"""Tests for Timepay daily-stat ingestion into raw attendance events."""

from __future__ import annotations

import unittest

from stabler.api._attendance_ingest import dedupe_key
from stabler.integrations.timepay.sync import events_from_daily_stat, sync_date


def row(**kw):
	base = {
		"id": 10783,
		"full_name": "Test Employee",
		"stats": {
			"first_check_in": "09:01",
			"last_check_out": "18:03",
		},
	}
	base.update(kw)
	return base


class FakeClient:
	def __init__(self, pages):
		self.pages = list(pages)
		self.calls = []

	def daily_stats(self, **kwargs):
		self.calls.append(kwargs)
		return self.pages.pop(0)


class FakeRepo:
	def __init__(self, seen=None):
		self.seen = set(seen or [])
		self.events = []
		self.logs = []

	def existing_keys(self, date):
		return set(self.seen)

	def insert_raw_event(self, event):
		self.events.append(event)
		key = dedupe_key(event)
		self.seen.add(key)
		return f"RAW-{len(self.events):04d}"

	def log(self, **kwargs):
		self.logs.append(kwargs)


class EventsFromDailyStatTest(unittest.TestCase):
	def test_first_and_last_times_become_deterministic_raw_punches(self):
		events = events_from_daily_stat(row(), date="2026-06-15")

		self.assertEqual(len(events), 2)
		self.assertEqual(events[0]["external_event_id"], "timepay:2026-06-15:10783:in")
		self.assertEqual(events[0]["device_user_id"], "10783")
		self.assertEqual(events[0]["timestamp"], "2026-06-15 09:01:00")
		self.assertEqual(events[0]["direction"], "IN")
		self.assertEqual(events[1]["external_event_id"], "timepay:2026-06-15:10783:out")
		self.assertEqual(events[1]["timestamp"], "2026-06-15 18:03:00")
		self.assertEqual(events[1]["direction"], "OUT")

	def test_missing_checkout_only_creates_checkin_event(self):
		events = events_from_daily_stat(row(stats={"first_check_in": "09:01", "last_check_out": None}), date="2026-06-15")

		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["direction"], "IN")


class SyncDateTest(unittest.TestCase):
	def test_sync_date_inserts_new_raw_events_and_logs_them(self):
		client = FakeClient([
			{"count": 1, "next": None, "previous": None, "results": [row()]},
		])
		repo = FakeRepo()

		out = sync_date(client=client, repo=repo, date="2026-06-15", page_limit=50)

		self.assertEqual(out, {"inserted": 2, "duplicates": 0, "rows_seen": 1})
		self.assertEqual(len(repo.events), 2)
		self.assertEqual([log["result"] for log in repo.logs], ["Processed", "Processed"])

	def test_sync_date_can_limit_to_one_timepay_employee(self):
		client = FakeClient([
			{"count": 1, "next": None, "previous": None, "results": [row()]},
		])
		repo = FakeRepo()

		sync_date(client=client, repo=repo, date="2026-06-15", employee_ids=[10783])

		self.assertEqual(client.calls[0]["employee_ids"], [10783])

	def test_sync_date_skips_existing_dedupe_keys_and_logs_duplicate(self):
		existing = events_from_daily_stat(row(), date="2026-06-15")[0]
		client = FakeClient([
			{"count": 1, "next": None, "previous": None, "results": [row()]},
		])
		repo = FakeRepo(seen={dedupe_key(existing)})

		out = sync_date(client=client, repo=repo, date="2026-06-15", page_limit=50)

		self.assertEqual(out, {"inserted": 1, "duplicates": 1, "rows_seen": 1})
		self.assertEqual(len(repo.events), 1)
		self.assertEqual([log["result"] for log in repo.logs], ["Duplicate", "Processed"])


if __name__ == "__main__":
	unittest.main()
