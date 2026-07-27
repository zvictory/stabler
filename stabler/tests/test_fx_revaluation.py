"""Unit tests for the pure FX-revaluation helpers (no Frappe, no DB)."""

from __future__ import annotations

import unittest
from decimal import Decimal

from stabler.api._fx_revaluation import compute_fx_delta, summarize_revaluation


class GainLossSignTest(unittest.TestCase):
	def test_rate_rose_debit_asset_is_gain(self):
		r = compute_fx_delta(
			balance_in_account_ccy=1000,
			new_rate=12500,
			book_rate=12000,
			precision=0,
		)
		self.assertEqual(r["gain_loss"], "gain")
		self.assertEqual(r["delta"], Decimal("500000"))

	def test_rate_fell_debit_asset_is_loss(self):
		r = compute_fx_delta(
			balance_in_account_ccy=1000,
			new_rate=11500,
			book_rate=12000,
			precision=0,
		)
		self.assertEqual(r["gain_loss"], "loss")
		self.assertEqual(r["delta"], Decimal("-500000"))

	def test_rate_unchanged_is_nil(self):
		r = compute_fx_delta(
			balance_in_account_ccy=500,
			new_rate=12000,
			book_rate=12000,
			precision=0,
		)
		self.assertEqual(r["gain_loss"], "nil")
		self.assertEqual(r["delta"], Decimal("0"))

	def test_negative_balance_liability_rate_rose_is_loss(self):
		r = compute_fx_delta(
			balance_in_account_ccy=-1000,
			new_rate=12500,
			book_rate=12000,
			precision=0,
		)
		self.assertEqual(r["gain_loss"], "loss")
		self.assertLess(r["delta"], 0)


class ZeroInputTest(unittest.TestCase):
	def test_zero_book_rate_first_revaluation(self):
		r = compute_fx_delta(
			balance_in_account_ccy=500,
			new_rate=12000,
			book_rate=0,
			precision=0,
		)
		self.assertEqual(r["delta"], Decimal("6000000"))
		self.assertEqual(r["gain_loss"], "gain")

	def test_zero_new_rate_missing_market_rate(self):
		r = compute_fx_delta(
			balance_in_account_ccy=500,
			new_rate=0,
			book_rate=12000,
			precision=0,
		)
		self.assertEqual(r["delta"], Decimal("-6000000"))
		self.assertEqual(r["gain_loss"], "loss")

	def test_zero_balance_no_position(self):
		r = compute_fx_delta(
			balance_in_account_ccy=0,
			new_rate=12500,
			book_rate=12000,
			precision=0,
		)
		self.assertEqual(r["delta"], Decimal("0"))
		self.assertEqual(r["gain_loss"], "nil")

	def test_both_rates_zero(self):
		r = compute_fx_delta(
			balance_in_account_ccy=1000,
			new_rate=0,
			book_rate=0,
			precision=0,
		)
		self.assertEqual(r["delta"], Decimal("0"))
		self.assertEqual(r["gain_loss"], "nil")


class PrecisionTest(unittest.TestCase):
	def test_uzs_precision_zero_dp(self):
		r = compute_fx_delta(
			balance_in_account_ccy="123.456",
			new_rate="12345.678901",
			book_rate="12000.000000",
			precision=0,
		)
		self.assertIsInstance(r["delta"], Decimal)
		# delta must be integer-rounded (0 dp)
		self.assertEqual(r["delta"], r["delta"].to_integral_value())

	def test_usd_precision_two_dp(self):
		r = compute_fx_delta(
			balance_in_account_ccy=100,
			new_rate="1.234567",
			book_rate="1.234000",
			precision=2,
		)
		# delta = 100 * 0.000567 = 0.0567 -> rounds to 0.06
		self.assertEqual(r["delta"], Decimal("0.06"))

	def test_kwd_precision_three_dp(self):
		r = compute_fx_delta(
			balance_in_account_ccy=1000,
			new_rate="3.500000",
			book_rate="3.499000",
			precision=3,
		)
		self.assertEqual(r["delta"], Decimal("1.000"))

	def test_rate_carries_six_dp(self):
		r = compute_fx_delta(
			balance_in_account_ccy=1,
			new_rate="12345.678901",
			book_rate="12345.123456",
			precision=0,
		)
		# rate_diff preserved at 6+ dp
		self.assertGreater(abs(r["rate_diff"]), Decimal("0.5"))

	def test_rate_precision_param_respected(self):
		r = compute_fx_delta(
			balance_in_account_ccy=1,
			new_rate="1.12345678",
			book_rate="1.00000000",
			precision=2,
			rate_precision=8,
		)
		self.assertEqual(r["new_rate"], Decimal("1.12345678"))


class GarbageInputTest(unittest.TestCase):
	def test_none_inputs_do_not_crash(self):
		r = compute_fx_delta(
			balance_in_account_ccy=None,
			new_rate=None,
			book_rate=None,
			precision=2,
		)
		self.assertEqual(r["delta"], Decimal("0"))
		self.assertEqual(r["gain_loss"], "nil")

	def test_string_garbage_treated_as_zero(self):
		r = compute_fx_delta(
			balance_in_account_ccy="not-a-number",
			new_rate="N/A",
			book_rate="",
			precision=2,
		)
		self.assertEqual(r["delta"], Decimal("0"))

	def test_empty_string_treated_as_zero(self):
		r = compute_fx_delta(
			balance_in_account_ccy="",
			new_rate="",
			book_rate="",
			precision=0,
		)
		self.assertEqual(r["delta"], Decimal("0"))

	def test_negative_precision_clamped_to_zero(self):
		r = compute_fx_delta(
			balance_in_account_ccy=1000,
			new_rate=12500,
			book_rate=12000,
			precision=-3,
		)
		self.assertIsInstance(r["delta"], Decimal)


class SummarizeTest(unittest.TestCase):
	def test_empty_rows(self):
		s = summarize_revaluation([])
		self.assertEqual(s["net_delta"], Decimal("0"))
		self.assertEqual(s["rows"], [])

	def test_gains_and_losses_totalled_correctly(self):
		rows = [
			{
				"account": "1210 - USD Receivables",
				"currency": "USD",
				"balance_in_account_ccy": 1000,
				"new_rate": 12500,
				"book_rate": 12000,
			},
			{
				"account": "2110 - USD Payables",
				"currency": "USD",
				"balance_in_account_ccy": -500,
				"new_rate": 12500,
				"book_rate": 12000,
			},
		]
		s = summarize_revaluation(rows, base_precision=0)
		self.assertEqual(s["total_gain"], Decimal("500000"))
		self.assertEqual(s["total_loss"], Decimal("-250000"))
		self.assertEqual(s["net_delta"], Decimal("250000"))

	def test_all_gains(self):
		rows = [
			{
				"account": "A",
				"currency": "USD",
				"balance_in_account_ccy": 100,
				"new_rate": 12500,
				"book_rate": 12000,
			},
			{
				"account": "B",
				"currency": "EUR",
				"balance_in_account_ccy": 200,
				"new_rate": 13000,
				"book_rate": 12800,
			},
		]
		s = summarize_revaluation(rows, base_precision=0)
		self.assertGreater(s["total_gain"], 0)
		self.assertEqual(s["total_loss"], Decimal("0"))
		self.assertGreater(s["net_delta"], 0)

	def test_all_losses(self):
		rows = [
			{
				"account": "A",
				"currency": "USD",
				"balance_in_account_ccy": 100,
				"new_rate": 11000,
				"book_rate": 12000,
			},
		]
		s = summarize_revaluation(rows, base_precision=0)
		self.assertEqual(s["total_gain"], Decimal("0"))
		self.assertLess(s["total_loss"], 0)
		self.assertLess(s["net_delta"], 0)

	def test_per_row_account_passthrough(self):
		rows = [
			{
				"account": "1210 - Cash USD",
				"currency": "USD",
				"balance_in_account_ccy": 500,
				"new_rate": 12500,
				"book_rate": 12000,
			},
		]
		s = summarize_revaluation(rows, base_precision=0)
		self.assertEqual(s["rows"][0]["account"], "1210 - Cash USD")
		self.assertEqual(s["rows"][0]["currency"], "USD")

	def test_garbage_row_does_not_crash(self):
		rows = [
			{
				"account": "",
				"currency": None,
				"balance_in_account_ccy": None,
				"new_rate": None,
				"book_rate": "bad",
			},
		]
		s = summarize_revaluation(rows, base_precision=0)
		self.assertEqual(s["net_delta"], Decimal("0"))


if __name__ == "__main__":
	unittest.main()
