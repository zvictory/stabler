"""Taslak faturayı güncelleyen uç: neyi yapmalı, neyi asla yapmamalı.

SPA'da bugün fatura taslağı düzenlenemiyor — `SalesInvoiceForm.vue`
`useDocumentForm`'a `updateApi` vermiyor, çünkü backend'de böyle bir uç yok.
Kullanıcı yanlış yazdığı bir taslağı silip baştan kesmek zorunda kalıyor.

Uç eklenirken asıl mesele hız değil, neyin DIŞARIDA bırakıldığı:

* **Yalnız taslak.** Gönderilmiş bir Satış Faturası muhasebe kaydı (GL),
  stok kaydı (SLE) ve e-fatura doğurmuştur. Yerinde güncellemek belgeyi
  kendi defterinden ayırır ve bunu hiçbir kontrol yakalamaz. Gönderilmiş
  belgenin tek meşru yolu iptal + `amend_sales_invoice` ya da iade faturası.
* **`ignore_validate_update_after_submit` kullanılmaz.** O bayrak submit
  sonrası birkaç alanı değiştirmek içindir; tutar/satır/hesap değiştirmek
  için kullanılırsa yukarıdaki ayrışma sessizce olur.
* **Satırlar tam değiştirilir, yamalanmaz.** Satır yamalamak `so_detail`
  gibi bağları ve satır kimliklerini sessizce bozar.
* **Toplamlar elle hesaplanmaz.** `doc.save()` zaten `validate()` →
  `calculate_taxes_and_totals()` çalıştırır; elle çağırıp sonra alan set
  etmek "toplamlar satırlarla tutmuyor" hatasının klasik kaynağıdır.
* **Müşteri değişirse `debit_to` sıfırlanır** ki `set_missing_values`
  alacak hesabını yeniden çözsün — eski hesabın para birimi yeni belgeyle
  uyuşmazsa hata submit anına ötelenir.
* **Eşzamanlılık kontrol edilir.** İki kasiyer aynı taslağı açtığında
  ikincisinin kaydı birincisininkini sessizce ezmemeli.

Ve satırlar `create_direct_sales_invoice` ile AYNI kurucudan geçmeli: koli
alanları (`custom_boxes` / `custom_box_kg`) bir uçta yazılıp diğerinde
unutulursa, taslağı düzenlemek koli bilgisini sıfırlar. Bu tam olarak
2026-08-18'de ölçülen kaybın tekrarı olurdu.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SALES = (ROOT / "api/sales.py").read_text(encoding="utf-8")


def _function_body(src: str, name: str) -> str:
	start = src.index(f"def {name}(")
	rest = src[start:]
	end = len(rest)
	for marker in ("\n@frappe.whitelist", "\ndef "):
		idx = rest.find(marker, 1)
		if idx != -1:
			end = min(end, idx)
	return rest[:end]


def _code_only(src: str) -> str:
	"""Yorumları at — bir kuralı ANLATAN yorum o kuralın ihlali değildir."""
	out = []
	for line in src.split("\n"):
		if line.lstrip().startswith("#"):
			continue
		out.append(line.split("  # ")[0])
	body = "\n".join(out)
	if body.count('"""') >= 2:
		a = body.index('"""')
		b = body.index('"""', a + 3) + 3
		body = body[:a] + body[b:]
	return body


class TestTheEndpointExists(unittest.TestCase):
	def test_it_is_defined_and_whitelisted(self):
		self.assertTrue("def update_sales_invoice(" in SALES, "uç tanımlı değil")
		idx = SALES.index("def update_sales_invoice(")
		self.assertTrue(
			"@frappe.whitelist()" in SALES[max(0, idx - 200) : idx],
			"uç whitelist edilmemiş — SPA çağıramaz",
		)


class TestItRefusesWhatItMustRefuse(unittest.TestCase):
	def setUp(self):
		self.body = _code_only(_function_body(SALES, "update_sales_invoice"))

	def test_only_drafts_may_be_edited(self):
		self.assertIn(
			"docstatus != 0",
			self.body,
			"gönderilmiş fatura yerinde güncellenebiliyor — GL ve SLE belgeden ayrışır",
		)

	def test_it_does_not_reach_for_the_after_submit_escape_hatch(self):
		self.assertNotIn(
			"ignore_validate_update_after_submit",
			self.body,
			"submit sonrası doğrulamayı atlatan bayrak kullanılmış",
		)

	def test_it_checks_concurrency(self):
		self.assertIn(
			"check_concurrency",
			self.body,
			"iki kasiyer aynı taslağı ezebilir",
		)

	def test_it_does_not_hand_calculate_totals(self):
		self.assertNotIn(
			"calculate_taxes_and_totals()",
			self.body,
			"toplamlar elle hesaplanmış — doc.save() zaten hesaplıyor",
		)


class TestItRebuildsRatherThanPatches(unittest.TestCase):
	def setUp(self):
		self.body = _code_only(_function_body(SALES, "update_sales_invoice"))

	def test_rows_are_replaced_wholesale(self):
		self.assertIn(
			'set("items", [])',
			self.body,
			"satırlar yamalanıyor — satır kimlikleri ve bağları bozulur",
		)

	def test_a_changed_customer_resets_the_receivable_account(self):
		self.assertIn(
			"debit_to",
			self.body,
			"müşteri değişince debit_to sıfırlanmıyor — yanlış para birimli hesap kalır",
		)

	def test_it_returns_the_new_timestamp(self):
		"""`useDocumentForm` `res.modified`'ı geri yazar; dönmezse ikinci
		kaydetme 'Stale request' ile reddedilir."""
		self.assertIn('"modified"', self.body, "dönüşte modified yok")


class TestBothEndpointsShareOneRowBuilder(unittest.TestCase):
	"""Koli alanlarının bir uçta yazılıp diğerinde unutulmasını engelleyen kilit."""

	BUILDER = "_direct_invoice_item_rows"

	def test_the_builder_exists(self):
		self.assertTrue(f"def {self.BUILDER}(" in SALES, "ortak satır kurucusu yok")

	def test_create_uses_it(self):
		body = _code_only(_function_body(SALES, "create_direct_sales_invoice"))
		self.assertIn(self.BUILDER, body, "create kendi satırını kuruyor")

	def test_update_uses_it(self):
		body = _code_only(_function_body(SALES, "update_sales_invoice"))
		self.assertIn(self.BUILDER, body, "update kendi satırını kuruyor")

	def test_the_builder_is_where_the_box_fields_live(self):
		body = _function_body(SALES, self.BUILDER)
		for field in ("custom_boxes", "custom_box_kg"):
			self.assertIn(field, body, f"{field} ortak kurucuda değil")


if __name__ == "__main__":
	unittest.main()
