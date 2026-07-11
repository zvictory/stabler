"""Unit tests for the 3-tier cross-border transport cost selection (Frappe-free).

Covers tier 1 (expense linked to the truck), tier 2 (unlinked expense matching
the trucking company, auto-consumed), tier 3 (truck's own flat cost), the
consumed-marking contract, and the Import Expense status / PI-gating helpers.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_transport_tiers -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import payment_math as pm


def _exp(name, amount, supplier="TRUCKER", currency="USD"):
	return {"name": name, "amount": amount, "supplier": supplier, "currency": currency}


class TestResolveTransportSource(unittest.TestCase):
	def test_tier1_expense_linked_to_truck_wins(self):
		src = pm.resolve_transport_source(
			tier1_expense=_exp("IMP-EXP-1", 1200),
			tier2_expense=_exp("IMP-EXP-2", 999),
			truck_transport_cost=500,
			truck_supplier="TRUCK-VENDOR",
			truck_currency="USD",
		)
		self.assertEqual(src["amount"], 1200.0)
		self.assertEqual(src["supplier"], "TRUCKER")
		self.assertEqual(src["consume_expense"], "IMP-EXP-1")

	def test_tier2_used_when_no_tier1(self):
		src = pm.resolve_transport_source(
			tier1_expense=None,
			tier2_expense=_exp("IMP-EXP-2", 800, supplier="TRUCKER"),
			truck_transport_cost=500,
			truck_supplier="TRUCK-VENDOR",
			truck_currency="USD",
		)
		self.assertEqual(src["amount"], 800.0)
		self.assertEqual(src["consume_expense"], "IMP-EXP-2")

	def test_tier3_flat_cost_fallback(self):
		src = pm.resolve_transport_source(
			tier1_expense=None,
			tier2_expense=None,
			truck_transport_cost=650,
			truck_supplier="TRUCK-VENDOR",
			truck_currency="EUR",
		)
		self.assertEqual(src["amount"], 650.0)
		self.assertEqual(src["supplier"], "TRUCK-VENDOR")
		self.assertEqual(src["currency"], "EUR")
		self.assertIsNone(src["consume_expense"])

	def test_none_when_no_source_has_cost(self):
		self.assertIsNone(
			pm.resolve_transport_source(
				tier1_expense=None,
				tier2_expense=None,
				truck_transport_cost=0,
				truck_supplier="TRUCK-VENDOR",
				truck_currency="USD",
			)
		)

	def test_zero_amount_expense_skipped_to_next_tier(self):
		src = pm.resolve_transport_source(
			tier1_expense=_exp("IMP-EXP-1", 0),
			tier2_expense=None,
			truck_transport_cost=400,
			truck_supplier="TRUCK-VENDOR",
			truck_currency="USD",
		)
		self.assertEqual(src["amount"], 400.0)
		self.assertIsNone(src["consume_expense"])

	def test_expense_supplier_falls_back_to_truck_supplier(self):
		src = pm.resolve_transport_source(
			tier1_expense=_exp("IMP-EXP-1", 300, supplier=None),
			tier2_expense=None,
			truck_transport_cost=0,
			truck_supplier="TRUCK-VENDOR",
			truck_currency="USD",
		)
		self.assertEqual(src["supplier"], "TRUCK-VENDOR")


class TestExpenseStatus(unittest.TestCase):
	def test_paid_when_fully_covered(self):
		self.assertEqual(pm.expense_status(100, 60, 40), "Paid")

	def test_paid_when_overpaid(self):
		self.assertEqual(pm.expense_status(100, 120, 0), "Paid")

	def test_partial(self):
		self.assertEqual(pm.expense_status(100, 30, 0), "Partial")

	def test_pending_when_nothing_paid(self):
		self.assertEqual(pm.expense_status(100, 0, 0), "Pending")

	def test_pending_when_amount_zero(self):
		self.assertEqual(pm.expense_status(0, 0, 0), "Pending")


class TestWantsExpensePi(unittest.TestCase):
	def test_transport_category_excluded(self):
		self.assertFalse(pm.wants_expense_pi("Transport", "SUP", 100, None))

	def test_non_transport_with_supplier_and_amount(self):
		self.assertTrue(pm.wants_expense_pi("Customs", "SUP", 100, None))

	def test_no_supplier(self):
		self.assertFalse(pm.wants_expense_pi("Customs", None, 100, None))

	def test_zero_amount(self):
		self.assertFalse(pm.wants_expense_pi("Customs", "SUP", 0, None))

	def test_already_billed(self):
		self.assertFalse(pm.wants_expense_pi("Customs", "SUP", 100, "PINV-0001"))


class TestBuildImportExpensePiPayload(unittest.TestCase):
	def test_draft_payload_shape(self):
		payload = pm.build_import_expense_pi_payload(
			company="MSA",
			supplier="SUP",
			currency="USD",
			amount=250,
			category="Customs",
			description="Broker fee",
			expense_name="IMP-EXP-2026-00001",
		)
		self.assertEqual(payload["bill_no"], "IMPEXP-IMP-EXP-2026-00001")
		self.assertEqual(len(payload["items"]), 1)
		self.assertEqual(payload["items"][0]["item_code"], pm.IMPORT_SERVICE_ITEM_CODE)
		self.assertEqual(payload["items"][0]["description"], "Customs: Broker fee")
		self.assertNotIn("docstatus", payload)

	def test_none_when_zero_amount(self):
		self.assertIsNone(
			pm.build_import_expense_pi_payload(
				company="MSA", supplier="SUP", currency="USD", amount=0,
				category="Customs", description="", expense_name="X",
			)
		)


if __name__ == "__main__":
	unittest.main()
