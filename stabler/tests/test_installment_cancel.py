"""Unit tests for the installment collection reversal arithmetic.

Covers the tricky same-day cancel cases: newest-covered-first ordering, partial
rows, multiple same-day Payment Entries against different rows and the same row
(subtraction must preserve the other PE's payment), and clamping so paid_amount
never goes negative if the schedule drifted. These are pure-function tests — no
DB — exercising stabler.api.installment._reverse_allocations directly.
"""

from __future__ import annotations

import unittest

from stabler.api.installment import _reverse_allocations


def _rows(dp_paid, i1_paid, i2_paid):
    return {
        "DP": {"payment_amount": 300, "paid_amount": dp_paid, "outstanding": 300 - dp_paid},
        "I1": {"payment_amount": 100, "paid_amount": i1_paid, "outstanding": 100 - i1_paid},
        "I2": {"payment_amount": 100, "paid_amount": i2_paid, "outstanding": 100 - i2_paid},
    }


class TestInstallmentReversal(unittest.TestCase):
    def test_single_pe_partial_row_newest_first(self):
        # One collection of 350 covered DP (300 full) + I1 (50 partial).
        alloc = [
            {"row_name": "DP", "row_index": 0, "due_date": "2026-07-01",
             "allocated_amount": 300, "previous_paid": 0, "previous_outstanding": 300},
            {"row_name": "I1", "row_index": 1, "due_date": "2026-08-01",
             "allocated_amount": 50, "previous_paid": 0, "previous_outstanding": 100},
        ]
        cur = _rows(300, 50, 0)
        writes = _reverse_allocations(cur, alloc)
        # Newest-covered (later due_date) restored first.
        self.assertEqual([w["row_name"] for w in writes], ["I1", "DP"])
        self.assertEqual(cur["DP"]["paid_amount"], 0)
        self.assertEqual(cur["DP"]["outstanding"], 300)
        self.assertEqual(cur["I1"]["paid_amount"], 0)
        self.assertEqual(cur["I1"]["outstanding"], 100)

    def test_other_same_day_pe_on_different_row_preserved(self):
        # PE1 paid DP; PE2 paid I1. Cancelling PE1 must leave I1 fully paid.
        alloc_pe1 = [
            {"row_name": "DP", "row_index": 0, "due_date": "2026-07-01",
             "allocated_amount": 300, "previous_paid": 0, "previous_outstanding": 300},
        ]
        cur = _rows(300, 100, 0)
        _reverse_allocations(cur, alloc_pe1)
        self.assertEqual(cur["DP"]["paid_amount"], 0)
        self.assertEqual(cur["I1"]["paid_amount"], 100)
        self.assertEqual(cur["I1"]["outstanding"], 0)

    def test_two_pes_same_row_subtraction_preserves_other(self):
        # PE_first paid 60 of I1, PE_second paid the remaining 40. Cancel PE_first.
        alloc_first = [
            {"row_name": "I1", "row_index": 1, "due_date": "2026-08-01",
             "allocated_amount": 60, "previous_paid": 0, "previous_outstanding": 100},
        ]
        cur = _rows(300, 100, 0)
        _reverse_allocations(cur, alloc_first)
        self.assertEqual(cur["I1"]["paid_amount"], 40)
        self.assertEqual(cur["I1"]["outstanding"], 60)

    def test_clamp_never_negative(self):
        # Snapshot claims 300 but the row only shows 100 paid now → clamp at 0.
        alloc_big = [
            {"row_name": "DP", "row_index": 0, "due_date": "2026-07-01",
             "allocated_amount": 300, "previous_paid": 0, "previous_outstanding": 300},
        ]
        cur = _rows(100, 0, 0)
        _reverse_allocations(cur, alloc_big)
        self.assertEqual(cur["DP"]["paid_amount"], 0)
        self.assertEqual(cur["DP"]["outstanding"], 300)

    def test_missing_row_skipped(self):
        alloc = [
            {"row_name": "GONE", "row_index": 9, "due_date": "2026-09-01",
             "allocated_amount": 50, "previous_paid": 0, "previous_outstanding": 50},
        ]
        cur = _rows(0, 0, 0)
        writes = _reverse_allocations(cur, alloc)
        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()
