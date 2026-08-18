"""MSA'nın fatura ekranı: Modern deneyim, ama sipariş kavramı olmadan.

MSA sipariş kullanmıyor — ölçüldüğünde 0 Satış Siparişi, 4937 Satış Faturası
vardı. Bu yüzden `enable_modern_sales_order` bayrağını açmak onlara hiçbir şey
yapmaz: o bayrak yalnız Satış Siparişi rotasındaki formu seçer. İstenen,
Modern formun DENEYİMİNİN fatura yazarken de olması.

Bu dosya yeni formun üç sınırını kilitliyor.

**1. Belge Satış Faturası'dır, Satış Siparişi değil.** Form `useDocumentForm`'a
`Sales Invoice` doctype'ını ve fatura uçlarını vermeli. Sipariş uçlarından
birine bağlanırsa ekran sessizce yanlış belgeyi yazar.

**2. Taslak kaydetmek ile göndermek AYRI eylemlerdir.** Sipariş formunda tek
tuşla kaydet-ve-gönder doğrudur: yanlış bir sipariş bedavadır, silinir.
Fatura öyle değil — gönderilen fatura muhasebe kaydı (GL), stok kaydı (SLE)
ve e-fatura doğurur. Tek tuş, geri alınamaz bir işlemi kazayla tetiklemenin
en kısa yoludur.

**3. Koli sütunları kalır.** Paranın birimi kilo, deponun birimi koli. Ortak
`LineItemsEditor` bileşeninin sütunları Item/Qty/UOM/Rate/Amount — koli yok.
Onu satır ızgarası olarak kullanmak koli bilgisini düşürürdü; onu koli
taşıyacak şekilde DEĞİŞTİRMEK ise aynı bileşeni kullanan altı kiracının
sipariş ekranına dokunmak olurdu. Bu yüzden ızgara faturaya özel kalıyor ve
yalnız güvenli ortak parçalar (Typeahead, FormPage, MoneyInput, DateInput,
Select) yeniden kullanılıyor.

Ayrıca kapı: sayfa, backend'in ZORLADIĞI bayrakla kapılanmalı. Eski sayfa
`imports` modülüne bakıyordu, backend ise `direct_invoicing`'e — bir kiracıda
`imports` açık `direct_invoicing` kapalı olsaydı ekran açılır, kayıt backend'de
patlardı.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "public/js/pages/sales/SalesInvoiceFormModern.vue"
ROUTER = (ROOT / "public/js/router.js").read_text(encoding="utf-8")
SHARED_EDITOR = (ROOT / "public/js/components/LineItemsEditor.vue").read_text(encoding="utf-8")


class TestTheFormExists(unittest.TestCase):
	def test_the_component_file_is_present(self):
		self.assertTrue(FORM.exists(), f"{FORM.name} yok")


class TestItWritesAnInvoiceNotAnOrder(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_the_document_engine_is_pointed_at_sales_invoice(self):
		self.assertIn('doctype: "Sales Invoice"', self.src, "doctype Satış Faturası değil")

	def test_it_binds_every_invoice_endpoint_including_update(self):
		for api in (
			"sales_invoice_detail",
			"create_direct_sales_invoice",
			"update_sales_invoice",
			"submit_sales_invoice",
			"cancel_sales_invoice",
		):
			self.assertIn(api, self.src, f"{api} bağlanmamış")

	def test_no_sales_order_endpoint_leaks_in(self):
		for leaked in (
			"create_sales_order",
			"update_sales_order",
			"submit_sales_order",
			"sales_order_detail",
			"close_sales_order",
		):
			self.assertNotIn(leaked, self.src, f"sipariş ucu sızmış: {leaked}")

	def test_order_only_concepts_are_absent(self):
		for concept in ("delivery_date", "reserved_qty", "reservation"):
			self.assertNotIn(concept, self.src, f"siparişe özgü kavram taşınmış: {concept}")


class TestSavingAndSubmittingAreSeparate(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_there_is_a_draft_save_action_and_a_separate_submit_action(self):
		self.assertIn("saveDraft", self.src, "taslak kaydetme eylemi yok")
		self.assertIn("submitInvoice", self.src, "ayrı gönderme eylemi yok")

	def test_submitting_asks_first(self):
		"""Geri alınamayan bir işlem onay istemeden çalışmamalı."""
		self.assertIn("confirm", self.src, "gönderme onay istemiyor")


class TestTheBoxColumnsSurvive(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_the_grid_still_carries_boxes_and_box_weight(self):
		for field in ("boxes", "box_kg"):
			self.assertIn(field, self.src, f"{field} sütunu düşmüş")

	def test_the_shared_editor_was_not_taught_about_boxes(self):
		"""Ortak bileşeni koli taşıyacak şekilde değiştirmek altı kiracının
		sipariş ekranına dokunmak olurdu — bu testin koruduğu sınır budur."""
		for field in ("boxes", "box_kg", "custom_boxes"):
			self.assertNotIn(
				field,
				SHARED_EDITOR,
				"LineItemsEditor değiştirilmiş — paylaşılan bileşen artık izole değil",
			)


class TestTheGateMatchesTheBackend(unittest.TestCase):
	def setUp(self):
		self.src = FORM.read_text(encoding="utf-8") if FORM.exists() else ""

	def test_it_gates_on_the_flag_the_backend_enforces(self):
		self.assertIn(
			"direct_invoicing",
			self.src,
			"ekran backend'in zorladığı bayrağa bakmıyor — form açılır, kayıt patlar",
		)


class TestTheRouteUsesIt(unittest.TestCase):
	def test_the_new_invoice_route_renders_the_new_form(self):
		self.assertIn("SalesInvoiceFormModern", ROUTER, "rota yeni forma bağlanmamış")


if __name__ == "__main__":
	unittest.main()
