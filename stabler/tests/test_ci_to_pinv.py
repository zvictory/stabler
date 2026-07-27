"""Unit tests for stabler.api._ci_to_pinv (WP-I5, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_to_pinv -v
"""

from __future__ import annotations

import unittest

from stabler.api._ci_to_pinv import (
	lines_total,
	no_double_count,
	pinv_lines_from_ci_items,
	plan_advance_allocation,
	reconciles,
)
from stabler.api._import_exposure import open_commitment


class TestLines(unittest.TestCase):
	def test_lines_from_ci_items(self):
		items = [
			{"item": "SNIK", "qty": 10, "rate": 5, "amount": 50},
			{"item": "VAFLI", "qty": 2, "rate": 100, "amount": 200},
		]
		lines = pinv_lines_from_ci_items(items)
		self.assertEqual(len(lines), 2)
		self.assertEqual(lines[0]["item_code"], "SNIK")
		self.assertEqual(lines_total(lines), 250.0)

	def test_skips_rows_without_item(self):
		items = [{"item": None, "amount": 999}, {"item_code": "X", "amount": 10}]
		lines = pinv_lines_from_ci_items(items)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["item_code"], "X")

	def test_amount_preserved_not_recomputed(self):
		# Weak-currency: amount is ground truth, never re-derived from qty×rate.
		items = [{"item": "A", "qty": 3, "rate": 8333.333, "amount": 25000}]
		self.assertEqual(lines_total(pinv_lines_from_ci_items(items)), 25000.0)

	def test_empty(self):
		self.assertEqual(pinv_lines_from_ci_items([]), [])
		self.assertEqual(pinv_lines_from_ci_items(None), [])
		self.assertEqual(lines_total(None), 0.0)


class TestAllocation(unittest.TestCase):
	def test_single_advance_covers_part(self):
		plan = plan_advance_allocation(10000, [{"name": "PE-1", "unallocated_amount": 7000}])
		self.assertEqual(plan["total_allocated"], 7000.0)
		self.assertEqual(plan["outstanding_after"], 3000.0)
		self.assertEqual(plan["allocations"], [{"payment_entry": "PE-1", "amount": 7000.0}])

	def test_advance_capped_at_invoice_total(self):
		# An advance larger than the invoice never over-allocates.
		plan = plan_advance_allocation(5000, [{"name": "PE-1", "unallocated_amount": 9000}])
		self.assertEqual(plan["total_allocated"], 5000.0)
		self.assertEqual(plan["outstanding_after"], 0.0)
		self.assertEqual(plan["allocations"][0]["amount"], 5000.0)

	def test_two_advances_bank_then_cash(self):
		plan = plan_advance_allocation(
			10000,
			[
				{"name": "PE-BANK", "unallocated_amount": 6000},
				{"name": "PE-CASH", "unallocated_amount": 6000},
			],
		)
		self.assertEqual(plan["total_allocated"], 10000.0)
		self.assertEqual(plan["outstanding_after"], 0.0)
		self.assertEqual([a["amount"] for a in plan["allocations"]], [6000.0, 4000.0])

	def test_zero_and_negative_advances_ignored(self):
		plan = plan_advance_allocation(
			1000,
			[
				{"name": "PE-0", "unallocated_amount": 0},
				{"name": "PE-NEG", "unallocated_amount": -50},
				{"name": "PE-OK", "unallocated_amount": 400},
			],
		)
		self.assertEqual(plan["total_allocated"], 400.0)
		self.assertEqual(plan["allocations"], [{"payment_entry": "PE-OK", "amount": 400.0}])

	def test_no_advances(self):
		plan = plan_advance_allocation(1000, [])
		self.assertEqual(plan["total_allocated"], 0.0)
		self.assertEqual(plan["outstanding_after"], 1000.0)


class TestNoDoubleCount(unittest.TestCase):
	def test_exposure_delta_equals_invoice(self):
		# Before: one open CI of 10000 in virtual exposure.
		before = open_commitment([{"status": "AVAILABLE", "agreed_total": 10000}])
		# After conversion the CI has a linked Purchase Invoice → drops out.
		after = open_commitment(
			[{"status": "AVAILABLE", "agreed_total": 10000, "has_purchase_invoice": True}]
		)
		self.assertEqual(before, 10000.0)
		self.assertEqual(after, 0.0)
		# The money that left exposure equals the A/P opened — no double-count, no gap.
		self.assertTrue(no_double_count(before, after, 10000))

	def test_converted_ci_excluded_from_open_commitment(self):
		rows = [
			{"status": "AVAILABLE", "agreed_total": 3000},
			{"status": "AVAILABLE", "agreed_total": 5000, "has_purchase_invoice": True},
			{"status": "DELIVERED_TO_UZBEKISTAN", "agreed_total": 9000},
		]
		# Only the un-converted, non-terminal CI counts.
		self.assertEqual(open_commitment(rows), 3000.0)

	def test_reconciles_kurus(self):
		self.assertTrue(reconciles(24999.6, 25000, eps=0.5))
		self.assertFalse(reconciles(24000, 25000, eps=0.5))


if __name__ == "__main__":
	unittest.main()
