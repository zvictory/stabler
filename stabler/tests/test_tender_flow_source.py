"""Süreç akışı ekranının sözleşmesi.

Ekranın tek işi "nerede takıldık" sorusuna cevap vermek. O cevabı bozmanın en
kolay yolu sayıları güzelleştirmek: ölçülemeyeni sıfır saymak, boş adımı
gizlemek, ortalamanın neye dayandığını söylememek. Bu dosya o üçünü kapatıyor.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VUE = (ROOT / "public/js/pages/tender/TenderFlow.vue").read_text(encoding="utf-8")
API = (ROOT / "api/tender.py").read_text(encoding="utf-8")
CSS = (ROOT / "public/css/stabler-modernist.css").read_text(encoding="utf-8")
ROUTER = (ROOT / "public/js/router.js").read_text(encoding="utf-8")
NAV = (ROOT / "public/js/pages/tender/TenderNav.vue").read_text(encoding="utf-8")

TEMPLATE = VUE[VUE.index("<template>") : VUE.rindex("</template>")]
FLAT = re.sub(r"\s+", " ", TEMPLATE)
ENDPOINT = API[API.index("def tender_flow(company: str)") :]
STYLE = re.sub(r"/\*.*?\*/", "", VUE[VUE.index("<style scoped>") : VUE.rindex("</style>")], flags=re.S)


def opening_tag(marker: str) -> str:
	"""The opening tag that carries `marker`.

	Anchored to the marker's own position rather than to a tag name: a slice
	that starts from a bare name can match a different element entirely, which
	has already happened twice on this package.
	"""
	at = TEMPLATE.index(marker)
	return TEMPLATE[TEMPLATE.rindex("<", 0, at) : TEMPLATE.index(">", at) + 1]


class TestTheScreenIsWired(unittest.TestCase):
	def test_it_is_on_the_design_layer(self):
		self.assertIn("<TenderPage", FLAT)

	def test_every_design_class_it_uses_exists_in_the_layer(self):
		used = {
			c
			for group in re.findall(r'class="([^"]*)"', TEMPLATE)
			for c in group.split()
			if c.startswith("ds-")
		}
		self.assertTrue(used)
		for cls in sorted(used):
			with self.subTest(cls=cls):
				self.assertIn(f".{cls}", CSS)

	def test_the_route_and_the_module_bar_agree(self):
		self.assertIn('path: "/tender/flow"', ROUTER)
		self.assertIn("component: TenderFlow", ROUTER)
		self.assertIn('module: "tender"', ROUTER[ROUTER.index('path: "/tender/flow"') :][:200])
		self.assertIn('to="/tender/flow"', NAV)

	def test_it_calls_the_one_endpoint(self):
		self.assertIn("stabler.api.tender.tender_flow", VUE)


class TestTheScreenDoesNotFlatterTheNumbers(unittest.TestCase):
	def test_an_unmeasurable_average_is_a_dash_not_a_zero(self):
		"""`avg_days` null iken 0 yazmak, ölçemediğimiz adımı en iyi adım gibi
		gösterirdi."""
		self.assertRegex(FLAT, r'v-if="row\.avg_days !== null"')
		self.assertRegex(FLAT, r'v-else class="ds-mono flow-dash">—')

	def test_the_row_says_how_many_deals_were_left_out(self):
		"""Bir ortalamanın neye dayandığını gizlemek, sayının kendisinden
		kötüdür."""
		self.assertRegex(FLAT, r'v-if="row\.unmeasured"')
		self.assertIn("without a stage stamp — not averaged", VUE)

	def test_the_screen_reports_the_unmeasured_total_as_a_kpi(self):
		self.assertRegex(VUE, r'key: "unmeasured"')
		self.assertIn("moved before the stage clock existed", VUE)

	def test_empty_and_unknown_are_different_words(self):
		"""Boş adımda bekleyen iş yok; damgasız adımda var ama süresi
		bilinmiyor. Aynı kelimeyi kullanmak tıkanmış adımı boş gösterir."""
		labels = (ROOT / "public/js/pages/tender/flowLabels.js").read_text(encoding="utf-8")
		self.assertIn('unknown: "Not measurable"', labels)
		self.assertIn('empty: "Empty"', labels)

	def test_the_layer_styles_both_honesty_states(self):
		for state in ("unknown", "empty"):
			with self.subTest(state=state):
				self.assertIn(f'.ds-sla[data-state="{state}"]', CSS)

	def test_only_edge_and_over_colour_the_wait(self):
		"""Sorunu olmayan bir bekleme süresini vurgulamak gözü yanlış satıra
		çeker."""
		labels = (ROOT / "public/js/pages/tender/flowLabels.js").read_text(encoding="utf-8")
		self.assertRegex(
			labels,
			r'waitState = \(row\) => \(row\.state === "out" \|\| row\.state === "edge" \? row\.state : null\)',
		)


class TestTheEndpointSharesOneSourceOfTruth(unittest.TestCase):
	def test_it_derives_the_stage_the_same_way_the_board_does(self):
		"""İki ekranın farklı sayı göstermesi ikisine de güveni bitirir."""
		block = ENDPOINT[: ENDPOINT.index("overrides = stage_sla_for")]
		self.assertIn("_funnel.classify", block)
		self.assertIn("custom_tender_stage", block)
		self.assertIn("_tender_deal_names(company)", block)

	def test_the_stored_stage_wins_over_the_derived_one(self):
		"""Kullanıcı kartı elle taşıdıysa ekran onu göstermeli; türetme yalnız
		taşınmamış anlaşmalar için."""
		self.assertRegex(ENDPOINT, r"stage = stored or _funnel\.classify\(")

	def test_it_reads_the_tenant_thresholds(self):
		self.assertIn("stage_sla_for(company)", ENDPOINT)

	def test_the_aggregation_itself_lives_in_the_pure_module(self):
		"""Toplama burada tekrarlanırsa iki kural olur ve biri sessizce eskir."""
		self.assertIn("_tender_flow.step_rows(deals,", ENDPOINT)
		self.assertIn("_tender_flow.bottleneck(rows)", ENDPOINT)

	def test_it_passes_the_gates_before_reading_anything(self):
		"""Kapı tek çağrıda: `_require_tender_view` şirket sınırını, modül
		iznini ve rol penceresini birlikte uyguluyor (tanımı `api/tender.py`).

		Burada üç ayrı çağrı aranıyordu; üçü de vardı ama ROL kapısı yoktu, yani
		menüde ekranı görmeyen kullanıcı URL'yi yazınca şirketin tüm SLA
		tablosunu okuyabiliyordu. Üçlüyü aramak o boşluğu göremezdi — sarmalayıcı
		aranınca görünüyor. Sarmalayıcının üç kapıyı gerçekten koruduğu ayrı
		modülde tutuluyor: `test_tender_view_gates`.
		"""
		head = ENDPOINT[: ENDPOINT.index("deal_names =")]
		self.assertIn('_require_tender_view("director", company)', head)

	def test_it_honours_per_document_read_permission(self):
		self.assertIn('frappe.has_permission("CRM Deal", "read", doc=deal)', ENDPOINT)

	def test_it_survives_a_site_without_the_stage_columns(self):
		"""Yama uygulanmamış sitede ekran boş değil, ölçülemez olmalı."""
		self.assertIn('has_column("CRM Deal", "custom_tender_stage")', ENDPOINT)
		self.assertIn('has_column("CRM Deal", "custom_tender_stage_entered_at")', ENDPOINT)


class TestTheScreenSaysWhichStateItIsIn(unittest.TestCase):
	"""W11 and W12 — a failed load, a refusal and a quiet pipeline were one branch.

	`v-else` on the table made it the fallback for EVERYTHING, so a load that
	fell over, a company nobody selected and a user without the director view
	all rendered five column headers over an empty tbody, under four counters
	reading zero — which is exactly what a healthy pipeline looks like. The only
	other signal was a toast that scrolls away.

	Corrects prompt 16 §5 on one point, measured 2026-09-02: a genuinely EMPTY
	pipeline was never one of those cases. `step_rows` emits a row per
	`WORKING_STAGES` whatever the data, so an empty company draws five rows
	reading `0 · — · — · Empty`. The empty case needed a sentence, not a branch.
	"""

	def test_every_state_precedes_the_tables_fallback(self):
		# WHAT WOULD MAKE THIS FAIL: a state added AFTER the table. The table is
		# the `v-else`, so anything below it is unreachable — it would read as
		# written, reviewed and shipped while never rendering once.
		fallback = TEMPLATE.index("<template v-else>")
		for marker in ('v-else-if="forbidden"', 'v-else-if="!activeCompany"', 'v-else-if="error"'):
			with self.subTest(marker=marker):
				self.assertLess(TEMPLATE.index(marker), fallback, f"{marker} is below the table")

	def test_a_refusal_names_the_door_that_is_shut(self):
		# WHAT WOULD MAKE THIS FAIL: treating a 403 as an ordinary failure. The
		# board is gated on the director view (`tender.py`), which is not
		# something a reader can fix by retrying; being told to retry forever is
		# worse than being told no.
		#
		# Anchored to the forbidden BRANCH and to a `t()` literal inside it. The
		# first version was `assertIn("director view", VUE)` over the raw file,
		# and the catch block's own comment says "gated on the director view" —
		# so it passed with the user-facing sentence replaced by "Something went
		# wrong." Measured 2026-09-02 by doing exactly that. The same trap
		# `tenderFlowCounters.spec.js` strips comments to avoid.
		branch = TEMPLATE[
			TEMPLATE.index('v-else-if="forbidden"') : TEMPLATE.index('v-else-if="!activeCompany"')
		]
		self.assertRegex(branch, r't\("[^"]*director view[^"]*"\)')
		self.assertRegex(VUE, r"err\?\.status === 403")
		self.assertRegex(VUE, r"forbidden\.value = true")

	def test_a_failed_load_leaves_no_timestamp_it_cannot_stand_behind(self):
		# WHAT WOULD MAKE THIS FAIL: keeping the last good payload through a
		# failure. `Last read` is derived from `data.generated_at`, so a
		# retained payload would print a timestamp from before the failure
		# beside a panel saying the screen could not read anything.
		#
		# THE COST IS DELIBERATE AND IS NOT FREE: a transient blip on Refresh
		# discards a payload the director was reading, and they have to press
		# Refresh again. The table is replaced by the error branch either way,
		# so retaining it would buy invisible state and sell a visible lie. This
		# test exists so the trade is a decision rather than an accident.
		self.assertRegex(VUE, r"data\.value = null")
		self.assertRegex(VUE, r"formatTime\(data\.value\?\.generated_at\)")

	def test_a_failed_load_is_written_into_the_panel(self):
		# WHAT WOULD MAKE THIS FAIL: going back to a toast alone. A toast is
		# gone in seconds and the panel underneath keeps claiming a pipeline;
		# the reader who looks away at the wrong moment sees a healthy screen.
		self.assertRegex(VUE, r"error\.value = err\?\.message")
		self.assertRegex(FLAT, r'v-else-if="error" class="ds-panel-foot flow-state" role="alert"')

	def test_the_counters_are_withheld_rather_than_zeroed(self):
		# WHAT WOULD MAKE THIS FAIL: the strip rendering through a failure. `0 ·
		# 0 / 5 steps · — · 0 / 0` is not a report of nothing being wrong; it is
		# four numbers the screen does not have, and it reads as good news.
		self.assertRegex(FLAT, r'<div v-if="data" class="ds-kpis"')
		self.assertRegex(VUE, r"data\.value = null")

	def test_an_empty_pipeline_says_so_in_words(self):
		# WHAT WOULD MAKE THIS FAIL: five rows of `Empty` and no sentence. The
		# rows are correct and still leave the reader asking whether the screen
		# worked; one line separates "nothing is waiting" from "nothing loaded".
		self.assertIn("No deal is waiting in any step.", VUE)
		self.assertRegex(FLAT, r'v-if="!data\?\.in_process"')

	def test_the_two_failure_states_are_announced(self):
		# WHAT WOULD MAKE THIS FAIL: a refusal that only appears visually. The
		# panel is replaced in place, far from where the reader pressed Refresh,
		# so nothing tells a screen reader that anything changed.
		for marker in ('v-else-if="forbidden"', 'v-else-if="error"'):
			with self.subTest(marker=marker):
				self.assertIn('role="alert"', opening_tag(marker))


class TestTheTableScrollsAndThePageDoesNot(unittest.TestCase):
	"""W13 — five columns and, until now, not one line of responsive CSS.

	Corrects prompt 16 §S4 on two points, both measured 2026-09-02.
	(1) The counter strip DOES have a phone rule: the shared layer collapses
	`ds-kpis[data-cols="4"]` to two columns at ≤992px
	(`stabler-modernist.css:452-454`). (2) `DirectorBoard`'s `.board-scroll` is
	`overflow-x: auto` and nothing else, and `.ds-table` is `width: 100%` with
	wrapping cells — so that container has nothing to scroll and prompt 14's
	fix, as written, does not engage. The minimum width is what makes it real.

	NOT VERIFIED HERE: that a phone actually scrolls the table and not the page.
	`vitest.config.mjs` sets `environment: "node"` and there is no jsdom in this
	repository, so no test in it can lay out a viewport. These assertions cover
	the CSS that would have to be true for it, and nothing more.
	"""

	def test_the_table_sits_inside_a_horizontal_scroller(self):
		# WHAT WOULD MAKE THIS FAIL: the table going back to being a direct
		# child of the panel. Five columns with two-line cells overflow a
		# 390px phone, and without a scroller it is the PAGE that moves —
		# taking the counter strip and the header sideways with it.
		self.assertRegex(FLAT, r'<div class="flow-scroll"[^>]*> <table class="ds-table">')
		self.assertRegex(STYLE, r"\.flow-scroll\s*\{[^}]*overflow-x:\s*auto")

	def test_the_scroller_has_something_to_scroll(self):
		# WHAT WOULD MAKE THIS FAIL: `overflow-x: auto` on its own. `.ds-table`
		# is `width: 100%` and its cells wrap, so the table shrinks to whatever
		# box it is given and the scrollbar never appears — the container reads
		# as a fix and behaves exactly like no fix at all.
		#
		# The bound is DERIVED, from the column widths the style declares and
		# the number of headers the template gives each of them. The first
		# version matched `min-width:\s*\d+px`, so `1px` satisfied it and the
		# very defect above came back green.
		widths = {name: int(px) for name, px in re.findall(r"\.(flow-c-\w+) \{ width: (\d+)px", STYLE)}
		self.assertTrue(widths, "no fixed column widths parsed, so the bound below means nothing")
		head = TEMPLATE[TEMPLATE.index("<thead>") : TEMPLATE.index("</thead>")]
		fixed = sum(widths[cls] for cls in re.findall(r"flow-c-\w+", head))

		found = re.search(r"\.flow-scroll \.ds-table\s*\{[^}]*min-width:\s*(\d+)px", STYLE)
		self.assertIsNotNone(found, "the table inside the scroller has no minimum width")
		minimum = int(found.group(1))

		# The Step column is what is left over, and it holds the longest text on
		# the row — it cannot be narrower than the widest column that is fixed.
		self.assertGreaterEqual(minimum - fixed, max(widths.values()))
		# And the whole thing must exceed the phone this rule exists for
		# (deliverable 6: 390x844). A minimum inside the viewport never scrolls.
		self.assertGreater(minimum, 390)

	def test_no_minimum_width_escapes_the_scroller(self):
		# WHAT WOULD MAKE THIS FAIL: a min-width on an element the scroller does
		# not contain. That is the same defect one level up — the page scrolls
		# instead of the table — and it is the easy mistake to make when a
		# later column needs more room.
		rules = re.findall(r"([^{}]+)\{([^{}]*)\}", STYLE)
		widened = [selector.strip() for selector, body in rules if "min-width" in body]
		self.assertTrue(widened, "no rule sets a minimum width, so this test asserts nothing")
		for selector in widened:
			with self.subTest(selector=selector):
				self.assertIn(".flow-scroll", selector)


class TestWhatCanBeReachedIsAnnounced(unittest.TestCase):
	"""W17 — the file carried zero `aria-*` and zero `role=`.

	NOT VERIFIED HERE, and not verifiable in this repository: that a keyboard
	actually reaches the scroller, that the arrow keys pan it, or that a screen
	reader announces any of this. There is no DOM in the test environment. What
	follows asserts the attributes are present on the element that scrolls —
	which is necessary and is not the same as proving the behaviour.
	"""

	def test_the_scrolling_region_is_focusable_and_named(self):
		# WHAT WOULD MAKE THIS FAIL: adding the scroller and stopping there. A
		# region a mouse can pan and a keyboard cannot is content that some
		# readers simply cannot see — the change would have made the screen
		# worse for them than the page-scrolling version it replaced. The name
		# is what stops it being announced as an unlabelled group.
		tag = opening_tag('class="flow-scroll"')
		self.assertIn('tabindex="0"', tag)
		self.assertIn('role="region"', tag)
		self.assertIn(":aria-label=", tag)

	def test_the_panel_reports_when_it_is_busy(self):
		# WHAT WOULD MAKE THIS FAIL: a refresh that changes nothing a screen
		# reader can perceive. The button disables itself and the panel swaps to
		# a skeleton — both invisible to a reader who is not looking at pixels.
		self.assertIn(':aria-busy="loading"', opening_tag('class="ds-panel flow-panel"'))

	def test_the_refresh_control_is_a_real_button(self):
		# WHAT WOULD MAKE THIS FAIL: a div with a click handler. It is the one
		# interactive control on this screen; making it a div would take the
		# whole screen out of the tab order for the sake of styling.
		self.assertRegex(FLAT, r'<button type="button" class="ds-btn"[^>]*@click="load"')

	def test_the_bottleneck_is_not_signalled_by_colour_alone(self):
		# WHAT WOULD MAKE THIS FAIL: the 3px stripe going back to being the only
		# mark on the row. A box-shadow has no text, no role and no name: to a
		# screen reader the bottleneck row was identical to every other row, and
		# the only place the finding existed in words was a counter three
		# regions away.
		self.assertIn('class="flow-neck"', TEMPLATE)
		self.assertIn('t("Bottleneck")', TEMPLATE)


if __name__ == "__main__":
	unittest.main()
