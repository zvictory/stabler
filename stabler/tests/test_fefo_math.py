"""FEFO allocation maths — pure, no site required."""

import unittest
from datetime import date, timedelta

from stabler.api import _fefo


def B(batch_no, qty, days_left, expiry_date=None):
	"""Batch row. The expiry date is derived from days_left when not given, so
	the fixture cannot drift out of sync with the ordering it is testing."""
	if expiry_date is None and days_left is not None:
		expiry_date = (date(2026, 1, 1) + timedelta(days=days_left)).isoformat()
	return {
		"batch_no": batch_no,
		"qty": qty,
		"days_left": days_left,
		"expiry_date": expiry_date,
	}


class ExpiryBucketTest(unittest.TestCase):
	def test_buckets(self):
		self.assertEqual(_fefo.expiry_bucket(-1), "expired")
		self.assertEqual(_fefo.expiry_bucket(0), "urgent")
		self.assertEqual(_fefo.expiry_bucket(30), "urgent")
		self.assertEqual(_fefo.expiry_bucket(31), "soon")
		self.assertEqual(_fefo.expiry_bucket(90), "soon")
		self.assertEqual(_fefo.expiry_bucket(91), "ok")

	def test_missing_expiry_is_not_treated_as_fresh(self):
		self.assertEqual(_fefo.expiry_bucket(None), "unknown")


class SortTest(unittest.TestCase):
	def test_nearest_expiry_first(self):
		rows = [B("C", 10, 90, "2026-04-01"), B("A", 10, 10, "2026-01-11"), B("B", 10, 45, "2026-02-15")]
		self.assertEqual([r["batch_no"] for r in _fefo.sort_fefo(rows)], ["A", "B", "C"])

	def test_undated_batches_sort_last(self):
		rows = [B("X", 5, None, None), B("A", 5, 10, "2026-01-11")]
		self.assertEqual([r["batch_no"] for r in _fefo.sort_fefo(rows)], ["A", "X"])

	def test_stable_on_equal_expiry(self):
		rows = [B("B", 5, 10), B("A", 5, 10)]
		self.assertEqual([r["batch_no"] for r in _fefo.sort_fefo(rows)], ["A", "B"])


class AllocateTest(unittest.TestCase):
	def test_single_batch_covers_demand(self):
		res = _fefo.allocate_fefo(100, [B("A", 500, 20)])
		self.assertEqual(res["allocated"], 100)
		self.assertEqual(res["shortfall"], 0)
		self.assertEqual(
			res["lines"],
			[{"batch_no": "A", "qty": 100, "expiry_date": "2026-01-21", "days_left": 20, "bucket": "urgent"}],
		)

	def test_spans_batches_in_expiry_order(self):
		res = _fefo.allocate_fefo(
			250,
			[B("LATE", 500, 200, "2026-08-01"), B("SOON", 100, 5, "2026-01-06")],
		)
		self.assertEqual([(l["batch_no"], l["qty"]) for l in res["lines"]], [("SOON", 100), ("LATE", 150)])
		self.assertEqual(res["shortfall"], 0)

	def test_shortfall_is_reported_not_raised(self):
		res = _fefo.allocate_fefo(1000, [B("A", 800, 20)])
		self.assertEqual(res["allocated"], 800)
		self.assertEqual(res["shortfall"], 200)

	def test_expired_batches_are_skipped_and_named(self):
		res = _fefo.allocate_fefo(100, [B("OLD", 500, -3), B("GOOD", 500, 40)])
		self.assertEqual([l["batch_no"] for l in res["lines"]], ["GOOD"])
		self.assertEqual(res["skipped_expired"], ["OLD"])

	def test_expired_can_be_overridden_deliberately(self):
		res = _fefo.allocate_fefo(100, [B("OLD", 500, -3)], allow_expired=True)
		self.assertEqual([l["batch_no"] for l in res["lines"]], ["OLD"])
		self.assertEqual(res["skipped_expired"], [])

	def test_zero_and_negative_stock_rows_ignored(self):
		res = _fefo.allocate_fefo(50, [B("EMPTY", 0, 10), B("NEG", -5, 12), B("A", 80, 20)])
		self.assertEqual([l["batch_no"] for l in res["lines"]], ["A"])

	def test_no_batches_is_a_full_shortfall(self):
		res = _fefo.allocate_fefo(40, [])
		self.assertEqual(res["allocated"], 0)
		self.assertEqual(res["shortfall"], 40)

	def test_fractional_kg_does_not_drift(self):
		res = _fefo.allocate_fefo(0.3, [B("A", 0.1, 10), B("B", 0.2, 20)])
		self.assertEqual(res["allocated"], 0.3)
		self.assertEqual(res["shortfall"], 0)


class SummariseTest(unittest.TestCase):
	def test_buckets_and_nearest_expiry(self):
		s = _fefo.summarise(
			[
				B("A", 100, 5, "2026-01-06"),
				B("B", 200, 60, "2026-03-01"),
				B("C", 50, -2, "2025-12-30"),
				B("D", 25, None, None),
			]
		)
		self.assertEqual(s["total_qty"], 375)
		self.assertEqual(s["batch_count"], 4)
		self.assertEqual(s["expired"], 50)
		self.assertEqual(s["urgent"], 100)
		self.assertEqual(s["soon"], 200)
		self.assertEqual(s["unknown"], 25)
		self.assertEqual(s["nearest_expiry"], "2025-12-30")

	def test_empty(self):
		s = _fefo.summarise([])
		self.assertEqual(s["total_qty"], 0)
		self.assertIsNone(s["nearest_expiry"])


if __name__ == "__main__":
	unittest.main()
