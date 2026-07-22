"""Shared sea lifecycle drift rules — pure, no site required."""

import unittest

from stabler.stabler.imports_module import sea_lifecycle as sl


def C(number, status, name=None):
    return {"name": name or f"CNT-{number}", "container_number": number, "status": status}


class RankTest(unittest.TestCase):
    def test_pipeline_order(self):
        self.assertEqual(sl.rank("BOOKED"), 0)
        self.assertLess(sl.rank("STUFFED"), sl.rank("ON_BOARD"))
        self.assertEqual(sl.rank("DELIVERED_TO_UZBEKISTAN"), len(sl.SEA_PIPELINE) - 1)

    def test_unknown_and_cancelled_have_no_position(self):
        for s in ("Cancelled", "", None, "NOT_A_STATUS"):
            with self.subTest(status=s):
                self.assertEqual(sl.rank(s), -1)


class DriftTest(unittest.TestCase):
    def test_aligned(self):
        self.assertEqual(sl.drift("ON_BOARD", "ON_BOARD"), {"state": "aligned", "steps": 0})

    def test_behind_counts_the_gap(self):
        d = sl.drift("IN_TRANSIT", "STUFFED")
        self.assertEqual(d["state"], "behind")
        self.assertEqual(d["steps"], 3)

    def test_ahead_is_a_contradiction_not_progress(self):
        # A container cannot be further along the voyage than its invoice.
        d = sl.drift("STUFFED", "IN_TRANSIT")
        self.assertEqual(d["state"], "ahead")
        self.assertEqual(d["steps"], 3)

    def test_cancelled_is_out_of_the_voyage_not_behind(self):
        self.assertEqual(sl.drift("IN_TRANSIT", "Cancelled")["state"], "cancelled")

    def test_unknown_status_is_flagged_not_guessed(self):
        self.assertEqual(sl.drift("IN_TRANSIT", "WAT")["state"], "unknown")
        self.assertEqual(sl.drift("WAT", "STUFFED")["state"], "unknown")


class SyncableTest(unittest.TestCase):
    def test_behind_can_be_pushed(self):
        self.assertTrue(sl.syncable("ON_BOARD", "STUFFED"))

    def test_aligned_needs_no_push(self):
        self.assertFalse(sl.syncable("ON_BOARD", "ON_BOARD"))

    def test_ahead_is_never_pushed_backwards(self):
        # Moving it back is a correction with its own reason workflow.
        self.assertFalse(sl.syncable("STUFFED", "IN_TRANSIT"))

    def test_cancelled_is_never_touched(self):
        self.assertFalse(sl.syncable("IN_TRANSIT", "Cancelled"))


class PathTest(unittest.TestCase):
    def test_walks_every_station(self):
        # The container controller allows one step at a time, so a three-station
        # catch-up must be walked, not jumped.
        self.assertEqual(sl.path("STUFFED", "IN_TRANSIT"), ["GATE_IN", "ON_BOARD", "IN_TRANSIT"])

    def test_single_step(self):
        self.assertEqual(sl.path("BOOKED", "STUFFED"), ["STUFFED"])

    def test_nothing_to_walk(self):
        self.assertEqual(sl.path("ON_BOARD", "ON_BOARD"), [])
        self.assertEqual(sl.path("IN_TRANSIT", "STUFFED"), [])
        self.assertEqual(sl.path("Cancelled", "ON_BOARD"), [])


class SummariseTest(unittest.TestCase):
    def test_counts_and_flag(self):
        s = sl.summarise("IN_TRANSIT", [
            C("A", "IN_TRANSIT"), C("B", "STUFFED"), C("C", "Cancelled"), C("D", "DISCHARGED"),
        ])
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["aligned"], 1)
        self.assertEqual(s["behind"], 1)
        self.assertEqual(s["ahead"], 1)
        self.assertEqual(s["cancelled"], 1)
        self.assertFalse(s["in_sync"])

    def test_in_sync_when_everything_matches_or_is_cancelled(self):
        s = sl.summarise("ON_BOARD", [C("A", "ON_BOARD"), C("B", "Cancelled")])
        self.assertTrue(s["in_sync"])

    def test_worst_rows_come_first(self):
        s = sl.summarise("IN_TRANSIT", [
            C("ALIGNED", "IN_TRANSIT"), C("BEHIND1", "ON_BOARD"),
            C("AHEAD", "AVAILABLE"), C("BEHIND3", "BOOKED"),
        ])
        self.assertEqual([r["container_number"] for r in s["rows"]],
                         ["AHEAD", "BEHIND3", "BEHIND1", "ALIGNED"])

    def test_empty_invoice_is_in_sync(self):
        s = sl.summarise("BOOKED", [])
        self.assertEqual(s["total"], 0)
        self.assertTrue(s["in_sync"])


if __name__ == "__main__":
    unittest.main()
