"""Unit tests for the GRN Checklist variance math (Frappe-free).

Ports the thresholds from Django ``GoodsReceiptNote.update_totals`` /
``GRNLineItem.update_totals``: NORMAL +/-2, MINOR <=5, MAJOR <=10, CRITICAL >10;
claim required when |variance%| > 2.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_grn_variance_math -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import grn_math


class TestVarianceCategory(unittest.TestCase):
	def test_thresholds(self):
		self.assertEqual(grn_math.variance_category(0), "NORMAL")
		self.assertEqual(grn_math.variance_category(2.0), "NORMAL")
		self.assertEqual(grn_math.variance_category(-2.0), "NORMAL")
		self.assertEqual(grn_math.variance_category(2.01), "MINOR")
		self.assertEqual(grn_math.variance_category(5.0), "MINOR")
		self.assertEqual(grn_math.variance_category(-5.0), "MINOR")
		self.assertEqual(grn_math.variance_category(5.01), "MAJOR")
		self.assertEqual(grn_math.variance_category(10.0), "MAJOR")
		self.assertEqual(grn_math.variance_category(10.01), "CRITICAL")
		self.assertEqual(grn_math.variance_category(-25.0), "CRITICAL")

	def test_claim_required_over_two_percent(self):
		self.assertFalse(grn_math.claim_required(2.0))
		self.assertFalse(grn_math.claim_required(-2.0))
		self.assertTrue(grn_math.claim_required(2.01))
		self.assertTrue(grn_math.claim_required(-3.0))


class TestVariancePct(unittest.TestCase):
	def test_zero_base_is_safe(self):
		self.assertEqual(grn_math.variance_pct(5, 0), 0.0)

	def test_negative_variance(self):
		# 980 received vs 1000 expected -> -2%
		self.assertEqual(grn_math.variance_pct(-20, 1000), -2.0)


class TestLineStatus(unittest.TestCase):
	def test_pending_partial_complete(self):
		self.assertEqual(grn_math.line_status(100, 0, 0), "Pending")
		self.assertEqual(grn_math.line_status(100, 40, -1.0), "Partial")
		self.assertEqual(grn_math.line_status(100, 100, 0), "Complete")

	def test_discrepancy_overrides(self):
		# Over-received by >5% -> Discrepancy even though boxes are "complete".
		self.assertEqual(grn_math.line_status(100, 110, 6.0), "Discrepancy")
		# Short by >5% -> Discrepancy over Partial.
		self.assertEqual(grn_math.line_status(100, 90, -6.0), "Discrepancy")


class TestComputeLine(unittest.TestCase):
	def test_derived_fields(self):
		out = grn_math.compute_line(
			expected_boxes=100, expected_kg=2000.0, received_boxes=98, received_kg=1960.0
		)
		self.assertEqual(out["pending_boxes"], 2)
		self.assertEqual(out["pending_kg"], 40.0)
		self.assertEqual(out["variance_kg"], -40.0)
		self.assertEqual(out["variance_pct"], -2.0)
		self.assertEqual(out["status"], "Partial")


class TestComputeHeader(unittest.TestCase):
	def test_normal_receipt(self):
		out = grn_math.compute_header(
			expected_boxes=100, expected_kg=2000.0, received_boxes=100, received_kg=2000.0
		)
		self.assertEqual(out["category"], "NORMAL")
		self.assertEqual(out["completion_pct"], 100.0)
		self.assertEqual(out["receipt_status"], "Complete")
		self.assertFalse(out["claim_required"])

	def test_critical_shortage_flags_claim_and_discrepancy(self):
		out = grn_math.compute_header(
			expected_boxes=100, expected_kg=2000.0, received_boxes=80, received_kg=1600.0
		)
		self.assertEqual(out["variance_pct"], -20.0)
		self.assertEqual(out["category"], "CRITICAL")
		self.assertTrue(out["claim_required"])
		self.assertEqual(out["receipt_status"], "Discrepancy")
		self.assertEqual(out["pending_kg"], 400.0)

	def test_partial_receipt_large_gap_reads_discrepancy(self):
		# Faithful to Django: variance is measured vs the expected TOTAL, so a
		# half-received GRN carries a big negative variance and reads Discrepancy
		# until it completes.
		out = grn_math.compute_header(
			expected_boxes=100, expected_kg=2000.0, received_boxes=50, received_kg=1000.0
		)
		self.assertEqual(out["completion_pct"], 50.0)
		self.assertEqual(out["receipt_status"], "Discrepancy")
		self.assertEqual(out["category"], "CRITICAL")

	def test_nearly_complete_reads_receiving(self):
		# 1 box / 20kg pending out of 100/2000 -> -1% variance -> Receiving.
		out = grn_math.compute_header(
			expected_boxes=100, expected_kg=2000.0, received_boxes=99, received_kg=1980.0
		)
		self.assertEqual(out["receipt_status"], "Receiving")
		self.assertEqual(out["category"], "NORMAL")
		self.assertFalse(out["claim_required"])

	def test_zero_expected_is_safe(self):
		out = grn_math.compute_header(0, 0.0, 0, 0.0)
		self.assertEqual(out["completion_pct"], 0.0)
		self.assertEqual(out["receipt_status"], "Pending")


if __name__ == "__main__":
	unittest.main()
