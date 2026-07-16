"""Unit tests for stabler.api._proforma supersede rules (WP-I2, Frappe-free)."""

from __future__ import annotations

import unittest

from stabler.api._proforma import (
	CANCELLED,
	CONFIRMED,
	DRAFT,
	SUPERSEDED,
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


if __name__ == "__main__":
	unittest.main()
