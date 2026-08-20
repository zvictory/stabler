"""The "Pay Remaining" exact-match tolerance, per currency (pure).

`create_payment_entry` refuses a targeted payment whose amount does not equal the
invoice's outstanding. "Equal" needs a tolerance, and the tolerance is NOT a
constant: it is half the smallest unit the currency actually has.

UZS was half a so'm (0.5) here until 2026-08-20, on the reading that the tiyin
left circulation in 1994. The wide tolerance was load-bearing for a reason that
no longer holds: `MoneyInput` rounded UZS input to whole so'm, so a user facing
an outstanding of 38 250 000,40 could not type it — the tolerance existed to
forgive a gap the FORM created. ERPNext stores UZS at precision 2 on every
tenant, the form now accepts kopecks, and so 0,40 stopped being noise and went
back to being forty kopecks of unpaid invoice.

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

	def test_uzs_rejects_a_forty_kopeck_deviation(self):
		"""Was tolerated while the form could not type kopecks; is a gap now.

		This is the assertion that flipped, and it is the whole point of the
		change: 0,40 so'm is representable in the ledger and therefore is unpaid
		invoice, not rounding. The user can now enter it, because `MoneyInput`
		stopped rounding UZS to whole units.
		"""
		self.assertTrue(_rejected(38_250_000.4, 38_250_000.0, "UZS"))

	def test_uzs_tolerates_sub_kopeck_float_dust(self):
		"""The reason a tolerance exists at all, at UZS's real precision.

		Without this the flip above could be satisfied by refusing everything,
		and float dust over allocation rows would block payments that match to
		the kopeck.
		"""
		self.assertFalse(_rejected(38_250_000.004, 38_250_000.0, "UZS"))

	def test_uzs_still_rejects_a_whole_som_deviation(self):
		"""One so'm IS representable in UZS, so it is a gap, not noise."""
		self.assertTrue(_rejected(38_250_001.0, 38_250_000.0, "UZS"))

	def test_unknown_currency_falls_back_to_half_a_cent(self):
		self.assertEqual(money_epsilon(None), 0.005)
		self.assertEqual(money_epsilon("USD"), 0.005)
		self.assertEqual(money_epsilon("UZS"), 0.005)


if __name__ == "__main__":
	unittest.main()
