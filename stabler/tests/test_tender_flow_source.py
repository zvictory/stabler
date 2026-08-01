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
ENDPOINT = API[API.index("def tender_flow(company: str)"):]


class TestTheScreenIsWired(unittest.TestCase):
	def test_it_is_on_the_design_layer(self):
		self.assertRegex(FLAT, r'<div class="tender-flow-page stbl-ds">')

	def test_every_design_class_it_uses_exists_in_the_layer(self):
		used = {c for group in re.findall(r'class="([^"]*)"', TEMPLATE) for c in group.split() if c.startswith("ds-")}
		self.assertTrue(used)
		for cls in sorted(used):
			with self.subTest(cls=cls):
				self.assertIn(f".{cls}", CSS)

	def test_the_route_and_the_module_bar_agree(self):
		self.assertIn('path: "/tender/flow"', ROUTER)
		self.assertIn("component: TenderFlow", ROUTER)
		self.assertIn('module: "tender"', ROUTER[ROUTER.index('path: "/tender/flow"'):][:200])
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
		labels = VUE[VUE.index("const STATE_LABEL"):]
		labels = labels[: labels.index("};")]
		self.assertIn('unknown: "Not measurable"', labels)
		self.assertIn('empty: "Empty"', labels)

	def test_the_layer_styles_both_honesty_states(self):
		for state in ("unknown", "empty"):
			with self.subTest(state=state):
				self.assertIn(f'.ds-sla[data-state="{state}"]', CSS)

	def test_only_edge_and_over_colour_the_wait(self):
		"""Sorunu olmayan bir bekleme süresini vurgulamak gözü yanlış satıra
		çeker."""
		self.assertRegex(
			VUE, r'waitState = \(row\) => \(row\.state === "out" \|\| row\.state === "edge" \? row\.state : null\)'
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


if __name__ == "__main__":
	unittest.main()
