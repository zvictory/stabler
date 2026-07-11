"""Unit tests for the pure customer-hierarchy logic (no frappe, no DB)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.stabler.customer_hierarchy import (
	ERR_HAS_CHILDREN,
	ERR_PARENT_HAS_PARENT,
	ERR_SELF,
	check_parent_link,
	children_balance_map,
	cumulative_balance,
)


class TestCheckParentLink(unittest.TestCase):
	def test_empty_parent_is_valid(self):
		# Clearing the link is always allowed.
		self.assertIsNone(
			check_parent_link("A", "", parent_has_own_parent=False, customer_has_children=False)
		)
		self.assertIsNone(
			check_parent_link("A", None, parent_has_own_parent=False, customer_has_children=False)
		)

	def test_valid_link(self):
		self.assertIsNone(
			check_parent_link("Child", "Parent", parent_has_own_parent=False, customer_has_children=False)
		)

	def test_self_parent_rejected(self):
		self.assertEqual(
			check_parent_link("A", "A", parent_has_own_parent=False, customer_has_children=False),
			ERR_SELF,
		)

	def test_parent_that_has_a_parent_rejected(self):
		# Chosen parent is itself a child → would create a 2-level tree.
		self.assertEqual(
			check_parent_link("A", "B", parent_has_own_parent=True, customer_has_children=False),
			ERR_PARENT_HAS_PARENT,
		)

	def test_customer_with_children_rejected(self):
		# This customer is already a parent → cannot also become a child.
		self.assertEqual(
			check_parent_link("A", "B", parent_has_own_parent=False, customer_has_children=True),
			ERR_HAS_CHILDREN,
		)

	def test_self_check_takes_precedence(self):
		self.assertEqual(
			check_parent_link("A", "A", parent_has_own_parent=True, customer_has_children=True),
			ERR_SELF,
		)


class TestChildrenBalanceMap(unittest.TestCase):
	def test_groups_and_sums_by_parent(self):
		rows = [
			{"name": "c1", "parent_customer": "P1", "balance": 100},
			{"name": "c2", "parent_customer": "P1", "balance": 250},
			{"name": "c3", "parent_customer": "P2", "balance": 40},
		]
		self.assertEqual(children_balance_map(rows), {"P1": 350.0, "P2": 40.0})

	def test_ignores_rows_without_parent(self):
		rows = [
			{"name": "top", "parent_customer": "", "balance": 999},
			{"name": "c1", "parent_customer": "P1", "balance": 10},
			{"name": "c2", "parent_customer": None, "balance": 5},
		]
		self.assertEqual(children_balance_map(rows), {"P1": 10.0})

	def test_custom_balance_key(self):
		rows = [{"parent_customer": "P1", "balance_acc": 12.5}]
		self.assertEqual(children_balance_map(rows, balance_key="balance_acc"), {"P1": 12.5})

	def test_none_and_missing_balance_treated_as_zero(self):
		rows = [
			{"parent_customer": "P1", "balance": None},
			{"parent_customer": "P1"},
			{"parent_customer": "P1", "balance": 7},
		]
		self.assertEqual(children_balance_map(rows), {"P1": 7.0})

	def test_empty_input(self):
		self.assertEqual(children_balance_map([]), {})


class TestCumulativeBalance(unittest.TestCase):
	def test_own_plus_children(self):
		self.assertEqual(cumulative_balance(1000, 350), 1350.0)

	def test_none_inputs(self):
		self.assertEqual(cumulative_balance(None, None), 0.0)
		self.assertEqual(cumulative_balance(500, None), 500.0)

	def test_negative_children(self):
		# Child in credit (customer overpaid) reduces the parent rollup.
		self.assertEqual(cumulative_balance(1000, -150), 850.0)

	def test_rounding(self):
		self.assertEqual(cumulative_balance(0.1, 0.2), 0.3)


if __name__ == "__main__":
	unittest.main()
