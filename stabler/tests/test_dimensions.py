"""Unit tests for the pure dimensional-quantity math (no frappe, no DB)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.api._dimensions import dimension_summary, dimensional_qty, is_dimensional


class TestIsDimensional(unittest.TestCase):
	def test(self):
		self.assertFalse(is_dimensional(""))
		self.assertFalse(is_dimensional(None))
		self.assertTrue(is_dimensional("Linear"))
		self.assertTrue(is_dimensional("Area"))
		self.assertTrue(is_dimensional("Volume"))


class TestQty(unittest.TestCase):
	def test_non_dimensional_returns_none(self):
		self.assertIsNone(dimensional_qty("", length=2, width=3))

	def test_linear(self):
		# 2.5 m × 4 pcs = 10 m
		self.assertEqual(dimensional_qty("Linear", length=2.5, pieces=4), 10.0)

	def test_area(self):
		# industrial belt: 2.5 × 0.3 × 10 = 7.5 m²
		self.assertEqual(dimensional_qty("Area", length=2.5, width=0.3, pieces=10), 7.5)

	def test_volume(self):
		# 2 × 1 × 0.5 × 3 = 3 m³
		self.assertEqual(dimensional_qty("Volume", length=2, width=1, height=0.5, pieces=3), 3.0)

	def test_blank_pieces_is_one(self):
		self.assertEqual(dimensional_qty("Area", length=2, width=3), 6.0)

	def test_zero_pieces_is_zero(self):
		self.assertEqual(dimensional_qty("Area", length=2, width=3, pieces=0), 0.0)

	def test_missing_dimension_is_zero(self):
		# Area with no width → 0 (can't compute area)
		self.assertEqual(dimensional_qty("Area", length=2, pieces=5), 0.0)

	def test_rounding(self):
		self.assertEqual(dimensional_qty("Area", length=1.111111, width=1, pieces=1), 1.111111)


class TestSummary(unittest.TestCase):
	def test_area(self):
		self.assertEqual(dimension_summary("Area", length=2.5, width=0.3, pieces=10), "2.5 × 0.3 × 10 pcs")

	def test_linear(self):
		self.assertEqual(dimension_summary("Linear", length=6, pieces=2), "6 × 2 pcs")

	def test_non_dimensional_blank(self):
		self.assertEqual(dimension_summary("", length=2), "")


if __name__ == "__main__":
	unittest.main()
