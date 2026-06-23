"""Unit tests for pure equipment-coverage helpers (no frappe, no DB)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.api._equipment import coverage_state, summarise_coverage


class TestCoverageState(unittest.TestCase):
	def test_none_when_no_dates(self):
		self.assertEqual(coverage_state(None, None, "2026-06-23"), "none")
		self.assertEqual(coverage_state("", "", "2026-06-23"), "none")

	def test_covered_by_warranty(self):
		self.assertEqual(coverage_state("2026-12-31", None, "2026-06-23"), "covered")

	def test_covered_by_amc_when_warranty_expired(self):
		self.assertEqual(coverage_state("2025-01-01", "2026-09-01", "2026-06-23"), "covered")

	def test_expired_when_both_past(self):
		self.assertEqual(coverage_state("2025-01-01", "2025-06-01", "2026-06-23"), "expired")

	def test_covered_on_exact_expiry_day(self):
		self.assertEqual(coverage_state("2026-06-23", None, "2026-06-23"), "covered")

	def test_handles_datetime_strings(self):
		self.assertEqual(coverage_state("2026-12-31 00:00:00", None, "2026-06-23"), "covered")


class TestSummarise(unittest.TestCase):
	def test_counts(self):
		rows = [
			{"warranty_expiry_date": "2026-12-31", "amc_expiry_date": None},
			{"warranty_expiry_date": "2025-01-01", "amc_expiry_date": "2025-02-01"},
			{"warranty_expiry_date": None, "amc_expiry_date": None},
			{"warranty_expiry_date": None, "amc_expiry_date": "2027-01-01"},
		]
		got = summarise_coverage(rows, "2026-06-23")
		self.assertEqual(got, {"total": 4, "covered": 2, "expired": 1, "none": 1})

	def test_empty(self):
		self.assertEqual(summarise_coverage([], "2026-06-23"), {"total": 0, "covered": 0, "expired": 0, "none": 0})


if __name__ == "__main__":
	unittest.main()
