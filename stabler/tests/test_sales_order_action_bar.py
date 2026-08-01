"""Satış Siparişi tek aksiyon çubuğu: aynı anda iki aksiyon çubuğu ya da iki
`btn-primary` olmamalı.

Antigravity'nin commit'i (`a0c9457`) yeni `.so-sticky-foot` çubuğunu ekledi ama
ebeveynden kalan `<template #actions>` bloğunu (`FormPage`'in `#actions`
slot'u) silmeyi unuttu. `useDocumentForm.js`'deki `editable = isCreate ||
docstatus === 0` yüzünden bu üç bozuk durumu üretiyordu:

  - Yeni sipariş: `#actions` yalnız yetim, stilsiz bir Cancel bağlantısı çizer.
  - Kaydedilmiş taslak: hem `.so-sticky-foot` (editable=true) hem `#actions`
    (isCreate=false dalı) aynı anda çizilir — iki tam çubuk, iki `btn-primary`.
  - Onaylanmış sipariş: `.so-sticky-foot` hiç çizilmez (v-if="editable" false),
    aksiyonlar `FormPage`'in `.form-page-actions` sınıfına düşer ve o sınıfın
    hiçbir yerde CSS'i yok.

Düzeltme: `#actions` bloğu tamamen silindi, `.so-sticky-foot` her zaman çizilir,
her buton kendi `v-if` koşulunu taşır. Ayrıca `actionError` uyarısı hem
`FormPage.vue`'da hem burada iki kere render ediliyordu — yerel kopya silindi.

Bu dosya kaynaktan kilitliyor, render'ı değil — projenin diğer `_source.py`
testleriyle aynı sınıf.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = (ROOT / "public/js/pages/sales/SalesOrderForm.vue").read_text(encoding="utf-8")


class TestTheDuplicateActionsBlockIsGone(unittest.TestCase):
	def test_the_actions_slot_template_no_longer_exists(self):
		self.assertNotIn("<template #actions>", FORM)


class TestTheStickyFootAlwaysRenders(unittest.TestCase):
	"""Onaylanmış siparişte de çubuk çizilmeli — yoksa Create Invoice / Cancel /
	Amend / Close & release / Delete hiçbir yerde görünmez."""

	def test_the_wrapper_no_longer_gates_on_editable(self):
		self.assertIn('<div class="so-sticky-foot">', FORM)
		self.assertNotIn('<div v-if="editable" class="so-sticky-foot">', FORM)


class TestEachStickyActionCarriesItsOwnGuard(unittest.TestCase):
	"""Sarmalayıcı artık kayıtsız çizildiği için para-toplayan iki buton
	(Save as draft / Submit & reserve stock) kendi v-if="editable"'ını taşımalı;
	aksi halde onaylanmış bir siparişte de görünürler."""

	def _actions_body(self):
		start = FORM.index('<div class="so-sticky-actions">')
		return FORM[start : FORM.index("\n\t\t\t</div>\n\t\t</div>\n\t</FormPage>")]

	def test_save_as_draft_is_gated_on_editable(self):
		body = self._actions_body()
		i = body.index('t("Save as draft")')
		preceding = body[:i]
		last_button = preceding[preceding.rindex("<button") :]
		self.assertIn('v-if="editable"', last_button)

	def test_submit_and_reserve_is_gated_on_editable(self):
		body = self._actions_body()
		i = body.index('t("Submit & reserve stock")')
		preceding = body[:i]
		last_button = preceding[preceding.rindex("<button") :]
		self.assertIn('v-if="editable"', last_button)

	def test_the_submitted_order_actions_carry_their_own_guards(self):
		body = self._actions_body()
		for literal in (
			'v-if="canCreateInvoice"',
			'v-if="can.cancel"',
			'v-if="can.amend"',
			'v-if="canCloseSo"',
			'v-if="can.delete"',
		):
			with self.subTest(literal=literal):
				self.assertIn(literal, body)


class TestStickyFootItemCountIsDefined(unittest.TestCase):
	"""Tarayıcı turunda bulundu: sticky-foot özet satırı hiçbir yerde tanımlı
	olmayan bir `filledCount`'a bakıyordu (Vue "accessed during render but is
	not defined" uyarısı) — bu, testlerin kaynak-okuyan olmasının B2'de olduğu
	gibi kaçırdığı bir render hatasıydı. Dosyada zaten aynı iş için kullanılan
	`form.items.length` (satır ~1304, tablo altı özeti) buraya da uygulandı."""

	def test_filled_count_reference_is_gone(self):
		self.assertNotIn("filledCount", FORM)

	def test_sticky_foot_title_uses_form_items_length(self):
		self.assertIn('{{ form.items.length }} {{ form.items.length === 1 ? t("item") : t("items") }}', FORM)


class TestSubmitCreateActuallySubmitsExistingDrafts(unittest.TestCase):
	"""Tarayıcı turunda bulundu: kaydedilmiş bir taslakta "Submit & reserve
	stock"'a basmak yalnızca `save()`'i (→ `update_sales_order`) çağırıyordu.
	Ebeveyn commit'teki `submitDoc()` (→ gerçek `submit()` → `submit_sales_order`)
	Antigravity'nin birleştirmesinde tamamen düştü — `update_sales_order`'ın
	imzasında `auto_submit` hiç yok, yani belge sessizce Draft'ta kalıyordu.
	Düzeltme: `submitCreate()` artık `isCreate=false` dalında (gerekirse
	`save()` sonrası) composable'ın gerçek `submit()`'ini çağırıyor."""

	def test_submit_is_destructured_from_use_document_form(self):
		self.assertIn("\tsubmit,\n", FORM)

	def test_submit_create_calls_the_real_submit_for_existing_drafts(self):
		start = FORM.index("async function submitCreate(")
		end = FORM.index("\nasync function createInvoice", start)
		body = FORM[start:end]
		self.assertIn("if (isCreate.value)", body)
		self.assertIn("await submit();", body)


class TestNoDuplicateActionErrorAlert(unittest.TestCase):
	"""FormPage.vue zaten `actionError`'ı kendi alert div'inde çiziyor
	(frameless dalı, prop üzerinden). Burada ikinci bir kopya olmamalı."""

	def test_the_local_duplicate_alert_div_is_gone(self):
		self.assertNotIn('class="alert alert-danger mb-3">{{ actionError }}', FORM)

	def test_the_prop_is_still_forwarded_to_form_page(self):
		self.assertEqual(FORM.count(':action-error="actionError"'), 1)


if __name__ == "__main__":
	unittest.main()
