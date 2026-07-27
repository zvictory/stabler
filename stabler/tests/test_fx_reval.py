"""Unit tests for stabler.api._fx_reval (WP-I11, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_fx_reval -v
"""

from __future__ import annotations

import unittest

from stabler.api._fx_reval import reval_row, reval_rows, reval_summary


class TestRevalRow(unittest.TestCase):
	def test_payable_rate_up_is_loss(self):
		# $30.000 borç, 12.000'de kayıtlı, kapanış 12.100 → borç 3.000.000 UZS büyüdü = ZARAR
		r = reval_row(30000, 12000, 12100)
		self.assertEqual(r["unrealized_loss"], 3_000_000.0)
		self.assertEqual(r["booked_base"], 360_000_000.0)
		self.assertEqual(r["closing_base"], 363_000_000.0)

	def test_payable_rate_down_is_gain(self):
		r = reval_row(30000, 12000, 11900)
		self.assertEqual(r["unrealized_loss"], -3_000_000.0)  # negatif = kazanç

	def test_same_rate_zero(self):
		self.assertEqual(reval_row(30000, 12000, 12000)["unrealized_loss"], 0.0)

	def test_garbage_safe(self):
		self.assertEqual(reval_row(None, "x", None)["unrealized_loss"], 0.0)


class TestRowsAndSummary(unittest.TestCase):
	def test_sorted_by_magnitude_and_summed(self):
		rows = reval_rows(
			[
				{"name": "PINV-A", "outstanding_foreign": 30000, "booked_rate": 12000},
				{"name": "PINV-B", "outstanding_foreign": 4000, "booked_rate": 12050},
			],
			12100,
		)
		self.assertEqual(rows[0]["name"], "PINV-A")  # 3.000.000 > 200.000
		s = reval_summary(rows)
		self.assertEqual(s["unrealized_loss"], 3_200_000.0)
		self.assertEqual(s["unrealized_gain"], 0.0)
		self.assertEqual(s["net_unrealized_loss"], 3_200_000.0)
		self.assertEqual(s["rows"], 2)

	def test_mixed_gain_loss_nets(self):
		rows = reval_rows(
			[
				{"name": "A", "outstanding_foreign": 1000, "booked_rate": 12000},  # +100.000 zarar
				{"name": "B", "outstanding_foreign": 5000, "booked_rate": 12160},  # -300.000 kazanç
			],
			12100,
		)
		s = reval_summary(rows)
		self.assertEqual(s["unrealized_loss"], 100_000.0)
		self.assertEqual(s["unrealized_gain"], 300_000.0)
		self.assertEqual(s["net_unrealized_loss"], -200_000.0)

	def test_empty(self):
		self.assertEqual(reval_summary(reval_rows([], 12100))["rows"], 0)


class TestAdvancesExcludedAtSource(unittest.TestCase):
	"""IAS 21: mal avansı parasal olmayan kalem — endpoint SQL'i yalnız Purchase
	Invoice bakiyelerini beslemeli, avans PE'lerini asla."""

	def test_endpoint_reads_only_purchase_invoices(self):
		import os
		import re

		api = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "imports.py")
		src = open(api, encoding="utf-8").read()
		m = re.search(r"^def fx_revaluation_preview\(", src, re.M)
		self.assertIsNotNone(m, "fx_revaluation_preview not found")
		tail = src[m.start() :]
		nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def )", tail[1:])
		body = tail[: nxt.start() + 1] if nxt else tail
		self.assertIn("tabPurchase Invoice", body)
		self.assertNotIn("tabPayment Entry", body)  # avanslar dahil edilemez
		self.assertIn("outstanding_amount", body)


if __name__ == "__main__":
	unittest.main()
