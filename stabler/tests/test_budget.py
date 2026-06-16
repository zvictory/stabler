"""Unit tests for the pure budget-variance helpers (no Frappe, no DB)."""
from __future__ import annotations

import unittest
from decimal import Decimal

from stabler.api._budget import compute_variance, compute_variance_report


class VarianceSignTest(unittest.TestCase):
	"""Favorable/unfavorable depends on account_type and variance sign."""

	# --- Expense / cost accounts ---
	def test_expense_actual_under_budget_is_favorable(self):
		r = compute_variance(budget=10000, actual=8000, account_type="Expense")
		self.assertEqual(r["variance"], Decimal("-2000.00"))
		self.assertEqual(r["status"], "favorable")

	def test_expense_actual_over_budget_is_unfavorable(self):
		r = compute_variance(budget=10000, actual=12000, account_type="Expense")
		self.assertEqual(r["variance"], Decimal("2000.00"))
		self.assertEqual(r["status"], "unfavorable")

	def test_expense_on_budget_exactly(self):
		r = compute_variance(budget=5000, actual=5000, account_type="Expense")
		self.assertEqual(r["variance"], Decimal("0.00"))
		self.assertEqual(r["status"], "on_budget")

	# --- Income / revenue accounts ---
	def test_income_actual_over_budget_is_favorable(self):
		r = compute_variance(budget=10000, actual=12000, account_type="Income")
		self.assertEqual(r["status"], "favorable")
		self.assertGreater(r["variance"], 0)

	def test_income_actual_under_budget_is_unfavorable(self):
		r = compute_variance(budget=10000, actual=8000, account_type="Income")
		self.assertEqual(r["status"], "unfavorable")
		self.assertLess(r["variance"], 0)

	def test_revenue_alias_treated_as_income(self):
		r = compute_variance(budget=10000, actual=12000, account_type="revenue")
		self.assertEqual(r["status"], "favorable")

	def test_income_case_insensitive(self):
		r = compute_variance(budget=10000, actual=12000, account_type="INCOME")
		self.assertEqual(r["status"], "favorable")


class NegativeVarianceTest(unittest.TestCase):
	def test_negative_actual_expense(self):
		# Rare but possible: refund / credit brings actuals negative
		r = compute_variance(budget=5000, actual=-500, account_type="Expense")
		self.assertEqual(r["variance"], Decimal("-5500.00"))
		self.assertEqual(r["status"], "favorable")

	def test_negative_budget_expense(self):
		# Negative budget is unusual but must not crash
		r = compute_variance(budget=-1000, actual=0, account_type="Expense")
		self.assertIsInstance(r["variance"], Decimal)

	def test_zero_actual_zero_budget(self):
		r = compute_variance(budget=0, actual=0)
		self.assertEqual(r["variance"], Decimal("0.00"))
		self.assertIsNone(r["variance_pct"])
		self.assertEqual(r["status"], "on_budget")


class DivideByZeroTest(unittest.TestCase):
	def test_zero_budget_variance_pct_is_none(self):
		r = compute_variance(budget=0, actual=5000, account_type="Expense")
		self.assertIsNone(r["variance_pct"])
		self.assertEqual(r["variance"], Decimal("5000.00"))
		self.assertEqual(r["status"], "unfavorable")

	def test_zero_budget_zero_actual_pct_is_none(self):
		r = compute_variance(budget=0, actual=0)
		self.assertIsNone(r["variance_pct"])


class VariancePctTest(unittest.TestCase):
	def test_pct_computed_correctly(self):
		r = compute_variance(budget=10000, actual=12000)
		# variance = 2000, pct = 20.00%
		self.assertEqual(r["variance_pct"], Decimal("20.00"))

	def test_negative_pct(self):
		r = compute_variance(budget=10000, actual=8000)
		self.assertEqual(r["variance_pct"], Decimal("-20.00"))

	def test_fractional_pct_rounded_two_dp(self):
		r = compute_variance(budget=3, actual=4, precision=2)
		# variance = 1, pct = 33.33...% -> 33.33
		self.assertEqual(r["variance_pct"], Decimal("33.33"))


class PrecisionTest(unittest.TestCase):
	def test_uzs_precision_zero_dp(self):
		r = compute_variance(budget=10000000, actual=9999999, account_type="Expense", precision=0)
		self.assertEqual(r["variance"], Decimal("-1"))
		self.assertEqual(r["budget"], Decimal("10000000"))

	def test_kwd_precision_three_dp(self):
		r = compute_variance(budget="1000.000", actual="999.001", precision=3)
		self.assertEqual(r["variance"], Decimal("-0.999"))


class GarbageInputTest(unittest.TestCase):
	def test_none_inputs_do_not_crash(self):
		r = compute_variance(budget=None, actual=None)
		self.assertEqual(r["budget"], Decimal("0.00"))
		self.assertEqual(r["actual"], Decimal("0.00"))
		self.assertEqual(r["variance"], Decimal("0.00"))
		self.assertEqual(r["status"], "on_budget")

	def test_string_garbage_treated_as_zero(self):
		r = compute_variance(budget="bad", actual="N/A")
		self.assertEqual(r["variance"], Decimal("0.00"))

	def test_empty_string_treated_as_zero(self):
		r = compute_variance(budget="", actual="")
		self.assertEqual(r["variance"], Decimal("0.00"))

	def test_unknown_account_type_defaults_to_cost_convention(self):
		# Unknown type -> cost convention -> underspend = favorable
		r = compute_variance(budget=10000, actual=8000, account_type="Asset")
		self.assertEqual(r["status"], "favorable")


class ReportTest(unittest.TestCase):
	def test_empty_rows(self):
		result = compute_variance_report([])
		self.assertEqual(result["rows"], [])
		self.assertEqual(result["totals"]["budget"], Decimal("0"))
		self.assertEqual(result["favorable_count"], 0)

	def test_mixed_rows_counts(self):
		# Sales: Income, actual 120k > 100k -> favorable
		# Rent: Expense, actual 12k > 10k -> unfavorable
		# Wages: Expense, actual 50k == 50k -> on_budget
		rows = [
			{"account": "4100 - Sales", "period": "2026-01", "budget": 100000, "actual": 120000, "account_type": "Income"},
			{"account": "5100 - Rent",  "period": "2026-01", "budget":  10000, "actual":  12000, "account_type": "Expense"},
			{"account": "5200 - Wages", "period": "2026-01", "budget":  50000, "actual":  50000, "account_type": "Expense"},
		]
		result = compute_variance_report(rows)
		self.assertEqual(result["favorable_count"], 1)
		self.assertEqual(result["unfavorable_count"], 1)
		self.assertEqual(result["on_budget_count"], 1)

	def test_totals_aggregated(self):
		rows = [
			{"account": "A", "budget": 1000, "actual": 800, "account_type": "Expense"},
			{"account": "B", "budget": 2000, "actual": 2500, "account_type": "Expense"},
		]
		result = compute_variance_report(rows)
		self.assertEqual(result["totals"]["budget"], Decimal("3000.00"))
		self.assertEqual(result["totals"]["actual"], Decimal("3300.00"))
		self.assertEqual(result["totals"]["variance"], Decimal("300.00"))

	def test_passthrough_fields_preserved(self):
		rows = [
			{"account": "5100 - Rent", "cost_center": "HQ", "period": "Q1",
			 "budget": 10000, "actual": 9000, "account_type": "Expense"},
		]
		result = compute_variance_report(rows)
		row = result["rows"][0]
		self.assertEqual(row["account"], "5100 - Rent")
		self.assertEqual(row["cost_center"], "HQ")
		self.assertEqual(row["period"], "Q1")

	def test_garbage_rows_do_not_crash(self):
		rows = [
			{"account": "X", "budget": None, "actual": "bad", "account_type": None},
		]
		result = compute_variance_report(rows)
		self.assertEqual(len(result["rows"]), 1)
		self.assertEqual(result["rows"][0]["variance"], Decimal("0.00"))

	def test_all_favorable(self):
		rows = [
			{"account": "A", "budget": 10000, "actual": 8000, "account_type": "Expense"},
			{"account": "B", "budget": 5000, "actual": 4000, "account_type": "Expense"},
		]
		result = compute_variance_report(rows)
		self.assertEqual(result["favorable_count"], 2)
		self.assertEqual(result["unfavorable_count"], 0)

	def test_negative_budget_does_not_crash(self):
		rows = [
			{"account": "A", "budget": -1000, "actual": 0, "account_type": "Expense"},
		]
		result = compute_variance_report(rows)
		self.assertEqual(len(result["rows"]), 1)

	def test_large_uzs_amounts_precision_zero(self):
		rows = [
			{"account": "5100", "budget": 100_000_000, "actual": 98_500_000,
			 "account_type": "Expense", "precision": 0},
		]
		# precision must come through compute_variance_report's precision param
		result = compute_variance_report(rows, precision=0)
		self.assertEqual(result["totals"]["variance"], Decimal("-1500000"))


if __name__ == "__main__":
	unittest.main()
