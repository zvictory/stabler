"""Unit tests for stabler.api._advance_aging (WP-I10, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_advance_aging -v
"""

from __future__ import annotations

import unittest
from datetime import date

from stabler.api._advance_aging import (
	age_days,
	aging_rows,
	aging_summary,
	classify,
)

_TODAY = date(2026, 7, 17)


class TestAge(unittest.TestCase):
	def test_age_days(self):
		self.assertEqual(age_days("2026-07-01", _TODAY), 16)
		self.assertEqual(age_days(date(2026, 1, 18), _TODAY), 180)

	def test_future_date_clamped(self):
		self.assertEqual(age_days("2026-08-01", _TODAY), 0)


class TestClassify(unittest.TestCase):
	def test_buckets(self):
		self.assertEqual(classify(0), "OK")
		self.assertEqual(classify(149), "OK")
		self.assertEqual(classify(150), "WARN")  # uyarı eşiği dahil
		self.assertEqual(classify(179), "WARN")
		self.assertEqual(classify(180), "BREACH")  # 180. gün = ihlal
		self.assertEqual(classify(365), "BREACH")


class TestRowsAndSummary(unittest.TestCase):
	def _rows(self):
		return [
			{"name": "PE-A", "posting_date": "2026-07-01", "unallocated_amount": 1000},  # 16g OK
			{"name": "PE-B", "posting_date": "2026-02-10", "unallocated_amount": 5000},  # 157g WARN
			{"name": "PE-C", "posting_date": "2025-12-01", "unallocated_amount": 20000},  # 228g BREACH
		]

	def test_rows_annotated_oldest_first(self):
		rows = aging_rows(self._rows(), _TODAY)
		self.assertEqual([r["name"] for r in rows], ["PE-C", "PE-B", "PE-A"])
		self.assertEqual(rows[0]["bucket"], "BREACH")
		self.assertEqual(rows[0]["days_to_breach"], 0)
		self.assertEqual(rows[1]["bucket"], "WARN")
		self.assertEqual(rows[1]["days_to_breach"], 180 - 157)
		self.assertEqual(rows[2]["bucket"], "OK")

	def test_summary_totals(self):
		s = aging_summary(aging_rows(self._rows(), _TODAY))
		self.assertEqual(s["total_unallocated"], 26000.0)
		self.assertEqual(s["warn_count"], 1)
		self.assertEqual(s["warn_amount"], 5000.0)
		self.assertEqual(s["breach_count"], 1)
		self.assertEqual(s["breach_amount"], 20000.0)
		self.assertEqual(s["at_risk_amount"], 25000.0)

	def test_empty_safe(self):
		self.assertEqual(aging_rows([], _TODAY), [])
		self.assertEqual(aging_summary([])["total_unallocated"], 0.0)


if __name__ == "__main__":
	unittest.main()
