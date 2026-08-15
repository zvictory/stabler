"""Pure allocation, reversal-order, FX and activation-gate contracts.

These modules are deliberately frappe-free, so the test imports them directly
— no ModuleSandbox fakes needed. The same allocator serves preview, collection
and supplier payment; these tests are what guarantees that stays true.
"""

from __future__ import annotations

import unittest

from stabler.api.vehicle_finance import activation as activation_mod
from stabler.api.vehicle_finance import allocation as allocation_mod


def _rows():
	return [
		{"row_name": "r0", "sequence": 0, "due_date": "2026-01-15", "amount": 100.0, "paid": 0.0},
		{"row_name": "r1", "sequence": 1, "due_date": "2026-02-15", "amount": 300.0, "paid": 0.0},
		{"row_name": "r2", "sequence": 2, "due_date": "2026-03-15", "amount": 300.0, "paid": 0.0},
		{"row_name": "r3", "sequence": 3, "due_date": "2026-04-15", "amount": 300.0, "paid": 0.0},
	]


class TestFifoAllocation(unittest.TestCase):
	def test_row_zero_down_payment_settles_first(self):
		allocs = allocation_mod.allocate(_rows(), 150.0)
		self.assertEqual([a["row_name"] for a in allocs], ["r0", "r1"])
		self.assertEqual(allocs[0]["allocated"], 100.0)
		self.assertEqual(allocs[1]["allocated"], 50.0)

	def test_partial_payment_single_row(self):
		allocs = allocation_mod.allocate(_rows(), 40.0)
		self.assertEqual(len(allocs), 1)
		self.assertEqual(allocs[0]["allocated"], 40.0)
		self.assertEqual(allocs[0]["outstanding_after"], 60.0)

	def test_one_payment_closing_multiple_rows(self):
		allocs = allocation_mod.allocate(_rows(), 1000.0)
		self.assertEqual([a["row_name"] for a in allocs], ["r0", "r1", "r2", "r3"])
		self.assertEqual(allocs[-1]["allocated"], 300.0)
		self.assertEqual(allocs[-1]["outstanding_after"], 0.0)

	def test_settled_rows_are_skipped_not_reopened(self):
		rows = _rows()
		rows[0]["paid"] = 100.0  # down payment already settled
		allocs = allocation_mod.allocate(rows, 50.0)
		self.assertEqual(allocs[0]["row_name"], "r1")

	def test_future_prepayment_into_future_rows(self):
		# Everything open is settled and the remainder flows into the last
		# (future) row — a cashier can never skip an overdue row.
		allocs = allocation_mod.allocate(_rows(), 850.0)
		self.assertEqual(allocs[-1]["row_name"], "r3")
		self.assertEqual(allocs[-1]["allocated"], 150.0)

	def test_amount_above_open_total_refuses_with_both_numbers(self):
		with self.assertRaises(ValueError) as ctx:
			allocation_mod.allocate(_rows(), 1001.0)
		self.assertIn("1000", str(ctx.exception))
		self.assertIn("1001", str(ctx.exception))

	def test_zero_or_negative_amount_rejected(self):
		with self.assertRaises(ValueError):
			allocation_mod.allocate(_rows(), 0)
		with self.assertRaises(ValueError):
			allocation_mod.allocate(_rows(), -5)

	def test_override_reorders_targets(self):
		allocs = allocation_mod.allocate(_rows(), 100.0, override_rows=["r2"])
		self.assertEqual([a["row_name"] for a in allocs], ["r2"])
		self.assertEqual(allocs[0]["allocated"], 100.0)

	def test_override_refuses_settled_row_and_unknown_row(self):
		rows = _rows()
		rows[2]["paid"] = 300.0
		with self.assertRaises(ValueError):
			allocation_mod.allocate(rows, 50.0, override_rows=["r2"])
		with self.assertRaises(ValueError):
			allocation_mod.allocate(rows, 50.0, override_rows=["nope"])

	def test_amount_larger_than_override_targets_refuses(self):
		with self.assertRaises(ValueError):
			allocation_mod.allocate(_rows(), 500.0, override_rows=["r1"])


class TestReversalOrder(unittest.TestCase):
	def test_newest_covered_row_first(self):
		applications = [
			{
				"name": "A1",
				"row_name": "r0",
				"sequence": 0,
				"due_date": "2026-01-15",
				"allocated_amount": 100.0,
			},
			{
				"name": "A2",
				"row_name": "r2",
				"sequence": 2,
				"due_date": "2026-03-15",
				"allocated_amount": 200.0,
			},
			{
				"name": "A3",
				"row_name": "r1",
				"sequence": 1,
				"due_date": "2026-02-15",
				"allocated_amount": 50.0,
			},
		]
		plan = allocation_mod.reversal_plan(applications)
		self.assertEqual([p["name"] for p in plan], ["A2", "A3", "A1"])


class TestPaymentFx(unittest.TestCase):
	def test_same_currency_no_exchange(self):
		fx = allocation_mod.compute_payment_fx(
			amount=100,
			party_currency="USD",
			bank_currency="USD",
			to_base_rates={"USD": 12900.0},
			payment_type="Receive",
		)
		self.assertFalse(fx["needs_exchange"])
		self.assertEqual(fx["paid_amount"], 100)
		self.assertEqual(fx["received_amount"], 100)

	def test_receive_party_usd_bank_uzs(self):
		fx = allocation_mod.compute_payment_fx(
			amount=100,
			party_currency="USD",
			bank_currency="UZS",
			to_base_rates={"UZS": 1.0, "USD": 12900.0},
			payment_type="Receive",
		)
		self.assertTrue(fx["needs_exchange"])
		self.assertEqual(fx["paid_amount"], 100)  # party currency
		self.assertEqual(fx["received_amount"], 100 * 12900.0)  # bank currency
		self.assertEqual(fx["source_exchange_rate"], 12900.0)
		self.assertEqual(fx["target_exchange_rate"], 1.0)

	def test_pay_bank_uzs_party_usd(self):
		fx = allocation_mod.compute_payment_fx(
			amount=100,
			party_currency="USD",
			bank_currency="UZS",
			to_base_rates={"UZS": 1.0, "USD": 12900.0},
			payment_type="Pay",
		)
		# paid_amount is always in the PAID-FROM (bank) currency.
		self.assertEqual(fx["paid_amount"], 100 * 12900.0)
		self.assertEqual(fx["received_amount"], 100)
		self.assertEqual(fx["source_exchange_rate"], 1.0)  # bank → base
		self.assertEqual(fx["target_exchange_rate"], 12900.0)  # party → base

	def test_cross_foreign_via_base(self):
		fx = allocation_mod.compute_payment_fx(
			amount=150,
			party_currency="USD",
			bank_currency="EUR",
			to_base_rates={"USD": 12900.0, "EUR": 14000.0},
			payment_type="Receive",
		)
		self.assertAlmostEqual(fx["received_amount"], 150 * 12900.0 / 14000.0)


def _agreement(**overrides):
	base = dict(
		company="ACME",
		direction="Disposition",
		settlement_mode="Installment",
		currency="USD",
		total_contract_price=1000.0,
		cash_price=800.0,
		disclosed_markup=150.0,
		approved_fees=30.0,
		tax_amount=20.0,
		down_payment=100.0,
		financed_amount=900.0,
		vehicle_unit="VEH-00001",
	)
	base.update(overrides)
	return base


def _settings(**overrides):
	base = dict(
		accounting_policy_approved=1,
		disposition_receivable_account="DR - ACME",
		disposition_deferred_income_account="DEF - ACME",
		disposition_income_account="INC - ACME",
		disposition_fee_item="FEE",
	)
	base.update(overrides)
	return base


class TestActivationGates(unittest.TestCase):
	def test_all_gates_pass(self):
		checks = activation_mod.check_activation_gates(
			_agreement(), _settings(), configured_records={}, schedule_rows_total=1000.0
		)
		self.assertTrue(all(c["passed"] for c in checks))
		self.assertEqual(
			[c["name"] for c in checks],
			[
				"accounting_policy_approved",
				"required_configuration",
				"records_belong_to_company",
				"agreement_invariants",
			],
		)

	def test_unapproved_policy_fails_with_field_name(self):
		checks = activation_mod.check_activation_gates(
			_agreement(),
			_settings(accounting_policy_approved=0),
			configured_records={},
			schedule_rows_total=1000.0,
		)
		failed = next(c for c in checks if not c["passed"])
		self.assertEqual(failed["name"], "accounting_policy_approved")
		self.assertIn("accounting_policy_approved", failed["message"])

	def test_each_missing_field_is_named(self):
		for field in (
			"disposition_receivable_account",
			"disposition_deferred_income_account",
			"disposition_income_account",
			"disposition_fee_item",
		):
			with self.subTest(field=field):
				settings = _settings()
				settings[field] = None
				checks = activation_mod.check_activation_gates(
					_agreement(), settings, configured_records={}, schedule_rows_total=1000.0
				)
				failed = next(c for c in checks if not c["passed"])
				self.assertEqual(failed["name"], "required_configuration")
				self.assertIn(field, failed["message"])

	def test_acquisition_requires_its_own_fields(self):
		checks = activation_mod.check_activation_gates(
			_agreement(direction="Acquisition"),
			_settings(),
			configured_records={},
			schedule_rows_total=1000.0,
		)
		failed = next(c for c in checks if not c["passed"])
		self.assertIn("acquisition_payable_account", failed["message"])

	def test_foreign_company_account_fails(self):
		checks = activation_mod.check_activation_gates(
			_agreement(),
			_settings(),
			configured_records={"disposition_receivable_account": {"company": "OTHER"}},
			schedule_rows_total=1000.0,
		)
		failed = next(c for c in checks if not c["passed"])
		self.assertEqual(failed["name"], "records_belong_to_company")
		self.assertIn("disposition_receivable_account", failed["message"])

	def test_schedule_sum_mismatch_fails(self):
		checks = activation_mod.check_activation_gates(
			_agreement(), _settings(), configured_records={}, schedule_rows_total=900.0
		)
		names = [c["name"] for c in checks if not c["passed"]]
		self.assertIn("agreement_invariants", names)

	def test_component_mismatch_fails(self):
		checks = activation_mod.check_activation_gates(
			_agreement(approved_fees=40.0), _settings(), configured_records={}, schedule_rows_total=1000.0
		)
		failed = next(c for c in checks if c["name"] == "agreement_invariants")
		self.assertFalse(failed["passed"])


class TestPlannedDocuments(unittest.TestCase):
	def test_disposition_plan(self):
		docs = activation_mod.planned_documents(_agreement())
		self.assertEqual([d["doctype"] for d in docs], ["Delivery Note", "Sales Invoice"])

	def test_acquisition_plan(self):
		docs = activation_mod.planned_documents(_agreement(direction="Acquisition"))
		self.assertEqual([d["doctype"] for d in docs], ["Purchase Receipt", "Purchase Invoice"])

	def test_cash_mode_is_flagged(self):
		docs = activation_mod.planned_documents(_agreement(settlement_mode="Cash"))
		self.assertIn("cash-settlement", docs[0]["purpose"])


if __name__ == "__main__":
	unittest.main()
