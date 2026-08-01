"""Satış Siparişi kur koruması: bilinmeyen kur asla sessizce sabit değere düşmemeli.

Antigravity'nin commit'i (`a0c9457`) `resolveRate()`'e sabit bir kur (`12006.39`)
gömmüştü: `get_currency_exchange_rate` çağrısı düşerse ya da eşik testi (`> 100`)
meşru bir kur çiftini (ör. EUR→USD ≈ 1.08) elerse, satır fiyatı o bayat sabitle
hesaplanıp **hiçbir uyarı olmadan** kaydediliyordu. CLAUDE.md'nin "tenant variance
lives in config/data, never in code constants" kuralının doğrudan ihlaliydi ve
kaydedilen paraya yazan tek bulguydu.

Düzeltme: kur bilinmiyorsa çeviri yapılmaz, çağıran satırın fiyatına dokunmaz,
kullanıcıya görünür bir uyarı çıkar. Bu dosya o davranışı kaynaktan kilitliyor —
render'ı değil, testin kendi projesindeki diğer `_source.py` testleri gibi.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = (ROOT / "public/js/pages/sales/SalesOrderForm.vue").read_text(encoding="utf-8")


def _squash(text: str) -> str:
	return re.sub(r"\s+", " ", text)


class TestTheHardcodedRateIsGone(unittest.TestCase):
	"""Sabit kur bir kere gömülüp unutulursa geri gelmesi kolay olur — literal
	arama, hangi fonksiyonda olursa olsun onu yakalar."""

	def test_the_literal_appears_nowhere_in_the_file(self):
		self.assertEqual(FORM.count("12006"), 0)


class TestResolveRateRefusesToGuess(unittest.TestCase):
	"""Kur bilinmiyorken resolveRate artık sessizce sabit bir değere düşmüyor —
	unconverted bayrağıyla çağırana haber veriyor."""

	def _body(self):
		fn = FORM[FORM.index("async function resolveRate("):]
		return fn[: fn.index("\nasync function refreshLineRatesForPriceList")]

	def test_the_function_reports_unconverted_when_no_rate_is_known(self):
		self.assertIn("unconverted: true", self._body())

	def test_it_does_not_fall_back_to_a_stale_constant(self):
		self.assertNotIn("12006", self._body())


class TestEquivalentAmountHasNoCurrencyLiterals(unittest.TestCase):
	"""Eski equivalentAmount UZS/CЎM/SOM/USD/EUR'u tek tek yazıyordu — her yeni
	para birimi kod değişikliği isterdi. exchangeRatePair'den türeyen genel
	kural bu sınıfın tamamını kapatıyor."""

	def _body(self):
		fn = FORM[FORM.index("const equivalentAmount = computed("):]
		return fn[: fn.index("\nconst baseGrandTotal")]

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
		fn = FORM[FORM.index("async function fetchExchangeRate("):]
		return fn[: fn.index("\n// Load existing doc")]

	def test_the_catch_block_nulls_the_rate(self):
		body = self._body()
		catch = body[body.index("} catch {"):]
		self.assertIn("exchangeRate.value = null;", catch)


class TestEveryCallSiteRespectsTheWarning(unittest.TestCase):
	"""unconverted dönüşünü yalnız bir çağıran dinlerse diğer üç yer sessiz yanlış
	fiyatı üretmeye devam eder. Dört çağıranın hepsi aynı deseni izlemeli:
	unconverted iken satıra dokunma, rateWarning'i set et. Dosyadaki tam ifadeleri
	sabit metin olarak arıyoruz — regex'le "hangi if hangi else'e ait" ayrıştırmak
	kırılgan olurdu, dört yerin gerçek kodu zaten önceden biliniyor."""

	# refreshLineRatesForPriceList — tek satır if/else
	SITE_1 = "if (unconverted) rateWarning.value = true;\n\t\telse if (rate) line.rate = rate;"
	# handlePickItem try bloğu — tek satır if/else (uom dalıyla ve catch bloğuyla aynı girinti)
	SITE_2_3 = "if (unconverted) rateWarning.value = true;\n\t\t\t\telse line.rate = rate;"
	# handlePickItem catch bloğu ve field === "uom" dalı — birbirinden bir tık daha içeride
	SITE_4 = "if (unconverted) rateWarning.value = true;\n\t\t\telse line.rate = rate;"

	def test_the_count_of_unconverted_checks_matches_the_known_call_sites(self):
		self.assertEqual(FORM.count("if (unconverted) rateWarning.value = true;"), 4)

	def test_each_known_call_site_pairs_the_check_with_its_else(self):
		self.assertIn(self.SITE_1, FORM)
		self.assertEqual(FORM.count(self.SITE_2_3), 1)
		self.assertEqual(FORM.count(self.SITE_4), 2)


class TestTheWarningIsVisibleInTheTemplate(unittest.TestCase):
	def test_the_sticky_foot_shows_a_warning_when_unconverted(self):
		self.assertRegex(
			_squash(FORM),
			r'<span v-if="rateWarning" class="so-sticky-submeta text-danger fw-semibold">',
		)
		self.assertIn(
			"Exchange rate unavailable — line prices were not converted. Enter the rate manually.",
			FORM,
		)


if __name__ == "__main__":
	unittest.main()
