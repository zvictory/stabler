"""`base_precision_for` must agree with the precision the site actually stores.

`stabler/api/_fx_residual.py` keeps a hardcoded set of whole-unit currencies and
sizes every FX rounding tolerance from it. That set is a claim about ERPNext's
storage, and ERPNext does not take precision from ISO 4217 — it takes it from
the site: the field's own `precision`, else System Settings `currency_precision`,
else the number format (`frappe/model/meta.py:905-917`).

Nothing checked the claim, and it was wrong. UZS sat in the set on the tiyin
argument (out of circulation since 1994) while every tenant runs
`currency_precision` unset and the global format "#,###.##" — precision 2. So
the tolerance was sized in whole so'm for a quantity recorded to the kopeck: a
3-leg entry tolerated 4,99, which is 499 units at the precision the difference
is measured at. Downstream, `MoneyInput` rounded away what the user typed.

This module is the check that was missing. It is a bench test because the answer
lives in the site's settings, not in the source: the same code is correct on one
site and wrong on another, and only the site can say which.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.model.meta import get_field_precision

from stabler.api._fx_residual import base_precision_for

#: The field every FX residual is ultimately measured against.
_DOCTYPE = "Journal Entry Account"
_FIELDNAME = "debit_in_account_currency"


def _site_precision(currency: str) -> int:
	df = frappe.get_meta(_DOCTYPE).get_field(_FIELDNAME)
	return get_field_precision(df, currency=currency)


class BasePrecisionMatchesTheSite(unittest.TestCase):
	def test_uzs_agrees(self):
		"""The currency this app is actually used in, asserted unconditionally.

		Unconditional on purpose: a module whose every test is skipped reports OK
		while asserting nothing, and `make test-bench` counts that as red. This
		one test is what keeps the module honest on a site with no companies.
		"""
		self.assertEqual(
			base_precision_for("UZS"),
			_site_precision("UZS"),
			"the hardcoded whole-unit set disagrees with what this site stores for UZS",
		)

	def test_usd_agrees(self):
		self.assertEqual(base_precision_for("USD"), _site_precision("USD"))

	def test_every_company_base_currency_agrees(self):
		"""The real surface: whatever the tenants actually book in.

		A currency nobody uses being wrong costs nothing; a company's base
		currency being wrong mis-sizes the tolerance on every Journal Entry and
		Payment Entry that company ever posts.
		"""
		currencies = {
			c.default_currency
			for c in frappe.get_all("Company", fields=["default_currency"])
			if c.default_currency
		}
		if not currencies:
			self.skipTest("no companies on this site")
		for currency in sorted(currencies):
			with self.subTest(currency=currency):
				self.assertEqual(
					base_precision_for(currency),
					_site_precision(currency),
					f"{currency} is a company base currency and the two precisions disagree",
				)


if __name__ == "__main__":
	unittest.main()
