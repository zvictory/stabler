"""Satış Siparişi kur koruması: bilinmeyen kur asla sessizce sabit değere düşmemeli,
ve bir fiyat listesinin parası asla okunmadan geçilmemeli.

Antigravity'nin commit'i (`a0c9457`) `resolveRate()`'e sabit bir kur (`12006.39`)
gömmüştü: `get_currency_exchange_rate` çağrısı düşerse ya da eşik testi (`> 100`)
meşru bir kur çiftini (ör. EUR→USD ≈ 1.08) elerse, satır fiyatı o bayat sabitle
hesaplanıp **hiçbir uyarı olmadan** kaydediliyordu. CLAUDE.md'nin "tenant variance
lives in config/data, never in code constants" kuralının doğrudan ihlaliydi ve
kaydedilen paraya yazan tek bulguydu.

Düzeltme: kur bilinmiyorsa çeviri yapılmaz, çağıran satırın fiyatına dokunmaz,
kullanıcıya görünür bir uyarı çıkar. Bu dosya o davranışı kaynaktan kilitliyor —
render'ı değil, testin kendi projesindeki diğer `_source.py` testleri gibi.

2026-08-21'de kapsam İKİ forma birden çıktı. Klasik form `res.currency`'yi hiç
okumuyordu: UZS'de kote edilmiş bir fiyat listesi, USD'ye yazılmış bir siparişte
so'm rakamını dolar alanına yazıyordu (~12 000 katı hata, müşterinin lehine).
`enable_modern_sales_order` üretimde her şirkette KAPALI, yani bu, sekiz
kiracının altısının bugün kullandığı formun canlı davranışıydı. Çevrim artık
`composables/fx.js`'teki tek bir saf fonksiyonda (`priceListRateForOrder`) ve
davranışı `tests/fx.spec.js` ölçüyor; buradaki testler o kuralın iki formda da
gerçekten ÇAĞRILDIĞINI ve her çağıranın uyarıyı dinlediğini kilitliyor.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public/js"
FORM = (JS / "pages/sales/SalesOrderFormModern.vue").read_text(encoding="utf-8")
CLASSIC = (JS / "pages/sales/SalesOrderFormClassic.vue").read_text(encoding="utf-8")
FX = (JS / "composables/fx.js").read_text(encoding="utf-8")

FORMS = {"Modern": FORM, "Classic": CLASSIC}


def _squash(text: str) -> str:
	return re.sub(r"\s+", " ", text)


class TestTheHardcodedRateIsGone(unittest.TestCase):
	"""Sabit kur bir kere gömülüp unutulursa geri gelmesi kolay olur — literal
	arama, hangi fonksiyonda olursa olsun onu yakalar. Çevrim ortak dosyaya
	taşındığı için orası da taranıyor."""

	def test_the_literal_appears_nowhere(self):
		for name, src in {**FORMS, "fx.js": FX}.items():
			with self.subTest(file=name):
				self.assertEqual(src.count("12006"), 0)


class TestTheConversionRuleHasExactlyOneImplementation(unittest.TestCase):
	"""Çevrimin iki kopyası, tam olarak birinin sessizce yanlış kalma yoludur —
	bu hatanın kendisi öyle doğdu. İki form da aynı saf fonksiyonu çağırır ve
	hiçbiri kuru kendi içinde yeniden uygulamaz."""

	@staticmethod
	def _resolve_rate_body(src: str) -> str:
		fn = src[src.index("async function resolveRate(") :]
		return fn[: fn.index("\nasync function refreshLineRatesForPriceList")]

	def test_both_forms_call_the_shared_rule(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertIn('priceListRateForOrder } from "../../composables/fx.js"', src)
				self.assertIn("return priceListRateForOrder(", src)

	def test_resolve_rate_itself_delegates_rather_than_reading_the_price_directly(self):
		# Dosyanın bir yerinde ortak kuralın çağrılıyor olması yetmez — hatayı
		# geri getiren düzenleme tam olarak şudur: `resolveRate` cevaptaki
		# `price_list_rate`'i alıp doğrudan döndürür ve `toOrderRate` kullanılmaz
		# hâle gelir. Bu yüzden kontrol `resolveRate`'in KENDİ gövdesinde.
		for name, src in FORMS.items():
			with self.subTest(form=name):
				body = self._resolve_rate_body(src)
				self.assertIn("return toOrderRate(", body)
				self.assertNotIn("res.price_list_rate", body)

	def test_neither_form_does_the_arithmetic_itself(self):
		# Yerel bir çevrim geri gelirse `resolveRate`'in gövdesinde elle yazılmış
		# bir çarpma/bölme (ve eski hâlde `.toFixed(4)`) olarak görünür. Kapsam
		# kasten bu gövdeyle sınırlı: Klasik'in `grandTotalBase`'i de kurla
		# çarpıyor ve o, CLAUDE.md'de belgelenmiş `≈` istisnası — dosya çapında
		# bir yasak onu yanlışlıkla yakalardı.
		for name, src in FORMS.items():
			fn = src[src.index("async function resolveRate(") :]
			body = fn[: fn.index("\nasync function refreshLineRatesForPriceList")]
			for expr in ("exRate", "activeRate", "exchangeRate.value", ".toFixed("):
				with self.subTest(form=name, expr=expr):
					self.assertNotIn(expr, body)

	def test_no_form_guesses_a_price_list_currency(self):
		# `res.currency || "UZS"` — para koduna sabit bir varsayılan vermek,
		# msa'da 675 faturayı kendi tarihinin kuru olmayan bir kurla yazan
		# sınıfın ta kendisi. USD tabanlı bir kiracıda doğru bir dolar fiyatını
		# ~12 000'e bölerdi.
		for name, src in {**FORMS, "fx.js": FX}.items():
			with self.subTest(file=name):
				self.assertNotIn('currency || "UZS"', src)


class TestTheSharedRuleRefusesToGuess(unittest.TestCase):
	"""Kur bilinmiyorken çevrim sessizce bir değere düşmüyor — `unconverted`
	bayrağıyla çağırana haber veriyor. Davranışın kendisi `fx.spec.js`'te
	ölçülüyor; burada kilitlenen, bayrağın var olmaya devam etmesi."""

	def _body(self):
		fn = FX[FX.index("export function priceListRateForOrder(") :]
		return fn[: fn.index("\n// Pretty number for a rate value")]

	def test_it_reports_unconverted_when_no_rate_is_known(self):
		self.assertIn("unconverted: true", self._body())

	def test_it_does_not_fall_back_to_a_stale_constant(self):
		self.assertNotIn("12006", self._body())


class TestEquivalentAmountHasNoCurrencyLiterals(unittest.TestCase):
	"""Eski equivalentAmount UZS/CЎM/SOM/USD/EUR'u tek tek yazıyordu — her yeni
	para birimi kod değişikliği isterdi. exchangeRatePair'den türeyen genel
	kural bu sınıfın tamamını kapatıyor."""

	def _body(self):
		# Bitiş çıpası bir sembol ADI değil, "bir sonraki üst seviye const" —
		# eskiden `\nconst baseGrandTotal`e sabitlenmişti ve o satır (kullanılmayan
		# bir computed olduğu için) silindiğinde test ValueError ile patladı.
		# Gövde içindeki const'lar girintili olduğu için "\nconst " onları yakalamaz.
		fn = FORM[FORM.index("const equivalentAmount = computed(") :]
		return fn[: fn.index("\nconst ", 1)]

	def test_no_currency_literals_remain(self):
		body = self._body()
		for literal in ('"CЎM"', '"SOM"', '"UZS"', '"USD"', '"EUR"'):
			with self.subTest(literal=literal):
				self.assertNotIn(literal, body)

	def test_the_direction_comes_from_the_shared_pair(self):
		self.assertIn("exchangeRatePair.value", self._body())


class TestFetchExchangeRateFailsClosed(unittest.TestCase):
	"""catch bloğu eskiden sabit kura düşüyordu; artık null'a düşer — activeRate
	ve resolveRate bunu "kur bilinmiyor" olarak okur."""

	def _body(self):
		fn = FORM[FORM.index("async function fetchExchangeRate(") :]
		return fn[: fn.index("\n// Load existing doc")]

	def test_the_catch_block_nulls_the_rate(self):
		body = self._body()
		catch = body[body.index("} catch {") :]
		self.assertIn("exchangeRate.value = null;", catch)


class TestEveryCallSiteRespectsTheWarning(unittest.TestCase):
	"""unconverted dönüşünü yalnız bir çağıran dinlerse diğerleri sessiz yanlış
	fiyatı üretmeye devam eder. Beş çağıranın hepsi aynı deseni izlemeli:
	unconverted iken satıra dokunma, rateWarning'i set et. Dosyadaki tam
	ifadeleri sabit metin olarak arıyoruz — regex'le "hangi if hangi else'e ait"
	ayrıştırmak kırılgan olurdu, beş yerin gerçek kodu zaten önceden biliniyor.

	İki form aynı beş yeri aynı girintilerle taşıyor; ayrışırlarsa bu test
	düşer, ki port'un sadık kalıp kalmadığını ölçen şey de odur."""

	CHECK = "if (unconverted) rateWarning.value = true;"
	# refreshLineRatesForPriceList — tek satır if/else
	SITE_1 = CHECK + "\n\t\telse if (rate) line.rate = rate;"
	# handlePickItem try bloğu: tercih edilen birim dalı + varsayılan birim dalı
	SITE_2_3 = CHECK + "\n\t\t\t\telse line.rate = rate;"
	# handlePickItem catch bloğu ve field === "uom" dalı — bir tık daha dışarıda
	SITE_4_5 = CHECK + "\n\t\t\telse line.rate = rate;"

	def test_the_count_of_unconverted_checks_matches_the_known_call_sites(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertEqual(src.count(self.CHECK), 5)

	def test_each_known_call_site_pairs_the_check_with_its_else(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertIn(self.SITE_1, src)
				self.assertEqual(src.count(self.SITE_2_3), 2)
				self.assertEqual(src.count(self.SITE_4_5), 2)

	def test_no_call_site_passes_an_unconverted_price_back_as_a_fallback(self):
		# Yedek değer de satıra yazılıyor. Ham `meta.price_list_rate`'i yedek
		# olarak geçirmek, çevrilmemiş sayıyı arka kapıdan geri sokardı.
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertNotIn("resolveRate(line.item_code, meta.price_list_rate", src)


class TestTheWarningIsVisibleInBothTemplates(unittest.TestCase):
	"""Uyarı görünmezse "fiyat dolmadı" sessiz bir eksiklik olur ve kullanıcı
	sıfır fiyatlı satırı fark etmeden gönderir."""

	MESSAGE = "Exchange rate unavailable — line prices were not converted. Enter the rate manually."

	def test_the_modern_sticky_foot_shows_a_warning_when_unconverted(self):
		self.assertRegex(
			_squash(FORM),
			r'<span v-if="rateWarning" class="so-sticky-submeta text-danger fw-semibold">',
		)
		self.assertIn(self.MESSAGE, FORM)

	def test_the_classic_totals_block_shows_the_same_warning(self):
		self.assertRegex(_squash(CLASSIC), r'<div v-if="rateWarning" class="text-danger[^"]*">')
		self.assertIn(self.MESSAGE, CLASSIC)


if __name__ == "__main__":
	unittest.main()
