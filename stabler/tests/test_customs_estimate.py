"""Unit tests for stabler.api._customs_estimate (WP-I13, Frappe-free).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_customs_estimate -v
"""

from __future__ import annotations

import unittest

from stabler.api._customs_estimate import estimate, scale_to_declared


class TestScale(unittest.TestCase):
	def test_proportional_scaling(self):
		rows = scale_to_declared(
			[{"hs_code": "0202", "amount": 60000}, {"hs_code": "0207", "amount": 40000}], 70000
		)
		self.assertEqual([r["declared_amount"] for r in rows], [42000.0, 28000.0])

	def test_no_declared_keeps_amounts(self):
		rows = scale_to_declared([{"amount": 100}], 0)
		self.assertEqual(rows[0]["declared_amount"], 100.0)


class TestEstimate(unittest.TestCase):
	def test_presentation_scenario(self):
		# Sunumdaki örnek: beyan 70.000 + transport banka 5.000; boj %10, KDV %12.
		est = estimate(
			[{"hs_code": "0202", "declared_amount": 70000}],
			{"0202": {"duty_pct": 10, "excise_pct": 0, "vat_pct": 12}},
			transport_bank=5000,
		)
		self.assertEqual(est["customs_value"], 75000.0)
		self.assertEqual(est["duty_total"], 7000.0)  # boj mal beyanı üzerinden
		self.assertEqual(est["vat_base"], 82000.0)
		self.assertEqual(est["vat_total"], 9840.0)
		self.assertEqual(est["capitalized_total"], 7000.0)  # KDV asla dahil değil
		self.assertEqual(est["payable_to_customs"], 16840.0)

	def test_unrated_hs_reported_not_guessed(self):
		est = estimate([{"hs_code": "9999", "declared_amount": 1000}], {})
		self.assertEqual(est["duty_total"], 0.0)
		self.assertEqual(est["unrated_hs_codes"], ["9999"])
		self.assertFalse(est["rows"][0]["rated"])

	def test_excise_in_vat_base_and_capitalized(self):
		est = estimate(
			[{"hs_code": "2203", "declared_amount": 1000}],
			{"2203": {"duty_pct": 10, "excise_pct": 5, "vat_pct": 12}},
		)
		self.assertEqual(est["duty_total"], 100.0)
		self.assertEqual(est["excise_total"], 50.0)
		self.assertEqual(est["vat_base"], 1150.0)
		self.assertEqual(est["capitalized_total"], 150.0)

	def test_empty(self):
		est = estimate([], {})
		self.assertEqual(est["payable_to_customs"], 0.0)


if __name__ == "__main__":
	unittest.main()
