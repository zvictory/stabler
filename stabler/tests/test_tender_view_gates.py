"""Rol kapıları uç noktada mı, yoksa yalnız menüde mi?

`TenderNav.vue` her bağlantıyı kullanıcının tender pencerelerine göre çiziyor.
Bu bir GÖRÜNÜRLÜK kararı; yetki değil. Uç nokta kendi kapısını taşımazsa,
bağlantıyı görmeyen kullanıcı URL'yi elle yazdığında 200 ve dolu veri alıyor —
ölçüldü 2026-08-01: sourcing / logist / declarant rolleri `/tender/flow`
üzerinden şirketin tüm SLA tablosunu, `/tender/crm` üzerinden bütün kanban'ı
okuyabiliyordu.

Bu modül, menünün rol sözleşmesi ile backend'in kapısının aynı şeyi söylemesini
tutuyor. Kaynağı metin olarak okuyor çünkü `frappe` bu koşumda import edilemiyor
(CI'ın frappe-free kümesi); iddia "kapı çağrısı fonksiyon gövdesinde ve ilk veri
okumasından ÖNCE" biçiminde kurulu — yani kapıyı silmek de, veri okumasının
altına kaydırmak da testi düşürüyor.
"""

from __future__ import annotations

import os
import re
import unittest

API_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api", "tender.py")
NAV_FILE = os.path.join(
	os.path.dirname(os.path.dirname(__file__)),
	"public",
	"js",
	"pages",
	"tender",
	"TenderNav.vue",
)

#: Uç nokta -> o ekranı menüde açabilen pencereler.
#: Kaynağı `TenderNav.vue`; aşağıdaki test ikisinin ayrışmadığını da doğruluyor.
GATED = {
	"tender_flow": ("director",),
	"crm_board": ("director", "sourcing"),
	"move_deal_stage": ("director", "sourcing"),
	"tender_funnel": ("director", "sourcing"),
}

#: Kapıdan ÖNCE gelirse veri kapı açılmadan okunmuş olur.
READ_CALLS = ("frappe.get_all(", "frappe.get_list(", "frappe.db.sql(", "frappe.db.get_all(")


def _function_body(source: str, name: str) -> str:
	"""`def name(` satırından bir sonraki üst düzey `def`/`@` satırına kadar."""
	start = re.search(rf"^def {re.escape(name)}\(", source, re.M)
	if start is None:
		raise AssertionError(f"{name}() kaynakta yok")
	rest = source[start.end() :]
	end = re.search(r"^(?:@|def )", rest, re.M)
	return rest[: end.start()] if end else rest


class TestTenderViewGates(unittest.TestCase):
	def setUp(self):
		with open(API_FILE, encoding="utf-8") as f:
			self.source = f.read()

	# --- kapının varlığı -------------------------------------------------- #

	def test_every_gated_endpoint_calls_a_view_gate(self):
		for fn, views in GATED.items():
			with self.subTest(endpoint=fn):
				body = _function_body(self.source, fn)
				if len(views) == 1:
					needle = f'_require_tender_view("{views[0]}", company)'
					self.assertIn(
						needle,
						body,
						f"{fn}() tek pencereye ait; kapı {needle} olmalı",
					)
				else:
					self.assertIsNotNone(
						re.search(r"_require_any_tender_view\(\s*\(([^)]*)\)", body),
						f"{fn}() birden çok pencereye açık; _require_any_tender_view çağırmalı",
					)

	def test_multi_view_gates_name_exactly_the_menu_windows(self):
		for fn, views in GATED.items():
			if len(views) == 1:
				continue
			with self.subTest(endpoint=fn):
				body = _function_body(self.source, fn)
				match = re.search(r"_require_any_tender_view\(\s*\(([^)]*)\)", body)
				self.assertIsNotNone(match, f"{fn}() kapısı yok")
				named = set(re.findall(r'"(\w+)"', match.group(1)))
				self.assertEqual(
					named,
					set(views),
					f"{fn}() kapısı {sorted(named)} diyor, menü {sorted(views)} diyor",
				)

	# --- kapının YERİ ----------------------------------------------------- #

	def test_the_gate_runs_before_the_first_data_read(self):
		# Kapıyı silmek bariz bir hata; ALTINA kaydırmak sessiz olanı. Veri
		# okunduktan sonra atılan bir izin hatası, veriyi zaten okumuş olur —
		# ve bir sonraki düzenleme "zaten okunmuş" diye erken dönüş eklerse
		# sızıntı geri gelir.
		for fn in GATED:
			with self.subTest(endpoint=fn):
				body = _function_body(self.source, fn)
				gate = re.search(r"_require_(?:any_)?tender_view\(", body)
				self.assertIsNotNone(gate, f"{fn}() kapısı yok")
				for call in READ_CALLS:
					idx = body.find(call)
					if idx == -1:
						continue
					self.assertLess(
						gate.start(),
						idx,
						f"{fn}(): {call} kapıdan önce çalışıyor",
					)

	# --- yardımcının kendisi ---------------------------------------------- #

	def test_any_view_helper_keeps_the_single_view_guards(self):
		body = _function_body(self.source, "_require_any_tender_view")
		for guard in ("_require_company(company)", "_require_tender(company)", "_assert_company_scope(company)"):
			self.assertIn(
				guard,
				body,
				f"_require_any_tender_view {guard} kaybederse şirket sınırı açılır",
			)

	def test_any_view_helper_requires_intersection_not_containment(self):
		# `views in _tender_views()` yazmak listeyi tek eleman gibi arar ve
		# HER ZAMAN yanlış olur -> kapı herkesi reddeder. `.issubset` yazmak
		# ise HER İKİ pencereyi birden şart koşar -> yalnız sourcing olan
		# kullanıcı Tender CRM'i açamaz. Doğrusu kesişim.
		body = _function_body(self.source, "_require_any_tender_view")
		self.assertIn(".intersection(views)", body)
		self.assertNotIn(".issubset(", body)

	def test_any_view_helper_throws_permission_error(self):
		body = _function_body(self.source, "_require_any_tender_view")
		self.assertIn("frappe.PermissionError", body)

	# --- menü ile backend ayrışmasın -------------------------------------- #

	def test_menu_still_gates_the_links_this_module_pins(self):
		# Bu tablo menüden türetildi. Menü değişip kapı değişmezse (ya da
		# tersi) iki yer yine ayrışır; ayrışmanın sessiz olmaması için menünün
		# hâlâ aynı rol kapılarını taşıdığını burada tutuyoruz.
		with open(NAV_FILE, encoding="utf-8") as f:
			nav = f.read()
		self.assertRegex(
			nav,
			r'v-if="can\(\'director\'\)"[^>]*\n?\s*to="/tender/flow"'
			r'|to="/tender/flow"[^>]*v-if="can\(\'director\'\)"',
			"akış bağlantısı menüde director kapısını kaybetti",
		)
		self.assertIn(
			"can('director') || can('sourcing')",
			nav,
			"Tender CRM bağlantısı menüde director||sourcing kapısını kaybetti",
		)

	def test_gate_helper_is_defined_once(self):
		self.assertEqual(
			self.source.count("def _require_any_tender_view("),
			1,
			"kapı yardımcısı iki kez tanımlanmış — biri güncellenip diğeri kalır",
		)


if __name__ == "__main__":
	unittest.main()
