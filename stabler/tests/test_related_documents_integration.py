"""Bağlantılı belgeler: Payment Entry'nin ödediği faturayı GÖSTERMESİ gerekir.

Gerçek site + veritabanı ister, `bench run-tests --app stabler --module
stabler.tests.test_related_documents_integration` ile koşar; düz
`python -m unittest` ile değil. Bu yüzden frappe-free listesine girmez.

Neden davranış testi: bu yol kaynağa bakarak korunamaz. `get_linked_documents`
konu doctype'ını kabul eder hâle geldikten sonra bile Payment Entry için boş
dönüyordu — Frappe'nin bağlantı yürüyücüsü Dynamic Link'i tersine çeviremiyor.
Faturadan ödemeyi bulur (Sales Invoice'ın linkinfo'sunda Payment Entry vardır),
ödemeden faturayı bulamaz. Yani 417 gitmiş, yerine aynı derecede boş bir 200
gelmişti; ekranda fark yoktu, ikisi de "—" çiziyordu.

Testler bu yüzden "yardımcı fonksiyon duruyor mu" değil, "panel ödemenin
faturasını gösteriyor mu" diye sorar: yardımcı silinirse de, Frappe ileride
Dynamic Link'i tersine çevirebilir hâle gelirse de doğru cevabı verir.

2026-08-28: fikstür artık kurulur, aranmaz. Ayrıntı `_seed_...`'in
docstring'inde. Üçü de ilk kez gerçekten koştu ve üçü de mutasyonla kırmızı
görüldü — her biri farklı bir satırla:

    _add_payment_entry_references çağrısı silinince  -> ödediği belge testi
    referans başına has_permission silinince         -> sızıntı testi
    sonuç filtresinden Payment Entry düşünce         -> ters yön testi
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

from stabler.api.sales import get_linked_documents


def _seed_payment_entry_with_a_reference() -> tuple[str, str, str]:
	"""Build the pair the panel has to link: a paid Sales Invoice, and the
	Payment Entry that paid it. Returns (payment_entry, "Sales Invoice", invoice).

	Built rather than looked up. Until 2026-08-28 this module hunted the site
	for an existing `Payment Entry Reference` row and skipped when it found
	none, which meant it reported OK while asserting nothing — the gate calls
	that red, correctly. And "no reference exists" was never even true here:
	the throwaway site holds 1503 such rows whose parents *and* target invoices
	have all been rolled back out from under them, so the lookup gave up on the
	first orphan it read. A test that only runs when someone else happened to
	leave the right data behind is not a test of anything.

	Everything it needs is created here, so the only site facts assumed are a
	Company with its default accounts and an open Fiscal Year. `FrappeTestCase`
	rolls the whole class back, so nothing is left behind for the next module
	to trip over — which is exactly what produced those 1503 orphans.

	Background enqueues are suppressed for the two submits. Submitting a Sales
	Invoice fires stabler's own `on_submit` hooks — a 1C push and an EHF
	submission — and `frappe.enqueue` reaches the real Redis queue even under
	`frappe.in_test`, where `_check_queue_size` raises `QueueOverloaded`. Left
	alone, this module would go red because an unrelated integration queue on
	the bench happened to be backed up, and it would add two more jobs to that
	backlog on every run. Neither integration is what is being tested here: the
	subject is whether the panel can walk from a payment to the invoice it paid.
	"""
	company = frappe.get_doc("Company", frappe.db.get_value("Company", {}, "name"))

	customer = frappe.db.get_value("Customer", {"customer_name": "_Stabler Linked Docs"}, "name")
	if not customer:
		customer = (
			frappe.get_doc({"doctype": "Customer", "customer_name": "_Stabler Linked Docs"})
			.insert(ignore_permissions=True)
			.name
		)

	item_code = "_Stabler Linked Docs Item"
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				# Non-stock on purpose: a stock item would drag warehouses,
				# valuation and a Stock Ledger Entry into a test about links.
				"is_stock_item": 0,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": frappe.db.get_value("UOM", {}, "name"),
			}
		).insert(ignore_permissions=True)

	# See the docstring: submit with the queue out of the picture.
	with patch("frappe.enqueue"), patch("frappe.enqueue_doc"):
		si, pe = _submit_invoice_and_payment(company, customer, item_code)
	return pe.name, "Sales Invoice", si.name


def _submit_invoice_and_payment(company, customer: str, item_code: str):
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": company.name,
			"customer": customer,
			"currency": company.default_currency,
			"posting_date": frappe.utils.today(),
			"due_date": frappe.utils.today(),
			"debit_to": company.default_receivable_account,
			"items": [
				{
					"item_code": item_code,
					"qty": 1,
					"rate": 100,
					"income_account": company.default_income_account,
					"cost_center": company.cost_center,
				}
			],
		}
	).insert(ignore_permissions=True)
	si.submit()

	pe = get_payment_entry("Sales Invoice", si.name)
	# ERPNext demands a transfer reference as soon as either leg is a Bank
	# account, and the company default may well be one.
	pe.reference_no = "_STABLER-LINKED-DOCS"
	pe.reference_date = frappe.utils.today()
	pe.insert(ignore_permissions=True)
	pe.submit()

	return si, pe


class RelatedDocumentsFromPaymentEntry(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.found = _seed_payment_entry_with_a_reference()

	def setUp(self):
		self.found = type(self).found

	def test_payment_entry_shows_the_document_it_pays(self):
		"""Panelin tek işi bu; Frappe tek başına bu yönü çözemiyor."""
		pe, ref_dt, ref_name = self.found
		linked = get_linked_documents("Payment Entry", pe)
		self.assertIn(
			ref_dt,
			linked,
			f"{pe} → {ref_dt} {ref_name} ödüyor ama panel {ref_dt} başlığını hiç çizmiyor",
		)
		self.assertIn(
			ref_name,
			[row["name"] for row in linked[ref_dt]],
			f"{ref_dt} başlığı var ama ödenen belge {ref_name} listede yok",
		)

	def test_the_reverse_direction_still_works(self):
		"""Faturadan ödemeye giden yol Frappe'nin kendi yürüyücüsü — kırmadığımızı kilitle."""
		pe, ref_dt, ref_name = self.found
		linked = get_linked_documents(ref_dt, ref_name)
		self.assertIn(
			"Payment Entry",
			linked,
			f"{ref_dt} {ref_name} üzerinden {pe} görünmüyor — yürüyücü yolu bozulmuş",
		)

	def test_an_unreadable_reference_is_not_leaked(self):
		"""Payment Entry'yi okuyabilmek, arkasındaki faturayı okuyabilmek değildir.

		İzin referans başına yeniden sorulmalı. Burada `has_permission` yalnız o
		referans için False'a çevrilir — çağrının kendi guard'ı etkilenmesin diye
		diğer her şey olduğu gibi geçer.
		"""
		pe, ref_dt, ref_name = self.found
		real = frappe.has_permission

		def gated(doctype=None, ptype="read", doc=None, *args, **kwargs):
			if doctype == ref_dt and doc == ref_name:
				return False
			return real(doctype, ptype, doc, *args, **kwargs)

		frappe.has_permission = gated
		try:
			linked = get_linked_documents("Payment Entry", pe)
		finally:
			frappe.has_permission = real

		self.assertNotIn(
			ref_name,
			[row["name"] for row in linked.get(ref_dt, [])],
			f"okuma izni olmayan {ref_dt} {ref_name} panele sızdı",
		)
		self.assertNotIn(
			ref_dt,
			[k for k, v in linked.items() if not v],
			"boş bir başlık kaldı — SPA her anahtar için başlık çizer",
		)


if __name__ == "__main__":
	unittest.main()
