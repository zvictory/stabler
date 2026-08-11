"""Contract tests for the cash-desk (kassa) leg of an Import Expense.

Until 2026-08-11 an Import Expense recorded `cash_payment` / `bank_payment` as
decorative numbers: the expense could read "Paid" while no cash desk had moved a
single so'm. These tests pin the opposite guarantee — a `paid_from_account` means
a real submitted Journal Entry whose credit leg is that desk, and saving the same
expense twice never posts a second voucher.

Every fixture is created by the test itself and rolled back in `tearDown`: no
pre-existing record is mutated and `frappe.db.commit()` is never called. Missing
fixtures skip with a reason so the suite stays green on a bare site — but the
call under test is never wrapped in a skip, so a real posting failure fails loud.

	bench --site <site> run-tests --module stabler.tests.test_import_expense_kasa
"""

from __future__ import annotations

import unittest

import frappe

from stabler.api import imports as imports_api

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase


def _first_company():
	return frappe.db.get_value("Company", {}, "name")


def _first_supplier():
	return frappe.db.get_value("Supplier", {}, "name")


def _kasa_account(company: str):
	"""A leaf cash desk / bank account — the credit leg of the voucher."""
	for account_type in ("Cash", "Bank"):
		name = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": account_type, "is_group": 0, "disabled": 0},
			"name",
		)
		if name:
			return name
	return None


def _expense_leaf(company: str, currency: str):
	"""A leaf Expense account in the desk's currency.

	`money.submit_expense_entry` rejects a line whose account is not `root_type =
	Expense` or whose currency differs from the paying leg, so both filters are
	part of picking the fixture, not an optimisation.
	"""
	return frappe.db.get_value(
		"Account",
		{
			"company": company,
			"root_type": "Expense",
			"is_group": 0,
			"disabled": 0,
			"account_currency": currency,
		},
		"name",
	)


class ImportExpenseKasaTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _first_company()
		cls.supplier = _first_supplier()

	def setUp(self):
		if not self.company:
			self.skipTest("no Company fixture available")
		for dt in ("Commercial Invoice", "Import Expense", "Stabler Settings", "Journal Entry"):
			if not frappe.db.exists("DocType", dt):
				self.skipTest(f"{dt} doctype not present")
		self.kasa = _kasa_account(self.company)
		if not self.kasa:
			self.skipTest("no leaf Cash/Bank account in the test company")
		self.kasa_currency = frappe.db.get_value("Account", self.kasa, "account_currency")
		self.expense_account = _expense_leaf(self.company, self.kasa_currency)
		if not self.expense_account:
			self.skipTest(f"no leaf Expense account in {self.kasa_currency}")
		self._set_imports_enabled(True)
		self.ci = self._new_ci()

	def tearDown(self):
		frappe.db.rollback()

	# -- fixtures ---------------------------------------------------------

	def _set_imports_enabled(self, enabled: bool) -> None:
		settings = frappe.get_single("Stabler Settings")
		row = None
		for r in settings.company_modules or []:
			if r.company == self.company:
				row = r
				break
		if row is None:
			row = settings.append("company_modules", {"company": self.company})
		row.enable_imports = 1 if enabled else 0
		settings.save(ignore_permissions=True)

	def _new_ci(self) -> str:
		if not self.supplier:
			self.skipTest("no Supplier fixture available")
		ci = frappe.get_doc(
			{
				"doctype": "Commercial Invoice",
				"company": self.company,
				"supplier": self.supplier,
				"ci_number": frappe.generate_hash(length=8),
				"ci_date": frappe.utils.today(),
				"currency": self.kasa_currency,
			}
		).insert(ignore_permissions=True)
		return ci.name

	def _cash_expense_values(self, amount: float = 125000.0, **overrides) -> dict:
		values = {
			"commercial_invoice": self.ci,
			"category": "Handling",
			"expense_date": frappe.utils.today(),
			"description": "Kassa contract test",
			"amount": amount,
			"currency": self.kasa_currency,
			"expense_account": self.expense_account,
			"paid_from_account": self.kasa,
		}
		values.update(overrides)
		return values

	# -- the posting ------------------------------------------------------

	def test_cash_desk_expense_posts_a_real_bank_entry(self):
		"""The whole point: the money must actually leave the selected desk."""
		amount = 125000.0
		res = imports_api.create_import_expense(self.company, self._cash_expense_values(amount))

		self.assertTrue(res.get("journal_entry"), "no Journal Entry was posted for a cash-desk expense")
		je = frappe.get_doc("Journal Entry", res["journal_entry"])
		self.assertEqual(je.voucher_type, "Bank Entry")
		self.assertEqual(je.company, self.company)

		credit = [r for r in je.accounts if r.account == self.kasa]
		debit = [r for r in je.accounts if r.account == self.expense_account]
		self.assertEqual(len(credit), 1, "the paying desk must appear exactly once")
		self.assertEqual(len(debit), 1)
		self.assertEqual(frappe.utils.flt(credit[0].credit_in_account_currency), amount)
		self.assertEqual(frappe.utils.flt(debit[0].debit_in_account_currency), amount)

		# The voucher carries the import attribution, so container/CI cost reports
		# can find it later; the custom field is patch-installed, hence the guard.
		if frappe.get_meta("Journal Entry").has_field("custom_commercial_invoice"):
			self.assertEqual(je.custom_commercial_invoice, self.ci)

		expense = frappe.get_doc("Import Expense", res["name"])
		self.assertEqual(expense.journal_entry, res["journal_entry"])
		if res.get("pending_approval"):
			# Routed for approval: no money has moved yet, so the split stays empty.
			self.assertEqual(expense.status, "Pending")
		else:
			self.assertEqual(je.docstatus, 1, "an unrouted expense voucher must be submitted")
			self.assertEqual(expense.status, "Paid")
			is_cash = frappe.db.get_value("Account", self.kasa, "account_type") == "Cash"
			paid = expense.cash_payment if is_cash else expense.bank_payment
			self.assertEqual(frappe.utils.flt(paid), amount)

	def test_second_save_does_not_post_a_second_voucher(self):
		"""`journal_entry` is the idempotency key — re-saving must not double-spend."""
		created = imports_api.create_import_expense(self.company, self._cash_expense_values())
		first_je = created["journal_entry"]
		before = frappe.db.count("Journal Entry")

		updated = imports_api.update_import_expense(
			created["name"],
			{"description": "Kassa contract test (edited)"},
			modified=frappe.db.get_value("Import Expense", created["name"], "modified"),
		)

		self.assertEqual(updated["journal_entry"], first_je)
		self.assertEqual(frappe.db.count("Journal Entry"), before, "a second voucher was posted")

	# -- the mutually exclusive settlement routes -------------------------

	def test_supplier_and_cash_desk_together_are_rejected(self):
		"""Supplier = billed (draft PI); cash desk = paid. Both would bill it twice."""
		with self.assertRaises(frappe.ValidationError):
			imports_api.create_import_expense(self.company, self._cash_expense_values(supplier=self.supplier))

	def test_expense_account_without_a_cash_desk_is_rejected(self):
		"""A debit leg with nothing to credit would post nowhere — catch it early."""
		with self.assertRaises(frappe.ValidationError):
			imports_api.create_import_expense(self.company, self._cash_expense_values(paid_from_account=None))

	def test_cash_desk_without_an_expense_account_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			imports_api.create_import_expense(self.company, self._cash_expense_values(expense_account=None))

	def test_currency_other_than_the_desk_currency_is_rejected(self):
		"""money.submit_expense_entry throws too; here the message names the field."""
		other = "EUR" if self.kasa_currency != "EUR" else "USD"
		with self.assertRaises(frappe.ValidationError):
			imports_api.create_import_expense(self.company, self._cash_expense_values(currency=other))


if __name__ == "__main__":
	unittest.main()
