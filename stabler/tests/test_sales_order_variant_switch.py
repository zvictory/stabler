"""Satış Siparişi formu iki varyant hâlinde yaşıyor ve varsayılan klasik olan.

`a0c9457` klasik iki sütunlu formu tek sütunlu bir yeniden tasarımla değiştirdi
— yedi kiracının hepsinde, hiçbirine sorulmadan. Sahibin talebi eskisini geri
getirmekti, ama yeniyi silmek de aynı hatanın tersi olurdu. Bu yüzden iki form
yan yana yaşıyor ve seçim `modern_sales_order` bayrağında.

Bu dosyanın kilitlediği asıl şey **varsayılanın yönü**: bayrak yoksa,
`undefined` ise, oturum modülleri hiç yüklenmemişse — klasik form çizilir.
`v-else` olan dal budur; ters çevrilirse regresyon sessizce geri döner.

İkinci kilit: seçim rota katmanına sızmamalı. `router.js`'teki rotaların tamamı
statik `component:` taşıyor (SPA'da hiç `defineAsyncComponent` yok); ince
sarmalayıcı tam da bu değişmezi korumak için var. Rota bir varyanta doğrudan
bakmaya başlarsa bayrak o rotada devre dışı kalır.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public/js"
SWITCH = (JS / "pages/sales/SalesOrderForm.vue").read_text(encoding="utf-8")
ROUTER = (JS / "router.js").read_text(encoding="utf-8")
VARIANTS = ("SalesOrderFormClassic.vue", "SalesOrderFormModern.vue")


class TestTheSwitcherPicksOnTheFlag(unittest.TestCase):
	def test_it_imports_both_variants(self):
		for name in VARIANTS:
			with self.subTest(variant=name):
				self.assertIn(f'from "./{name}"', SWITCH)

	def test_it_reads_the_tenant_flag(self):
		self.assertIn("session.modules?.modern_sales_order", SWITCH)

	def test_the_classic_form_is_the_fallback_branch(self):
		"""`v-else` = bayrak yok/kapalı/oturum yüklenmemiş → klasik form.
		Dallar ters çevrilirse yedi kiracı yine yeni tasarıma düşer."""
		self.assertRegex(SWITCH, r"<SalesOrderFormModern\s+v-if=\"modern\"\s*/>")
		self.assertRegex(SWITCH, r"<SalesOrderFormClassic\s+v-else\s*/>")

	def test_it_stays_a_thin_wrapper(self):
		"""Sarmalayıcıya form mantığı sızarsa iki varyant sessizce üçüncü bir
		davranış paylaşmaya başlar."""
		self.assertLess(len(SWITCH.splitlines()), 40)
		code = SWITCH[SWITCH.index("*/"):]  # başlıktaki gerekçe yorumunu say(ma)
		for token in ("useDocumentForm", "call(", "MoneyInput"):
			with self.subTest(token=token):
				self.assertNotIn(token, code)


class TestTheRouterStillSeesOneComponent(unittest.TestCase):
	def test_both_sales_order_routes_point_at_the_switcher(self):
		self.assertIn('import SalesOrderForm from "./pages/sales/SalesOrderForm.vue";', ROUTER)
		self.assertEqual(2, ROUTER.count("component: SalesOrderForm,"))

	def test_no_route_reaches_past_the_switcher_into_a_variant(self):
		for name in VARIANTS:
			with self.subTest(variant=name):
				self.assertNotIn(name.replace(".vue", ""), ROUTER)

	def test_the_all_static_route_invariant_holds(self):
		self.assertNotIn("defineAsyncComponent", ROUTER)


class TestBothVariantsAreWholeForms(unittest.TestCase):
	def test_each_variant_carries_its_own_document_engine_and_payload(self):
		for name in VARIANTS:
			with self.subTest(variant=name):
				src = (JS / "pages/sales" / name).read_text(encoding="utf-8")
				self.assertIn("useDocumentForm", src)
				self.assertIn("conversion_rate:", src)


if __name__ == "__main__":
	unittest.main()
