import unittest

from stabler.api._imports_rules import calculate_ci_cost_overview, per_kg


class TestCiCostOverview(unittest.TestCase):
	"""Pure unit tests for CI Form v4 cost overview math (frappe-free)."""

	def test_container_allocations_and_gap(self):
		containers = [
			{"name": "CNT-1", "total_kg": 28000.0, "total_boxes": 1400, "goods_amount": 100000.0},
			{"name": "CNT-2", "total_kg": 28000.0, "total_boxes": 1400, "goods_amount": 100000.0},
		]
		expenses = [
			{
				"name": "EXP-1",
				"category": "Transport",
				"supplier": "Carrier A",
				"supplier_name": "Carrier A",
				"container": "CNT-1",
				"truck": None,
				"amount": 1000.0,
				"bank_payment": 1000.0,
				"cash_payment": 0.0,
				"purchase_invoice": "PINV-101",
			},
			{
				"name": "EXP-2",
				"category": "Transport",
				"supplier": "Carrier B",
				"supplier_name": "Carrier B",
				"container": None,
				"truck": None,
				"amount": 2000.0,
				"bank_payment": 1000.0,
				"cash_payment": 0.0,
				"purchase_invoice": None,
			},
			{
				"name": "EXP-3",
				"category": "Customs",
				"supplier": "Broker",
				"supplier_name": "Broker",
				"container": None,
				"truck": None,
				"amount": 500.0,
				"bank_payment": 500.0,
				"cash_payment": 0.0,
				"purchase_invoice": None,
			},
		]
		bills = [
			{
				"name": "PINV-101",
				"supplier": "Carrier A",
				"supplier_name": "Carrier A",
				"bill_no": "BILL-1",
				"category": "transport",
				"grand_total": 1000.0,
				"outstanding_amount": 0.0,
			},
			{
				"name": "PINV-GOODS",
				"supplier": "Supplier X",
				"supplier_name": "Supplier X",
				"bill_no": "BILL-GOODS",
				"category": "product",
				"grand_total": 190000.0,
				"outstanding_amount": 0.0,
			},
		]

		res = calculate_ci_cost_overview(
			ci_name="CI-2026-001",
			items_agreed_total=200000.0,
			items_docs_total=180000.0,
			cargo_kg=56000.0,
			containers=containers,
			expenses=expenses,
			bills=bills,
			lcv_total=1000.0,
			customs_duties=1500.0,
			duties_estimated=True,
			currency="USD",
			cost_visible=True,
		)

		# Allocation check: EXP-1 is direct to CNT-1 (1000). EXP-2 is weight-split (1000 each).
		by_cnt = {c["container"]: c for c in res["by_container"]}
		self.assertEqual(by_cnt["CNT-1"]["logistics_amount"], 2000.0)
		self.assertEqual(by_cnt["CNT-2"]["logistics_amount"], 1000.0)

		# Transport expenses sum = 3000. Other expenses sum = 500.
		self.assertEqual(res["operational"]["goods"], 200000.0)
		self.assertEqual(res["operational"]["transport"], 3000.0)
		self.assertEqual(res["operational"]["other"], 500.0)
		self.assertEqual(res["operational"]["duties"], 1500.0)
		self.assertEqual(res["operational"]["total"], 205000.0)
		self.assertTrue(res["operational"]["duties_estimated"])

		# Accounting: billed_goods=190000 (from product bill, NOT docs_total 180000) + lcv_total=1000 = 191000.0
		self.assertEqual(res["accounting"]["billed_goods"], 190000.0)
		self.assertEqual(res["accounting"]["lcv_total"], 1000.0)
		self.assertEqual(res["accounting"]["total"], 191000.0)

		# Gap: 205000 - 191000 = 14000.0
		self.assertEqual(res["gap"]["amount"], 14000.0)
		self.assertEqual(res["gap"]["per_kg"], per_kg(14000.0, 56000.0))

		# Reconciliation identity check: transport == billed + unbilled
		self.assertAlmostEqual(res["totals"]["transport"], res["totals"]["billed"] + res["totals"]["unbilled"], places=2)
		self.assertEqual(res["totals"]["billed"], 1000.0)
		self.assertEqual(res["totals"]["unbilled"], 2000.0)

	def test_masked_financials(self):
		containers = [{"name": "CNT-1", "total_kg": 1000.0, "total_boxes": 50, "goods_amount": 5000.0}]
		expenses = [
			{
				"name": "EXP-1",
				"category": "Transport",
				"supplier": "Carrier",
				"supplier_name": "Carrier",
				"amount": 500.0,
				"bank_payment": 200.0,
				"cash_payment": 0.0,
			}
		]
		res = calculate_ci_cost_overview(
			ci_name="CI-2026-002",
			items_agreed_total=5000.0,
			items_docs_total=4000.0,
			cargo_kg=1000.0,
			containers=containers,
			expenses=expenses,
			bills=[],
			lcv_total=0.0,
			customs_duties=0.0,
			cost_visible=False,
		)
		self.assertIsNone(res["expenses"][0]["amount"])
		self.assertIsNone(res["expenses"][0]["bank_payment"])
		self.assertIsNone(res["operational"]["total"])
		self.assertIsNone(res["gap"]["amount"])
		self.assertEqual(res["totals"]["containers"], 1)
		self.assertEqual(res["totals"]["cargo_kg"], 1000.0)


if __name__ == "__main__":
	unittest.main()
