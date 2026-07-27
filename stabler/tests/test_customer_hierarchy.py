"""Unit tests for the pure customer-hierarchy logic (no frappe, no DB)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.stabler.customer_hierarchy import (
	ERR_ALLOC_EMPTY,
	ERR_ALLOC_EXCEEDS,
	ERR_ALLOC_NONPOSITIVE,
	ERR_ALLOC_UNKNOWN_INVOICE,
	ERR_HAS_CHILDREN,
	ERR_PARENT_HAS_PARENT,
	ERR_SELF,
	ERR_XFER_EMPTY,
	ERR_XFER_EXCEEDS,
	ERR_XFER_NONPOSITIVE,
	ERR_XFER_UNKNOWN_CHILD,
	check_parent_link,
	children_balance_map,
	credit_limit_decision,
	cumulative_balance,
	group_allocations_by_party,
	validate_bulk_allocations,
	validate_transfers,
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


class TestValidateBulkAllocations(unittest.TestCase):
	def setUp(self):
		# Two children, three open invoices in the chain.
		self.party_map = {"SI-1": "ChildA", "SI-2": "ChildA", "SI-3": "ChildB"}
		self.outstanding = {"SI-1": 100.0, "SI-2": 50.0, "SI-3": 200.0}

	def test_valid_allocation(self):
		allocs = [{"invoice": "SI-1", "amount": 100}, {"invoice": "SI-3", "amount": 150}]
		self.assertIsNone(validate_bulk_allocations(allocs, self.party_map, self.outstanding))

	def test_empty_is_rejected(self):
		self.assertEqual(validate_bulk_allocations([], self.party_map, self.outstanding), ERR_ALLOC_EMPTY)

	def test_all_zero_rows_is_empty(self):
		allocs = [{"invoice": "SI-1", "amount": 0}, {"invoice": "SI-3", "amount": 0}]
		self.assertEqual(validate_bulk_allocations(allocs, self.party_map, self.outstanding), ERR_ALLOC_EMPTY)

	def test_unknown_invoice_rejected(self):
		allocs = [{"invoice": "SI-99", "amount": 10}]
		self.assertEqual(
			validate_bulk_allocations(allocs, self.party_map, self.outstanding),
			ERR_ALLOC_UNKNOWN_INVOICE,
		)

	def test_negative_amount_rejected(self):
		allocs = [{"invoice": "SI-1", "amount": -5}]
		self.assertEqual(
			validate_bulk_allocations(allocs, self.party_map, self.outstanding),
			ERR_ALLOC_NONPOSITIVE,
		)

	def test_over_outstanding_rejected(self):
		allocs = [{"invoice": "SI-2", "amount": 60}]  # outstanding is 50
		self.assertEqual(
			validate_bulk_allocations(allocs, self.party_map, self.outstanding),
			ERR_ALLOC_EXCEEDS,
		)

	def test_exactly_outstanding_passes(self):
		allocs = [{"invoice": "SI-2", "amount": 50}]
		self.assertIsNone(validate_bulk_allocations(allocs, self.party_map, self.outstanding))

	def test_two_partial_rows_summed_against_outstanding(self):
		# 30 + 30 = 60 > 50 → exceeds even though each row alone is under.
		allocs = [{"invoice": "SI-2", "amount": 30}, {"invoice": "SI-2", "amount": 30}]
		self.assertEqual(
			validate_bulk_allocations(allocs, self.party_map, self.outstanding),
			ERR_ALLOC_EXCEEDS,
		)


class TestGroupAllocationsByParty(unittest.TestCase):
	def test_groups_by_child_party(self):
		party_map = {"SI-1": "ChildA", "SI-2": "ChildA", "SI-3": "ChildB"}
		allocs = [
			{"invoice": "SI-1", "amount": 100},
			{"invoice": "SI-3", "amount": 150},
			{"invoice": "SI-2", "amount": 25},
		]
		self.assertEqual(
			group_allocations_by_party(allocs, party_map),
			{
				"ChildA": [{"invoice": "SI-1", "amount": 100.0}, {"invoice": "SI-2", "amount": 25.0}],
				"ChildB": [{"invoice": "SI-3", "amount": 150.0}],
			},
		)

	def test_skips_zero_and_unknown(self):
		party_map = {"SI-1": "ChildA"}
		allocs = [
			{"invoice": "SI-1", "amount": 0},
			{"invoice": "SI-9", "amount": 10},
			{"invoice": "SI-1", "amount": 5},
		]
		self.assertEqual(
			group_allocations_by_party(allocs, party_map),
			{"ChildA": [{"invoice": "SI-1", "amount": 5.0}]},
		)


class TestCreditLimitDecision(unittest.TestCase):
	def test_zero_limit_is_unlimited(self):
		d = credit_limit_decision(0, 5000, 1000)
		self.assertFalse(d.exceeded)
		self.assertTrue(d.unlimited)

	def test_none_limit_is_unlimited(self):
		self.assertFalse(credit_limit_decision(None, 5000, 1000).exceeded)

	def test_exceeded(self):
		d = credit_limit_decision(1000, 800, 300)  # 800 + 300 = 1100 > 1000
		self.assertTrue(d.exceeded)
		self.assertEqual(d.projected, 1100.0)

	def test_exactly_at_limit_passes(self):
		d = credit_limit_decision(1000, 700, 300)  # exactly 1000
		self.assertFalse(d.exceeded)
		self.assertEqual(d.projected, 1000.0)

	def test_amend_subtracts_prev_outstanding(self):
		# Chain already includes this invoice's old 300 outstanding; new grand
		# total 500 → delta only. 1000 chain - 300 prev + 500 new = 1200 > 1000.
		d = credit_limit_decision(1000, 1000, 500, prev_outstanding=300)
		self.assertTrue(d.exceeded)
		self.assertEqual(d.projected, 1200.0)

	def test_unlimited_ignores_huge_amount(self):
		# The bypass/role logic lives in the frappe layer; at the pure level an
		# unlimited chain never flags regardless of amount.
		self.assertFalse(credit_limit_decision(0, 10**9, 10**9).exceeded)


class TestValidateTransfers(unittest.TestCase):
	def setUp(self):
		self.children = {"ChildA", "ChildB"}

	def test_valid(self):
		xfers = [{"child": "ChildA", "amount": 100}, {"child": "ChildB", "amount": 200}]
		self.assertIsNone(validate_transfers(xfers, 500, self.children))

	def test_empty_rejected(self):
		self.assertEqual(validate_transfers([], 500, self.children), ERR_XFER_EMPTY)

	def test_unknown_child_rejected(self):
		xfers = [{"child": "Stranger", "amount": 10}]
		self.assertEqual(validate_transfers(xfers, 500, self.children), ERR_XFER_UNKNOWN_CHILD)

	def test_nonpositive_rejected(self):
		xfers = [{"child": "ChildA", "amount": -1}]
		self.assertEqual(validate_transfers(xfers, 500, self.children), ERR_XFER_NONPOSITIVE)

	def test_exceeds_unallocated_rejected(self):
		xfers = [{"child": "ChildA", "amount": 300}, {"child": "ChildB", "amount": 300}]
		self.assertEqual(validate_transfers(xfers, 500, self.children), ERR_XFER_EXCEEDS)

	def test_exactly_unallocated_passes(self):
		xfers = [{"child": "ChildA", "amount": 500}]
		self.assertIsNone(validate_transfers(xfers, 500, self.children))


if __name__ == "__main__":
	unittest.main()
