"""Unit tests for the FX residual tolerance helpers (pure)."""

from __future__ import annotations

import unittest

from stabler.api._fx_residual import (
	base_precision_for,
	residual_tolerance,
	within_tolerance,
)


class BasePrecisionTest(unittest.TestCase):
	def test_two_dp_currencies(self):
		self.assertEqual(base_precision_for("USD"), 2)
		self.assertEqual(base_precision_for("EUR"), 2)

	def test_zero_dp_currencies(self):
		self.assertEqual(base_precision_for("UZS"), 0)
		self.assertEqual(base_precision_for("JPY"), 0)
		self.assertEqual(base_precision_for("vnd"), 0)  # case-insensitive

	def test_unknown_defaults_two(self):
		self.assertEqual(base_precision_for(None), 2)
		self.assertEqual(base_precision_for(""), 2)


class ResidualToleranceTest(unittest.TestCase):
	def test_usd_scales_with_refs(self):
		# 1 ref -> 0.01*(1+2)=0.03 ; 5 refs -> 0.07
		self.assertAlmostEqual(residual_tolerance(1, 2), 0.03)
		self.assertAlmostEqual(residual_tolerance(5, 2), 0.07)

	def test_zero_refs_has_cushion(self):
		self.assertAlmostEqual(residual_tolerance(0, 2), 0.02)

	def test_zero_dp_currency(self):
		# whole-unit currency: tolerance in whole units
		self.assertEqual(residual_tolerance(1, 0), 3)


class WithinToleranceTest(unittest.TestCase):
	def test_the_reported_case(self):
		# the live bug: -$0.01 with one invoice -> tol 0.03 -> within
		self.assertTrue(within_tolerance(-0.01, residual_tolerance(1, 2)))

	def test_boundary_inclusive(self):
		self.assertTrue(within_tolerance(0.03, 0.03))
		self.assertFalse(within_tolerance(0.04, 0.03))

	def test_zero_is_not_a_residual(self):
		# nothing to book when already balanced
		self.assertFalse(within_tolerance(0, 0.03))
		self.assertFalse(within_tolerance(0.0, 0.05))

	def test_large_difference_rejected(self):
		# a real allocation error, not rounding
		self.assertFalse(within_tolerance(5.0, 0.05))

	def test_garbage_safe(self):
		self.assertFalse(within_tolerance("x", 0.03))
		self.assertFalse(within_tolerance(0.01, None))


if __name__ == "__main__":
	unittest.main()
