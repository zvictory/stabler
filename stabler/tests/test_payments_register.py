"""Payments Register raporunun USD sütunu — bench-only entegrasyon testi.

Neden var: bu rapor `paid_amount_in_company_currency` diye var olmayan bir
kolonu seçiyordu, yani her çağrıda "Unknown column" ile düşüyordu ve bunu
kimse fark etmemişti. Tek bir çağrı bile test edilmediği için sessizce
bozuk kaldı.

Asıl sınanan iş kuralı: her ödeme **kendi tarihindeki** kurla değerlenir.
Bugünün kuruyla değerlenirse aynı rapor her gün başka bir USD toplamı verir
ve deftere oturmaz. Kur bulunamadığında da uydurulmuş bir sabit değil,
"kur yok" (None) döner — tahmini gerçek tutar gibi göstermek muhasebede
yanlış bilgidir.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from stabler.api.reports import get_payments_register_report

RATE_OLD = 10000.0
RATE_NEW = 12000.0
RATE_ON_DOC = 11000.0


class PaymentsRegisterFXTest(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no Company fixture available")

		self.base_currency = frappe.db.get_value("Company", self.company, "default_currency")
		if self.base_currency == "USD":
			self.skipTest("company already reports in USD; nothing to convert")

		self.receivable = self._leaf("Receivable", self.base_currency)
		self.bank = self._leaf("Cash", self.base_currency) or self._leaf("Bank", self.base_currency)
		if not (self.receivable and self.bank):
			self.skipTest("no receivable / cash account available")

		# Kur tablosunu bu testin kontrolüne alıyoruz: sitede kalmış eski bir
		# satır "kur yok" senaryosunu sessizce geçerli hale getirirdi.
		frappe.db.sql(
			"""DELETE FROM `tabCurrency Exchange`
			WHERE (from_currency = 'USD' AND to_currency = %s)
			   OR (from_currency = %s AND to_currency = 'USD')""",
			(self.base_currency, self.base_currency),
		)

		self.d_old = add_days(today(), -60)
		self.d_new = add_days(today(), -10)
		self._rate(self.d_old, RATE_OLD)
		self._rate(self.d_new, RATE_NEW)

		self.customer = self._customer()

	def tearDown(self):
		frappe.db.rollback()

	# --- yardımcılar ---------------------------------------------------

	def _leaf(self, account_type: str, currency: str) -> str | None:
		return frappe.db.get_value(
			"Account",
			{
				"company": self.company,
				"account_type": account_type,
				"account_currency": currency,
				"is_group": 0,
				"disabled": 0,
			},
			"name",
		)

	def _rate(self, date: str, rate: float) -> None:
		frappe.get_doc(
			{
				"doctype": "Currency Exchange",
				"date": date,
				"from_currency": "USD",
				"to_currency": self.base_currency,
				"exchange_rate": rate,
			}
		).insert(ignore_permissions=True)

	def _customer(self) -> str:
		doc = frappe.new_doc("Customer")
		doc.customer_name = "PayReg_" + frappe.generate_hash(length=6)
		doc.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
		doc.insert(ignore_permissions=True)
		return doc.name

	def _payment(
		self,
		posting_date: str,
		paid_amount: float,
		paid_from: str | None = None,
		exchange_rate: float = 1.0,
	) -> str:
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Receive"
		pe.company = self.company
		pe.posting_date = posting_date
		pe.party_type = "Customer"
		pe.party = self.customer
		pe.paid_from = paid_from or self.receivable
		pe.paid_to = self.bank
		pe.paid_amount = paid_amount
		pe.source_exchange_rate = exchange_rate
		pe.target_exchange_rate = 1.0
		pe.received_amount = paid_amount * exchange_rate
		pe.reference_no = "PR-" + frappe.generate_hash(length=6)
		pe.reference_date = posting_date
		pe.insert(ignore_permissions=True)
		pe.submit()
		return pe.name

	def _rows_by_name(self) -> dict:
		res = get_payments_register_report(company=self.company)
		return {r["name"]: r for r in res["rows"]}, res["totals"]

	# --- testler -------------------------------------------------------

	def test_each_payment_uses_the_rate_of_its_own_date(self):
		"""İki ödeme, iki farklı kur dönemi — ikisi de kendi dönemiyle değerlenir.

		Her ikisi de "en son kur" ile değerlenseydi tutarlar 100/100 değil,
		83.33/100 çıkardı. Testin kırılma noktası tam olarak orası.
		"""
		mid = self._payment(add_days(today(), -30), 1_000_000.0)  # eski kur dönemi
		late = self._payment(add_days(today(), -5), 1_200_000.0)  # yeni kur dönemi

		rows, totals = self._rows_by_name()

		self.assertEqual(flt(rows[mid]["fx_rate"]), RATE_OLD)
		self.assertEqual(flt(rows[mid]["usd_amount"]), 100.0)
		self.assertEqual(flt(rows[late]["fx_rate"]), RATE_NEW)
		self.assertEqual(flt(rows[late]["usd_amount"]), 100.0)
		self.assertEqual(flt(totals["usd_total"]), 200.0)

	def test_payment_before_any_published_rate_is_not_invented(self):
		"""Kur yoksa satır boş döner ve toplama karışmaz.

		Eski kod burada 12800 sabitini basıyordu: uydurma bir kur, gerçek bir
		tutar gibi görünüyordu. Toplam da o uydurmayı içeriyordu.
		"""
		early = self._payment(add_days(today(), -90), 500_000.0)

		rows, totals = self._rows_by_name()

		self.assertIsNone(rows[early]["fx_rate"])
		self.assertIsNone(rows[early]["usd_amount"])
		self.assertEqual(flt(totals["usd_total"]), 0.0)

	def test_usd_denominated_payment_keeps_its_own_recorded_rate(self):
		"""USD hesabından gelen ödeme çevrilmez, kendi kuruyla raporlanır.

		Tabana çevirip geri çevirmek yuvarlama hatası ekler; ayrıca belgenin
		kendi kaydettiği kur, o gün CBU'nun yayımladığından farklı olabilir —
		muhasebede geçerli olan belgedeki kurdur.
		"""
		usd_receivable = self._usd_receivable()
		# ERPNext, ödemenin para birimini müşterinin varsayılan alacak hesabının
		# para birimiyle karşılaştırır; USD ödeme ancak müşteri USD hesaba
		# bağlıysa geçer. Gerçek kiracıda da kurulum böyledir.
		customer = frappe.get_doc("Customer", self.customer)
		customer.default_currency = "USD"
		customer.append("accounts", {"company": self.company, "account": usd_receivable})
		customer.save(ignore_permissions=True)

		pe = self._payment(
			add_days(today(), -5), 250.0, paid_from=usd_receivable, exchange_rate=RATE_ON_DOC
		)

		rows, _ = self._rows_by_name()

		self.assertEqual(flt(rows[pe]["usd_amount"]), 250.0)
		self.assertEqual(flt(rows[pe]["fx_rate"]), RATE_ON_DOC)
		# Taban tutar belgenin kuruyla hesaplanır, raporun kuruyla değil.
		self.assertEqual(flt(rows[pe]["uzs_amount"]), 250.0 * RATE_ON_DOC)

	def _usd_receivable(self) -> str:
		existing = self._leaf("Receivable", "USD")
		if existing:
			return existing

		parent = frappe.db.get_value("Account", self.receivable, "parent_account")
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": "PayReg USD Receivable " + frappe.generate_hash(length=4),
				"company": self.company,
				"parent_account": parent,
				"account_type": "Receivable",
				"account_currency": "USD",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
		return doc.name
