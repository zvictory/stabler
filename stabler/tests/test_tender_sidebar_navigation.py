"""Tender gezinmesi: kenar çubuğu modülü, modül çubuğu ekranları gösterir.

Stabler'da gezinme iki katmanlı ve on beş modülün on dördü buna uyuyor: her
modülün `/modul` kökünde bir hub'ı var, kenar çubuğunda tek maddesi, ekranları
sayfanın kendi üst çubuğunda.

Tender istisnaydı ve bedelini üç kusurla ödedi:

  1. Direktör panosu (`/tender/portfolio`) kenar çubuğunda HİÇ yoktu. Ona giden
     tek yol modül çubuğuydu, o da yalnız başka bir tender sayfasındayken
     görünüyordu. Ekran taşındı, test edildi, çevrildi — ve kimse bulamadı.
  2. Kenar çubuğundaki "Kontrol Kulesi" maddesi `/tender/director`'a gidiyordu;
     o rota `/dashboard`'a redirect. Menüden tıklayan sessizce panoya düşüyordu.
  3. Aynı ekranlar iki yerde listeleniyordu ve listeler birbirini tutmuyordu.

Bu dosya artık mimariyi kilitliyor, tek tek satırları değil: kenar çubuğu modül
kökü taşır, alt yol taşımaz; modülün her ekranı modül çubuğundan erişilebilir;
modül çubuğundaki her yol gerçek bir rotaya çözülür.
"""

from __future__ import annotations

import os
import re
import unittest
from typing import ClassVar

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIDEBAR = os.path.normpath(os.path.join(_HERE, "..", "public", "js", "components", "Sidebar.vue"))
_ROUTER = os.path.normpath(os.path.join(_HERE, "..", "public", "js", "router.js"))
_TENDER_NAV = os.path.normpath(os.path.join(_HERE, "..", "public", "js", "pages", "tender", "TenderNav.vue"))


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTheSidebarCarriesModulesNotScreens(unittest.TestCase):
	"""Asıl mimari kural. Bir modül ekranlarını kenar çubuğuna dökerse iki
	gezinme yeri olur ve ikisi kaçınılmaz olarak ayrışır."""

	def setUp(self):
		self.sidebar = _read(_SIDEBAR)

	def test_tender_is_in_operations_group(self):
		self.assertIn(
			'names: ["purchasing", "imports", "tender", "tender-documents", "inventory"', self.sidebar
		)

	def test_no_tender_sub_path_is_listed_in_the_sidebar(self):
		"""`/tender/portfolio` modülün giriş kapısı; `/tender/documents` ise
		dört rolün (direktör, sourcing, declarant, logist) ortak çalışma alanı
		istisnasıdır. Kalan her `/tender/...` yolu TenderNav'a aittir."""
		paths = set(re.findall(r'"(/tender/[a-z-]+)"', self.sidebar))
		self.assertEqual(
			paths - {"/tender/portfolio", "/tender/documents"},
			set(),
			"kenar çubuğu modül ekranı listeliyor — bunlar TenderNav'a ait",
		)

	def test_the_sidebar_no_longer_carries_a_second_navigation(self):
		"""Alt menü, aç/kapa düğmesi ve rol filtresi modül çubuğuna taşındı;
		burada kalan kalıntı ikinci bir gezinme yeri demek olurdu."""
		for leftover in ("tenderChildren", "toggleTender", "nav-submenu", "sidebar-tender-children"):
			with self.subTest(leftover=leftover):
				self.assertNotIn(leftover, self.sidebar)

	def test_the_sidebar_still_primes_the_view_list(self):
		"""Modül çubuğu yalnız tender sayfalarında render ediliyor, kenar çubuğu
		her sayfada. Görünüm listesi ilk açılışta hazır olmalı, yoksa çubuk bir
		an eksik çiziliyor."""
		self.assertIn("ensureTenderViews", self.sidebar)

	def test_no_sidebar_entry_leads_to_a_bare_redirect(self):
		"""Menüden tıklayıp başka bir yere düşmek, kırık bir menü maddesidir —
		"Kontrol Kulesi" tam olarak buydu."""
		router = _read(_ROUTER)
		redirects = set(re.findall(r'\{\s*path:\s*"([^"]+)",\s*redirect:', router))
		listed = set(re.findall(r'path: "(/[a-z0-9/-]+)"', self.sidebar))
		self.assertEqual(listed & redirects, set(), "kenar çubuğu bir redirect rotasına bağlanmış")


class TestTheModuleBarCarriesEveryScreen(unittest.TestCase):
	def setUp(self):
		self.nav = _read(_TENDER_NAV)
		self.router = _read(_ROUTER)

	def test_the_bar_uses_the_design_layer(self):
		"""Tasarımın modül navı; altı referans sayfasının hepsinde bu çubuk var."""
		self.assertIn('class="ds-modnav"', self.nav)
		self.assertIn("stbl-ds", self.nav)
		self.assertIn("ds-modnav-brand", self.nav)

	# Modül çubuğuna GİRMEYEN rotalar. Buraya bir yol eklemek bilinçli bir
	# karardır: "bu ekran modülün bir sayfası değil, bir kaydın detayı".
	DRILL_DOWNS: ClassVar[set[str]] = {
		# Bir anlaşmanın teklif karşılaştırması. `?deal=` ile geliyor ve beş
		# ayrı ekrandan linkli (Sözleşme panosu, CRM çekmecesi, PO kontrol,
		# Tedarikçiler, CRM Anlaşmalar). Çubuğa koymak dokuzuncu maddeyi
		# eklerdi ve kullanıcı oraya bağlamsız gitmez.
		"/tender/sourcing",
		"/tender/overview",
		"/tender/documents",
		# RFQ oluşturma akışı: her zaman bir lot bağlamıyla (`?deal=`) gelir —
		# RFQ listesinin "New request" düğmesinden ve sourcing workspace'in
		# "Request for quotation" bağlantısından. Çubukta liste (`/tender/rfq`)
		# var; oluşturma bağlamsız bir varış noktası değil.
		"/tender/rfq/new",
	}

	def test_every_tender_screen_is_reachable_from_the_bar(self):
		"""Rotası olup hiçbir yerden linklenmeyen ekran ölü koddur. Direktör
		panosu neredeyse öyle oldu — ve `TenderControlTower.vue` gerçekten öyle
		(319 satır, hiçbir rota, hiçbir import)."""
		routed = set(re.findall(r'path: "(/tender/[a-z-]+)"[^}]*?component:', self.router))
		linked = set(re.findall(r'to="(/tender/[a-z-]+)"', self.nav))
		self.assertEqual(
			routed - linked - self.DRILL_DOWNS,
			set(),
			"rotası var, modül çubuğunda yok ve drill-down olarak da işaretlenmemiş",
		)

	def test_every_drill_down_is_linked_from_a_real_screen(self):
		"""Muafiyet bir kaçış kapısı olmamalı: çubuğa girmeyen ekran EN AZ bir
		yerden linklenmeli, yoksa muafiyet listesi ölü kodun saklandığı yer
		olur. Sorgu taşıyan bağlantılar SPA'nın deyimi olan isim-tabanlı
		router-link kullanır; yolun kendisi ya da rota adı eşleşir."""
		pages = os.path.normpath(os.path.join(_HERE, "..", "public", "js"))
		sources = []
		for root, _dirs, files in os.walk(pages):
			for name in files:
				if name.endswith(".vue"):
					sources.append(_read(os.path.join(root, name)))
		blob = "\n".join(sources)
		for path in sorted(self.DRILL_DOWNS):
			route_name = path.lstrip("/").replace("/", "-")
			with self.subTest(path=path):
				self.assertTrue(
					path in blob or f'"{route_name}"' in blob,
					f"{path} hiçbir ekrandan linklenmiyor — öksüz",
				)

	def test_every_tender_screen_actually_renders_the_bar(self):
		"""Çubuğun VAR olması yetmiyor; ekranın onu ÇİZMESİ gerekiyor.

		Ölçüldü 2026-08-01: `/tender/desk`, `/tender/board`, `/tender/sourcing`
		ve `/tender/po-control` TenderNav'ı hiç import etmiyordu. Kenar
		çubuğundan tender'a giren kullanıcı menüsüz bir sayfaya düşüyor, oradan
		başka bir tender ekranına geçemiyordu — Direktör panosunun kaybolma
		hikâyesinin aynısı, bu sefer giriş kapısında. Üstelik o dört ekranın
		üçü, çubuğun taşıdığı bağlantıların kendi seçtikleri bir alt kümesini
		sayfa başlığına düğme olarak serpiştirmişti: kenar çubuğundan
		kaldırdığımız ikinci navigasyon, dağılmış hâliyle geri gelmişti.

		Bu iddia rotalardan türüyor, elle yazılmış listeden değil: yeni bir
		tender ekranı eklendiğinde de kendiliğinden kapsanır.
		"""
		js_root = os.path.normpath(os.path.join(_HERE, "..", "public", "js"))
		imports = dict(re.findall(r'import (\w+) from "\.(/[^"]+\.vue)";', self.router))
		screens = re.findall(r'path: "(/tender/[a-z-]+)"[^}]*?component:\s*(\w+)', self.router)
		self.assertTrue(screens, "router'da hiç tender ekranı bulunamadı — desen bozulmuş")
		for path, component in sorted(screens):
			if path in self.DRILL_DOWNS:
				continue
			with self.subTest(path=path):
				rel = imports.get(component)
				self.assertIsNotNone(rel, f"{component} import satırı bulunamadı")
				source = _read(os.path.normpath(os.path.join(js_root, rel.lstrip("/"))))
				self.assertTrue(
					"<TenderNav" in source or "<TenderPage" in source,
					f"{path} ({component}) modül çubuğunu çizmiyor — menüsüz açılıyor",
				)

	def test_no_tender_screen_keeps_its_own_link_row(self):
		"""Çubuk geldikten sonra sayfa başlığındaki tender bağlantıları ikinci
		bir gezinme yeridir; ikisi kaçınılmaz olarak ayrışır (bu dosyanın
		docstring'indeki üçüncü kusur). İstisna `?deal=` taşıyan drill-down
		linkleri: onlar gezinme değil, bir KAYDA gidiş."""
		js_root = os.path.normpath(os.path.join(_HERE, "..", "public", "js"))
		imports = dict(re.findall(r'import (\w+) from "\.(/[^"]+\.vue)";', self.router))
		for path, component in sorted(
			re.findall(r'path: "(/tender/[a-z-]+)"[^}]*?component:\s*(\w+)', self.router)
		):
			rel = imports.get(component)
			if not rel:
				continue
			source = _read(os.path.normpath(os.path.join(js_root, rel.lstrip("/"))))
			bare = re.findall(r'<router-link\s+to="(/tender/[a-z-]+)"', source)
			with self.subTest(path=path):
				self.assertEqual(
					bare, [], f"{path} ({component}) kendi tender bağlantı satırını taşıyor: {bare}"
				)

	def test_every_link_in_the_bar_resolves_to_a_route(self):
		for path in sorted(set(re.findall(r'to="(/[a-z0-9/-]+)"', self.nav))):
			with self.subTest(path=path):
				self.assertRegex(
					self.router,
					rf'path: "{re.escape(path)}"',
					f"{path} modül çubuğunda var ama router'da yok",
				)

	def test_the_director_board_is_linked_and_role_gated(self):
		self.assertIn('to="/tender/portfolio"', self.nav)
		self.assertRegex(self.nav, r"v-if=\"can\('director'\)\"\s+to=\"/tender/portfolio\"")

	def test_role_gating_survived_the_move(self):
		"""Kapılar kenar çubuğundan buraya taşındı; taşınırken gevşemiş olamaz."""
		self.assertIn("session.tenderViews.includes(view)", self.nav)
		for view, path in (
			("sourcing", "/tender/my-tenders"),
			("sourcing", "/tender/po-control"),
			("declarant", "/tender/customs"),
			("logist", "/tender/logistics"),
		):
			with self.subTest(view=view, path=path):
				self.assertRegex(self.nav, rf"v-if=\"can\('{view}'\)\"\s+to=\"{re.escape(path)}\"")

	def test_the_crm_is_open_to_both_director_and_sourcing(self):
		self.assertRegex(self.nav, r"v-if=\"can\('director'\) \|\| can\('sourcing'\)\"\s+to=\"/tender/crm\"")

	def test_there_is_a_way_back_to_the_dashboard(self):
		"""Konum değil VARLIK garanti: modüller arası geçiş artık kenar
		çubuğunun işi, ama pano tender'ın da özeti (Masa oraya gömülü)."""
		self.assertIn('to="/dashboard"', self.nav)
		self.assertIn('t("Overview")', self.nav)

	def test_the_dead_bookmark_is_not_linked(self):
		self.assertNotIn('to="/tender/director"', self.nav)


class TestTheOperationsDeskRouteIsWhole(unittest.TestCase):
	"""Rota kaydı olmadan ekran ölü kod: `api/tender_desk.py` prod'da canlıydı
	ama ona giden `/tender/desk` rotası hiçbir commit'te yoktu — yalnız bir
	oturumun commit'lenmemiş `router.js`'inde duruyordu."""

	def test_route_is_registered_module_gated_and_resolvable(self):
		router = _read(_ROUTER)
		self.assertIn('import OperationsDesk from "./pages/tender/OperationsDesk.vue";', router)
		route = next((line for line in router.splitlines() if '"/tender/desk"' in line), "")
		self.assertIn('name: "tender-desk"', route)
		self.assertIn("component: OperationsDesk", route)
		self.assertIn('module: "tender"', route)
		self.assertTrue(
			os.path.exists(
				os.path.normpath(
					os.path.join(_HERE, "..", "public", "js", "pages", "tender", "OperationsDesk.vue")
				)
			),
			"rota OperationsDesk.vue'ye bağlanıyor ama dosya depoda yok",
		)

	def test_the_old_director_bookmark_still_lands_somewhere(self):
		"""Redirect'in kendisi doğru: `/tender/director` eski bir yer imi ve
		404 vermemeli. Kusur onu bir MENÜ MADDESİ olarak sunmaktı."""
		router = _read(_ROUTER)
		self.assertIn('{ path: "/tender/director", redirect: "/tender/portfolio"', router)


if __name__ == "__main__":
	unittest.main()
