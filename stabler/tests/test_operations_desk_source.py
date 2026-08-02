"""Operasyon Masası'nın tasarım katmanına taşınmış hâlinin sözleşmesi.

Neden vitest değil: repo'nun vitest kapsamı bilerek SAF MANTIK ile sınırlı
(vitest.config.mjs: environment "node", jsdom yok, bileşen mount edilmiyor).
Bileşeni mount etmek için jsdom + @vue/test-utils eklemek gerekirdi; repo
bunun yerine kaynak tarayan Python testleri kullanıyor (test_*_source.py).
Aynı yolu izliyoruz.

Testler iki şeyi kilitliyor: (1) ekran gerçekten yeni dile taşınmış ve eski
Tabler işaretlemesi geri sızmamış, (2) taşımada davranış kaybolmamış.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "stabler/public/js/pages/tender/OperationsDesk.vue").read_text(encoding="utf-8")
TEMPLATE = SOURCE[SOURCE.index("<template>") : SOURCE.index("<script setup>")]


class TestDesignLayerIsSwitchedOn(unittest.TestCase):
	def test_root_carries_the_wrapper_class(self):
		self.assertIn("<TenderPage", TEMPLATE)

	def test_counter_strip_uses_the_layer(self):
		self.assertIn('class="ds-kpis"', TEMPLATE)
		self.assertIn('class="ds-kpi"', TEMPLATE)
		for part in ("ds-kpi-val", "ds-kpi-cap", "ds-kpi-note"):
			with self.subTest(part=part):
				self.assertIn(part, TEMPLATE)

	def test_work_plan_uses_bands_and_rows(self):
		for cls in ("ds-band", "ds-row", "ds-row--lead", "ds-sev", "ds-row-owner", "ds-row-due"):
			with self.subTest(cls=cls):
				self.assertIn(cls, TEMPLATE)

	def test_side_column_uses_week_and_load(self):
		for cls in ("ds-week", "ds-week-day", "ds-week-n", "ds-load", "ds-load-bar", "ds-load-n"):
			with self.subTest(cls=cls):
				self.assertIn(cls, TEMPLATE)


class TestOldMarkupIsGone(unittest.TestCase):
	"""Taşıma yarım kalırsa iki dil aynı ekranda karışır. Bunlar Tabler'ın
	kutu/rozet sınıfları — yeni dilde karşılıkları var, geri sızmamalı."""

	FORBIDDEN = (
		"card-hover",
		"list-group-item",
		"bg-primary-lt",
		"bg-danger-lt",
		"bg-warning-lt",
		"bg-info-lt",
		"btn-ghost-secondary",
		"table-sm",
	)

	def test_tabler_component_classes_are_not_reintroduced(self):
		for cls in self.FORBIDDEN:
			with self.subTest(cls=cls):
				self.assertNotIn(cls, TEMPLATE)

	def test_no_hardcoded_hex_colours_in_the_template(self):
		"""Renk katmandan gelir. Şablona hex gömmek kiracı temasından
		kopmak demektir."""
		self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", TEMPLATE), [])


class TestBehaviourSurvivedTheMigration(unittest.TestCase):
	def test_all_four_api_counters_are_still_shown(self):
		"""Görsel dil değişti; HANGİ dört sayının gösterildiği değişmedi.
		Bunları değiştirmek tasarım değil ürün kararı olurdu."""
		for counter in ("due_today", "overdue", "awaiting_me", "waiting_others"):
			with self.subTest(counter=counter):
				self.assertIn(counter, SOURCE)

	def test_every_filter_branch_is_preserved(self):
		for key in ("today", "overdue", "awaiting_me", "waiting_others"):
			with self.subTest(filter=key):
				self.assertIn(f'activeFilter.value === "{key}"', SOURCE)

	def test_pressing_an_active_counter_returns_to_the_unfiltered_view(self):
		"""Eski şablonda ayrı bir 'Tümü' düğmesi vardı; yeni dilde filtreyi
		kartlar sürüyor. Bu satır olmadan filtreden çıkış yolu kalmıyor."""
		self.assertRegex(
			SOURCE,
			r'activeFilter\.value === filterKey \? "all" : filterKey',
		)

	def test_access_gates_are_intact(self):
		self.assertIn("canAccessModule('tender')", TEMPLATE)
		self.assertIn("session.activeCompany", TEMPLATE)

	def test_routing_targets_are_unchanged(self):
		for route in ("/purchasing/orders/", "/purchasing/invoices/", "/tender/crm?deal="):
			with self.subTest(route=route):
				self.assertIn(route, SOURCE)

	def test_the_desk_endpoint_is_unchanged(self):
		self.assertIn("stabler.api.tender_desk.operations_desk", SOURCE)


class TestLanesAreDerived(unittest.TestCase):
	"""Bantlar severity'den TÜRETİLİR. Elle taşınan bir durum alanı eklemek
	iki kaynaklı gerçek yaratır ve ikisi kaçınılmaz olarak ayrışır."""

	def test_band_order_is_explicit_and_severity_driven(self):
		self.assertRegex(
			SOURCE,
			r'SEVERITY_ORDER\s*=\s*\["overdue",\s*"today",\s*"soon",\s*"info"\]',
		)

	def test_lead_item_is_picked_from_the_ordering_not_flagged(self):
		self.assertIn("for (const severity of SEVERITY_ORDER)", SOURCE)
		self.assertNotIn("is_lead", SOURCE)
		self.assertNotIn("isLead", SOURCE)

	def test_empty_groups_are_dropped(self):
		self.assertIn("filter((g) => g.items.length > 0)", SOURCE)

	def test_lead_item_is_not_repeated_inside_its_band(self):
		"""Aynı iş hem büyük kartta hem listede çıkarsa kullanıcı iki ayrı
		iş sanır."""
		self.assertIn("i !== lead", SOURCE)


class TestSeverityIsNotColourOnly(unittest.TestCase):
	"""Renk körlüğü ve tek renkli çıktı için: her severity'nin metin
	karşılığı da var."""

	def test_short_codes_exist_for_every_severity(self):
		block = SOURCE[SOURCE.index("function sevShort") :]
		block = block[: block.index("}\n\n")]
		for severity in ("overdue", "today", "soon", "info"):
			with self.subTest(severity=severity):
				self.assertIn(severity, block)


class TestTeamLoadScaling(unittest.TestCase):
	def test_bar_is_scaled_to_the_busiest_queue_not_a_made_up_ceiling(self):
		"""Uydurulmuş bir tavan yükü olduğundan hafif ya da ağır gösterir.
		Math.max(1, ...) sıfır bölmesini de kapatıyor."""
		self.assertIn("Math.max(1, ...rows.map((r) => r.open_lots || 0))", SOURCE)


class TestNoInventedData(unittest.TestCase):
	"""Tasarımda ilerleme çubukları (.ds-meter, '2/9 PO açıldı') var ama API
	plan kalemlerinde oran taşımıyor. Çizmek sayı uydurmak olurdu."""

	def test_meters_are_not_rendered_without_a_data_source(self):
		self.assertNotIn("ds-meter", TEMPLATE)


if __name__ == "__main__":
	unittest.main()
