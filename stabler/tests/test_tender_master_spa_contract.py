"""Rota bağlantısı, SPA sınırı ve i18n — taşınmış Tender CRM ekranı için.

Ekranın davranış sözleşmesi (kanban/liste, sürükle-bırak, çekmece, uç nokta
adları, tasarım katmanı sınıfları) `test_tender_crm_source.py`'de duruyor.
Burada yalnız o dosyanın kapsamadığı üç şey var: ekrana giden yol, Desk'e
sızıntı olmadığı, ve render edilen her dizgenin beş katalogda karşılığı.
İddia tekrarı bırakılmadı — çakışan her kontrol sözleşme dosyasında.
"""

import csv
import re
import unittest
from pathlib import Path

TENDER_CRM = Path(__file__).parents[1] / "public/js/pages/tender/TenderCrm.vue"
ROUTER = Path(__file__).parents[1] / "public/js/router.js"
SIDEBAR = Path(__file__).parents[1] / "public/js/components/Sidebar.vue"
TENDER_NAV = Path(__file__).parents[1] / "public/js/pages/tender/TenderNav.vue"
TRANSLATIONS = Path(__file__).parents[1] / "translations"
LANGUAGES = ("en", "ru", "uz", "uzc", "tr")
# Çıkarımın gerçekten ekranı okuduğunu kanıtlayan çapa dizgeler. Bunlar
# hedef değil kanıt: regex bozulsa ya da dosya boşalsa aşağıdaki katalog
# turu boş kümeyle sessizce geçerdi.
ANCHOR_KEYS = ("Tender CRM", "Kanban", "List", "Owner", "Readiness")


class TestTenderCrmRouteIsReachable(unittest.TestCase):
	def test_route_sidebar_and_nav_all_point_at_the_crm(self):
		"""Üçü birden olmadan ekran erişilemez: rota kaydı olmadan URL 404,
		kenar çubuğu girdisi olmadan kimse bulamaz, nav bağlantısı olmadan
		tender modülünün içinden geçilemez."""
		router = ROUTER.read_text()
		sidebar = SIDEBAR.read_text()
		nav = TENDER_NAV.read_text()
		self.assertIn('path: "/tender/crm"', router)
		self.assertIn('name: "tender-crm"', router)
		self.assertIn('path: "/tender/crm"', sidebar)
		self.assertIn('to="/tender/crm"', nav)
		self.assertIn("v-if=\"can('director') || can('sourcing')\"", nav)
		self.assertIn('{ view: "director", path: "/tender/crm"', sidebar)
		self.assertIn('{ view: "sourcing", path: "/tender/crm"', sidebar)


class TestTenderCrmStaysInsideTheSpa(unittest.TestCase):
	def test_no_desk_link_and_no_hand_written_stripe_class(self):
		"""`/app/` = Frappe Desk'e kaçış; projenin sert kuralı bunu yasaklıyor.
		`table-striped` global css'ten zaten geliyor, elle yazılması iki kez
		uygulanan bir kural demek."""
		source = TENDER_CRM.read_text()
		self.assertNotIn("/app/", source)
		self.assertNotIn("table-striped", source)


class TestTenderCrmIsFullyLocalized(unittest.TestCase):
	@staticmethod
	def _catalog(language):
		with (TRANSLATIONS / f"{language}.csv").open(newline="", encoding="utf-8") as handle:
			return {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}

	@staticmethod
	def _rendered():
		return set(re.findall(r"""\bt\(\s*["']([^"']+)["']""", TENDER_CRM.read_text()))

	def test_the_extraction_actually_sees_the_screen(self):
		rendered = self._rendered()
		for key in ANCHOR_KEYS:
			self.assertIn(key, rendered, f"{key!r} ekranda render edilmiyor — çıkarım bozuk")

	def test_every_rendered_string_has_a_filled_target_in_every_catalog(self):
		"""Elle tutulan bir anahtar listesi, kimsenin eklemeyi hatırlamadığı
		dizgeyi tanımı gereği yakalayamaz — dokuz tanesi tam böyle geçti.
		Bu yüzden liste ekranın kendisinden türetiliyor.

		Satırın var olması yetmiyor: `Anahtar,` biçimindeki boş hedef de
		kullanıcıya İngilizce gösteriyor. `Owner` ve `Readiness` tam olarak
		bu şekilde dört dilde çevrilmemiş duruyordu."""
		rendered = self._rendered()
		for language in LANGUAGES:
			catalog = self._catalog(language)
			missing = sorted(key for key in rendered if key not in catalog)
			self.assertEqual(missing, [], f"{language}: katalog satırı yok — {missing}")
			untranslated = sorted(key for key in rendered if not catalog[key].strip())
			self.assertEqual(untranslated, [], f"{language}: hedefi boş — {untranslated}")
