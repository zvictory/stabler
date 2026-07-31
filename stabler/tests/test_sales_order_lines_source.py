"""Satış siparişi satır düzenleyicisinin sözleşmesi.

Bu ekran paylaşılan LineItemsEditor'ı bırakıp kendi düzenleyicisine geçti
(SalesOrderLines.vue). Geçişte üç davranış sessizce düştü ve hiçbiri hata
vermedi — hepsi "çalışıyor gibi görünüp yanlış sonuç veren" cinstendi:

  1. Ölçüden miktar üreten kalemlerin (Item.custom_dimension_mode) boy/en/adet
     girişleri hiç çizilmedi. Kullanıcı miktarı elle yazdı, sunucu kancası
     kayıtta ölçüden yeniden hesaplayıp yazdığını attı.
  2. Arama çubuğundan ürün seçmek hiçbir şey yapmadı: emit `{ item, line: null }`
     gönderiyordu, üst bileşen `field === "item"` bekliyordu.
  3. Birim değiştirince fiyat eski birimde kaldı; iskonto sütunu hiç çizilmedi
     ama satır tutarından düşülmeye devam etti.

Buradaki testlerin hepsi bu üçünden birini kilitliyor. Kaynak metnine bakıyorlar
çünkü bunlar ŞABLON kararları — bir input'un var olup olmadığını runtime'da
kanıtlamak için tüm SPA'yı ayağa kaldırmak gerekirdi.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINES = (ROOT / "public/js/pages/sales/SalesOrderLines.vue").read_text(encoding="utf-8")
FORM = (ROOT / "public/js/pages/sales/SalesOrderForm.vue").read_text(encoding="utf-8")
SALES_API = (ROOT / "api/sales.py").read_text(encoding="utf-8")
DIMENSIONS = (ROOT / "api/_dimensions.py").read_text(encoding="utf-8")


def _squash(text: str) -> str:
	"""Boşlukları tek boşluğa indir — testler biçimlendirmeye değil ifadeye baksın."""
	return re.sub(r"\s+", " ", text)


LINES_FLAT = _squash(LINES)
FORM_FLAT = _squash(FORM)


class TestTheEditableScreenUsesItsOwnEditor(unittest.TestCase):
	"""Hangi düzenleyicinin çizildiği bu dosyadaki her testin ön koşulu."""

	def test_editable_path_renders_sales_order_lines(self):
		self.assertRegex(FORM_FLAT, r'<SalesOrderLines v-if="editable"')

	def test_readonly_path_still_renders_the_shared_editor(self):
		"""Salt-okunur görünüm paylaşılan bileşende kaldı; rezerve/teslim
		sütunları orada yaşıyor."""
		self.assertRegex(FORM_FLAT, r'<LineItemsEditor v-if="form && !editable"')


class TestDimensionalEntryExists(unittest.TestCase):
	"""1A — ölçüden miktar. Motor üretimde; kaybolan tek şey girişlerdi."""

	MEASUREMENT_FIELDS = ("custom_length", "custom_width", "custom_height", "custom_pieces")

	def test_every_measurement_field_has_an_input(self):
		for field in self.MEASUREMENT_FIELDS:
			with self.subTest(field=field):
				self.assertRegex(
					LINES_FLAT,
					rf'v-model\.number="line\.{field}"',
					f"{field} için ölçü girişi yok — ölçülü kalem elle miktar ister hâle döner",
				)

	def test_measurement_inputs_recompute_the_quantity(self):
		"""Giriş var ama @input yoksa miktar ekranda güncellenmez; kullanıcı
		kaydedene kadar ne sipariş ettiğini göremez."""
		inputs = re.findall(r'v-model\.number="line\.(custom_\w+)"[^>]*?/>', LINES_FLAT)
		self.assertEqual(len(inputs), 4, f"beklenen 4 ölçü girişi, bulunan {inputs}")
		for block in re.findall(r'<input v-model\.number="line\.custom_\w+".*?/>', LINES_FLAT):
			with self.subTest(block=block[:70]):
				self.assertIn("@input=\"recalcDim(line)\"", block)

	def test_width_and_height_are_gated_on_the_mode(self):
		"""Doğrusal bir kalemde (profil, boru) en/yükseklik sorulmamalı —
		formülde yokturlar, sorulursa kullanıcı anlamsız bir sayı girer."""
		self.assertRegex(LINES_FLAT, r'v-if="dimNeedsWidth\(line\)"')
		self.assertRegex(LINES_FLAT, r'v-if="dimNeedsHeight\(line\)"')
		self.assertRegex(LINES_FLAT, r'dimNeedsWidth = \(l\) => l\?\.dimension_mode === "Area" \|\| l\?\.dimension_mode === "Volume"')
		self.assertRegex(LINES_FLAT, r'dimNeedsHeight = \(l\) => l\?\.dimension_mode === "Volume"')

	def test_the_column_only_appears_when_a_line_needs_it(self):
		"""Dondurma siparişinde her satırda boş bir ölçü sütunu istemiyoruz."""
		self.assertRegex(LINES_FLAT, r'<th v-if="hasDims"')
		self.assertRegex(LINES_FLAT, r'<td v-if="hasDims">')
		self.assertRegex(LINES_FLAT, r'hasDims = computed\(\(\) => props\.items\.some\(isDim\)\)')


class TestDerivedQuantityIsNotTypeable(unittest.TestCase):
	"""Miktar ölçüden türüyorsa kullanıcı onu yazamamalı. Yazabilseydi girdiği
	sayı ile ölçüsü çelişirdi ve sunucu kayıtta ölçüyü kazanan taraf yapardı —
	yani yazdığı sessizce kaybolurdu."""

	def test_a_dimensional_line_shows_a_computed_value_not_an_input(self):
		self.assertRegex(LINES_FLAT, r'<div v-if="isDim\(line\)" class="ds-calc">')

	def test_the_quantity_stepper_is_the_non_dimensional_branch(self):
		"""Stepper `v-else-if` olmalı: `v-if` olsaydı ölçülü satırda da çizilirdi."""
		self.assertRegex(LINES_FLAT, r'<span v-else-if="editable" class="ds-stepper">')

	def test_no_writable_quantity_input_inside_the_dimensional_branch(self):
		calc = re.search(r'<div v-if="isDim\(line\)" class="ds-calc">.*?</div> </div>', LINES_FLAT)
		self.assertIsNotNone(calc, "ds-calc bloğu bulunamadı")
		self.assertNotIn("v-model", calc.group(0))


class TestUnitIsFixedForDimensionalLines(unittest.TestCase):
	"""Ölçülü kalemde fiyat da miktar da stok biriminde (m / m² / m³). Bir
	birim seçici sunmak katsayı ile ölçüyü aynı anda uygulamak demek — miktar
	iki kez çarpılır."""

	def test_uom_options_are_empty_for_a_dimensional_line(self):
		self.assertRegex(
			LINES_FLAT,
			r'function uomOptions\(line\) \{ // [^}]*? if \(isDim\(line\)\) return \[\];',
		)

	def test_the_unit_cell_states_that_it_is_fixed(self):
		self.assertRegex(LINES_FLAT, r'<template v-if="isDim\(line\)"> <span class="ds-mono so-uom-flat">\{\{ line\.stock_uom')


class TestTheClientFormulaMatchesTheServer(unittest.TestCase):
	"""İki taraf ayrışırsa kullanıcı bir sayı görür, belge başka bir sayı
	kaydeder. Sunucu yetkili (dimensions_hook kayıtta yeniden hesaplıyor), yani
	ayrışmanın maliyetini hep kullanıcı öder."""

	def test_linear_area_and_volume_use_the_same_products(self):
		self.assertIn('if (line.dimension_mode === "Linear") line.qty = round6(L * P);', LINES_FLAT)
		self.assertIn('else if (line.dimension_mode === "Area") line.qty = round6(L * W * P);', LINES_FLAT)
		self.assertIn("else line.qty = round6(L * W * H * P);", LINES_FLAT)

	def test_blank_pieces_means_one_on_both_sides(self):
		"""Sunucu: `1.0 if pieces in (None, "") else _f(pieces)`. İstemci aynı
		ayrımı yapmazsa boş adet 0 sayılır ve miktar sıfıra düşer."""
		self.assertIn('pieces_v = 1.0 if pieces in (None, "") else _f(pieces)', _squash(DIMENSIONS))
		self.assertRegex(
			LINES_FLAT,
			r'line\.custom_pieces === null \|\| line\.custom_pieces === undefined \|\| line\.custom_pieces === "" \? 1 : Number\(line\.custom_pieces\) \|\| 0',
		)

	def test_both_sides_round_to_six_places(self):
		self.assertIn("return round(qty, 6)", _squash(DIMENSIONS))
		self.assertIn("round6 = (n) => Math.round((Number(n) || 0) * 1e6) / 1e6", LINES_FLAT)


class TestTheModeIsWiredOnItemPick(unittest.TestCase):
	"""Mod satıra yazılmazsa isDim hep false döner ve ölçü girişi hiç çizilmez —
	girişleri eklemek tek başına yetmiyor."""

	def test_the_api_returns_the_mode(self):
		meta = SALES_API[SALES_API.index("def item_sales_meta"):]
		meta = meta[: meta.index("\n@frappe.whitelist()")]
		self.assertRegex(meta, r'"dimension_mode": getattr\(doc, "custom_dimension_mode", None\) or ""')

	def test_the_form_writes_the_mode_from_the_api_response(self):
		self.assertRegex(FORM_FLAT, r'setDimensionMode\(line, meta\.dimension_mode \|\| item\?\.custom_dimension_mode \|\| ""\)')

	def test_switching_items_clears_the_previous_measurements(self):
		"""3 m'lik profilden sandviç panele geçince o 3 kalırsa miktar sessizce
		yanlış çıkar — üstelik sunucu onu geçerli kabul eder."""
		fn = re.search(r"function setDimensionMode\(line, mode\) \{.*?\n\}", FORM, flags=re.S)
		self.assertIsNotNone(fn, "setDimensionMode yok")
		body = _squash(fn.group(0))
		for field in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			with self.subTest(field=field):
				self.assertIn(f"line.{field} = null;", body)

	def test_a_dimensional_line_is_pinned_to_the_stock_unit(self):
		fn = _squash(re.search(r"function setDimensionMode\(line, mode\) \{.*?\n\}", FORM, flags=re.S).group(0))
		self.assertIn("line.conversion_factor = 1;", fn)


class TestTheSearchBarActuallyAddsALine(unittest.TestCase):
	"""Formdaki en sık iş. Sözleşme koptuğunda hiçbir hata çıkmadı — olay
	sessizce düştü, ekran hiç tepki vermedi."""

	def test_the_search_emits_a_field_the_parent_handles(self):
		self.assertRegex(LINES_FLAT, r'emit\("pick-item", \{ item, field: "search" \}\)')

	def test_the_parent_handles_that_field(self):
		self.assertRegex(FORM_FLAT, r'if \(field === "search"\) \{')

	def test_the_parent_fills_an_empty_line_before_opening_a_new_one(self):
		handler = FORM[FORM.index('if (field === "search") {'):]
		handler = _squash(handler[: handler.index("if (field === \"item\") {")])
		self.assertIn('findIndex((l) => !l.item_code)', handler)
		self.assertIn("form.value.items.push(blankLine(form.value.set_warehouse))", handler)

	def test_the_child_does_not_mutate_the_items_prop(self):
		"""Satır listesinin sahibi üst bileşen. Çocuk prop'a push ederse iki
		taraf aynı diziyi ayrı ayrı yönetir."""
		self.assertNotIn("props.items.push", LINES)


class TestUnitChangeRepricesTheLine(unittest.TestCase):
	def test_picking_a_unit_tells_the_parent(self):
		"""Koli fiyatı ile dona fiyatı aynı sayı değil; emit olmadan birim
		değişiyor ama fiyat eski birimde kalıyordu."""
		fn = _squash(re.search(r"function pickUom\(line, uom\) \{.*?\n\}", LINES, flags=re.S).group(0))
		self.assertIn('emit("pick-item", { line, field: "uom" });', fn)


class TestDiscountsAreVisibleWhereTheyApply(unittest.TestCase):
	"""Sütun gizliyken bile satır tutarından düşülüyordu: kullanıcı qty×rate ile
	uyuşmayan bir tutar görüp nedenini bulamıyordu."""

	def test_the_discount_columns_are_rendered(self):
		self.assertRegex(LINES_FLAT, r'<th v-if="showDiscounts"')
		self.assertRegex(LINES_FLAT, r'v-model\.number="line\.discount_percentage"')
		self.assertRegex(LINES_FLAT, r'v-model\.number="line\.discount_amount"')

	def test_the_line_amount_matches_the_forms_own_formula(self):
		"""İki formül ayrışırsa tabloda bir sayı, özet rayında başka bir sayı
		görünür. `discount_amount` BIRIM BAŞINA bir indirim; satır gross'undan
		bir kez düşülemez."""
		child = _squash(re.search(r"const lineAmount = \(l\) => \{.*?\n\};", LINES, flags=re.S).group(0))
		parent = _squash(re.search(r"function lineAmount\(line\) \{.*?\n\}", FORM, flags=re.S).group(0))
		for src, name in ((child, "SalesOrderLines"), (parent, "SalesOrderForm")):
			with self.subTest(source=name):
				self.assertRegex(src, r"discPct > 0.*?rate \* \(1 - discPct / 100\)")
				self.assertRegex(src, r"discAmt > 0.*?rate - discAmt")

	def test_the_child_does_not_subtract_the_amount_from_the_line_total(self):
		child = _squash(re.search(r"const lineAmount = \(l\) => \{.*?\n\};", LINES, flags=re.S).group(0))
		self.assertNotIn("gross", child)


class TestAvailabilityLoadsOnEveryPath(unittest.TestCase):
	"""Rezerv paneli bu veriye muhtaç. onMounted'a koymak yetmiyordu: belge üç
	yoldan yükleniyor (mount, docName watcher, kaydetme sonrası) ve yalnız ilki
	kapatılmıştı."""

	def test_priming_lives_in_the_load_function(self):
		load = FORM[FORM.index("async function loadDoc() {"):]
		load = _squash(load[: load.index("\nasync function loadDraftUoms")])
		self.assertIn("scheduleAvailability(line)", load)

	def test_the_mounted_hook_no_longer_carries_its_own_copy(self):
		mounted = FORM[FORM.index("onMounted(async () => {"):]
		mounted = mounted[: mounted.index("\n});")]
		self.assertNotIn("scheduleAvailability", mounted)


class TestFocusAfterPickReachesTheNewEditor(unittest.TestCase):
	def test_the_focus_lookup_covers_both_editors(self):
		"""Seçici yalnız paylaşılan tabloya bakıyordu; yeni düzenleyicide o sınıf
		yok, yani formun ASIL kullanıldığı yolda odak hiçbir yere gitmiyordu."""
		self.assertIn('.so-lines tbody, .stbl-items-table tbody', FORM)
		self.assertRegex(LINES_FLAT, r'data-field="qty"')


if __name__ == "__main__":
	unittest.main()
