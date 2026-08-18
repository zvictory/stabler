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

import re
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

	#: Which `useDocumentForm` slot each endpoint belongs in. Asserting the SLOT and
	#: not merely the presence of the name is the whole point: the previous version
	#: of this test looped over the same five names with `assertIn(api, self.src)`,
	#: which is true no matter which key holds which endpoint. `detailApi` and
	#: `updateApi` were transposed — the writer bound to the read slot and the
	#: reader to the write slot — and all 27 tests on this branch stayed green.
	BINDINGS = (
		("detailApi", "sales_invoice_detail"),
		("createApi", "create_direct_sales_invoice"),
		("updateApi", "update_sales_invoice"),
		("submitApi", "submit_sales_invoice"),
		("cancelApi", "cancel_sales_invoice"),
		("amendApi", "amend_sales_invoice"),
		("deleteApi", "delete_sales_invoice"),
	)

	def _bound(self, key: str) -> str | None:
		"""The endpoint bound to `key`, or None if the key is absent."""
		found = re.search(rf'\b{key}:\s*"([^"]+)"', self.src)
		return found.group(1) if found else None

	def test_every_endpoint_is_bound_to_the_slot_that_calls_it(self):
		for key, endpoint in self.BINDINGS:
			with self.subTest(slot=key):
				self.assertEqual(
					self._bound(key),
					f"stabler.api.sales.{endpoint}",
					f"{key} does not name {endpoint}; the form calls the wrong endpoint "
					f"for this slot and no other test on this branch can see it",
				)

	def test_the_load_slot_never_names_a_writer(self):
		"""`detailApi` is called on page load, so it must be safe to merely look.

		`useDocumentForm.js:60` calls it as `call(detailApi, { name })` — one
		argument, on mount, before the user has done anything. A mutating endpoint
		there means opening a document edits it. When this was wrong the damage was
		masked rather than absent: `update_sales_invoice` runs `check_concurrency`
		first and threw "Stale request" on the missing `modified`, so the screen
		merely refused to open. That refusal is not a safety property — it is a
		staleness check that happened to fire first, and the obvious way to "fix" a
		page that will not load is to thread `modified` through, which removes it
		and turns every page view into a save.

		So the rule is about the slot, not about that one endpoint: nothing whose
		name says it writes may sit in the slot that is called on sight.
		"""
		loader = self._bound("detailApi")
		self.assertIsNotNone(loader, "detailApi is not bound at all")
		for verb in ("create_", "update_", "submit_", "cancel_", "amend_", "delete_"):
			self.assertNotIn(
				verb,
				loader.rsplit(".", 1)[-1],
				f"detailApi names {loader}, which mutates — opening the form would call it",
			)

	def test_no_endpoint_is_bound_to_two_slots(self):
		# The transposition put two endpoints in each other's slot; a duplicate is
		# the other shape of the same mistake, and it reads as harmless.
		bound = [self._bound(key) for key, _ in self.BINDINGS]
		present = [b for b in bound if b]
		self.assertEqual(
			len(present),
			len(set(present)),
			f"an endpoint is bound to more than one slot: {present}",
		)

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
