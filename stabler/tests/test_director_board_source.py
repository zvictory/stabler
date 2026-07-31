"""Direktör panosunun tasarım katmanına taşınmış hâlinin sözleşmesi.

Aynı gerekçe test_operations_desk_source.py'deki gibi: repo'nun vitest kapsamı
saf mantıkla sınırlı (jsdom yok, mount yok), bileşen sözleşmesi kaynak
taramasıyla kilitleniyor.

Bu ekranda kaybolması EN kolay şey davranış: satır tıklaması, yönetici atama,
rota filtreleri ve otomatik yenileme hepsi şablonun içinde duruyor.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "stabler/public/js/pages/tender/DirectorBoard.vue").read_text(encoding="utf-8")
TEMPLATE = SOURCE[SOURCE.index("<template>"): SOURCE.index("<style scoped>")]


class TestDesignLayerIsSwitchedOn(unittest.TestCase):
	def test_root_carries_the_wrapper_class(self):
		self.assertRegex(TEMPLATE, r'class="director-board-page stbl-ds"')

	def test_counter_strip_and_table_use_the_layer(self):
		for cls in ("ds-kpis", "ds-kpi", "ds-kpi-val", "ds-kpi-note", "ds-kpi-q",
		            "ds-panel", "ds-panel-head", "ds-panel-foot", "ds-table", "ds-td-num", "ds-chip"):
			with self.subTest(cls=cls):
				self.assertIn(cls, TEMPLATE)


class TestOldMarkupIsGone(unittest.TestCase):
	FORBIDDEN = (
		"card-table", "card-body", "badge", "bg-green-lt", "bg-red-lt",
		"bg-yellow-lt", "bg-secondary-lt", "btn-ghost-secondary",
		"form-select", "container-xl", "text-secondary", "font-monospace",
	)

	def test_tabler_component_classes_are_not_reintroduced(self):
		for cls in self.FORBIDDEN:
			with self.subTest(cls=cls):
				self.assertNotIn(cls, TEMPLATE)

	def test_no_hardcoded_hex_colours_in_the_template(self):
		self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", TEMPLATE), [])


class TestBehaviourSurvivedTheMigration(unittest.TestCase):
	"""Bu ekran salt okunur DEĞİL — satır tıklaması ve yönetici ataması var.
	Yeniden yazımda en kolay düşecek şeyler bunlar."""

	def test_row_click_still_opens_the_deal(self):
		self.assertRegex(TEMPLATE, r'@click="openDeal\(r\.deal\)"')

	def test_manager_cell_stops_propagation(self):
		"""Atama hücresi satır tıklamasını yutmalı; yoksa açılır menüyü
		açmaya çalışan her tıklama sayfayı değiştirir."""
		self.assertIn("@click.stop", TEMPLATE)

	def test_assignment_still_calls_the_endpoint(self):
		self.assertIn("stabler.api.tender.assign_tender", SOURCE)
		self.assertIn("stabler.api.tender.tender_managers", SOURCE)

	def test_board_endpoint_is_unchanged(self):
		self.assertIn("stabler.api.tender.tender_director_board", SOURCE)

	def test_route_filters_and_clear_are_kept(self):
		for symbol in ("tenderRouteFilters", "activeTenderFilters", "filterTenderRows", "clearFilters"):
			with self.subTest(symbol=symbol):
				self.assertIn(symbol, SOURCE)

	def test_auto_refresh_and_escape_back_are_kept(self):
		self.assertIn("useAutoRefresh(load)", SOURCE)
		self.assertIn("useEscapeBack", SOURCE)

	def test_the_embedded_funnel_is_still_rendered(self):
		self.assertIn("<TenderFunnel />", TEMPLATE)
		self.assertIn("<TenderNav />", TEMPLATE)


class TestNoCounterWasDropped(unittest.TestCase):
	"""Görsel dil değişti; HANGİ sayıların gösterildiği değişmedi. Bir sayacı
	elemek tasarım değil ürün kararı olurdu."""

	KPI_KEYS = ("count", "win_rate", "at_risk", "total_value", "avg_margin", "ostatok")

	def test_all_six_counters_are_present(self):
		block = SOURCE[SOURCE.index("const kpis = computed"):SOURCE.index("const unverified")]
		for key in self.KPI_KEYS:
			with self.subTest(kpi=key):
				self.assertIn(f'key: "{key}"', block)

	def test_every_counter_states_the_rule_that_produced_it(self):
		"""Tasarımın imzası: her rakam kendi sorgusunu taşır."""
		block = SOURCE[SOURCE.index("const kpis = computed"):SOURCE.index("const unverified")]
		self.assertEqual(block.count("rule:"), len(self.KPI_KEYS))
		self.assertEqual(block.count("note:"), len(self.KPI_KEYS))


class TestUnverifiedHistoryIsSurfaced(unittest.TestCase):
	def test_warning_is_hidden_when_the_count_is_zero(self):
		"""Sıfır göstermek gürültü; uyarı yalnız gerçekten eksik kayıt
		varken çıkmalı."""
		self.assertRegex(TEMPLATE, r'v-if="unverified"')


class TestStatusIsNotColourOnly(unittest.TestCase):
	"""Renk körlüğü ve tek renkli çıktı için: risk ve sonuç rozetlerinin
	metin karşılığı da var."""

	def test_risk_and_result_have_text_labels(self):
		self.assertIn("riskLabel", SOURCE)
		self.assertIn("resultLabel", SOURCE)
		for state in ("good", "warn", "risk"):
			with self.subTest(state=state):
				self.assertIn(state, SOURCE[SOURCE.index("const riskLabel"):][:220])


class TestWideTableScrollsItself(unittest.TestCase):
	def test_table_has_its_own_scroll_container(self):
		"""Dokuz sütun dar ekrana sığmıyor. Sayfanın tamamını yatay
		kaydırmak yerine tabloyu kaydır."""
		self.assertIn('class="board-scroll"', TEMPLATE)
		self.assertRegex(SOURCE, r"\.board-scroll\s*\{[^}]*overflow-x:\s*auto")


if __name__ == "__main__":
	unittest.main()
