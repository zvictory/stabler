"""Unit tests for stabler.api._kts_amendment (WP-I15, Frappe-free).

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kts_amendment -v
"""

from __future__ import annotations

import unittest

from stabler.api._kts_amendment import amendment_delta, gl_routing


class TestDelta(unittest.TestCase):
	def test_upward_revision_routes_three_ways(self):
		# Gümrük kıymeti yukarı düzeltildi: boj 7000→9000, KDV 9240→11880, ceza 500.
		d = amendment_delta(
			{"duty_amount": 7000, "excise_amount": 0, "vat_amount": 9240},
			{"duty_amount": 9000, "excise_amount": 0, "vat_amount": 11880},
			penalty=500,
		)
		self.assertEqual(d["duty_delta"], 2000.0)
		self.assertEqual(d["vat_delta"], 2640.0)
		self.assertEqual(d["capitalized_delta"], 2000.0)   # boj+aksiz → stok
		self.assertEqual(d["input_vat_delta"], 2640.0)     # KDV → varlık
		self.assertEqual(d["pl_expense"], 500.0)           # ceza → P&L
		self.assertEqual(d["total_extra_payable"], 5140.0)

	def test_excise_capitalizes_with_duty(self):
		d = amendment_delta(
			{"duty_amount": 100, "excise_amount": 50, "vat_amount": 0},
			{"duty_amount": 180, "excise_amount": 90, "vat_amount": 0},
		)
		self.assertEqual(d["capitalized_delta"], 80 + 40)

	def test_downward_revision_negative(self):
		d = amendment_delta(
			{"duty_amount": 9000, "excise_amount": 0, "vat_amount": 11880},
			{"duty_amount": 7000, "excise_amount": 0, "vat_amount": 9240},
		)
		self.assertEqual(d["capitalized_delta"], -2000.0)
		self.assertEqual(d["input_vat_delta"], -2640.0)
		self.assertEqual(d["pl_expense"], 0.0)

	def test_penalty_never_in_capitalized(self):
		d = amendment_delta({}, {}, penalty=1000)
		self.assertEqual(d["capitalized_delta"], 0.0)
		self.assertEqual(d["input_vat_delta"], 0.0)
		self.assertEqual(d["pl_expense"], 1000.0)


class TestRouting(unittest.TestCase):
	def test_routing_lines_only_nonzero(self):
		d = amendment_delta(
			{"duty_amount": 100, "vat_amount": 0},
			{"duty_amount": 200, "vat_amount": 0},
			penalty=0,
		)
		routing = gl_routing(d)
		self.assertEqual(len(routing), 1)
		self.assertEqual(routing[0]["bucket"], "capitalized")

	def test_penalty_routed_to_pl_never_stock(self):
		routing = gl_routing(amendment_delta({}, {}, penalty=500))
		self.assertEqual([r["bucket"] for r in routing], ["penalty"])
		self.assertIn("P&L", routing[0]["account_hint"])
		self.assertNotIn("Stock", routing[0]["account_hint"])


if __name__ == "__main__":
	unittest.main()
