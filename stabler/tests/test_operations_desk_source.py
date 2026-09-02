"""Operasyon Masası'nın tasarım katmanına taşınmış hâlinin sözleşmesi.

Neden vitest değil: repo'nun vitest kapsamı bilerek SAF MANTIK ile sınırlı
(vitest.config.mjs: environment "node", jsdom yok, bileşen mount edilmiyor).
Bileşeni mount etmek için jsdom + @vue/test-utils eklemek gerekirdi; repo
bunun yerine kaynak tarayan Python testleri kullanıyor (test_*_source.py).
Aynı yolu izliyoruz.

Testler iki şeyi kilitliyor: (1) ekran gerçekten yeni dile taşınmış ve eski
Tabler işaretlemesi geri sızmamış, (2) taşımada davranış kaybolmamış.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "stabler/public/js/pages/tender/OperationsDesk.vue").read_text(encoding="utf-8")
TEMPLATE = SOURCE[SOURCE.index("<template>") : SOURCE.index("<script setup>")]
RULES_SOURCE = (ROOT / "stabler/api/_desk_rules.py").read_text(encoding="utf-8")


def _code_only(source: str) -> str:
	"""`source` with every comment and docstring removed.

	Three assertions below scan _desk_rules.py as RAW TEXT for things only its
	code may say -- the rule kinds it emits, and whether any rule reads
	`delivery_deadline`. A comment mentioning either moved them. They failed in
	the safe direction (noise, not a blind spot), but the effect was that the file
	could not be commented about the very fields these tests read -- and the D19
	comment explaining why delivery was dropped is exactly such a comment.

	`ast.unparse` drops comments by construction; docstrings survive it, so they
	are popped explicitly. Quotes are normalised to single by unparse, which is
	why the kind regex below accepts either.
	"""
	tree = ast.parse(source)
	holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
	for node in ast.walk(tree):
		if not isinstance(node, holders):
			continue
		first = node.body[0] if node.body else None
		if (
			isinstance(first, ast.Expr)
			and isinstance(first.value, ast.Constant)
			and isinstance(first.value.value, str)
		):
			node.body.pop(0)
	return ast.unparse(tree)


RULES_CODE = _code_only(RULES_SOURCE)
_KIND_RE = re.compile(r"""['"]kind['"]:\s*['"]([a-z_]+)['"]""")
TENDER_SOURCE = (ROOT / "stabler/api/tender.py").read_text(encoding="utf-8")
DESK_API_SOURCE = (ROOT / "stabler/api/tender_desk.py").read_text(encoding="utf-8")


def _js_map(name: str) -> set[str]:
	"""The keys of a top-level `const NAME = { … };` object literal in the .vue."""
	start = SOURCE.index(f"const {name} = {{")
	body = SOURCE[start : SOURCE.index("\n};", start)]
	return set(re.findall(r"^\t([a-z_]+):", body, re.M))


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
		"""İki kapı da duruyor — ama artık ŞABLONDA değil.

		2026-09-02'ye kadar bu test kapıları `<template>` içinde arıyordu; plan
		paneli kapıların kendi kopyasını tutuyordu ve yan sütundaki üç panel
		hiçbirini çizmiyordu. Dört bölge tek isteği paylaştığı için karar tek
		yere, `regionState` hesaplanmışına taşındı. Kapılar kaybolmadı; yeri
		değişti, ve bu test onları yeni yerinde arıyor. Şablonu da kontrol
		ediyor: bir bölge kapıyı kendi başına yeniden karara bağlarsa iki
		zincir yeniden ayrışır.

		`assertIn` DEĞİL: gövde 20 KB ve başarısızlıkta hepsini basıyordu.
		"""
		gate = SOURCE[SOURCE.index("const regionState = computed(") :]
		gate = gate[: gate.index("\n});")]
		self.assertIn('canAccessModule("tender")', gate, "module gate left regionState")
		self.assertIn("session.activeCompany", gate, "company gate left regionState")
		self.assertTrue(
			"canAccessModule" not in TEMPLATE,
			"a region decides the module gate for itself again",
		)
		self.assertTrue(
			"session.activeCompany" not in TEMPLATE,
			"a region decides the company gate for itself again",
		)

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


class TestMachineVocabularyStaysOnTheWire(unittest.TestCase):
	"""D10/D11. The desk's promise is that the reader will not have to ask anyone
	what a number means; printing the engine's own identifiers at them breaks it
	on the most prominent row of the page.

	These are the CROSS-FILE half. The Vue file holds two literal-keyed label maps
	(the TenderDocumentsPanel.vue:29 idiom -- literal because t() is harvested by
	scanning the source, so a computed key ships untranslated). Nothing in the .vue
	can notice when Python grows a ninth rule or a fifth role view, and the label
	maps deliberately do NOT fall back to the raw id for a rule kind. So the
	failure has to be reported here, at build time, rather than to a user."""

	def test_every_rule_kind_the_engine_emits_has_a_human_label(self):
		# WHAT WOULD MAKE THIS FAIL: adding a rule to _desk_rules.py without a
		# label. The evidence line is `v-if`-guarded on the label, so an unlabelled
		# kind renders NOTHING -- the new rule's rows would silently lose the one
		# line that says which query produced them, and no screen would look broken.
		emitted = set(_KIND_RE.findall(RULES_CODE))
		self.assertTrue(emitted, "no rule kinds found in _desk_rules.py -- has it moved?")
		missing = sorted(emitted - _js_map("KIND_LABEL"))
		self.assertEqual(missing, [], f"KIND_LABEL in OperationsDesk.vue has no entry for: {missing}")

	def test_no_label_is_kept_for_a_rule_that_no_longer_exists(self):
		# WHAT WOULD MAKE THIS FAIL: deleting a rule and leaving its label behind.
		# A label with no rule is a translated string nobody can reach, and it makes
		# the map read as a list of what the desk checks when it is not one.
		emitted = set(_KIND_RE.findall(RULES_CODE))
		stale = sorted(_js_map("KIND_LABEL") - emitted)
		self.assertEqual(stale, [], f"KIND_LABEL names rules _desk_rules.py cannot emit: {stale}")

	def test_every_role_view_the_server_offers_has_a_human_label(self):
		# WHAT WOULD MAKE THIS FAIL: adding a fifth view to _TENDER_VIEW_ROLES. The
		# picker falls back to the raw id there -- an <option> with empty text is a
		# blank row the reader can select and cannot name, so the fallback is the
		# lesser evil and this test is what stops it being the outcome.
		block = TENDER_SOURCE[TENDER_SOURCE.index("_TENDER_VIEW_ROLES = {") :]
		block = block[: block.index("\n}\n")]
		views = set(re.findall(r'^\t"([a-z]+)":', block, re.M))
		self.assertEqual(len(views), 4, f"expected the four documented views, found {sorted(views)}")
		missing = sorted(views - _js_map("VIEW_LABEL"))
		self.assertEqual(missing, [], f"VIEW_LABEL in OperationsDesk.vue has no entry for: {missing}")

	def test_the_desk_endpoint_does_not_ship_an_id_dressed_as_a_label(self):
		# WHAT WOULD MAKE THIS FAIL: restoring `{"id": v, "label": v}`
		# (tender_desk.py:40). The key said "label" and held the id, so the one
		# consumer rendered `logist` at the user and t() returned it unchanged --
		# none of the four ids is a key in any catalogue. A field that lies about
		# what it holds invites the next screen to render it too.
		line = re.search(r"^\tavailable_views = .*$", DESK_API_SOURCE, re.M)
		self.assertIsNotNone(line, "available_views is gone from tender_desk.py")
		self.assertNotIn('"label"', line.group(0), "a label is not an id; the client names the views")


class TestTheCalendarPromisesOnlyWhatTheEngineComputes(unittest.TestCase):
	"""D19. `delivery_deadline` is resolved out of the intake JSON
	(tender_desk.py:140), carried into `lots_fact` (:277) and read by NOTHING:
	measured 2026-09-02, `_desk_rules.py` contains zero occurrences of it. The
	calendar's own sublabel meanwhile read "Bid · delivery · due".

	The deliverable is not the missing rule -- the prompt's hard rules forbid
	inventing one -- it is that the screen stops advertising a dimension the engine
	does not compute."""

	@staticmethod
	def _calendar_sublabel() -> str:
		"""What the calendar's panel head RENDERS -- markup comments stripped.

		Anchored on the panel's own heading, not on the word "delivery": a slice
		taken by searching for the promise cannot notice the promise is gone. And
		the comments have to go, or the note explaining WHY delivery was dropped
		would itself read as the promise being kept."""
		head = TEMPLATE.index('<h3>{{ t("Next 7 days") }}</h3>')
		block = TEMPLATE[head : TEMPLATE.index("</div>", head)]
		return re.sub(r"<!--.*?-->", "", block, flags=re.S)

	def test_the_word_delivery_appears_exactly_when_a_rule_consumes_it(self):
		# WHAT WOULD MAKE THIS FAIL, in both directions. Putting "delivery" back in
		# the sublabel while no rule reads delivery_deadline: the screen promises a
		# dimension no row can ever carry, on the one region a reader scans to plan
		# a week. And -- the other direction, which a one-sided assertNotIn would
		# have frozen -- writing a delivery rule and forgetting to say so: this test
		# then demands the word back, so the promise and the engine move together
		# rather than drifting apart again.
		consumed = "delivery_deadline" in RULES_CODE
		promised = "delivery" in self._calendar_sublabel().lower()
		self.assertEqual(
			promised,
			consumed,
			"the calendar sublabel and _desk_rules.py disagree about delivery: "
			f"promised={promised}, consumed={consumed}",
		)

	def test_the_unread_fact_still_reaches_the_engine(self):
		# WHAT WOULD MAKE THIS FAIL: deleting delivery_deadline from `lots_fact` to
		# "tidy up" an unread key. The gap is the finding -- the intake holds a
		# delivery date, the desk resolves it correctly after a real bug fix, and no
		# rule asks for it. Removing it would erase the evidence that a delivery rule
		# is writable at all, and the next reader would have to rediscover the field.
		#
		# Anchored on the `lots_fact` block, not on the file: `delivery_deadline`
		# also appears in the intake fallback and in comments, so a whole-file
		# assertIn passes with the fact deleted from the only place the engine reads.
		facts = DESK_API_SOURCE[DESK_API_SOURCE.index("\tlots_fact = [") :]
		facts = facts[: facts.index("\n\tfacts = {")]
		self.assertIn('"delivery_deadline":', facts, "the engine no longer receives the delivery date")


class TestTheSourceScannersReadCodeNotProse(unittest.TestCase):
	"""The scanners above answer questions about CODE. Prose must not move them."""

	def test_a_comment_cannot_invent_a_rule_or_a_consumer(self):
		# WHAT WOULD MAKE THIS FAIL: going back to scanning the raw file. A comment
		# reading `# "kind": "ghost_rule"` would then demand a KIND_LABEL entry for
		# a rule that cannot fire, and a comment saying delivery_deadline is unread
		# would prove it read -- the D19 note explaining the gap would itself close
		# the gap it documents.
		code = _code_only(
			'# "kind": "ghost_rule" and delivery_deadline\n'
			'X = {"kind": "bid_due"}  # delivery_deadline again\n'
		)
		self.assertNotIn("ghost_rule", code, "a commented kind survived the strip")
		self.assertNotIn("delivery_deadline", code, "a commented field survived the strip")
		self.assertEqual({"bid_due"}, set(_KIND_RE.findall(code)), "the real kind was lost")

	def test_a_docstring_cannot_either(self):
		# WHAT WOULD MAKE THIS FAIL: stripping `#` comments only. ast.unparse keeps
		# docstrings, and _desk_rules.py documents its rules in them -- build_calendar's
		# own docstring is several paragraphs about what the rules produce.
		code = _code_only('"""delivery_deadline is not read here."""\nX = 1\n')
		self.assertNotIn("delivery_deadline", code, "a docstring survived the strip")

	def test_the_engine_still_yields_its_rules_after_the_strip(self):
		# WHAT WOULD MAKE THIS FAIL: a strip so aggressive it eats the code. The two
		# assertions that consume RULES_CODE both pass vacuously on an empty set.
		self.assertGreaterEqual(
			len(set(_KIND_RE.findall(RULES_CODE))), 8, "the rule kinds vanished with the comments"
		)


if __name__ == "__main__":
	unittest.main()
