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
