"""The "Pay Remaining" exact-match tolerance, per currency (pure).

`create_payment_entry` refuses a targeted payment whose amount does not equal the
invoice's outstanding. "Equal" needs a tolerance, and the tolerance is NOT a
constant: it is half the smallest unit the currency actually has. USD has a cent,
so half a cent (0.005) is noise. UZS has had no tiyin in circulation since 1994,
so its smallest unit is one so'm and half a so'm (0.5) is noise — a hardcoded
0.01 rejected legitimate sub-so'm rounding on every UZS invoice.

Frappe-free: the rule under test is `money_epsilon`, and the guard is a plain
`abs(a - b) > eps` comparison, so both sides are asserted here without booting a
site. `money.py` and `composables/money.js` must both use this same rule.
"""

from __future__ import annotations

import unittest

from stabler.api._money import money_epsilon


def _rejected(entered: float, outstanding: float, currency: str) -> bool:
	"""Mirrors the guard in `money.py:create_payment_entry`."""
	return abs(entered - outstanding) > money_epsilon(currency)


class PayRemainingToleranceTest(unittest.TestCase):
	def test_usd_rejects_a_one_cent_deviation(self):
		"""A cent is a real amount in USD — never rounding noise."""
		self.assertTrue(_rejected(1000.01, 1000.00, "USD"))
		self.assertTrue(_rejected(999.99, 1000.00, "USD"))

	def test_usd_tolerates_sub_cent_float_dust(self):
		"""Float arithmetic over allocation rows leaves dust below half a cent."""
		self.assertFalse(_rejected(1000.004, 1000.00, "USD"))

	def test_uzs_tolerates_sub_som_rounding(self):
		"""The old hardcoded 0.01 rejected this and blocked real UZS payments."""
		self.assertFalse(_rejected(38_250_000.4, 38_250_000.0, "UZS"))

	def test_uzs_still_rejects_a_whole_som_deviation(self):
		"""One so'm IS representable in UZS, so it is a gap, not noise."""
		self.assertTrue(_rejected(38_250_001.0, 38_250_000.0, "UZS"))

	def test_unknown_currency_falls_back_to_half_a_cent(self):
		self.assertEqual(money_epsilon(None), 0.005)
		self.assertEqual(money_epsilon("USD"), 0.005)
		self.assertEqual(money_epsilon("UZS"), 0.5)


if __name__ == "__main__":
	unittest.main()
