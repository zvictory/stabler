"""Kesim tarihi gerçek bir defteri gerçekten kesiyor mu — ve nereden kesiyor?

`test_customer_balance_as_of_source.py` sınırın *her* GL toplamasına yazıldığını
kaynaktan kanıtlar. Kanıtlayamadığı iki şey var, ikisi de ancak canlı bir defterde
görünür:

* sınır gerçekten süzüyor mu (f-string'e çevrilen sorgular derleniyor, parametre
  bağlanıyor, `posting_date` karşılaştırması tutuyor);
* sınır **kapsayıcı** mı. `<` ile `<=` arasındaki fark, "30 Haziran itibarıyla"
  cümlesinin 30 Haziran'ı içerip içermemesidir. Bir gün, bir günlük ciro; ve
  yanlış tarafta durduğunda hiçbir şey hata vermez — rapor sadece başka bir
  rakam gösterir. Bu yüzden kesim gününe ayrı bir kalem konur.

Üç kalem, tek müşteri: kesimden önce, tam kesim gününde, kesimden sonra. Ölçüm
farkla yapılır (öncesi/sonrası), böylece test sitesinde müşterinin hâlihazırda
bir bakiyesi olması sonucu bozmaz.

Sapma düzeltmesi (`drift`) yalnız Payment Entry'lere bakar; buradaki kalemler
Sales Invoice olduğu için o terim bu testte sıfırdır. Onun da sınırı taşıdığını
kaynak testi ayrıca güvence altına alır.
"""

from __future__ import annotations

import unittest

import frappe

from stabler.api.sales import list_customers_with_balances

CUTOFF = "2026-06-30"
BEFORE = ("2026-06-01", 100.0)
ON_CUTOFF = (CUTOFF, 40.0)
AFTER = ("2026-07-15", 250.0)


class TestCustomerBalanceAsOfBench(unittest.TestCase):
	def setUp(self) -> None:
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no Company fixture available")
		self.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		if not self.customer:
			self.skipTest("no Customer fixture available")
		row = frappe.db.get_value(
			"Account",
			{"company": self.company, "account_type": "Receivable", "is_group": 0},
			["name", "account_currency"],
		)
		if not row:
			self.skipTest("no receivable account for this company")
		self.account, self.account_currency = row
		self.gle_names: list[str] = []

	def tearDown(self) -> None:
		for name in self.gle_names:
			frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", (name,))
		frappe.db.commit()

	def _post(self, tag: str, posting_date: str, amount: float) -> None:
		name = f"TEST-GLE-ASOF-{tag}"
		self.gle_names.append(name)
		frappe.db.sql(
			"""
			INSERT INTO `tabGL Entry` (
				name, company, account, account_currency, party_type, party,
				voucher_type, voucher_no, debit, debit_in_account_currency,
				credit, credit_in_account_currency, is_cancelled, posting_date
			)
			VALUES (%s, %s, %s, %s, 'Customer', %s, 'Sales Invoice', %s,
			        %s, %s, 0.0, 0.0, 0, %s)
			""",
			(
				name,
				self.company,
				self.account,
				self.account_currency,
				self.customer,
				name,
				amount,
				amount,
				posting_date,
			),
		)
		frappe.db.commit()

	def _balance(self, as_of: str | None) -> tuple[float, float]:
		data = list_customers_with_balances(self.company, limit=10000, as_of=as_of)
		for r in data.get("rows", []):
			if r.get("name") == self.customer:
				return float(r.get("balance_base") or 0), float(r.get("balance_acc") or 0)
		self.fail(f"{self.customer} missing from the balance list")

	def test_the_cutoff_excludes_later_postings_and_keeps_the_cutoff_day(self):
		"""Kesim günü içeride, ertesi gün dışarıda — aradaki fark bir günlük cirodur."""
		all_before = self._balance(None)
		cut_before = self._balance(CUTOFF)

		self._post("BEFORE", *BEFORE)
		self._post("ONDAY", *ON_CUTOFF)
		self._post("AFTER", *AFTER)

		all_after = self._balance(None)
		cut_after = self._balance(CUTOFF)

		everything = BEFORE[1] + ON_CUTOFF[1] + AFTER[1]
		up_to_cutoff = BEFORE[1] + ON_CUTOFF[1]

		for i, axis in enumerate(("balance_base", "balance_acc")):
			with self.subTest(axis=axis):
				self.assertAlmostEqual(
					everything,
					all_after[i] - all_before[i],
					places=2,
					msg=f"{axis}: the unbounded balance must still see every posting",
				)
				self.assertAlmostEqual(
					up_to_cutoff,
					cut_after[i] - cut_before[i],
					places=2,
					msg=(
						f"{axis}: as of {CUTOFF} the balance must include the posting made ON "
						f"{CUTOFF} and exclude the one made on {AFTER[0]}"
					),
				)

	def test_overdue_is_refused_under_a_cutoff(self):
		"""Geçmiş bir tarihe gecikme uydurmaktansa cevap vermemek."""
		with self.assertRaises(frappe.ValidationError):
			list_customers_with_balances(self.company, as_of=CUTOFF, only_overdue=1)


if __name__ == "__main__":
	unittest.main()
