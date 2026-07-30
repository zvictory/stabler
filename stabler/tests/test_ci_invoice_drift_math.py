"""CI ↔ booked Purchase Invoice drift — the arithmetic.

A submitted Purchase Invoice is immutable; the Commercial Invoice behind it
keeps being corrected. These tests pin what "the payable no longer describes
the deal" means, including the cases the business actually hits: a rate fix, a
line added after booking, and an over-booked invoice (which must show a
NEGATIVE difference, never be clamped to zero).
"""

from __future__ import annotations

import unittest

from stabler.api import _ci_to_pinv as m


def L(code, qty, amount):
    return {"item_code": code, "qty": qty, "amount": amount}


class InSyncTest(unittest.TestCase):
    def test_identical_documents_are_in_sync(self):
        lines = [L("BEEF-CUT", 10, 1000.0), L("BEEF-TRIM", 5, 250.0)]
        d = m.invoice_drift(1250.0, lines, 1250.0, list(lines))
        self.assertTrue(d["in_sync"])
        self.assertEqual(d["delta_total"], 0.0)
        self.assertEqual((d["lines_changed"], d["lines_added"], d["lines_removed"]), ([], [], []))

    def test_sub_epsilon_rounding_is_not_drift(self):
        d = m.invoice_drift(1000.30, [L("A", 1, 1000.30)], 1000.0, [L("A", 1, 1000.0)])
        self.assertTrue(d["in_sync"], "a 30-tiyin rounding gap is not a business change")

    def test_same_item_split_across_lines_is_summed_not_flagged(self):
        # The CI may carry one product on several lines; the invoice merges them.
        d = m.invoice_drift(
            300.0, [L("A", 1, 100.0), L("A", 2, 200.0)], 300.0, [L("A", 3, 300.0)]
        )
        self.assertTrue(d["in_sync"])


class DriftTest(unittest.TestCase):
    def test_price_correction_after_booking(self):
        d = m.invoice_drift(1400.0, [L("A", 10, 1400.0)], 1250.0, [L("A", 10, 1250.0)])
        self.assertFalse(d["in_sync"])
        self.assertEqual(d["delta_total"], 150.0)
        self.assertEqual(len(d["lines_changed"]), 1)
        self.assertEqual(d["lines_changed"][0]["delta"], 150.0)

    def test_line_added_after_booking(self):
        d = m.invoice_drift(1500.0, [L("A", 10, 1250.0), L("B", 2, 250.0)], 1250.0, [L("A", 10, 1250.0)])
        self.assertEqual([x["item_code"] for x in d["lines_added"]], ["B"])
        self.assertEqual(d["delta_total"], 250.0)

    def test_line_removed_after_booking(self):
        d = m.invoice_drift(1250.0, [L("A", 10, 1250.0)], 1500.0, [L("A", 10, 1250.0), L("B", 2, 250.0)])
        self.assertEqual([x["item_code"] for x in d["lines_removed"]], ["B"])
        self.assertEqual(d["delta_total"], -250.0)

    def test_over_booked_shows_a_negative_difference_never_clamped(self):
        # We booked MORE than the deal now says. Hiding that behind max(0, …)
        # would make an over-stated payable invisible.
        d = m.invoice_drift(900.0, [L("A", 1, 900.0)], 1000.0, [L("A", 1, 1000.0)])
        self.assertEqual(d["delta_total"], -100.0)
        self.assertLess(d["lines_changed"][0]["delta"], 0)

    def test_quantity_change_at_the_same_amount_is_still_drift(self):
        # Same money, different goods — the customs and stock story changed.
        d = m.invoice_drift(1000.0, [L("A", 12, 1000.0)], 1000.0, [L("A", 10, 1000.0)])
        self.assertFalse(d["in_sync"])
        self.assertEqual(d["lines_changed"][0]["qty_now"], 12)
        self.assertEqual(d["lines_changed"][0]["qty_booked"], 10)

    def test_totals_are_always_reported_for_the_narrative(self):
        d = m.invoice_drift(1400.0, [L("A", 10, 1400.0)], 1250.0, [L("A", 10, 1250.0)])
        self.assertEqual(d["agreed_total"], 1400.0)
        self.assertEqual(d["invoiced_total"], 1250.0)


class EmptyTest(unittest.TestCase):
    def test_lines_without_an_item_are_ignored_on_both_sides(self):
        d = m.invoice_drift(100.0, [L(None, 1, 100.0)], 100.0, [{"qty": 1, "amount": 100.0}])
        self.assertTrue(d["in_sync"])

    def test_no_lines_at_all_still_compares_totals(self):
        d = m.invoice_drift(500.0, [], 400.0, [])
        self.assertFalse(d["in_sync"])
        self.assertEqual(d["delta_total"], 100.0)


if __name__ == "__main__":
    unittest.main()
