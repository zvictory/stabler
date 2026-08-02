"""Tender CRM ekranının tasarım katmanına göçü.

Ekran paylaşılan Tabler bileşenlerinden `.stbl-ds` diline taşındı: kanban
`.ds-kanban/.ds-col/.ds-card`, yandan kayan detay `.ds-drawer` ailesi. Göç
ŞABLON değişikliği; iş mantığı (crm_board, move_deal_stage, sürükle-bırak,
çekmece yükleme) olduğu gibi kaldı.

Bu dosyanın koruduğu üç şey:

  1. Göç TAM olmalı. Yarı taşınmış bir ekran en kötüsü — iki tasarım dili aynı
     sayfada. O yüzden Tabler kalıntıları tek tek aranıyor.
  2. Davranış korunmalı. Bir şablon yeniden yazımının verebileceği tek söz bu.
  3. Tıklanabilir her şey klavyeyle de çalışmalı. Kart artık <div>; sürükleme
     ile buton çakıştığı için böyle, ama o zaman role/tabindex/Enter şart.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRM = (ROOT / "public/js/pages/tender/TenderCrm.vue").read_text(encoding="utf-8")
CSS = (ROOT / "public/css/stabler-modernist.css").read_text(encoding="utf-8")

# Dikkat: dosyada birden çok </template> var — `<template v-if=…>` blokları da
# öyle kapanıyor. İlkine göre kesmek çekmeceyi tamamen dışarıda bırakıyordu ve
# testler "yok" diye geçiyordu. Kök şablon SON kapanışa kadar sürüyor.
TEMPLATE = CRM[CRM.index("<template>") : CRM.rindex("</template>")]
SCRIPT = CRM[: CRM.index("<template>")]
FLAT = re.sub(r"\s+", " ", TEMPLATE)


class TestTheScreenIsOnTheLayer(unittest.TestCase):
	def test_root_carries_the_opt_in_wrapper(self):
		self.assertIn("<TenderPage", FLAT)

	def test_every_design_class_it_uses_exists_in_the_layer(self):
		"""Şablonda var, katmanda yok = sessizce stilsiz bir kutu."""
		used = set(re.findall(r'class="([^"]*)"', TEMPLATE))
		ds = {c for group in used for c in group.split() if c.startswith("ds-")}
		self.assertTrue(ds, "ekran hiç ds-* sınıfı kullanmıyor")
		for cls in sorted(ds):
			with self.subTest(cls=cls):
				self.assertIn(f".{cls}", CSS, f".{cls} katmanda tanımlı değil")


class TestTheMigrationIsComplete(unittest.TestCase):
	"""Yarı taşınmış ekran, taşınmamış ekrandan kötüdür: aynı sayfada iki dil."""

	LEFTOVERS = (
		"card-body",
		"card-header",
		"card-table",
		"table-vcenter",
		"offcanvas",
		"progress-bar",
		"spinner-border",
		"input-icon",
		"btn-group",
		"list-group",
		"avatar",
	)

	def test_no_tabler_component_markup_survives(self):
		for token in self.LEFTOVERS:
			with self.subTest(token=token):
				self.assertNotIn(token, TEMPLATE, f"Tabler kalıntısı: {token}")

	def test_no_tabler_utility_colours_survive(self):
		"""bg-red-lt / text-secondary gibi yardımcı sınıflar katmanın rengiyle
		çakışıyor; önem artık data-sev / data-tone ile veriliyor."""
		for pattern in (r"\bbg-\w+-lt\b", r"\btext-(secondary|danger|primary)\b", r"\bbadge\b"):
			with self.subTest(pattern=pattern):
				self.assertNotRegex(TEMPLATE, pattern)

	def test_severity_is_expressed_as_a_level_not_a_css_class(self):
		self.assertNotIn("riskBadgeClass", CRM)
		self.assertRegex(SCRIPT, r"function riskSev\(risk\)")
		self.assertRegex(FLAT, r'data-tone="riskSev\(')


class TestBehaviourSurvivedTheRewrite(unittest.TestCase):
	"""Bir şablon yeniden yazımının verebileceği tek söz: hiçbir şey kaybolmadı."""

	def test_the_two_endpoints_are_still_called(self):
		self.assertIn("stabler.api.tender.crm_board", CRM)
		self.assertIn("stabler.api.tender.move_deal_stage", CRM)

	def test_both_views_still_exist(self):
		self.assertRegex(FLAT, r"v-if=\"viewMode === 'kanban'\"")
		self.assertRegex(FLAT, r'<table v-else class="ds-table crm-list">')
		self.assertRegex(FLAT, r"@click=\"viewMode = 'kanban'\"")
		self.assertRegex(FLAT, r"@click=\"viewMode = 'list'\"")

	def test_drag_and_drop_is_wired_on_both_ends(self):
		"""Kolon bırakmayı, kart sürüklemeyi taşıyor. Biri düşerse aşama
		değiştirme tamamen ölür ve hiçbir hata çıkmaz."""
		self.assertRegex(FLAT, r'@dragover\.prevent="dragOverLane = l\.id"')
		self.assertRegex(FLAT, r'@drop="onDrop\(l\.id\)"')
		self.assertRegex(FLAT, r'draggable="true"')
		self.assertRegex(FLAT, r'@dragstart="onCardDragStart\(c\.name, \$event\)"')

	def test_the_drawer_still_opens_from_both_views(self):
		self.assertEqual(len(re.findall(r'@click="openDealDrawer\(c\)"', FLAT)), 2)
		self.assertRegex(FLAT, r'v-if="drawerOpen && selectedDeal"')

	def test_the_search_box_is_still_bound(self):
		self.assertRegex(FLAT, r'v-model="searchQuery"')


class TestStageNamesComeFromTheLanes(unittest.TestCase):
	"""`stage` bir kimlik ("seen", "go"), çeviri anahtarı değil. t("seen")
	kullanıcıya "seen" gösteriyordu — üç yerde birden."""

	def test_no_raw_stage_id_is_translated(self):
		self.assertNotIn("t(c.stage)", CRM)
		self.assertNotIn("t(selectedDeal.stage)", CRM)
		self.assertNotIn("t(targetLaneId)", CRM)

	def test_the_label_is_looked_up_in_the_lanes(self):
		fn = re.search(r"const stageLabel = \(id\) => \{.*?\n\};", CRM, flags=re.S)
		self.assertIsNotNone(fn, "stageLabel yok")
		self.assertIn("lanes.value", fn.group(0))
		self.assertIn("l.id === id", fn.group(0))

	def test_the_move_toast_names_the_stage_properly(self):
		self.assertRegex(
			CRM, r'toast\.success\(t\("Moved to \{0\}"\)\.replace\("\{0\}", stageLabel\(targetLaneId\)\)\)'
		)


class TestEverythingClickableIsReachableByKeyboard(unittest.TestCase):
	"""Kart <button> olamıyor: Firefox draggable bir butonu sürüklemiyor. O
	zaman erişilebilirliği elle kurmak gerekiyor — aksi hâlde ekranın ana
	etkileşimi yalnız fareye kalır."""

	def test_cards_and_rows_announce_themselves_and_take_focus(self):
		for block in re.findall(r'<(?:div|tr)[^>]*@click="openDealDrawer\(c\)"[^>]*>', FLAT):
			with self.subTest(block=block[:60]):
				self.assertIn('role="button"', block)
				self.assertIn('tabindex="0"', block)
				self.assertIn("@keydown.enter", block)

	def test_the_drawer_is_a_dialog_and_names_itself(self):
		self.assertRegex(
			FLAT, r'<aside class="ds-drawer" role="dialog" aria-modal="true" aria-labelledby="crm-dw-title">'
		)
		self.assertRegex(FLAT, r'id="crm-dw-title"')

	def test_the_backdrop_is_a_real_control_with_a_label(self):
		"""Tıklanabilir bir div ekran okuyucuda yok gibidir."""
		self.assertRegex(FLAT, r'<button class="ds-drawer-backdrop" :aria-label="t\(\'Close panel\'\)"')

	def test_the_current_stage_is_marked_for_assistive_tech(self):
		self.assertRegex(FLAT, r":aria-current=\"l\.id === selectedDeal\.stage \? 'step' : null\"")


class TestTheKpiStripIsHonest(unittest.TestCase):
	def test_kpis_derive_from_the_existing_payload(self):
		"""Yeni bir uç nokta eklenmedi — dördü de crm_board'ın döndürdüğü
		alanlardan çıkıyor."""
		block = SCRIPT[SCRIPT.index("const kpis = computed(") :]
		block = block[: block.index("\n});")]
		for field in ("contract_value", "has_min_5", "has_2_countries", "risk", "doc_progress"):
			with self.subTest(field=field):
				self.assertIn(field, SCRIPT)
		self.assertNotIn("call(", block)

	def test_a_kpi_press_filters_and_says_so(self):
		"""Bir sayı gösterip "hangileri?" sorusunu cevapsız bırakmak, sayıyı
		bilmeceye çevirir."""
		self.assertRegex(FLAT, r':aria-pressed="String\(activeKpi === k\.key\)"')
		self.assertIn("KPI_TESTS[activeKpi.value]", SCRIPT)

	def test_the_policy_kpi_only_turns_green_when_it_is_actually_met(self):
		"""3/7 iyi haber değil; yeşil bir kutu iyi haber demektir."""
		self.assertRegex(SCRIPT, r'sev: all\.length && all\.every\(KPI_TESTS\.policy\) \? "ok" : "today"')


class TestTheEndpointsExistOnTheServer(unittest.TestCase):
	"""Bu iddia paralel oturumun test_tender_crm_board_api.py'sinden alındı.

	Dosyanın kendisi kaldırıldı — iki modülün geri kalanı buradaki testlerin
	daha zayıf bir kopyasıydı. Ama BU iddia kopya değildi ve kaybedilemezdi:
	yukarıdaki testlerin hepsi ekranın hangi uç noktayı ÇAĞIRDIĞINA bakıyor.
	Biri Python tarafındaki fonksiyonu yeniden adlandırsa hepsi yeşil kalır,
	ekran ise çalışma anında 404 alır. Sözleşmenin iki ucu da tutulmalı."""

	def test_the_api_defines_both_whitelisted_functions(self):
		import ast

		tree = ast.parse((ROOT / "api/tender.py").read_text(encoding="utf-8"))
		funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
		for name in ("crm_board", "move_deal_stage"):
			with self.subTest(function=name):
				self.assertIn(name, funcs, f"api/tender.py {name} tanımlamıyor")

	def test_the_names_the_screen_calls_match_the_names_the_api_defines(self):
		"""Adı iki yerde ayrı ayrı yazmak yerine, ekranın çağırdığı dotted path'in
		son parçasını alıp sunucudakiyle karşılaştır — böylece test, adı elle
		güncellemeyi unutan bir yeniden adlandırmayı da yakalar."""
		import ast

		called = set(re.findall(r'"stabler\.api\.tender\.(\w+)"', CRM))
		self.assertTrue(called, "ekran hiç tender uç noktası çağırmıyor")
		tree = ast.parse((ROOT / "api/tender.py").read_text(encoding="utf-8"))
		defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
		self.assertEqual(called - defined, set(), f"sunucuda karşılığı olmayan çağrı: {called - defined}")


if __name__ == "__main__":
	unittest.main()
