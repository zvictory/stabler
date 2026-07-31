"""Nakliye masası ekranının kaynak düzeyli koruyucuları.

Bu ekran (`/imports/transporters`) `imports` modülüne, yani **msa** kiracısına
ait: navlun maliyeti ve nakit/banka ödeme kırılımı taşıyor. Buradaki testlerin
tamamı Frappe önyüklemesi olmadan koşar — dosyaları okur, `ast` ile ayrıştırır.
Amaç davranışı değil, davranışın dayandığı **sözleşmeyi** tutmak: şirket süzgeci,
bağlanmamış SQL parametresi kalmaması, permlevel 1 maskesi ve ekranın erişilebilir
olması.
"""

from __future__ import annotations

import ast
import csv
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.normpath(os.path.join(_HERE, ".."))
_IMPORTS_API = os.path.join(_APP, "api", "imports.py")
_IMPORTS_RULES = os.path.join(_APP, "api", "_imports_rules.py")
_ROUTER = os.path.join(_APP, "public", "js", "router.js")
_IMPORTS_HOME = os.path.join(_APP, "public", "js", "pages", "imports", "ImportsHome.vue")
_SCREEN = os.path.join(_APP, "public", "js", "pages", "imports", "TransporterCenter.vue")

LANGUAGES = ("en", "ru", "uz", "uzc", "tr")


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as source:
		return source.read()


def _function_source(path: str, name: str) -> str:
	"""Bir fonksiyonun kendi gövdesi — dosyanın tamamı değil.

	Dosya 7000 satırın üzerinde ve aynı dizgeler başka uçlarda da geçiyor;
	`assertIn(..., whole_file)` bu yüzden neredeyse her zaman geçer ve hiçbir
	şey kanıtlamaz."""
	text = _read(path)
	tree = ast.parse(text)
	node = next(
		n
		for n in tree.body
		if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
	)
	lines = text.splitlines()
	return "\n".join(lines[node.lineno - 1 : node.end_lineno])


class TestTransporterDashboardQuery(unittest.TestCase):
	"""`transporter_dashboard` SQL sözleşmesi."""

	@classmethod
	def setUpClass(cls):
		cls.fn = _function_source(_IMPORTS_API, "transporter_dashboard")

	def test_every_sql_placeholder_is_bound(self):
		"""`%(search)s` sorguya yazılmış ama `query_params`'a hiç konmamıştı:
		arama kutusuna bir harf yazan her kullanıcı 500 alıyordu, yani özellik
		canlıda ölüydü. Bağlanmamış tek bir isim bile aynı hatayı geri getirir."""
		placeholders = set(re.findall(r"%\((\w+)\)s", self.fn))
		bound = set(re.findall(r"""query_params\[["'](\w+)["']\]\s*=""", self.fn))
		literal = re.search(r"query_params[^=\n]*=\s*(\{[^}]*\})", self.fn)
		if literal:
			bound |= set(re.findall(r"""["'](\w+)["']\s*:""", literal.group(1)))
		self.assertTrue(placeholders, "sorguda hiç adlandırılmış parametre yok — test yanlış yeri okuyor")
		self.assertEqual(
			sorted(placeholders - bound),
			[],
			"SQL'de geçen ama query_params'a bağlanmayan parametre var",
		)

	def test_query_is_scoped_to_the_requested_company(self):
		"""`_assert_imports_access(company)` yalnız *o* şirketin ithalatını
		okuyabileceğini kanıtlar. WHERE şirkete bağlanmazsa aynı sitedeki her
		şirketin navlun maliyeti ve ödeme kırılımı dönerdi."""
		self.assertIn('"fb.company = %(company)s"', self.fn)
		self.assertIn("%(company)s", self.fn)

	def test_summary_is_grouped_by_currency_not_summed_across(self):
		"""`fb.currency` yalnızca USD'ye *varsayılan* bir Link alanı. Tek bir SUM
		UZS ile USD'yi toplayıp sonucu sayfanın en büyük yazısında USD diye
		gösteriyordu. CLAUDE.md tam bunu yasaklıyor: tutarlar kendi para
		biriminde, toplamlar hiç çevrilmeden."""
		self.assertIn("GROUP BY COALESCE(fb.currency, 'USD')", self.fn)
		self.assertIn('"currency": s.currency or "USD"', self.fn)

	def test_money_is_masked_for_rows_and_for_the_summary(self):
		"""`amount`, `cash_payment`, `bank_payment` doctype'ta permlevel 1.
		Bu uç onları yeni takma adlar altında yansıtıyor — maskeden tam da
		böyle kaçmışlardı. Yalnız satırları maskelemek de yetmez: özet, gizli
		rakamların toplamıdır."""
		self.assertIn("rules.mask_named(formatted_rows, rules.TRANSPORTER_ROW_MASK_FIELDS, visible)", self.fn)
		self.assertIn("rules.mask_named(summary, rules.TRANSPORTER_SUMMARY_MASK_FIELDS, visible)", self.fn)
		self.assertIn("visible = _cost_visible()", self.fn)

	def test_mask_field_names_match_the_aliases_the_endpoint_projects(self):
		"""`mask_named` anahtarları birebir eşleştirir. Takma ad ile maske
		listesi bir harf ayrışırsa maske hiçbir şeyi boşaltmaz ama kod
		maskeliyormuş gibi okunur — sessiz sızıntının en kötü biçimi."""
		rules_src = _read(_IMPORTS_RULES)
		for tuple_name in ("TRANSPORTER_ROW_MASK_FIELDS", "TRANSPORTER_SUMMARY_MASK_FIELDS"):
			block = re.search(rf"{tuple_name}[^=]*=\s*\((.*?)\)", rules_src, re.S)
			self.assertIsNotNone(block, f"{tuple_name} bulunamadı")
			fields = re.findall(r'"([^"]+)"', block.group(1))
			self.assertTrue(fields, f"{tuple_name} boş")
			for field in fields:
				self.assertIn(
					f'"{field}"',
					self.fn,
					f"{tuple_name} içindeki {field!r} uçtaki hiçbir anahtarla eşleşmiyor",
				)


class TestTransporterWritePath(unittest.TestCase):
	"""`save_container_transport_cost` yazma yolu."""

	@classmethod
	def setUpClass(cls):
		cls.fn = _function_source(_IMPORTS_API, "save_container_transport_cost")

	def test_the_written_record_is_bound_to_the_claimed_company(self):
		"""`company` çağıranın iddiası, `name` ise gerçekten yazılan kayıt.
		Erişebildiğin bir şirket + başka şirketin rezervasyon adı verilirse
		erişim denetimi geçer, yazma başka yere düşer."""
		self.assertIn('frappe.db.get_value("Freight Booking", name, "company") != company', self.fn)
		self.assertIn("_assert_imports_access(company)", self.fn)

	def test_writing_permlevel_1_costs_requires_the_cost_gate(self):
		"""Yazılan alanların tümü permlevel 1. Okuyamadığın rakamı yazabilmek,
		o rakamı yoklamanın bir yoludur."""
		self.assertIn("_assert_cost_visible()", self.fn)
		self.assertIn('_assert_can_write("Freight Booking", name, "write")', self.fn)


class TestTransporterScreenIsReachable(unittest.TestCase):
	"""Rota + kapı. İkisi olmadan ekran ölü kod."""

	@classmethod
	def setUpClass(cls):
		cls.router = _read(_ROUTER)
		cls.home = _read(_IMPORTS_HOME)

	def test_route_is_registered_module_gated_and_resolvable(self):
		self.assertIn('import TransporterCenter from "./pages/imports/TransporterCenter.vue";', self.router)
		route = next((line for line in self.router.splitlines() if '"transporters"' in line), "")
		self.assertIn('name: "imports-transporters"', route)
		self.assertIn("component: TransporterCenter", route)
		self.assertIn('module: "imports"', route)
		self.assertTrue(
			os.path.exists(_SCREEN),
			"rota TransporterCenter.vue'ye bağlanıyor ama dosya depoda yok",
		)

	def test_the_screen_has_a_front_door_in_the_imports_module_header(self):
		"""Kenar çubuğunda `imports` girdisinin çocuğu yok; modülün gezinmesi
		tamamen `ImportsHome.vue` sekmelerinden geliyor. Sekme eklenmezse rota
		yalnız elle URL yazarak açılır — CLAUDE.md'nin yasakladığı Desk
		yönlendirmesine düşmenin sessiz yolu."""
		self.assertIn('name: "imports-transporters"', self.home)
		self.assertIn('path: "/imports/transporters"', self.home)

	def test_the_active_tab_resolver_does_not_swallow_the_route_name(self):
		"""`activeTab` bir dizi `startsWith` zinciri; `imports-tr…` ile başlayan
		bir kural eklenirse bu sekme başka bir sekmeyi yakar ve hiç
		işaretlenmez."""
		swallowing = [
			prefix
			for prefix in re.findall(r'n\.startsWith\("([^"]+)"\)', self.home)
			if "imports-transporters".startswith(prefix)
		]
		self.assertEqual(swallowing, [], f"bu önekler rota adını yutuyor: {swallowing}")


class TestTransporterScreenConventions(unittest.TestCase):
	"""CLAUDE.md'nin SPA kuralları — hepsi gözden kaçması kolay olanlar."""

	@classmethod
	def setUpClass(cls):
		cls.screen = _read(_SCREEN)

	def test_no_desk_redirect(self):
		self.assertNotIn("/app/", self.screen)

	def test_money_uses_the_shared_input_and_never_a_bare_number_field(self):
		self.assertIn('import MoneyInput from "../../components/MoneyInput.vue";', self.screen)
		self.assertNotIn('type="number"', self.screen)

	def test_striping_is_not_hand_written(self):
		self.assertNotIn("table-striped", self.screen)

	def test_masked_money_is_not_rendered_as_zero(self):
		"""Maskelenen tutar `null` döner. `formatMoney(null)` bunu `0,00` yazar;
		kullanıcı da "borç yok" diye okur. Doğrusu "görme yetkin yok"tur."""
		self.assertIn("if (value === null || value === undefined) return", self.screen)
		money_calls = len(re.findall(r"\bmoney\(", self.screen))
		self.assertGreaterEqual(money_calls, 8, "para hücreleri money() yardımcısından geçmiyor")

	def test_in_flight_responses_cannot_overwrite_a_newer_one(self):
		"""Süzgeç, arama ve sayfa aynı `load()`u tetikliyor; jeton olmadan yavaş
		bir ilk yanıt hızlı ikinciyi eziyor ve tablo süzgeçle uyuşmaz kalıyor."""
		self.assertIn("let reqToken = 0;", self.screen)
		self.assertIn("const token = ++reqToken;", self.screen)
		# Üç yol da korunmalı: başarı, hata ve `finally`. Yalnız başarıyı
		# korumak eski bir hatanın mesajını yeni yanıtın üstüne yazar; yalnız
		# `finally`yi bırakmak da iptal edilmiş bir isteğin yüklenme göstergesini
		# kapatmasına izin verir.
		self.assertGreaterEqual(
			self.screen.count("if (token !== reqToken) return;"),
			2,
			"yarış jetonu hem başarı hem hata yolunda kontrol edilmeli",
		)
		self.assertIn("if (token === reqToken) loading.value = false;", self.screen)

	def test_search_is_debounced_through_the_toolbar_not_watched_per_keystroke(self):
		"""`ListToolbar` modeli her tuşta günceller, yalnız `search` olayını
		geciktirir. `search` ref'ini izlemek harf başına bir istek demekti."""
		self.assertIn('@search="reload"', self.screen)
		watched = re.findall(r"watch\(\s*(\[[^\]]*\]|\w+)", self.screen)
		self.assertTrue(watched, "hiç watch yok — test yanlış yeri okuyor")
		self.assertEqual(
			[w for w in watched if re.search(r"\bsearch\b", w)],
			[],
			"search ref'i izleniyor — her tuşta bir istek gider",
		)

	def test_filter_changes_reset_to_the_first_page(self):
		"""3. sayfadayken süzgeç değiştirmek, kısalmış sonucun boş bir
		sayfasına düşürüyordu."""
		self.assertIn("function reload() {", self.screen)
		self.assertIn("if (page.value !== 1) page.value = 1;", self.screen)

	def test_the_edit_action_is_hidden_when_costs_are_masked(self):
		"""Uç, maliyet kapısı olmadan bu yazmayı reddediyor. Her zaman görünen
		bir Düzenle düğmesi yalnızca "—" dolu bir formu açıp kaydetmede hata
		verirdi."""
		self.assertIn('v-if="costVisible"', self.screen)


class TestTransporterScreenTranslations(unittest.TestCase):
	"""Ekranın kendi kaynağından çıkarılan anahtarlar, beş katalogda dolu mu."""

	#: Çıkarımın gerçekten *bu* ekranı okuduğunun kanıtı. Regex bozulursa
	#: boş küme döner ve döngü sessizce geçerdi.
	ANCHOR_KEYS = (
		"Transport operations desk",
		"Total Freight Cost",
		"Transporter Vendor",
	)

	@classmethod
	def setUpClass(cls):
		cls.rendered = set(re.findall(r"""\bt\(\s*["']([^"']+)["']""", _read(_SCREEN)))

	@staticmethod
	def _catalog(language: str) -> dict[str, str]:
		path = os.path.join(_APP, "translations", f"{language}.csv")
		with open(path, encoding="utf-8") as handle:
			return {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}

	def test_the_extraction_actually_reads_the_screen(self):
		for key in self.ANCHOR_KEYS:
			self.assertIn(key, self.rendered)

	def test_every_rendered_string_has_a_filled_target_in_every_catalog(self):
		for language in LANGUAGES:
			catalog = self._catalog(language)
			missing = sorted(key for key in self.rendered if key not in catalog)
			self.assertEqual(missing, [], f"{language}: katalog satırı yok — {missing}")
			untranslated = sorted(key for key in self.rendered if not catalog[key].strip())
			self.assertEqual(untranslated, [], f"{language}: hedefi boş — {untranslated}")

	def test_the_backend_error_string_is_translated_too(self):
		"""Şirket bağlama denetimi yeni bir `_()` anahtarı getirdi; Python
		tarafındaki dizgeler de aynı beş katalogdan geçiyor."""
		key = "Freight Booking {0} belongs to another company."
		self.assertIn(key, _function_source(_IMPORTS_API, "save_container_transport_cost"))
		for language in LANGUAGES:
			catalog = self._catalog(language)
			self.assertIn(key, catalog, f"{language}: katalog satırı yok")
			self.assertTrue(catalog[key].strip(), f"{language}: hedefi boş")


if __name__ == "__main__":
	unittest.main()
