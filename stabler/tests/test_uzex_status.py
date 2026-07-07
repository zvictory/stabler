"""Unit tests for stabler.integrations.uzex._status (WP-303, Frappe-free).

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_uzex_status -v
"""

from __future__ import annotations

import unittest
from datetime import datetime

from stabler.integrations.uzex._status import (
	deal_status_for,
	hours_until,
	is_deadline_soon,
	is_terminal,
	map_result,
)


class TestMapResult(unittest.TestCase):
	def test_known_id_wins_over_name(self):
		# id 5 = cancelled -> lost, even if the name is ambiguous.
		self.assertEqual(map_result(5, "anything"), "lost")

	def test_name_lost_fallback(self):
		self.assertEqual(map_result(None, "Буюртмачи томонидан бекор қилинган"), "lost")
		self.assertEqual(map_result(999, "Rad etilgan"), "lost")

	def test_name_won_fallback(self):
		self.assertEqual(map_result(None, "G'olib deb topildi"), "won")

	def test_unknown_is_pending(self):
		self.assertEqual(map_result(None, "Faol"), "pending")
		self.assertEqual(map_result(None, None), "pending")
		self.assertEqual(map_result("", ""), "pending")

	def test_garbage_id(self):
		self.assertEqual(map_result("abc", "Faol"), "pending")


class TestTerminalAndDealStatus(unittest.TestCase):
	def test_is_terminal(self):
		self.assertTrue(is_terminal("won"))
		self.assertTrue(is_terminal("lost"))
		self.assertFalse(is_terminal("pending"))

	def test_deal_status_for(self):
		self.assertEqual(deal_status_for("won"), "Won")
		self.assertEqual(deal_status_for("lost"), "Lost")
		self.assertIsNone(deal_status_for("pending"))  # never force an open lot back


class TestDeadline(unittest.TestCase):
	def setUp(self):
		self.now = datetime(2026, 7, 8, 12, 0, 0)

	def test_hours_until_future(self):
		self.assertAlmostEqual(hours_until("2026-07-09 12:00:00", self.now), 24.0, places=3)

	def test_hours_until_past_negative(self):
		self.assertLess(hours_until("2026-07-07 12:00:00", self.now), 0)

	def test_hours_until_unparseable(self):
		self.assertIsNone(hours_until("garbage", self.now))
		self.assertIsNone(hours_until(None, self.now))

	def test_soon_within_48h(self):
		self.assertTrue(is_deadline_soon("2026-07-09 12:00:00", self.now))  # 24h
		self.assertTrue(is_deadline_soon("2026-07-10 11:00:00", self.now))  # 47h

	def test_not_soon_beyond_48h(self):
		self.assertFalse(is_deadline_soon("2026-07-11 12:00:00", self.now))  # 72h

	def test_not_soon_when_passed(self):
		self.assertFalse(is_deadline_soon("2026-07-07 12:00:00", self.now))  # passed

	def test_accepts_iso_t(self):
		self.assertTrue(is_deadline_soon("2026-07-09T12:00:00", self.now))


if __name__ == "__main__":
	unittest.main()
