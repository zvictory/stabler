"""Unit tests for stabler.api._ci_to_pinv (WP-I5, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_to_pinv -v
"""

from __future__ import annotations

import unittest

from stabler.api import _ci_to_pinv as ci_math
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

	def test_pi_advance_is_capped_to_the_ci_share(self):
		"""A small CI must not consume the supplier's whole PI advance."""
		plan = plan_advance_allocation(
			300_000,
			[
				{
					"name": "PE-ADV-1",
					"unallocated_amount": 1_800_000,
					"proforma_invoice": "PI-MEAT-6M",
					"ci_amount": 300_000,
					"advance_percentage": 30,
				}
			],
		)
		self.assertEqual(plan["total_allocated"], 90_000.0)
		self.assertEqual(plan["outstanding_after"], 210_000.0)

	def test_multiple_payments_share_one_pi_percentage_cap(self):
		"""Two bank/cash advances for one PI must share one 30% allocation cap."""
		plan = plan_advance_allocation(
			300_000,
			[
				{
					"name": "PE-BANK",
					"unallocated_amount": 60_000,
					"proforma_invoice": "PI-MEAT-6M",
					"ci_amount": 300_000,
					"advance_percentage": 30,
				},
				{
					"name": "PE-CASH",
					"unallocated_amount": 60_000,
					"proforma_invoice": "PI-MEAT-6M",
					"ci_amount": 300_000,
					"advance_percentage": 30,
				},
			],
		)
		self.assertEqual(plan["total_allocated"], 90_000.0)
		self.assertEqual([a["amount"] for a in plan["allocations"]], [60_000.0, 30_000.0])

	def test_zero_percent_pi_does_not_fall_back_to_greedy_allocation(self):
		"""A PI that requires no advance must never consume supplier credit."""
		plan = plan_advance_allocation(
			300_000,
			[
				{
					"name": "PE-OTHER-CREDIT",
					"unallocated_amount": 100_000,
					"proforma_invoice": "PI-NO-ADVANCE",
					"ci_amount": 300_000,
					"advance_percentage": 0,
				}
			],
		)
		self.assertEqual(plan["total_allocated"], 0.0)
		self.assertEqual(plan["outstanding_after"], 300_000.0)

	def test_draft_reservation_reduces_reusable_payment_credit(self):
		"""A second draft bill cannot reserve the first draft's PI advance again."""
		plan = plan_advance_allocation(
			300_000,
			[
				{
					"name": "PE-ADV-1",
					"unallocated_amount": 100_000,
					"reserved_amount": 90_000,
					"proforma_invoice": "PI-MEAT-6M",
					"ci_amount": 300_000,
					"advance_percentage": 30,
				}
			],
		)
		self.assertEqual(plan["total_allocated"], 10_000.0)
		self.assertEqual(plan["outstanding_after"], 290_000.0)

	def test_twenty_cis_consume_exactly_the_six_million_pi_terms(self):
		"""Each $300k CI uses only its $90k contractual PI share without drift."""
		allocations = [
			plan_advance_allocation(
				300_000,
				[
					{
						"name": "PE-ADV-1",
						"unallocated_amount": 1_800_000 - index * 90_000,
						"proforma_invoice": "PI-MEAT-6M",
						"ci_amount": 300_000,
						"advance_percentage": 30,
					}
				],
			)["total_allocated"]
			for index in range(20)
		]
		self.assertEqual(allocations, [90_000.0] * 20)
		self.assertEqual(sum(allocations), 1_800_000.0)


class TestPiAdvanceLedger(unittest.TestCase):
	def test_six_million_pi_tracks_posted_and_reserved_ci_shares(self):
		"""Posted and planned CI rows must reduce different summary buckets."""
		builder = getattr(
			ci_math,
			"build_pi_advance_ledger",
			lambda **_: {"summary": {"advance_paid": -1, "advance_available": -1}, "rows": []},
		)
		ledger = builder(
			pi_total=6_000_000,
			advance_percentage=30,
			payments=[
				{
					"name": "PE-00042",
					"posting_date": "2026-08-11",
					"docstatus": 1,
					"paid_amount": 1_800_000,
				}
			],
			ci_movements=[
				{
					"ci_name": "CI-MEAT-001",
					"posting_date": "2026-08-18",
					"ci_amount": 300_000,
					"status": "Posted",
				},
				{
					"ci_name": "CI-MEAT-002",
					"posting_date": "2026-08-25",
					"ci_amount": 300_000,
					"status": "Planned",
				},
			],
		)
		self.assertEqual(
			ledger["summary"],
			{
				"pi_total_cost": 6_000_000.0,
				"advance_percentage": 30.0,
				"advance_paid": 1_800_000.0,
				"advance_pending_approval": 0.0,
				"advance_allocated": 90_000.0,
				"advance_reserved": 90_000.0,
				"advance_available": 1_620_000.0,
				"total_ci_amount": 600_000.0,
				"remaining_pi_cost": 5_400_000.0,
				"remaining_vendor_payments": 4_200_000.0,
			},
		)
		self.assertEqual(ledger["rows"][1]["advance_out"], 90_000.0)
		self.assertEqual(ledger["rows"][1]["running_advance_balance"], 1_710_000.0)
		self.assertEqual(ledger["rows"][2]["running_pi_cost"], 5_400_000.0)

	def test_draft_payment_does_not_create_available_vendor_credit(self):
		"""A draft Payment Entry is visible but cannot fund CI allocations."""
		builder = getattr(
			ci_math,
			"build_pi_advance_ledger",
			lambda **_: {
				"summary": {"advance_paid": -1, "advance_available": -1},
				"rows": [{"status": "Missing"}],
			},
		)
		ledger = builder(
			pi_total=6_000_000,
			advance_percentage=30,
			payments=[
				{
					"name": "PE-DRAFT",
					"posting_date": "2026-08-11",
					"docstatus": 0,
					"paid_amount": 1_800_000,
				}
			],
			ci_movements=[],
		)
		self.assertEqual(ledger["summary"]["advance_paid"], 0.0)
		self.assertEqual(ledger["summary"]["advance_available"], 0.0)
		self.assertEqual(ledger["rows"][0]["status"], "Pending Approval")
		# The screen must explain the zero instead of just showing it: the money is
		# entered and waiting for approval, which is why it buys no credit yet.
		self.assertEqual(ledger["summary"]["advance_pending_approval"], 1_800_000.0)
		self.assertEqual(ledger["rows"][0]["advance_in"], 0.0)

	def test_ci_without_purchase_invoice_reduces_pi_cost_but_reserves_no_advance(self):
		"""Creating an operational CI has no GL allocation before a draft bill exists."""
		ledger = ci_math.build_pi_advance_ledger(
			pi_total=6_000_000,
			advance_percentage=30,
			payments=[{"name": "PE-1", "docstatus": 1, "paid_amount": 1_800_000}],
			ci_movements=[{"ci_name": "CI-1", "ci_amount": 300_000, "status": "Unallocated"}],
		)
		self.assertEqual(ledger["summary"]["advance_reserved"], 0.0)
		self.assertEqual(ledger["summary"]["advance_available"], 1_800_000.0)
		self.assertEqual(ledger["summary"]["remaining_pi_cost"], 5_700_000.0)
		self.assertEqual(ledger["rows"][1]["advance_out"], 0.0)

	def test_submitted_legacy_reference_is_paid_but_not_reusable_until_amended(self):
		"""Legacy PI references must fail loud instead of advertising false free credit."""
		ledger = ci_math.build_pi_advance_ledger(
			pi_total=6_000_000,
			advance_percentage=30,
			payments=[
				{
					"name": "PE-LEGACY",
					"docstatus": 1,
					"paid_amount": 1_800_000,
					"usable_amount": 0,
					"ledger_status": "Migration Required",
				}
			],
			ci_movements=[],
		)
		self.assertEqual(ledger["summary"]["advance_paid"], 1_800_000.0)
		self.assertEqual(ledger["summary"]["advance_available"], 0.0)
		self.assertEqual(ledger["rows"][0]["status"], "Migration Required")


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
