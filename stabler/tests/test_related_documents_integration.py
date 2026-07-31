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
"""

from __future__ import annotations

import unittest

import frappe

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from stabler.api.sales import _LINKED_DOCTYPES, get_linked_documents


def _a_payment_entry_with_a_reference() -> tuple[str, str, str] | None:
	"""(payment_entry, reference_doctype, reference_name) — SPA'nın çizdiği bir referans."""
	rows = frappe.get_all(
		"Payment Entry Reference",
		filters={"parenttype": "Payment Entry", "reference_doctype": ["in", sorted(_LINKED_DOCTYPES)]},
		fields=["parent", "reference_doctype", "reference_name"],
		limit=1,
	)
	if not rows:
		return None
	r = rows[0]
	if not frappe.db.exists(r.reference_doctype, r.reference_name):
		return None
	return r.parent, r.reference_doctype, r.reference_name


class RelatedDocumentsFromPaymentEntry(FrappeTestCase):
	def setUp(self):
		self.found = _a_payment_entry_with_a_reference()
		if not self.found:
			self.skipTest("referanslı Payment Entry yok — çıplak site")

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
