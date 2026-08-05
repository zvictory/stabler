"""Unit tests for CI transport expense allocation and landed cost calculation.

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_transport_allocation -v
"""

from __future__ import annotations

import unittest

from stabler.api import _imports_rules as rules


class TestCiTransportAllocation(unittest.TestCase):
	def test_direct_and_weight_allocation(self):
		expenses = [
			{
				"name": "EXP-001",
				"category": "Transport",
				"supplier": "SUPP-01",
				"supplier_name": "TransCorp",
				"amount": 1000.0,
				"container": "CNT-001",
				"bank_payment": 600.0,
				"cash_payment": 400.0,
			},
			{
				"name": "EXP-002",
				"category": "Handling",
				"supplier": "SUPP-01",
				"supplier_name": "TransCorp",
				"amount": 3000.0,
				"container": None,
				"bank_payment": 1500.0,
				"cash_payment": 500.0,
			},
		]
		containers = [
			{"name": "CNT-001", "total_kg": 10000.0},
			{"name": "CNT-002", "total_kg": 20000.0},
		]
		out = rules.calculate_ci_transport_costs(
			raw_expenses=expenses,
			containers=containers,
			ci_total_kg=30000.0,
			ci_agreed_total=120000.0,
			currency="USD",
		)

		self.assertEqual(out["totals"]["transport"], 4000.0)
		self.assertEqual(out["totals"]["paid"], 3000.0)
		self.assertEqual(out["totals"]["outstanding"], 1000.0)
		self.assertEqual(out["totals"]["per_container"], 2000.0)
		self.assertAlmostEqual(out["totals"]["per_kg"], 0.1333, places=4)
		self.assertAlmostEqual(out["totals"]["goods_per_kg"], 4.0, places=4)
		self.assertAlmostEqual(out["totals"]["landed_per_kg"], 4.1333, places=4)

		# CNT-001 gets 1000 direct + 3000*(10000/30000) = 2000
		# CNT-002 gets 0 direct + 3000*(20000/30000) = 2000
		cnt_map = {c["container"]: c["amount"] for c in out["by_container"]}
		self.assertEqual(cnt_map["CNT-001"], 2000.0)
		self.assertEqual(cnt_map["CNT-002"], 2000.0)

	def test_equal_allocation_when_weights_zero(self):
		expenses = [
			{
				"name": "EXP-003",
				"category": "Border Crossing",
				"supplier": "SUPP-02",
				"supplier_name": "BorderServices",
				"amount": 1000.0,
				"container": None,
				"bank_payment": 500.0,
				"cash_payment": 500.0,
			}
		]
		containers = [
			{"name": "CNT-A", "total_kg": 0.0},
			{"name": "CNT-B", "total_kg": 0.0},
		]
		out = rules.calculate_ci_transport_costs(
			raw_expenses=expenses,
			containers=containers,
			ci_total_kg=0.0,
			ci_agreed_total=50000.0,
			currency="USD",
		)
		cnt_map = {c["container"]: c["amount"] for c in out["by_container"]}
		self.assertEqual(cnt_map["CNT-A"], 500.0)
		self.assertEqual(cnt_map["CNT-B"], 500.0)
		# Zero kg safety
		self.assertEqual(out["totals"]["per_kg"], 0.0)
		self.assertEqual(out["totals"]["goods_per_kg"], 0.0)
		self.assertEqual(out["totals"]["landed_per_kg"], 0.0)

	def test_category_separation(self):
		expenses = [
			{
				"name": "EXP-TRANS",
				"category": "Transport",
				"supplier": "SUPP-01",
				"amount": 2000.0,
				"bank_payment": 2000.0,
				"cash_payment": 0.0,
			},
			{
				"name": "EXP-CUSTOMS",
				"category": "Customs",
				"supplier": "SUPP-03",
				"amount": 500.0,
				"bank_payment": 500.0,
				"cash_payment": 0.0,
			},
		]
		out = rules.calculate_ci_transport_costs(
			raw_expenses=expenses,
			containers=[],
			ci_total_kg=10000.0,
			ci_agreed_total=40000.0,
		)
		self.assertEqual(out["totals"]["transport"], 2000.0)
		self.assertEqual(out["other_total"], 500.0)
		self.assertEqual(len(out["other_rows"]), 1)
		self.assertEqual(out["other_rows"][0]["name"], "EXP-CUSTOMS")

	def test_masked_payments(self):
		expenses = [
			{
				"name": "EXP-MASKED",
				"category": "Storage",
				"supplier": "SUPP-01",
				"amount": 1500.0,
				"bank_payment": None,
				"cash_payment": None,
			}
		]
		out = rules.calculate_ci_transport_costs(
			raw_expenses=expenses,
			containers=[],
			ci_total_kg=10000.0,
			ci_agreed_total=40000.0,
		)
		self.assertIsNone(out["totals"]["paid"])
		self.assertIsNone(out["totals"]["outstanding"])
		self.assertIsNone(out["by_vendor"][0]["paid"])
		self.assertIsNone(out["by_vendor"][0]["outstanding"])


if __name__ == "__main__":
	unittest.main()
