"""Unit tests for stabler.api._proforma supersede rules (WP-I2, Frappe-free)."""

from __future__ import annotations

import unittest

from stabler.api._proforma import (
	CANCELLED,
	CONFIRMED,
	DRAFT,
	SUPERSEDED,
	accepts_another_ci,
	can_supersede,
	is_already_linked,
)


class TestCanSupersede(unittest.TestCase):
	def test_draft_and_confirmed_can(self):
		self.assertTrue(can_supersede(DRAFT))
		self.assertTrue(can_supersede(CONFIRMED))

	def test_terminal_cannot(self):
		self.assertFalse(can_supersede(SUPERSEDED))
		self.assertFalse(can_supersede(CANCELLED))
		self.assertFalse(can_supersede(None))
		self.assertFalse(can_supersede(""))


class TestAlreadyLinked(unittest.TestCase):
	def test_same_ci_is_noop(self):
		# Re-linking the same CI to an already-superseded PI → no-op.
		self.assertTrue(is_already_linked(SUPERSEDED, "CI-2026-1", "CI-2026-1"))

	def test_different_ci_not_linked(self):
		self.assertFalse(is_already_linked(SUPERSEDED, "CI-2026-1", "CI-2026-2"))

	def test_not_superseded_not_linked(self):
		self.assertFalse(is_already_linked(CONFIRMED, "", "CI-2026-1"))
		self.assertFalse(is_already_linked(DRAFT, None, "CI-2026-1"))


class TestAcceptsAnotherCi(unittest.TestCase):
	"""A PI ships in several containers; only the first one takes the link.

	PI-AUG-26 contracted 8 400 boxes and shipped 4 134 in its first CI, leaving
	4 266 the picker kept offering. Saving the second container refused the
	supersede and threw, so the shipment could not be recorded at all.
	"""

	def test_open_balance_lets_a_further_container_through(self):
		self.assertTrue(accepts_another_ci(SUPERSEDED, True))

	def test_a_fully_shipped_pi_is_still_reported(self):
		# Nothing left to ship means the CI is pointing at the wrong PI, which is
		# exactly the mistake the throw exists to catch.
		self.assertFalse(accepts_another_ci(SUPERSEDED, False))

	def test_cancelled_never_passes(self):
		self.assertFalse(accepts_another_ci(CANCELLED, True))

	def test_supersedable_statuses_are_not_this_rule(self):
		# DRAFT/CONFIRMED must reach can_supersede and get the link, not skip it.
		self.assertFalse(accepts_another_ci(DRAFT, True))
		self.assertFalse(accepts_another_ci(CONFIRMED, True))
		self.assertFalse(accepts_another_ci(None, True))


if __name__ == "__main__":
	unittest.main()
