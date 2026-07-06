"""Unit tests for stabler.api._payroll_residual (whole-UZS residual allocation).

Run with:
    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_payroll_residual -v
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from stabler.api._payroll_residual import (
	distribute_amount,
	largest_remainder_round,
	round_uzs,
)


class TestRoundUzs(unittest.TestCase):
	def test_half_up_positive(self):
		self.assertEqual(round_uzs(1234.5), 1235)
		self.assertEqual(round_uzs(1234.49), 1234)

	def test_half_away_from_zero_negative(self):
		# math.floor(x + 0.5) would give -1234 for -1234.5; half-away gives -1235.
		self.assertEqual(round_uzs(-1234.5), -1235)
		self.assertEqual(round_uzs(-1234.49), -1234)

	def test_decimal_and_int_inputs(self):
		self.assertEqual(round_uzs(Decimal("10.5")), 11)
		self.assertEqual(round_uzs(7), 7)
		self.assertEqual(round_uzs(None), 0)


class TestLargestRemainderRound(unittest.TestCase):
	def test_parts_sum_to_rounded_total(self):
		r = largest_remainder_round([100 / 3, 100 / 3, 100 / 3])
		self.assertEqual(sum(r), 100)
		self.assertEqual(sorted(r), [33, 33, 34])

	def test_target_override_ties_out(self):
		# parts must sum to an externally supplied net, not their own round-sum.
		r = largest_remainder_round([33.3, 33.3, 33.3], target_total=100)
		self.assertEqual(sum(r), 100)

	def test_integer_inputs_unchanged(self):
		self.assertEqual(largest_remainder_round([5, 7, 8]), [5, 7, 8])

	def test_sign_preserved_with_deduction(self):
		r = largest_remainder_round([100.6, -30.6])  # sum 70.0
		self.assertEqual(sum(r), 70)

	def test_all_negative(self):
		self.assertEqual(sum(largest_remainder_round([-10.4, -10.4, -10.4])), -31)

	def test_residual_exceeds_part_count(self):
		# floors 0,0 with residual 2 -> both parts absorb one unit.
		self.assertEqual(largest_remainder_round([0.9, 0.9]), [1, 1])

	def test_empty(self):
		self.assertEqual(largest_remainder_round([]), [])

	def test_largest_remainder_gets_the_unit(self):
		# 10.1 + 10.1 + 10.8 = 31.0 -> target 31; bases 10,10,10; residual 1
		# goes to the largest remainder (0.8), i.e. the third element.
		self.assertEqual(largest_remainder_round([10.1, 10.1, 10.8]), [10, 10, 11])


class TestDistributeAmount(unittest.TestCase):
	def test_even_pool_ties_out(self):
		r = distribute_amount(100, [1, 1, 1])
		self.assertEqual(sum(r), 100)
		self.assertEqual(sorted(r), [33, 33, 34])

	def test_weighted_pool(self):
		self.assertEqual(distribute_amount(100, [70, 30]), [70, 30])

	def test_large_pool_no_so_m_lost(self):
		r = distribute_amount(1_000_000, [3.1, 2.9, 4.0])
		self.assertEqual(sum(r), 1_000_000)

	def test_zero_weights_put_all_on_first(self):
		r = distribute_amount(500, [0, 0, 0])
		self.assertEqual(sum(r), 500)
		self.assertEqual(r[0], 500)

	def test_empty_weights(self):
		self.assertEqual(distribute_amount(100, []), [])

	def test_fractional_total_rounded(self):
		# total 99.6 -> 100, split evenly, still ties out.
		r = distribute_amount(99.6, [1, 1])
		self.assertEqual(sum(r), 100)


if __name__ == "__main__":
	unittest.main()
