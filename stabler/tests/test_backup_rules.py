"""Unit tests for the pure backup/DR decision logic (no Frappe, no I/O)."""
from __future__ import annotations

import unittest

from stabler.api._backup_rules import (
	classify_backup_file,
	group_backup_sets,
	human_size,
	parse_backup_timestamp,
	prune_by_policy,
	restore_test_overdue,
	restore_test_schedule,
	select_for_retention,
	verify_checksum,
)

DB = "20260615_120000-anjan_erpstable_com-database.sql.gz"
FILES = "20260615_120000-anjan_erpstable_com-files.tar"
PRIV = "20260615_120000-anjan_erpstable_com-private-files.tar"
CFG = "20260615_120000-anjan_erpstable_com-site_config_backup.json"


class ParseAndClassifyTest(unittest.TestCase):
	def test_timestamp_extracted(self):
		self.assertEqual(parse_backup_timestamp(DB), "20260615_120000")

	def test_non_backup_name_is_none(self):
		self.assertIsNone(parse_backup_timestamp("random.txt"))
		self.assertIsNone(parse_backup_timestamp(""))

	def test_classify(self):
		self.assertEqual(classify_backup_file(DB), "database")
		self.assertEqual(classify_backup_file(FILES), "files")
		self.assertEqual(classify_backup_file(PRIV), "private-files")
		self.assertEqual(classify_backup_file(CFG), "config")
		self.assertEqual(classify_backup_file("whatever.zip"), "other")

	def test_private_files_not_misread_as_files(self):
		# "-private-files.tar" also ends with "files.tar" — order matters.
		self.assertEqual(classify_backup_file(PRIV), "private-files")


class HumanSizeTest(unittest.TestCase):
	def test_units(self):
		self.assertEqual(human_size(512), "512 B")
		self.assertEqual(human_size(1024), "1.0 KB")
		self.assertEqual(human_size(1536), "1.5 KB")
		self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")

	def test_garbage(self):
		self.assertEqual(human_size("x"), "—")
		self.assertEqual(human_size(None), "—")


class GroupSetsTest(unittest.TestCase):
	def test_groups_by_timestamp(self):
		files = [
			{"name": DB, "size": 1000, "modified": "2026-06-15 12:00:00"},
			{"name": FILES, "size": 2000, "modified": "2026-06-15 12:00:01"},
			{"name": PRIV, "size": 500, "modified": "2026-06-15 12:00:02"},
			{"name": "20260614_120000-anjan_erpstable_com-database.sql.gz", "size": 900,
			 "modified": "2026-06-14 12:00:00"},
		]
		sets = group_backup_sets(files)
		self.assertEqual(len(sets), 2)
		# newest first
		self.assertEqual(sets[0]["key"], "20260615_120000")
		self.assertTrue(sets[0]["has_database"])
		self.assertTrue(sets[0]["has_files"])
		self.assertEqual(sets[0]["total_size"], 3500)
		self.assertFalse(sets[1]["has_files"])

	def test_ignores_unparseable(self):
		self.assertEqual(group_backup_sets([{"name": "junk", "size": 1}]), [])


class RetentionTest(unittest.TestCase):
	def _keys(self, n):
		# n daily sets ending 2026-06-15
		import datetime as dt
		base = dt.datetime(2026, 6, 15, 12, 0, 0)
		return [(base - dt.timedelta(days=i)).strftime("%Y%m%d_%H%M%S") for i in range(n)]

	def test_keeps_minimum_even_if_old(self):
		keys = self._keys(10)
		# keep_days=3 would delete most, but keep_min=5 protects newest 5.
		delete = select_for_retention(keys, keep_days=3, keep_min=5, now_ts="20260615_120000")
		self.assertNotIn(keys[0], delete)
		self.assertNotIn(keys[4], delete)  # 5th newest protected
		self.assertIn(keys[9], delete)  # 10-day-old removed

	def test_keep_days_zero_deletes_nothing(self):
		keys = self._keys(10)
		self.assertEqual(select_for_retention(keys, keep_days=0, keep_min=2, now_ts="20260615_120000"), [])

	def test_recent_sets_never_deleted(self):
		keys = self._keys(3)  # all within 3 days
		delete = select_for_retention(keys, keep_days=14, keep_min=1, now_ts="20260615_120000")
		self.assertEqual(delete, [])


class RestoreOverdueTest(unittest.TestCase):
	def test_never_tested_is_overdue(self):
		self.assertTrue(restore_test_overdue(None, interval_days=90, today="2026-06-15"))
		self.assertTrue(restore_test_overdue("", interval_days=90, today="2026-06-15"))

	def test_recent_test_not_overdue(self):
		self.assertFalse(restore_test_overdue("2026-05-01", interval_days=90, today="2026-06-15"))

	def test_old_test_overdue(self):
		self.assertTrue(restore_test_overdue("2026-01-01", interval_days=90, today="2026-06-15"))

	def test_interval_zero_disables(self):
		self.assertFalse(restore_test_overdue(None, interval_days=0, today="2026-06-15"))


# ---------------------------------------------------------------------------
# Phase 2: prune_by_policy
# ---------------------------------------------------------------------------

class PruneByPolicyTest(unittest.TestCase):
	def _daily_keys(self, n_days: int, base: str = "20260615") -> list[str]:
		"""Generate n_days consecutive daily backup keys ending on base date."""
		import datetime as dt
		b = dt.datetime.strptime(base, "%Y%m%d")
		return [(b - dt.timedelta(days=i)).strftime("%Y%m%d_120000") for i in range(n_days)]

	def test_empty_returns_empty(self):
		self.assertEqual(prune_by_policy([], keep_daily=7, keep_weekly=4, now_ts="20260615_120000"), [])

	def test_keep_daily_protects_newest(self):
		keys = self._daily_keys(30)
		to_delete = prune_by_policy(keys, keep_daily=7, keep_weekly=0, now_ts="20260615_120000")
		# Newest 7 must not appear in delete list.
		for k in keys[:7]:
			self.assertNotIn(k, to_delete)
		# Older ones should be deleted (weekly disabled).
		self.assertIn(keys[20], to_delete)

	def test_keep_weekly_preserves_one_per_week(self):
		# 28 daily keys = 4 weeks.
		keys = self._daily_keys(28)
		to_delete = prune_by_policy(keys, keep_daily=0, keep_weekly=4, now_ts="20260615_120000")
		kept = set(keys) - set(to_delete)
		# We should have exactly 4 sets kept (one per week).
		self.assertEqual(len(kept), 4)

	def test_daily_and_weekly_tiers_combine(self):
		keys = self._daily_keys(30)
		to_delete = prune_by_policy(keys, keep_daily=7, keep_weekly=3, now_ts="20260615_120000")
		kept = set(keys) - set(to_delete)
		# At least 7 (daily) + up to 3 more weekly (that don't overlap with daily).
		self.assertGreaterEqual(len(kept), 7)

	def test_nothing_deleted_when_below_daily_threshold(self):
		keys = self._daily_keys(5)
		to_delete = prune_by_policy(keys, keep_daily=7, keep_weekly=4, now_ts="20260615_120000")
		self.assertEqual(to_delete, [])

	def test_keep_daily_zero_still_applies_weekly(self):
		keys = self._daily_keys(14)
		to_delete = prune_by_policy(keys, keep_daily=0, keep_weekly=2, now_ts="20260615_120000")
		kept = set(keys) - set(to_delete)
		# 14 days = 2 full weeks → 2 weekly keepers.
		self.assertEqual(len(kept), 2)

	def test_deletion_is_complement_of_kept(self):
		keys = self._daily_keys(10)
		to_delete = prune_by_policy(keys, keep_daily=3, keep_weekly=2, now_ts="20260615_120000")
		kept = set(keys) - set(to_delete)
		self.assertEqual(sorted(to_delete + list(kept)), sorted(keys))


# ---------------------------------------------------------------------------
# Phase 2: restore_test_schedule
# ---------------------------------------------------------------------------

class RestoreTestScheduleTest(unittest.TestCase):
	def test_never_tested_is_overdue_immediately(self):
		r = restore_test_schedule(None, interval_days=90, today="2026-06-15")
		self.assertTrue(r["overdue"])
		self.assertEqual(r["next_due"], "2026-06-15")
		self.assertLessEqual(r["days_until_due"], 0)

	def test_fresh_test_not_overdue(self):
		r = restore_test_schedule("2026-06-01", interval_days=90, today="2026-06-15")
		self.assertFalse(r["overdue"])
		self.assertEqual(r["next_due"], "2026-08-30")  # 2026-06-01 + 90 days
		self.assertGreater(r["days_until_due"], 0)

	def test_old_test_overdue(self):
		r = restore_test_schedule("2026-01-01", interval_days=90, today="2026-06-15")
		self.assertTrue(r["overdue"])
		self.assertLess(r["days_until_due"], 0)

	def test_zero_interval_disabled(self):
		r = restore_test_schedule(None, interval_days=0, today="2026-06-15")
		self.assertFalse(r["overdue"])
		self.assertIsNone(r["next_due"])

	def test_exact_due_date_is_overdue(self):
		"""When today == next_due, the test is due (days_until_due == 0 → overdue)."""
		r = restore_test_schedule("2026-03-17", interval_days=90, today="2026-06-15")
		self.assertEqual(r["next_due"], "2026-06-15")
		self.assertTrue(r["overdue"])
		self.assertEqual(r["days_until_due"], 0)

	def test_returns_all_expected_keys(self):
		r = restore_test_schedule("2026-05-01", interval_days=30, today="2026-06-15")
		for key in ("next_due", "overdue", "days_until_due", "interval_days", "last_test_date"):
			self.assertIn(key, r)


# ---------------------------------------------------------------------------
# Phase 2: verify_checksum
# ---------------------------------------------------------------------------

GOOD_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
OTHER_SHA256 = "abc123def456abc123def456abc123def456abc123def456abc123def456abc1"

class VerifyChecksumTest(unittest.TestCase):
	def test_matching_checksums_pass(self):
		r = verify_checksum(GOOD_SHA256, GOOD_SHA256)
		self.assertTrue(r["ok"])
		self.assertEqual(r["reason"], "match")

	def test_mismatching_checksums_fail(self):
		r = verify_checksum(GOOD_SHA256, OTHER_SHA256)
		self.assertFalse(r["ok"])
		self.assertEqual(r["reason"], "mismatch")

	def test_missing_expected_fails(self):
		r = verify_checksum(None, GOOD_SHA256)
		self.assertFalse(r["ok"])
		self.assertEqual(r["reason"], "missing expected")

	def test_missing_actual_fails(self):
		r = verify_checksum(GOOD_SHA256, None)
		self.assertFalse(r["ok"])
		self.assertEqual(r["reason"], "missing actual")

	def test_both_missing_fails(self):
		r = verify_checksum(None, None)
		self.assertFalse(r["ok"])
		self.assertEqual(r["reason"], "missing expected")

	def test_case_insensitive(self):
		"""sha256sum outputs lowercase; openssl dgst outputs uppercase."""
		r = verify_checksum(GOOD_SHA256.upper(), GOOD_SHA256.lower())
		self.assertTrue(r["ok"])

	def test_whitespace_trimmed(self):
		r = verify_checksum("  " + GOOD_SHA256 + " ", GOOD_SHA256)
		self.assertTrue(r["ok"])

	def test_algorithm_stored_in_result(self):
		r = verify_checksum(GOOD_SHA256, GOOD_SHA256, algorithm="sha512")
		self.assertEqual(r["algorithm"], "sha512")

	def test_empty_string_expected_fails(self):
		r = verify_checksum("", GOOD_SHA256)
		self.assertFalse(r["ok"])
		self.assertEqual(r["reason"], "missing expected")

	def test_returns_all_expected_keys(self):
		r = verify_checksum(GOOD_SHA256, GOOD_SHA256)
		for key in ("ok", "algorithm", "expected", "actual", "reason"):
			self.assertIn(key, r)


if __name__ == "__main__":
	unittest.main()
