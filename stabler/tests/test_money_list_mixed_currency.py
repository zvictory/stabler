"""The Amount column of /money/expenses and /money/transfers, against a real ledger.

``test_money_list_currency`` pins the same rule bench-free, by handing
``list_bank_entries`` canned rows. That proves the decision; it cannot prove the
*premises* the decision rests on, all of which are claims about what ERPNext
actually stores on a Journal Entry:

* ``credit_in_account_currency`` is denominated in the LEG's currency, so summing
  it across legs of different currencies really does add unlike units;
* ``credit`` is ERPNext's own translation of that leg into the company currency,
  so summing THAT across the same legs really is a figure that can be produced
  honestly;
* ``stabler.api.fx_balance`` really does append its rounding leg to
  ``accounts`` with ``user_remark = 'fx-rounding-auto'``, in the company
  currency, on a document the SPA saves normally — which is what turned
  single-currency expenses into mixed ones (council finding P0-MONEY-1).

So this module builds the vouchers for real and reads the list back. Every
fixture is created by the test and rolled back in ``tearDown``; nothing existing
is mutated and ``frappe.db.commit()`` is never called. A missing fixture skips
with a reason, but the call under test is never inside a skip — a real failure
has to fail loudly.

    bench --site <site> run-tests --module stabler.tests.test_money_list_mixed_currency
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import nowdate

from stabler.api import money as money_api
from stabler.api.fx_balance import _JE_MARKER

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

#: 1 USD in so'm, near enough to the real rate for the arithmetic below to read
#: like money. Exact by construction: 100 * 12 335 = 1 233 500 with no residual,
#: so the mixed-currency case is not accidentally also a rounding case.
RATE = 12_335.0


def _leaf(company: str, **filters) -> str | None:
	filters.update({"company": company, "is_group": 0, "disabled": 0})
	return frappe.db.get_value("Account", filters, "name")


class BankEntryListAmountTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")

	def setUp(self):
		if not self.company:
			self.skipTest("no Company fixture available")
		self.base_currency = frappe.db.get_value("Company", self.company, "default_currency")
		if not self.base_currency:
			self.skipTest("company has no default currency")

		self.base_cash = _leaf(self.company, account_type="Cash", account_currency=self.base_currency)
		if not self.base_cash:
			self.skipTest(f"no leaf Cash account in {self.base_currency}")

		# Any leaf account whose currency is NOT the company's. `fixtures.py`
		# seeds `_Test FX Account` (USD) precisely so a non-base leg exists.
		self.fx_account = frappe.db.get_value(
			"Account",
			{
				"company": self.company,
				"is_group": 0,
				"disabled": 0,
				"account_currency": ("!=", self.base_currency),
			},
			["name", "account_currency"],
			as_dict=True,
		)
		if not self.fx_account:
			self.skipTest("no leaf account in a currency other than the company's")

		self.expense = _leaf(self.company, root_type="Expense", account_currency=self.base_currency)
		if not self.expense:
			self.skipTest(f"no leaf Expense account in {self.base_currency}")

	def tearDown(self):
		frappe.db.rollback()

	# -- fixtures ---------------------------------------------------------

	def _bank_entry(self, legs: list[dict], *, multi_currency: int, resave: bool = False) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Bank Entry",
				"company": self.company,
				"posting_date": nowdate(),
				"multi_currency": multi_currency,
				"user_remark": f"list-amount test {frappe.generate_hash(length=6)}",
				"accounts": legs,
			}
		)
		doc.insert(ignore_permissions=True)
		if resave:
			# THE RESIDUAL CANNOT EXIST BEFORE THE SECOND SAVE, and that is a
			# property of the framework, not of the tolerance.
			#
			# `fx_balance` is registered on `before_validate` (hooks.py), which
			# frappe runs ONCE per save and BEFORE `validate`
			# (frappe/model/document.py:run_before_save_methods). ERPNext fills
			# the company-currency columns `debit`/`credit` inside `validate`, in
			# `set_amounts_in_company_currency` (journal_entry.py:977). So on the
			# insert of a document built the way the SPA builds one — only
			# `*_in_account_currency` set — `_balance_journal_entry` calls
			# `set_total_debit_credit()`, which sums those still-empty base
			# columns to 0 and 0, finds `diff == 0`, and returns at
			# `if not diff` long before it reaches the tolerance check.
			#
			# Nothing is wrong with that in production: ERPNext only enforces the
			# balance in `before_submit` (journal_entry.py:196-200), never in
			# `validate`, and every Stabler path submits on a LATER save
			# (`doc.insert()` then `doc.submit()`), by which time the base columns
			# are populated and the residual is booked. `_balance_payment_entry`
			# documents the same ordering for its own doctype.
			#
			# A test that saves once therefore observes a voucher that never had a
			# residual, and its exclusion assertion passes for no reason. Saving
			# again is what production does, not a trick to provoke the hook.
			doc = frappe.get_doc("Journal Entry", doc.name)
			doc.save(ignore_permissions=True)
		return doc.name

	def _row(self, name: str) -> dict:
		rows = money_api.list_bank_entries(
			company=self.company,
			from_date=nowdate(),
			to_date=nowdate(),
			limit=500,
			entry_type="All",
		)
		for row in rows:
			if row["name"] == name:
				return row
		self.fail(f"{name} is missing from list_bank_entries — the list cannot describe it at all")

	# -- a voucher whose credit side genuinely spans two currencies -------

	def _mixed_voucher(self) -> str:
		"""1 000 000 so'm out of the cash desk AND $100 out of the FX account.

		Both are credits, in different currencies, on one voucher. There is no
		single-currency total here — which is the whole point.
		"""
		fx_base = 100.0 * RATE
		return self._bank_entry(
			[
				{
					"account": self.expense,
					"debit_in_account_currency": 1_000_000.0 + fx_base,
					"exchange_rate": 1.0,
				},
				{
					"account": self.base_cash,
					"credit_in_account_currency": 1_000_000.0,
					"exchange_rate": 1.0,
				},
				{
					"account": self.fx_account.name,
					"credit_in_account_currency": 100.0,
					"exchange_rate": RATE,
				},
			],
			multi_currency=1,
		)

	def test_the_two_credit_legs_are_not_added_as_if_they_were_one_currency(self):
		# 1 000 000 + 100 = 1 000 100 was what `SUM(credit_in_account_currency)`
		# returned. It is not so'm, it is not dollars, and the column then put a
		# currency symbol in front of it.
		row = self._row(self._mixed_voucher())

		self.assertNotEqual(row["total_amount"], 1_000_100.0)

	def test_a_mixed_voucher_reports_the_base_total_erpnext_itself_computed(self):
		# The honest figure, and this is the assertion that proves the premise:
		# the per-leg `credit` column really is the company-currency translation,
		# so its sum matches the document's own `total_credit`. If ERPNext ever
		# stored something else there, the base equivalent would be a second
		# invented number and this test would say so.
		name = self._mixed_voucher()
		row = self._row(name)

		self.assertEqual(row["currency"], self.base_currency)
		self.assertEqual(row["amount_is_base_equivalent"], 1)
		self.assertAlmostEqual(
			row["total_amount"],
			frappe.db.get_value("Journal Entry", name, "total_credit"),
			places=2,
		)

	# -- the synthetic leg fx_balance books ------------------------------

	def test_the_auto_rounding_leg_is_not_counted_as_money_anybody_spent(self):
		"""The council's own example, provoked rather than simulated.

		The debit side is one so'm-hundredth larger than the translated credit
		side, which is a rounding residual: `fx_balance` closes it with a leg in
		the COMPANY currency, on the credit side. The voucher now has a $100 leg
		and a 0,01 so'm leg both credited, and the old column summed them into
		100.01 and labelled it with whichever the storage engine returned first.

		Saved twice on purpose — see `_bank_entry`: the hook runs at
		`before_validate`, so the base-currency columns it needs do not exist
		yet on the first save and no residual can be booked then.
		"""
		if not (
			frappe.get_cached_value("Company", self.company, "exchange_gain_loss_account")
			or frappe.get_cached_value("Company", self.company, "round_off_account")
		):
			self.skipTest("company has no exchange gain/loss or round-off account to book a residual to")

		name = self._bank_entry(
			[
				{
					"account": self.expense,
					"debit_in_account_currency": 100.0 * RATE + 0.01,
					"exchange_rate": 1.0,
				},
				{
					"account": self.fx_account.name,
					"credit_in_account_currency": 100.0,
					"exchange_rate": RATE,
				},
			],
			multi_currency=1,
			resave=True,
		)

		# Asserted, never skipped. This is the only check on the DB path that the
		# exclusion rule protects anything, so a voucher that turned out to carry
		# no residual must fail here rather than quietly excuse itself — that is
		# how the first version of this test reported OK while proving nothing.
		remarks = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": name},
			pluck="user_remark",
		)
		self.assertIn(
			_JE_MARKER,
			remarks,
			"fx_balance booked no residual, so the exclusion below would pass for the wrong reason",
		)

		row = self._row(name)

		self.assertEqual(row["total_amount"], 100.0)
		self.assertEqual(row["currency"], self.fx_account.account_currency)
		self.assertEqual(row["amount_is_base_equivalent"], 0)

	# -- the ordinary voucher must be left alone -------------------------

	def test_a_single_currency_voucher_still_reports_its_own_amount(self):
		# A fix that answered "base equivalent" for everything would never mix
		# currencies and would still be a worse screen than the bug.
		name = self._bank_entry(
			[
				{"account": self.expense, "debit_in_account_currency": 1_000_000.0},
				{"account": self.base_cash, "credit_in_account_currency": 1_000_000.0},
			],
			multi_currency=0,
		)

		row = self._row(name)

		self.assertEqual(row["total_amount"], 1_000_000.0)
		self.assertEqual(row["currency"], self.base_currency)
		self.assertEqual(row["amount_is_base_equivalent"], 0)


if __name__ == "__main__":
	unittest.main()
