"""Deterministic schedule builder and money-invariant contracts.

Bench-free: frappe.utils is faked with the real semantics it must carry
(flt rounding, getdate parsing, add_months month-end clamping), then the
builder is imported against the fakes via ModuleSandbox.
"""

from __future__ import annotations

import calendar
import importlib
import sys
import types
import unittest
from datetime import date

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


def _flt(value, precision=None):
	result = float(value or 0)
	if precision is not None:
		result = round(result, int(precision))
	return result


def _getdate(value):
	if isinstance(value, date):
		return value
	return date.fromisoformat(str(value)[:10])


def _add_months(start, months):
	"""Month-end clamping like frappe.utils.add_months: 31 Jan + 1 = Feb end."""
	year, month = divmod(start.month - 1 + months, 12)
	year += start.year
	month += 1
	last = calendar.monthrange(year, month)[1]
	return date(year, month, min(start.day, last))


def _install_fakes() -> None:
	frappe_mod = types.ModuleType("frappe")
	frappe_mod._ = lambda s: s
	frappe_mod.throw = lambda msg, exc=None: (_ for _ in ()).throw(
		(exc or Exception)(msg) if exc else Exception(msg)
	)
	utils = types.ModuleType("frappe.utils")
	utils.flt = _flt
	utils.getdate = _getdate
	utils.add_months = _add_months
	frappe_mod.utils = utils
	frappe_mod.throw = lambda msg, exc=None: (_ for _ in ()).throw(exc(Exception) if exc else Exception(msg))
	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")
	document.Document = type("Document", (), {})
	model.document = document
	frappe_mod.model = model
	_SANDBOX.evict(
		"frappe",
		"frappe.utils",
		"frappe.model",
		"frappe.model.document",
		"stabler.api.vehicle_finance.schedule",
		"stabler.stabler.doctype.vehicle_agreement.vehicle_agreement",
	)
	_SANDBOX.install(
		{
			"frappe": frappe_mod,
			"frappe.utils": utils,
			"frappe.model": model,
			"frappe.model.document": document,
		}
	)


def setUpModule():
	"""Install fakes only when the tests actually run.

	Frappe's bench test runner imports every test module up front just to
	categorise it; an import-time install would poison that process's
	sys.modules with the fakes (tearDownModule never runs there)."""
	global schedule, build_schedule, vehicle_agreement
	_install_fakes()
	schedule = importlib.import_module("stabler.api.vehicle_finance.schedule")
	build_schedule = schedule.build_schedule
	vehicle_agreement = importlib.import_module(
		"stabler.stabler.doctype.vehicle_agreement.vehicle_agreement"
	)


def _amounts(rows):
	return [r["amount"] for r in rows]


class TestEqualMonthly(unittest.TestCase):
	def test_clean_division_and_row_zero_included(self):
		rows = build_schedule(
			total=12000,
			down_payment=2000,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date="2026-01-15",
			first_installment_date="2026-02-15",
			installment_count=10,
		)
		self.assertEqual(rows[0]["row_type"], "Down Payment")
		self.assertEqual(rows[0]["amount"], 2000)
		self.assertEqual(rows[0]["due_date"], date(2026, 1, 15))
		self.assertEqual(len(rows), 11)
		self.assertEqual(_amounts(rows)[1:], [1000.0] * 10)
		self.assertEqual(round(sum(_amounts(rows)), 2), 12000.0)

	def test_rounding_residual_lands_only_on_the_final_row(self):
		rows = build_schedule(
			total=1000,
			down_payment=0,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date="2026-01-15",
			first_installment_date="2026-02-15",
			installment_count=3,
		)
		# 1000 / 3 = 333.33 each = 999.99; the final row alone absorbs 0.01.
		self.assertEqual(_amounts(rows)[1:], [333.33, 333.33, 333.34])
		self.assertEqual(round(sum(_amounts(rows)), 2), 1000.0)

	def test_month_end_rollover_from_31_january(self):
		rows = build_schedule(
			total=3000,
			down_payment=0,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date="2026-01-31",
			first_installment_date="2026-02-28",
			installment_count=3,
		)
		dates = [r["due_date"] for r in rows][1:]
		self.assertEqual(dates, [date(2026, 2, 28), date(2026, 3, 28), date(2026, 4, 28)])

	def test_leap_year_february(self):
		rows = build_schedule(
			total=2000,
			down_payment=0,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date="2028-01-31",
			first_installment_date="2028-02-29",
			installment_count=2,
		)
		dates = [r["due_date"] for r in rows][1:]
		self.assertEqual(dates, [date(2028, 2, 29), date(2028, 3, 29)])


class TestBalloon(unittest.TestCase):
	def test_balloon_becomes_the_final_row_and_absorbs_residual(self):
		rows = build_schedule(
			total=1000,
			down_payment=100,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date="2026-01-15",
			first_installment_date="2026-02-15",
			installment_count=3,
			balloon_amount=200,
		)
		financed = 1000 - 100 - 200  # 700 over 3 installments = 233.33 x3 = 699.99
		self.assertEqual(rows[-1]["row_type"], "Balloon")
		# Residual (699.99 + 200 = 899.99 vs 1000 total → 0.01) lands on the
		# balloon row: 200.01, never on an installment row.
		self.assertEqual(rows[-1]["amount"], 200.01)
		self.assertEqual(_amounts(rows)[1:-1], [233.33, 233.33, 233.33])
		self.assertEqual(round(sum(_amounts(rows)), 2), 1000.0)


class TestCash(unittest.TestCase):
	def test_cash_is_a_single_row_equal_to_the_total(self):
		rows = build_schedule(
			total=5000,
			down_payment=5000,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date="2026-03-10",
			settlement_mode="Cash",
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["row_type"], "Cash Settlement")
		self.assertEqual(rows[0]["amount"], 5000.0)
		self.assertEqual(rows[0]["due_date"], date(2026, 3, 10))


class TestCustom(unittest.TestCase):
	def _rows(self):
		return [
			{"sequence": 0, "due_date": "2026-01-15", "amount": 200.0, "row_type": "Down Payment"},
			{"sequence": 1, "due_date": "2026-02-15", "amount": 400.0, "row_type": "Installment"},
			{"sequence": 2, "due_date": "2026-03-15", "amount": 400.0, "row_type": "Installment"},
		]

	def test_balanced_custom_schedule_passes(self):
		rows = build_schedule(
			total=1000,
			down_payment=200,
			currency_precision=2,
			plan_type="Custom",
			agreement_date="2026-01-15",
			custom_rows=self._rows(),
		)
		self.assertEqual(len(rows), 3)
		self.assertEqual(round(sum(_amounts(rows)), 2), 1000.0)

	def test_unbalanced_custom_schedule_states_both_numbers(self):
		rows = self._rows()
		rows[2]["amount"] = 300.0
		with self.assertRaises(ValueError) as ctx:
			build_schedule(
				total=1000,
				down_payment=200,
				currency_precision=2,
				plan_type="Custom",
				agreement_date="2026-01-15",
				custom_rows=rows,
			)
		self.assertIn("900", str(ctx.exception))
		self.assertIn("1000", str(ctx.exception))

	def test_non_monotonic_custom_dates_rejected(self):
		rows = self._rows()
		rows[1]["due_date"] = "2026-01-10"
		with self.assertRaises(ValueError):
			build_schedule(
				total=1000,
				down_payment=200,
				currency_precision=2,
				plan_type="Custom",
				agreement_date="2026-01-15",
				custom_rows=rows,
			)

	def test_custom_row_zero_must_be_down_payment_on_agreement_date(self):
		rows = self._rows()
		rows[0]["row_type"] = "Installment"
		with self.assertRaises(ValueError):
			build_schedule(
				total=1000,
				down_payment=200,
				currency_precision=2,
				plan_type="Custom",
				agreement_date="2026-01-15",
				custom_rows=rows,
			)


class TestRejections(unittest.TestCase):
	def _build(self, **overrides):
		payload = dict(
			total=1000,
			down_payment=100,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date="2026-01-15",
			first_installment_date="2026-02-15",
			installment_count=3,
		)
		payload.update(overrides)
		return build_schedule(**payload)

	def test_negative_down_payment_rejected(self):
		with self.assertRaises(ValueError):
			self._build(down_payment=-1)

	def test_down_payment_above_total_rejected(self):
		with self.assertRaises(ValueError):
			self._build(down_payment=1001)

	def test_negative_financed_amount_rejected(self):
		with self.assertRaises(ValueError):
			self._build(balloon_amount=901)

	def test_installment_count_below_one_rejected(self):
		with self.assertRaises(ValueError):
			self._build(installment_count=0)

	def test_due_date_before_agreement_rejected(self):
		with self.assertRaises(ValueError):
			self._build(first_installment_date="2026-01-10")

	def test_zero_total_rejected(self):
		with self.assertRaises(ValueError):
			self._build(total=0)


class TestAgreementMoneyInvariants(unittest.TestCase):
	"""Invariants 1, 3 and 4 as pure functions."""

	def test_components_sum_to_total(self):
		total = vehicle_agreement.compute_total_contract_price(800, 150, 30, 20)
		self.assertEqual(total, 1000.0)

	def test_down_payment_bounds(self):
		with self.assertRaises(ValueError):
			vehicle_agreement.validate_down_payment(-1, 1000)
		with self.assertRaises(ValueError):
			vehicle_agreement.validate_down_payment(1001, 1000)
		vehicle_agreement.validate_down_payment(0, 1000)
		vehicle_agreement.validate_down_payment(1000, 1000)

	def test_financed_amount_never_negative(self):
		with self.assertRaises(ValueError):
			vehicle_agreement.validate_financed_amount(-0.01)
		vehicle_agreement.validate_financed_amount(0)

	def test_party_type_derives_from_direction(self):
		self.assertEqual(
			vehicle_agreement.PARTY_TYPE_BY_DIRECTION["Acquisition"], "Supplier"
		)
		self.assertEqual(
			vehicle_agreement.PARTY_TYPE_BY_DIRECTION["Disposition"], "Customer"
		)


if __name__ == "__main__":
	unittest.main()
