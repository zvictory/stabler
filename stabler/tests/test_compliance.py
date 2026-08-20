from __future__ import annotations

import unittest

import frappe

from stabler.api.compliance import gl_integrity_scan


class TestComplianceGLIntegrity(unittest.TestCase):
	def setUp(self) -> None:
		# Şirket adına bağlanmıyoruz: "ANJAN" sabiti bu testi tek bir kiracının
		# verisine bağlıyordu ve test sitesinde hep atlanıyordu.
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no Company fixture available")
		self.base_currency = frappe.db.get_value("Company", self.company, "default_currency")
		self.gle_names = []

	def tearDown(self) -> None:
		for name in self.gle_names:
			frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", (name,))
		frappe.db.commit()

	def test_gl_integrity_scan_detects_d2_posting(self) -> None:
		# D2 kuralı `acc.account_currency <> c.default_currency` üzerinden çalışır,
		# dolayısıyla aradığımız şey "USD olmayan" değil, "şirketin tabanı olmayan"
		# bir hesap (ör. UZS tabanlı şirkette USD kasası).
		non_base_acc, non_base_currency = frappe.db.get_value(
			"Account",
			{
				"company": self.company,
				"account_currency": ["!=", self.base_currency],
				"is_group": 0,
			},
			["name", "account_currency"],
		) or (None, None)
		if not non_base_acc:
			self.skipTest("No non-base currency account found for testing")

		# Initial scan
		init_res = gl_integrity_scan(self.company)

		# Insert 1:1 posting
		name = "TEST-GLE-D2-01"
		self.gle_names.append(name)
		frappe.db.sql(
			"""
			INSERT INTO `tabGL Entry` (
				name, company, account, account_currency, debit, debit_in_account_currency,
				credit, credit_in_account_currency, is_cancelled, posting_date
			)
			VALUES (%s, %s, %s, %s, 100.0, 100.0, 0.0, 0.0, 0, '2026-06-13')
			""",
			(name, self.company, non_base_acc, non_base_currency),
		)
		frappe.db.commit()

		new_res = gl_integrity_scan(self.company)
		self.assertEqual(new_res["d2_postings"], init_res["d2_postings"] + 1)

	def test_gl_integrity_scan_detects_wrong_account_type(self) -> None:
		# Find a non-receivable account dynamically
		non_rec_acc = frappe.db.get_value(
			"Account",
			{
				"company": self.company,
				"account_type": ["not in", ["Receivable", "Payable"]],
				"is_group": 0,
			},
			"name",
		)
		if not non_rec_acc:
			self.skipTest("No non-receivable/payable account found for testing")

		# Initial scan
		init_res = gl_integrity_scan(self.company)

		# Insert Customer posting into non-receivable account
		name = "TEST-GLE-WRONG-TYPE-01"
		self.gle_names.append(name)
		frappe.db.sql(
			"""
			INSERT INTO `tabGL Entry` (
				name, company, account, account_currency, debit, debit_in_account_currency,
				credit, credit_in_account_currency, party_type, party, is_cancelled, posting_date
			)
			VALUES (%s, %s, %s, %s, 100.0, 100.0, 0.0, 0.0, 'Customer', 'Test Customer', 0, '2026-06-13')
			""",
			(name, self.company, non_rec_acc, self.base_currency),
		)
		frappe.db.commit()

		new_res = gl_integrity_scan(self.company)
		self.assertEqual(new_res["wrong_account_type_postings"], init_res["wrong_account_type_postings"] + 1)


class TheAlarmMustNotGoBlindWhenTheStoredRateIsZero(unittest.TestCase):
	"""A rate of zero is the loudest anomaly there is, not the absence of one.

	msa carried 363 submitted USD purchase invoices at `conversion_rate = 0`, each
	booking its whole USD value as 0 UZS. `gl_integrity_scan` scores them because
	the Purchase Invoice branch divides by the CBU rate unconditionally and gets a
	100% deviation. The Payment Entry and Journal Entry branches test
	`flt(rate) > 0` first, so the same defect on those doctypes is skipped in
	silence -- and silence from this function is read as "the ledger is clean".

	Raw SQL is the fixture deliberately. ERPNext's own validation will not pass a
	zero rate through `submit()`, so the only way such a row exists is the way it
	actually arose on msa: written underneath the document API. Catching that is
	the entire reason this scan runs nightly.
	"""

	PLANTED = (
		("Journal Entry Account", "TEST-JEA-ZERO-RATE-01"),
		("Journal Entry", "TEST-JE-ZERO-RATE-01"),
		("Payment Entry", "TEST-PE-ZERO-RATE-01"),
		("Currency Exchange", "TEST-FX-ZERO-RATE-01"),
	)
	FX_DATE = "2020-01-01"
	DOC_DATE = "2020-01-15"
	FX_RATE = 12000.0

	def setUp(self) -> None:
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no Company fixture available")
		self.base_currency = frappe.db.get_value("Company", self.company, "default_currency")
		self.account, self.currency = frappe.db.get_value(
			"Account",
			{"company": self.company, "account_currency": ["!=", self.base_currency], "is_group": 0},
			["name", "account_currency"],
		) or (None, None)
		if not self.account:
			self.skipTest("no non-base-currency account to hang a foreign document on")
		self._cleanup()
		# The scan can only judge a rate it has something to compare against, so the
		# comparison rate is planted too rather than borrowed from whatever the site
		# happens to hold.
		frappe.db.sql(
			"""
			INSERT INTO `tabCurrency Exchange` (name, from_currency, to_currency, date, exchange_rate)
			VALUES (%s, %s, %s, %s, %s)
			""",
			("TEST-FX-ZERO-RATE-01", self.currency, self.base_currency, self.FX_DATE, self.FX_RATE),
		)
		frappe.db.commit()

	def tearDown(self) -> None:
		self._cleanup()

	def _cleanup(self) -> None:
		for doctype, name in self.PLANTED:
			frappe.db.sql(f"DELETE FROM `tab{doctype}` WHERE name = %s", (name,))
		frappe.db.commit()

	def test_a_payment_entry_at_a_zero_rate_is_counted(self) -> None:
		before = gl_integrity_scan(self.company)["off_cbu_docs"]
		# One foreign leg only: the receiving side stays in base currency so the
		# assertion counts a single judgement, not an accidental pair.
		frappe.db.sql(
			"""
			INSERT INTO `tabPayment Entry` (
				name, company, docstatus, posting_date,
				paid_from_account_currency, paid_to_account_currency,
				source_exchange_rate, target_exchange_rate
			)
			VALUES (%s, %s, 1, %s, %s, %s, 0.0, 1.0)
			""",
			("TEST-PE-ZERO-RATE-01", self.company, self.DOC_DATE, self.currency, self.base_currency),
		)
		frappe.db.commit()

		after = gl_integrity_scan(self.company)["off_cbu_docs"]
		self.assertEqual(
			after,
			before + 1,
			"a payment booked at 1 {0} = 0 {1} did not register as off-CBU".format(
				self.currency, self.base_currency
			),
		)

	def test_a_journal_line_at_a_zero_rate_is_counted(self) -> None:
		before = gl_integrity_scan(self.company)["off_cbu_docs"]
		frappe.db.sql(
			"""
			INSERT INTO `tabJournal Entry` (name, company, docstatus, posting_date)
			VALUES (%s, %s, 1, %s)
			""",
			("TEST-JE-ZERO-RATE-01", self.company, self.DOC_DATE),
		)
		frappe.db.sql(
			"""
			INSERT INTO `tabJournal Entry Account` (
				name, parent, parenttype, parentfield, account, exchange_rate,
				debit, debit_in_account_currency, credit, credit_in_account_currency
			)
			VALUES (%s, %s, 'Journal Entry', 'accounts', %s, 0.0, 0.0, 100.0, 0.0, 0.0)
			""",
			("TEST-JEA-ZERO-RATE-01", "TEST-JE-ZERO-RATE-01", self.account),
		)
		frappe.db.commit()

		after = gl_integrity_scan(self.company)["off_cbu_docs"]
		self.assertEqual(
			after,
			before + 1,
			"a journal line booked at 1 {0} = 0 {1} did not register as off-CBU".format(
				self.currency, self.base_currency
			),
		)
