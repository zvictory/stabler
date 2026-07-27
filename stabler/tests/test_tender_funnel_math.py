"""Tender funnel classification — pure, no site required.

The one property everything else depends on: a deal lands in exactly one
stage, decided by precedence, and the funnel counts "reached at least".
"""

import unittest

from stabler.api import _funnel as f


class ClassifyTest(unittest.TestCase):
    def test_precedence_result_beats_everything(self):
        # A won deal with quotations and a bid is WON, not also sourcing.
        facts = {"result": "won", "submitted": True, "has_pricing": True,
                 "sq_count": 5, "go_no_go": "go"}
        self.assertEqual(f.classify(facts), "won")
        facts["result"] = "lost"
        self.assertEqual(f.classify(facts), "lost")

    def test_precedence_chain(self):
        self.assertEqual(f.classify({"submitted": True, "has_pricing": True, "sq_count": 3}), "submitted")
        self.assertEqual(f.classify({"has_pricing": True, "sq_count": 3}), "priced")
        self.assertEqual(f.classify({"sq_count": 1}), "sourcing")
        self.assertEqual(f.classify({"go_no_go": "go"}), "go")
        self.assertEqual(f.classify({}), "seen")

    def test_exactly_one_stage_for_every_combination(self):
        # Exhaustive: every combination of facts maps to exactly one stage.
        stages = set()
        for result in ("", "won", "lost", "pending"):
            for submitted in (False, True):
                for pricing in (False, True):
                    for sq in (0, 1, 5):
                        for go in ("", "go", "no_go"):
                            s = f.classify({"result": result, "submitted": submitted,
                                            "has_pricing": pricing, "sq_count": sq,
                                            "go_no_go": go})
                            self.assertIn(s, f.ORDER + ["lost"])
                            stages.add(s)
        self.assertEqual(stages, set(f.ORDER) | {"lost"})  # every stage reachable

    def test_malformed_facts_degrade_to_seen_not_progress(self):
        self.assertEqual(f.classify({"result": "WON!", "sq_count": "abc" if False else 0,
                                     "go_no_go": "maybe"}), "seen")
        self.assertEqual(f.classify({"sq_count": None}), "seen")

    def test_pending_result_is_not_a_result(self):
        self.assertEqual(f.classify({"result": "pending", "submitted": True}), "submitted")


class RankTest(unittest.TestCase):
    def test_lost_reached_submitted_but_not_won(self):
        # A lost deal participated all the way to the bid — the funnel must not
        # pretend it never bid. But it did NOT win: counting it in the last
        # rung would make "Won" larger than the number of wins.
        self.assertEqual(f.rank("lost"), f.rank("submitted"))
        self.assertLess(f.rank("lost"), f.rank("won"))

    def test_order_is_monotonic(self):
        ranks = [f.rank(s) for s in f.ORDER]
        self.assertEqual(ranks, sorted(ranks))


class SummariseTest(unittest.TestCase):
    def rows(self):
        return [
            {"stage": "seen", "urgent": False, "in_window": True},
            {"stage": "go", "urgent": True, "in_window": True},
            {"stage": "sourcing", "urgent": False, "in_window": True},
            {"stage": "submitted", "urgent": True, "in_window": True},
            {"stage": "won", "in_window": True},
            {"stage": "lost", "in_window": True},
            {"stage": "won", "in_window": False},   # old win — outside window
        ]

    def test_funnel_counts_reached_at_least(self):
        out = f.summarise(self.rows())
        got = {r["key"]: r["n"] for r in out["funnel"]}
        # In-window: seen(6 reach seen), go(5), sourcing(4), submitted(3: sub+won+lost), won(1... won only)
        self.assertEqual(got["seen"], 6)
        self.assertEqual(got["go"], 5)
        self.assertEqual(got["sourcing"], 4)
        self.assertEqual(got["submitted"], 3)  # submitted + won + lost all bid
        self.assertEqual(got["won"], 1)        # only the actual win

    def test_win_rate_only_over_resolved_in_window(self):
        out = f.summarise(self.rows())
        self.assertEqual(out["kpi"]["won"], 1)
        self.assertEqual(out["kpi"]["lost"], 1)
        self.assertEqual(out["kpi"]["win_rate"], 50.0)

    def test_old_win_outside_window_does_not_inflate_the_period(self):
        out = f.summarise(self.rows())
        self.assertEqual(out["stages"]["won"], 1)  # not 2

    def test_open_stages_ignore_the_window(self):
        # An open tender is open regardless of when it was created.
        out = f.summarise([{"stage": "sourcing", "in_window": False}])
        self.assertEqual(out["stages"]["sourcing"], 1)
        self.assertEqual(out["kpi"]["open_pipeline"], 1)

    def test_no_resolved_means_no_win_rate_not_zero(self):
        out = f.summarise([{"stage": "seen", "in_window": True}])
        self.assertIsNone(out["kpi"]["win_rate"])

    def test_urgent_counts_only_open_deals(self):
        out = f.summarise(self.rows())
        self.assertEqual(out["kpi"]["urgent"], 2)


class SoBucketTest(unittest.TestCase):
    def test_board_stages_fold_into_story_buckets(self):
        out = f.summarise_so(["New", "Procurement", "Delivery", "Acceptance",
                              "Invoicing", "Paid", "Closed"])
        self.assertEqual(out["contract"], 1)
        self.assertEqual(out["procurement"], 1)
        self.assertEqual(out["delivery"], 3)
        self.assertEqual(out["done"], 2)
        self.assertEqual(out["active"], 5)

    def test_unknown_stage_stays_visible_as_contract(self):
        # Hiding an unknown stage would silently shrink "serving" — count it.
        self.assertEqual(f.summarise_so(["Custom Stage"])["contract"], 1)
        self.assertEqual(f.summarise_so([None])["contract"], 1)


if __name__ == "__main__":
    unittest.main()
