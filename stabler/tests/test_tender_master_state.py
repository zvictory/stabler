"""Tender Master board lane derivation — pure, no site required.

The one property everything else depends on: the lane is always recomputed
from the child lots' actual funnel stages, so a hand-maintained status field
can never drift from what the lots really say.
"""

import unittest

from stabler.api import _tender_master_state as s


class DeriveRuleTableTest(unittest.TestCase):
	"""One test per priority rule so a failure names exactly which rule broke."""

	def test_rule_1_no_lots_is_preparation(self):
		# If nobody has touched a lot yet, the parent can't claim any progress.
		self.assertEqual(s.derive([]), "Preparation")

	def test_rule_2_every_lot_terminal_is_completed(self):
		# Only when every lot has a result (won or lost) is the tender done.
		self.assertEqual(s.derive(["won", "lost", "won"]), "Completed")

	def test_rule_3_some_terminal_some_open_is_partial_result(self):
		# A parent with two winners and one still-open lot cannot read
		# "Completed" — that would hide the lot still in flight.
		self.assertEqual(s.derive(["won", "sourcing"]), "Partial Result")

	def test_rule_4_no_terminal_but_submitted_is_awaiting_result(self):
		# Bids are in and nobody has won or lost yet — waiting on the buyer.
		self.assertEqual(s.derive(["submitted", "submitted"]), "Awaiting Result")

	def test_rule_5_sourcing_or_priced_is_active(self):
		# Work is underway (quoting suppliers or pricing) but nothing submitted.
		self.assertEqual(s.derive(["sourcing"]), "Active")
		self.assertEqual(s.derive(["priced"]), "Active")

	def test_rule_6_seen_or_go_only_is_preparation(self):
		# Lots exist but no sourcing/pricing/submission work has started.
		self.assertEqual(s.derive(["seen", "go"]), "Preparation")


class DeriveScenarioTest(unittest.TestCase):
	def test_single_won_lot_is_completed(self):
		self.assertEqual(s.derive(["won"]), "Completed")

	def test_single_lost_lot_is_completed(self):
		# Losing is still a resolution — the tender is done, not "in progress".
		self.assertEqual(s.derive(["lost"]), "Completed")

	def test_won_plus_open_lot_is_partial_result(self):
		self.assertEqual(s.derive(["won", "go"]), "Partial Result")

	def test_all_submitted_is_awaiting_result(self):
		self.assertEqual(s.derive(["submitted", "submitted", "submitted"]), "Awaiting Result")

	def test_sourcing_and_priced_mixed_with_open_is_active(self):
		self.assertEqual(s.derive(["seen", "sourcing", "priced"]), "Active")

	def test_unknown_stage_alone_degrades_to_preparation(self):
		# An unrecognised stage string must not be mistaken for progress —
		# it is treated as a plain non-terminal, non-submitted, non-active
		# lot, same as "seen"/"go".
		self.assertEqual(s.derive(["zzz"]), "Preparation")

	def test_unknown_stage_mixed_with_terminal_is_partial_result(self):
		# The unknown lot is NOT terminal, so ["won", "zzz"] has one terminal
		# and one non-terminal lot -> Partial Result, not Completed. Treating
		# the unknown value as terminal would silently invent a second win.
		self.assertEqual(s.derive(["won", "zzz"]), "Partial Result")


class LanesContractTest(unittest.TestCase):
	def test_lanes_are_exactly_the_five_expected_values_in_order(self):
		# The SPA renders board columns straight from this list; reordering
		# or renaming a lane here would silently reorder or rename columns.
		self.assertEqual(
			s.LANES,
			["Preparation", "Active", "Awaiting Result", "Partial Result", "Completed"],
		)

	def test_every_derivable_lane_is_a_member_of_lanes(self):
		# Exhaustive over stage combinations: derive() must never return a
		# value the SPA's board doesn't know how to render as a column.
		stages_pool = ["seen", "go", "sourcing", "priced", "submitted", "won", "lost", "zzz"]
		seen_lanes = set()
		for a in stages_pool:
			for b in stages_pool:
				for c in ("", *stages_pool):
					combo = [a, b] + ([c] if c else [])
					lane = s.derive(combo)
					self.assertIn(lane, s.LANES)
					seen_lanes.add(lane)
		self.assertEqual(seen_lanes, set(s.LANES))


if __name__ == "__main__":
	unittest.main()
