"""Kur her zaman güçlü yönde okunur: "1 USD = 12 060 UZS", asla "0,000082632".

Sahibin kuralı: *"Rate olarak bizim kural vardi 1usd=?uzs kullaniyoruz her
zaman!!! rate 0.000082632 seklinde degil, rate 12060 seklinde"*.

Neden bu bir *iş* kuralı, biçimlendirme zevki değil: anjan'ın defter parası USD,
işlemleri UZS. ERPNext'in `conversion_rate`'i "1 belge parası = N taban parası"
demek, yani bu çiftte meşru olarak 8,2632e-05'tir ve öyle de saklanmalıdır.
Ekranda o kesri göstermek kullanıcıya kurunu doğrulayamayacağı bir sayı vermek
demek — 12 060'ı gören satıcı yanlış kuru bir bakışta yakalar, 0,0000826'yı
gören yakalayamaz. Bu yüzden *saklama* yönü değişmez, *sunum* yönü sabittir.

`composables/fx.js` bu kuralın tek uygulaması ve altı para ekranında zaten
kullanımda; Satış Siparişi onu benimsemeyen son ekrandı. Bu dosya her iki
varyantın da ona bağlı kaldığını ve yolun herhangi bir yerinde ham kesre geri
düşmediğini kilitliyor.

Kaynaktan kilitler, render'dan değil — projenin diğer `_source`/`_guard`
testleriyle aynı sınıf. Tarayıcı turu bunun yerine geçmez.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FX = (ROOT / "public/js/composables/fx.js").read_text(encoding="utf-8")
FORMS = {
	name: (ROOT / f"public/js/pages/sales/{name}").read_text(encoding="utf-8")
	for name in ("SalesOrderFormClassic.vue", "SalesOrderFormModern.vue")
}
CLASSIC = FORMS["SalesOrderFormClassic.vue"]
MODERN = FORMS["SalesOrderFormModern.vue"]


def _template(src):
	return src[src.index("<template>") :]


class TestTheRuleLivesInFxJsAndNowhereElse(unittest.TestCase):
	def test_fx_inverts_a_sub_one_rate_so_the_quote_is_always_ge_one(self):
		"""Kuralın çekirdeği: kur 1'den küçükse taban para güçlü taraftır ve
		gösterilen sayı 1/r olur. Bu satır giderse 0,0000826 geri gelir."""
		self.assertIn("return { strong: baseCcy, weak: accountCcy, value: 1 / r };", FX)

	def test_both_forms_import_the_shared_helper(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertRegex(
					src, r'import \{[^}]*readableRate[^}]*\} from "\.\./\.\./composables/fx\.js";'
				)

	def test_no_form_hand_rolls_the_direction_again(self):
		"""Eski `rateIsInverted` yönü `form.currency === "UZS"` literaliyle
		saptıyordu — RUB-belge/USD-defter çiftinde yanlış cevap verir ve
		CLAUDE.md'nin "kiracı farkı koda gömülmez" kuralını çiğner."""
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertNotIn("rateIsInverted", src)


class TestTheScreenNeverShowsARawRate(unittest.TestCase):
	def test_the_quote_is_rendered_as_one_strong_equals_n_weak(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertRegex(
					_template(src),
					r"1 \{\{ [A-Za-z.]*[Ss]trong[A-Za-z]* \}\} = \{\{ formatRate\(",
				)

	def test_no_unformatted_rate_interpolation_survives(self):
		"""Kullanıcının şikâyet ettiği tam satır buydu:
		`· {{ t("rate") }} {{ displayExchangeRate }}` — ham sayı, gruplama yok."""
		self.assertNotIn("{{ displayExchangeRate }}", _template(CLASSIC))
		self.assertNotIn("{{ rateQuote.value }}", _template(MODERN))
		self.assertNotIn("{{ activeRate }}", _template(MODERN))

	def test_the_classic_rate_box_converts_typed_input_back_to_erpnext_direction(self):
		"""Klasik formdaki kutu düzenlenebilir: kullanıcı 12 060 yazar,
		`toLineRate` bunu 1/12060'a çevirir. Bu çağrı giderse kullanıcının
		girdiği güçlü-yön sayısı olduğu gibi saklanır — 12 060 katı hata."""
		self.assertIn("exchangeRate.value = toLineRate(", CLASSIC)


class TestAnUnknownRateIsNeverSilentlyOne(unittest.TestCase):
	"""Yön düzeltmesinin para tarafı: bilinmeyen kur `1` olamaz. USD defterinde
	945 000 UZS'lik bir sipariş `conversion_rate = 1` ile 945 000 USD olarak
	defterlenir ve hiçbir uyarı çıkmaz."""

	def test_the_ref_starts_unknown_not_one(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertIn("const exchangeRate = ref(null);", src)

	def test_the_payload_omits_the_key_instead_of_defaulting(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertNotIn("exchangeRate.value || 1", src)
				self.assertRegex(src, r"conversion_rate:[^\n]*\n(?:[^\n]*\n)?[^\n]*exchangeRate\.value > 0")

	def test_a_failed_rate_lookup_leaves_it_unknown(self):
		body = re.search(r"async function fetchExchangeRate\(\).*?\n}\n", CLASSIC, re.S).group(0)
		catch = body[body.index("} catch") :]
		self.assertIn("exchangeRate.value = null;", catch)
		self.assertNotIn("= 1", catch)


class TestASavedOrderShowsTheRateItWasBookedAt(unittest.TestCase):
	"""Gösterilen kur, belgenin defterlendiği kur olmalı — bugünün kuru değil.

	Klasik varyantta `load()` `form.currency`'yi doldurduğu an kur izleyicisi
	tetikleniyordu; izleyici canlı CBU kurunu çekip `loadDoc`'un az önce
	yazdığı belge kurunu eziyordu. `SAL-ORD-2026-05890` 11 973,9 ile
	defterlenmişken ekran 12 006,39 gösteriyordu — onaylanmış bir siparişte
	kullanıcıya hiç kullanılmamış bir kur.
	"""

	def test_the_classic_watchers_stand_down_while_a_document_loads(self):
		self.assertIn("const loadingDoc = ref(false);", CLASSIC)
		watchers = re.findall(
			r"watch\(\n\t\(\) => form\.value\?\.(currency|transaction_date),\n(.*?)\n\);",
			CLASSIC,
			re.S,
		)
		self.assertEqual(2, len(watchers), "kur izleyicilerinin ikisi de bulunmalı")
		for name, body in watchers:
			with self.subTest(watcher=name):
				self.assertIn("if (loadingDoc.value) return;", body)

	def test_the_modern_variant_prefers_the_documents_own_rate(self):
		"""Modern varyant aynı hatayı başka bir yoldan kapatıyor: canlı kur
		ayrı bir ref'te durur, `activeRate` belgeninkini önceler."""
		block = MODERN[MODERN.index("const activeRate = computed(") :]
		block = block[: block.index("\n});")]
		self.assertIn("if (isForeignCurrency.value && docRate > 0)", block)


if __name__ == "__main__":
	unittest.main()
