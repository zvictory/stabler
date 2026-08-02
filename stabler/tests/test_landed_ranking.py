"""Pure unit tests for landed cost calculation and ranking logic (_landed.py).

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_landed_ranking -v
"""

from __future__ import annotations

import unittest

from stabler.api._landed import (
	calculate_quotation_landed,
	parse_landed_charges,
	rank_quotations_landed,
)


class TestLandedRanking(unittest.TestCase):
	def test_vat_tax_non_capitalization(self):
		"""IAS 2 §11: Recoverable VAT must NOT be capitalized into landed cost."""
		raw = [
			{"charge_type": "Freight", "amount": 1000.0},
			{"charge_type": "Customs Duty", "amount": 500.0},
			{"charge_type": "VAT", "amount": 300.0, "is_recoverable_vat": True},
		]
		total, clean, has_est = parse_landed_charges(raw)
		self.assertTrue(has_est)
		self.assertEqual(total, 1500.0, "VAT 300 must be excluded from landed total")
		self.assertEqual(len(clean), 3)
		vat_clean = [c for c in clean if c["charge_type"] == "VAT"][0]
		self.assertEqual(vat_clean["capitalized_amount"], 0.0)

	def test_incomplete_estimate_rule_k3(self):
		"""K3 Rule: If any quotation lacks landed charges, cheapest_landed is not set."""
		quotes = [
			{
				"name": "SQ-CHINA",
				"base_grand_total": 874000.0,
				"custom_landed_charges": '[{"charge_type":"Freight","amount":150000.0}]',
			},
			{
				"name": "SQ-LOCAL-NO-ESTIMATE",
				"base_grand_total": 846400.0,
				"custom_landed_charges": None,  # Missing estimate
			},
		]
		res = rank_quotations_landed(quotes)
		self.assertFalse(res["estimate_complete"])
		self.assertIsNone(res["cheapest_landed_quote"])
		self.assertEqual(res["missing_estimates"], ["SQ-LOCAL-NO-ESTIMATE"])
		self.assertEqual(res["cheapest_price_quote"], "SQ-LOCAL-NO-ESTIMATE")

	def test_complete_estimate_flips_cheapest_supplier(self):
		"""Demonstrates how landed charges flip the winner from sticker price to delivered total."""
		quotes = [
			{
				"name": "SQ-CHINA",
				"supplier": "Hebei Rail Parts (China)",
				"base_grand_total": 874000.0,
				"custom_landed_charges": '[{"charge_type":"Freight & Customs","amount":50000.0}]',
				# Landed total = 924,000
			},
			{
				"name": "SQ-LOCAL",
				"supplier": "Temiryo'l Ta'minot (Local)",
				"base_grand_total": 846400.0,
				"custom_landed_charges": '[{"charge_type":"Local Delivery","amount":100000.0}]',
				# Landed total = 946,400
			},
		]
		res = rank_quotations_landed(quotes)
		self.assertTrue(res["estimate_complete"])
		self.assertEqual(res["cheapest_price_quote"], "SQ-LOCAL")
		self.assertEqual(res["cheapest_landed_quote"], "SQ-CHINA")

		sq_china = [q for q in res["quotations"] if q["name"] == "SQ-CHINA"][0]
		sq_local = [q for q in res["quotations"] if q["name"] == "SQ-LOCAL"][0]

		self.assertFalse(sq_china["is_cheapest_price"])
		self.assertTrue(sq_china["is_cheapest_landed"])

		self.assertTrue(sq_local["is_cheapest_price"])
		self.assertFalse(sq_local["is_cheapest_landed"])

		# Delta and percentage over cheapest landed (SQ-CHINA = 924,000)
		self.assertEqual(sq_local["landed_delta"], 22400.0)
		self.assertGreater(sq_local["landed_pct"], 0.0)

	def test_empty_list_handling(self):
		res = rank_quotations_landed([])
		self.assertEqual(res["quotations"], [])
		self.assertIsNone(res["cheapest_price_quote"])
		self.assertIsNone(res["cheapest_landed_quote"])
		self.assertFalse(res["estimate_complete"])


if __name__ == "__main__":
	unittest.main()
