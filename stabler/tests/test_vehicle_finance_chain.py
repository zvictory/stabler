"""Restructure-chain position maths (stabler-vjfd).

Bench-free: `chain` imports nothing from frappe by construction, so the maths
behind `3/3 · restructured twice` is proved by `make check` rather than left to
`make test-bench`. The DB half — walking `restructured_from` in both directions
to build a closed set — lives in `read._chain_positions` and is covered there.
"""

from __future__ import annotations

import unittest

from stabler.api.vehicle_finance import chain


class ChainPositionTest(unittest.TestCase):
	def test_an_agreement_that_was_never_restructured_reads_as_one_of_one(self):
		"""The common case must not look like a chain. If a plain agreement
		rendered `1/1 · restructured zero times` as anything else, the badge
		would fire on every row and stop meaning anything."""
		self.assertEqual(
			chain.positions({"VA-0001": None}),
			{"VA-0001": {"chain_position": 1, "chain_length": 1, "restructure_count": 0}},
		)

	def test_the_fallback_matches_a_lone_agreement(self):
		"""`SOLE_AGREEMENT` is what the serialisers substitute when a name is
		missing from the map. It has to agree with what the maths would have
		said, or a lookup miss would silently change what the UI shows."""
		self.assertEqual(chain.positions({"VA-0001": None})["VA-0001"], chain.SOLE_AGREEMENT)

	def test_every_member_of_a_chain_reports_the_same_history(self):
		"""The condition of the owner's vote on the ADR: you learn the history
		from whichever agreement you happen to be looking at. Position moves
		along the chain; length and restructure count do not — otherwise you
		are back to hunting for the last closed agreement."""
		result = chain.positions({"VA-0001": None, "VA-0002": "VA-0001", "VA-0003": "VA-0002"})
		self.assertEqual(result["VA-0001"]["chain_position"], 1)
		self.assertEqual(result["VA-0002"]["chain_position"], 2)
		self.assertEqual(result["VA-0003"]["chain_position"], 3)
		for name in ("VA-0001", "VA-0002", "VA-0003"):
			self.assertEqual(result[name]["chain_length"], 3, name)
			self.assertEqual(result[name]["restructure_count"], 2, name)

	def test_two_chains_do_not_contaminate_each_other(self):
		"""Chain length is the size of one connected component, not of the
		batch. A page mixing several parties must not report one party's
		restructures against another's agreement."""
		result = chain.positions(
			{
				"VA-0001": None,
				"VA-0002": "VA-0001",
				"VA-0100": None,
			}
		)
		self.assertEqual(result["VA-0002"]["chain_length"], 2)
		self.assertEqual(result["VA-0100"]["chain_length"], 1)
		self.assertEqual(result["VA-0100"]["restructure_count"], 0)

	def test_a_predecessor_outside_the_set_reads_as_a_root(self):
		"""That is exactly what a CANCELLED predecessor looks like once
		`_chain_positions` filters it out. A restructure that was cancelled did
		not happen, so the successor is the start of the history — and the
		queue must render rather than raise a KeyError."""
		result = chain.positions({"VA-0002": "VA-0001-CANCELLED"})
		self.assertEqual(
			result["VA-0002"],
			{"chain_position": 1, "chain_length": 1, "restructure_count": 0},
		)

	def test_a_cycle_terminates_instead_of_hanging(self):
		"""No writer can produce this today, but the work queue is read on every
		page load and a corrupt pair of rows must degrade to a wrong number
		rather than spin a worker forever."""
		result = chain.positions({"VA-0001": "VA-0002", "VA-0002": "VA-0001"})
		self.assertEqual(result["VA-0001"]["chain_length"], 2)
		self.assertEqual(result["VA-0002"]["chain_length"], 2)

	def test_an_empty_map_is_an_empty_answer(self):
		self.assertEqual(chain.positions({}), {})


if __name__ == "__main__":
	unittest.main()
