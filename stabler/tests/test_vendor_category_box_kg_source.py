"""Vendor category kutu kilosu — üç yerde aynı formül kalsın.

Bir vendor category, bir konteyner ŞABLONUdur: MSA'da 1 konteyner ≈ 1400 kutu
ve 28 000 kg. "Bu şablon bir konteyneri dolduruyor mu" sorusu ancak toplam kutu
VE toplam kilo yan yana görününce cevaplanır — ekrandaki BUFFALO COMPENSATED
1220 kutu topluyor ama kaç kilo ettiği hiçbir yerde yazmıyordu.

Kilo satır bazındadır çünkü kutular eşit değil (18 kg, 20 kg …). Bu yüzden
`boxes_per_container × box_kg` üç ayrı yerde türetilir — liste SQL'i, detay
uç noktası ve modaldaki canlı alt toplam — ve hiçbir yerde saklanmaz. Bu
testler o üç türetmeyi birbirine çiviler: biri kayarsa (ör. SQL COALESCE'ı
düşürülürse tek bir NULL kilo bütün kategorinin toplamını NULL yapar) ekranda
sessizce yanlış bir konteyner doğrulaması çıkar.
"""

from __future__ import annotations

import json
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

IMPORTS_API = os.path.join(_ROOT, "api", "imports.py")
PURCHASING_API = os.path.join(_ROOT, "api", "purchasing.py")
CHILD_DOCTYPE = os.path.join(
	_ROOT,
	"stabler",
	"doctype",
	"stabler_vendor_category_item",
	"stabler_vendor_category_item.json",
)
CATEGORIES_VUE = os.path.join(_ROOT, "public", "js", "pages", "inventory", "VendorCategories.vue")
PROFORMA_VUE = os.path.join(_ROOT, "public", "js", "pages", "imports", "ProformaForm.vue")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


def vue_fn(src, opener):
	"""Bir SFC fonksiyonunun gövdesi — iddialar komşu fonksiyona kaymasın diye."""
	i = src.index(opener)
	nxt = re.search(r"\n(?:async function |function |const |</script>)", src[i + len(opener) :])
	return src[i : i + len(opener) + nxt.start()] if nxt else src[i:]


class ChildDoctypeContractTest(unittest.TestCase):
	"""Alan paylaşılan bir doctype'ta yaşıyor — sözleşmesi de oraya yazılı."""

	def setUp(self):
		self.dt = json.loads(read(CHILD_DOCTYPE))
		self.fields = {f["fieldname"]: f for f in self.dt["fields"]}

	def test_box_kg_is_a_float_on_the_row_not_on_the_category(self):
		# NECK kutusu ile TENDERLOIN kutusu aynı değil; kategori seviyesinde tek
		# bir kilo tutmak 18'lik kalemi 20 sayar ve PI qty'sini yanlış üretir.
		self.assertIn("box_kg", self.fields, "kutu kilosu satırın kendi alanı olmalı")
		self.assertEqual(self.fields["box_kg"]["fieldtype"], "Float")
		self.assertEqual(str(self.fields["box_kg"].get("precision")), "2")
		self.assertIn("box_kg", self.dt["field_order"])

	def test_box_kg_is_not_required(self):
		# Doctype 7 kiracının hepsine gidiyor ve msa'da 20 kategori kayıtlı.
		# reqd yapılırsa mevcut satırlar kaydedilemez hale gelir ve `imports`
		# kullanmayan kiracılar zorunlu bir alanla karşılaşır.
		self.assertNotIn("reqd", self.fields["box_kg"])

	def test_row_total_is_never_stored(self):
		# Satır toplamı türetilen bir sayı. Saklanırsa boxes veya kg düzenlendiğinde
		# bayatlar ve "1220 kutu / 24 400 kg" iddiası kaynağıyla çelişir.
		self.assertNotIn("total_kg", self.fields)


class BackendDerivationTest(unittest.TestCase):
	def setUp(self):
		self.src = read(IMPORTS_API)

	def test_list_aggregate_survives_a_row_with_no_weight(self):
		# COALESCE olmadan tek bir NULL box_kg çarpımı NULL yapar ve SUM bütün
		# kategoriyi NULL döndürür: kilosu girilmemiş bir satır yüzünden zaten
		# girilmiş 19 satır ekrandan silinir.
		fn = body(self.src, "list_vendor_categories")
		self.assertIn("SUM(boxes_per_container * COALESCE(box_kg, 0))", fn)
		self.assertIn('r["total_boxes"]', fn)
		self.assertIn('r["total_kg"]', fn)

	def test_detail_returns_the_same_product_as_the_list(self):
		fn = body(self.src, "vendor_category_detail")
		self.assertIn('"box_kg": flt(it.box_kg, 2)', fn)
		self.assertIn('i["boxes_per_container"] * i["box_kg"]', fn)
		self.assertIn('"total_boxes_per_container"', fn)

	def test_save_persists_the_row_weight(self):
		# Modal kilo gösterip kaydetmezse ekran yalan söyler.
		self.assertIn('"box_kg": flt(row.get("box_kg"))', body(self.src, "save_vendor_category"))

	def test_pi_fill_endpoint_reads_the_weight(self):
		# İkinci tüketici: PI'ın "kategoriden doldur" akışı aynı child tablodan
		# okur; alanı çekmezse frontend satır kilosunu asla göremez.
		fn = body(read(PURCHASING_API), "get_vendor_category_items")
		self.assertIn("box_kg", fn)


class ModalTotalsTest(unittest.TestCase):
	def setUp(self):
		self.src = read(CATEGORIES_VUE)

	def test_totals_are_computed_client_side(self):
		# Sunucudan gelen toplam yalnız açılış anında doğru. Kullanıcı satır
		# eklerken/silerken alt toplam canlı takip etmezse doğrulama işe yaramaz.
		self.assertIn("function lineKg(line)", self.src)
		self.assertIn("(Number(line.boxes_per_container) || 0) * (Number(line.box_kg) || 0)", self.src)
		self.assertIn("const totalBoxes = computed(", self.src)
		self.assertIn("const totalKg = computed(", self.src)

	def test_modal_has_a_footer_row(self):
		# Kullanıcının istediği şey buydu: "en altta toplam box ve toplam kg".
		self.assertIn("<tfoot>", self.src)
		self.assertIn("{{ totalBoxes }}", self.src)
		self.assertIn("{{ totalKg.toFixed(2) }}", self.src)

	def test_weight_survives_a_round_trip(self):
		# blankLine → openEdit → saveCategory zincirinin herhangi bir halkası
		# box_kg'yi düşürürse alan kaydedilir ama geri okunmaz (ya da tersi).
		self.assertIn("box_kg: 0", self.src)
		self.assertIn("box_kg: Number(it.box_kg) || 0", self.src)
		self.assertIn("box_kg: l.box_kg,", self.src)


class ProformaFillTest(unittest.TestCase):
	def test_category_weight_beats_the_global_box(self):
		# PI'daki tek "Box weight" kutusu bütün satırlara aynı değeri yazıyordu:
		# 18 kg'lık kalem 20 sayılıyor, qty yanlış çıkıyordu. Kategori kendi
		# kilosunu taşıyorsa o kazanır; taşımıyorsa global kutu yedek kalır.
		fn = vue_fn(read(PROFORMA_VUE), "async function applyFillCategory(")
		self.assertIn("const rowWeight = Number(it.box_kg) || boxWeight;", fn)
		self.assertIn("box_weight_kg: rowWeight", fn)
		self.assertIn("qty: round2(boxes * rowWeight)", fn)


if __name__ == "__main__":
	unittest.main()
