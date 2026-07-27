"""Unit tests for stabler.integrations.kassa.shadow_store (WP-S4a, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_shadow_store -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from stabler.integrations.kassa import shadow_store as ss

CO = "mikas"
D = "2026-07-19"


class TestShadowStore(unittest.TestCase):
	def setUp(self):
		fd, self.path = tempfile.mkstemp(suffix=".sqlite")
		os.close(fd)

	def tearDown(self):
		try:
			os.remove(self.path)
		except OSError:
			pass

	def test_opening_and_empty_balance(self):
		ss.set_opening(self.path, CO, D, "nakit", 402_250_000)
		ss.set_opening(self.path, CO, D, "pk", 3_000_000)
		ss.set_opening(self.path, CO, D, "usd", 400)
		self.assertEqual(
			ss.balances(self.path, CO, D), {"nakit": 402_250_000.0, "pk": 3_000_000.0, "usd": 400.0}
		)

	def test_opening_upsert(self):
		ss.set_opening(self.path, CO, D, "nakit", 100)
		ss.set_opening(self.path, CO, D, "nakit", 250)  # overwrite
		self.assertEqual(ss.get_openings(self.path, CO, D)["nakit"], 250.0)

	def test_multi_leg_kirim_updates_balances(self):
		ss.set_opening(self.path, CO, D, "nakit", 402_250_000)
		ss.set_opening(self.path, CO, D, "pk", 3_000_000)
		ss.set_opening(self.path, CO, D, "usd", 400)
		# "Mijozdan 2 mln naqd, 3 mln karta va 500 dollar oldim"
		ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="kirim",
			counterparty="Mijoz",
			raw_text="Mijozdan 2 mln naqd...",
			date=D,
			deltas=[
				{"kassa": "nakit", "delta": 2_000_000},
				{"kassa": "pk", "delta": 3_000_000},
				{"kassa": "usd", "delta": 500},
			],
		)
		self.assertEqual(
			ss.balances(self.path, CO, D), {"nakit": 404_250_000.0, "pk": 6_000_000.0, "usd": 900.0}
		)

	def test_chiqim_negative_delta(self):
		ss.set_opening(self.path, CO, D, "nakit", 1_000_000)
		ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="chiqim",
			date=D,
			purpose="ijara",
			deltas=[{"kassa": "nakit", "delta": -100_000}],
		)
		self.assertEqual(ss.balances(self.path, CO, D)["nakit"], 900_000.0)

	def test_konversiya_two_legs(self):
		ss.set_opening(self.path, CO, D, "nakit", 13_000_000)
		ss.set_opening(self.path, CO, D, "usd", 0)
		# buy 1000$ @ 12900 from Nakit: nakit -12,900,000 ; usd +1000
		ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="konversiya",
			rate=12900,
			date=D,
			deltas=[{"kassa": "nakit", "delta": -12_900_000}, {"kassa": "usd", "delta": 1000}],
		)
		b = ss.balances(self.path, CO, D)
		self.assertEqual(b["nakit"], 100_000.0)
		self.assertEqual(b["usd"], 1000.0)

	def test_list_and_delete(self):
		eid = ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="kirim",
			counterparty="Ali",
			raw_text="Alidan 600 ming oldim",
			parsed={"op": "kirim"},
			deltas=[{"kassa": "nakit", "delta": 600_000}],
		)
		lst = ss.list_entries(self.path, CO, D if False else ss._today())
		# entry lands under today's date (add_entry defaults date=today)
		today = ss._today()
		lst = ss.list_entries(self.path, CO, today)
		self.assertEqual(len(lst), 1)
		self.assertEqual(lst[0]["counterparty"], "Ali")
		self.assertEqual(lst[0]["legs"], [{"kassa": "nakit", "delta": 600_000.0}])
		ss.delete_entry(self.path, eid, CO)
		self.assertEqual(ss.list_entries(self.path, CO, today), [])
		self.assertEqual(ss.balances(self.path, CO, today).get("nakit", 0), 0.0)

	def test_company_isolation(self):
		ss.add_entry(
			self.path,
			company="mikas",
			kassir="1",
			op="kirim",
			deltas=[{"kassa": "nakit", "delta": 500}],
			date=D,
		)
		ss.add_entry(
			self.path,
			company="other",
			kassir="2",
			op="kirim",
			deltas=[{"kassa": "nakit", "delta": 999}],
			date=D,
		)
		self.assertEqual(ss.balances(self.path, "mikas", D)["nakit"], 500.0)
		self.assertEqual(ss.balances(self.path, "other", D)["nakit"], 999.0)


if __name__ == "__main__":
	unittest.main()
