"""Koli sayısını saklayamayan bir tabloya koli yazmak — artık sessiz değil.

Frappe bilinmeyen bir anahtarı `get_valid_dict()`e hiç ulaştırmadan atar. Yani
`custom_boxes`ı Custom Field'ın bulunmadığı bir sitede yazmak sayıyı hatasız,
logsuz ve başarısız istek olmadan kaybeder: çağırana yazma başarılı denir, sayı
yoktur. Dalın var olma sebebi olan üç haftalık sessiz kaybın mekanizması budur.

`v94_sales_invoice_box_fields` alanları, doğrudan faturalama BUGÜN açık olan her
sitede yaratır. Geriye iki delik kalır; bu korumanın tek işi ikisini de sessizden
sesliye çevirmektir:

  1. Patch KOŞTUKTAN SONRA `direct_invoicing`i açan kiracı alan almaz, çünkü
     patch'ler bir kez çalışır. Yeni bir kapı icat etmek yerine kayıp anını
     gürültülü yapmak, CLAUDE.md kural 2'nin istediği asgari çözümdür.
  2. `execute_sales_import` hiçbir modül kapısı taşımaz — yalnızca
     `has_permission` ve şirket kapsamı bakar (sales_import.py:344-352). Yani
     patch'in bilerek hiçbir şey yaratmadığı altı kiracıda da çağrılabilir.
     Üstelik faturayı `doc.submit()` eder: kayıp taslakta değil, artık
     değiştirilemez bir belgede olur.

İkinci delik birincisinden ağırdır; testlerin ağırlığı da ona göredir.

Bu dosya kaynak metni ve AST'yi yargılar, çalışma zamanı davranışını değil —
o bench işi. Kanıtlayabildiği üç şey var: koruma her yazan yolda çağrılıyor,
importer'da oluşturma döngüsünden ÖNCE çağrılıyor, ve koli alanına dokunan hiçbir
fonksiyon sınıflandırılmadan kalamıyor.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_si_box_write_guard -v
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GUARD = "_assert_box_columns"
BOX_FIELDS = ("custom_boxes", "custom_box_kg")

COMMON_REL = "api/_common.py"
SALES_REL = "api/sales.py"
IMPORTER_REL = "stabler/api/sales_import.py"
PURCHASE_REL = "api/imports.py"

#: Koli alanlarını bir BELGEYE yazan, dolayısıyla korumayı çağırmak zorunda olan
#: fonksiyonlar. `execute_sales_import` koli adlarını kendi gövdesinde geçirmez —
#: onları `build_payloads` kurar — ama DB'ye yazan odur, koruma da oraya aittir.
GUARDED = {
	SALES_REL: {"_direct_invoice_item_rows"},
	IMPORTER_REL: {"execute_sales_import"},
}

#: Koli adlarına dokunan ama belgeye yazmayan fonksiyonlar. Her biri için gerekçe
#: burada yazılı; gerekçesiz muafiyet yok.
EXEMPT = {
	(SALES_REL, "sales_invoice_detail"): (
		"okuma yolu: faturadan ekrana taşır, hiçbir belgeye yazmaz, dolayısıyla kaybedeceği bir şey yok"
	),
	(IMPORTER_REL, "build_payloads"): (
		"saf kurucu: dict üretir, DB'ye dokunmaz; koruma onu çağıran execute_sales_import'ta, "
		"oluşturma döngüsünden önce"
	),
}


def _source(rel: str) -> str:
	return (ROOT / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.Module:
	return ast.parse(_source(rel))


def _functions(rel: str) -> dict[str, ast.FunctionDef]:
	return {n.name: n for n in ast.walk(_tree(rel)) if isinstance(n, ast.FunctionDef)}


def _called_names(node: ast.AST) -> set[str]:
	"""Bu düğümün altında çağrılan her adı döndürür — `f()` ve `x.f()` dahil."""
	names: set[str] = set()
	for n in ast.walk(node):
		if isinstance(n, ast.Call):
			func = n.func
			if isinstance(func, ast.Name):
				names.add(func.id)
			elif isinstance(func, ast.Attribute):
				names.add(func.attr)
	return names


def _guard_call_lines(node: ast.AST) -> list[int]:
	return sorted(
		n.lineno
		for n in ast.walk(node)
		if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == GUARD
	)


def _touches_box_fields(node: ast.AST) -> bool:
	for n in ast.walk(node):
		if isinstance(n, ast.Constant) and n.value in BOX_FIELDS:
			return True
		if isinstance(n, ast.Attribute) and n.attr in BOX_FIELDS:
			return True
	return False


class TestTheGuardItself(unittest.TestCase):
	"""Koruma var, her iki alanı da yokluyor ve durduruyor."""

	def setUp(self):
		self.fns = _functions(COMMON_REL)
		self.src = _source(COMMON_REL)

	def test_the_guard_exists_where_both_writers_can_reach_it(self):
		# İki yazan iki ayrı pakette (`stabler/api/` ve `stabler/stabler/api/`).
		# Ortak ev `_common.py`; ikisi de zaten oradan `_require_company` alıyor.
		self.assertIn(GUARD, self.fns, f"{COMMON_REL} içinde {GUARD} tanımlı değil")

	def test_the_guard_refuses_rather_than_warns(self):
		self.assertIn(
			"throw",
			_called_names(self.fns[GUARD]),
			"koruma frappe.throw etmiyor — log ya da uyarı sessizliği bitirmez, çağıran yine 'yazıldı' duyar",
		)

	def test_the_guard_probes_the_database_not_the_doctype_json(self):
		# Custom Field kaydı silinmeden kolon düşürülebilir ve tersi de olur.
		# Kaybı belirleyen kolonun kendisidir, meta değil.
		self.assertIn(
			"has_column",
			_called_names(self.fns[GUARD]),
			"koruma frappe.db.has_column ile yoklamıyor",
		)

	def test_the_guard_checks_both_fields_not_just_the_first(self):
		# Yarım kayıp da kayıptır: `custom_boxes` varken `custom_box_kg` yoksa
		# koli sayısı kalır, kilosu sessizce gider.
		guard_src = ast.get_source_segment(self.src, self.fns[GUARD]) or ""
		self.assertIn(
			"BOX_FIELDS",
			guard_src,
			"koruma tek bir alan adına sabitlenmiş — iki alanın listesi üzerinden dönmeli",
		)

	def test_both_field_names_are_named_once_in_one_place(self):
		names = [
			n.value
			for n in ast.walk(_tree(COMMON_REL))
			if isinstance(n, ast.Constant) and n.value in BOX_FIELDS
		]
		self.assertEqual(
			sorted(set(names)),
			sorted(BOX_FIELDS),
			"BOX_FIELDS iki alanı da adlandırmıyor",
		)


class TestEveryWriterCallsTheGuard(unittest.TestCase):
	"""Belgeye koli yazan her yol korumayı çağırır — biri unutulursa test kırmızı."""

	def test_the_direct_invoice_row_builder_calls_the_guard(self):
		fn = _functions(SALES_REL)["_direct_invoice_item_rows"]
		self.assertIn(GUARD, _called_names(fn), "doğrudan fatura satır kurucusu korumasız")

	def test_the_importer_calls_the_guard(self):
		fn = _functions(IMPORTER_REL)["execute_sales_import"]
		self.assertIn(GUARD, _called_names(fn), "içe aktarma ucu korumasız")

	def test_every_declared_writer_really_calls_it(self):
		for rel, names in GUARDED.items():
			fns = _functions(rel)
			for name in names:
				self.assertIn(name, fns, f"{rel}::{name} artık yok — GUARDED listesi bayatladı")
				self.assertIn(GUARD, _called_names(fns[name]), f"{rel}::{name} korumayı çağırmıyor")

	def test_the_writer_list_is_not_empty(self):
		# Boş liste yukarıdaki döngüyü boş geçirir ve test hiçbir şey ölçmeden yeşil kalır.
		self.assertGreaterEqual(sum(len(v) for v in GUARDED.values()), 2)


class TestTheGuardFiresAtTheRightMoment(unittest.TestCase):
	"""Doğru yerde çağırmak, çağırmak kadar önemli."""

	def test_the_row_builder_only_guards_when_boxes_were_actually_sent(self):
		# Koli göndermeyen bir çağıran hiçbir şey kaybetmez; onu engellemek
		# altı kiracıda doğrudan faturalamayı sebepsiz kırardı.
		fn = _functions(SALES_REL)["_direct_invoice_item_rows"]
		guarded_conditionally = any(
			_guard_call_lines(node) for node in ast.walk(fn) if isinstance(node, ast.If)
		)
		self.assertTrue(
			guarded_conditionally,
			"koruma koşulsuz çağrılıyor — koli göndermeyen çağıranı da engeller",
		)

	def test_the_importer_guards_before_it_creates_anything(self):
		fn = _functions(IMPORTER_REL)["execute_sales_import"]
		guard_lines = _guard_call_lines(fn)
		self.assertTrue(guard_lines, "içe aktarma ucunda koruma çağrısı yok")

		creation_loops = [
			node for node in ast.walk(fn) if isinstance(node, ast.For) and "insert" in _called_names(node)
		]
		self.assertEqual(len(creation_loops), 1, "oluşturma döngüsü tek değil — bu testin varsayımı değişti")

		self.assertLess(
			guard_lines[0],
			creation_loops[0].lineno,
			"koruma oluşturma döngüsünün İÇİNDE: döngü her istisnayı errors'a çeviriyor, "
			"yani site geneli bir yapılandırma hatası müşteri başına bir aksaklık gibi görünür",
		)

	def test_that_loop_really_does_swallow_exceptions(self):
		# Yukarıdaki testin GEREKÇESİ ölçülür olmalı: döngü gerçekten yutuyor mu?
		# Yutmuyorsa o test yanlış sebeple yeşildir.
		fn = _functions(IMPORTER_REL)["execute_sales_import"]
		loop = next(
			node for node in ast.walk(fn) if isinstance(node, ast.For) and "insert" in _called_names(node)
		)
		handlers = [n for n in ast.walk(loop) if isinstance(n, ast.ExceptHandler)]
		self.assertTrue(handlers, "döngü artık istisna yakalamıyor — 'önce çağır' gerekçesi değişti")


class TestNoWriterCanHideFromThisFile(unittest.TestCase):
	"""Koli adına dokunan her fonksiyon ya korumalı ya gerekçeli muaf."""

	def test_every_function_touching_box_fields_is_classified(self):
		for rel in (SALES_REL, IMPORTER_REL):
			for name, node in _functions(rel).items():
				if not _touches_box_fields(node):
					continue
				classified = name in GUARDED.get(rel, set()) or (rel, name) in EXEMPT
				self.assertTrue(
					classified,
					f"{rel}::{name} koli alanına dokunuyor ama ne GUARDED'da ne EXEMPT'te — "
					f"yeni bir yazan eklendiyse korumayı çağırmalı, okuma yolu ise gerekçesiyle muaf edilmeli",
				)

	def test_the_sweep_actually_finds_something(self):
		found = [
			(rel, name)
			for rel in (SALES_REL, IMPORTER_REL)
			for name, node in _functions(rel).items()
			if _touches_box_fields(node)
		]
		self.assertGreaterEqual(len(found), 3, f"tarama koli alanı bulamadı: {found}")

	def test_every_exemption_still_names_a_real_function(self):
		for (rel, name), reason in EXEMPT.items():
			self.assertIn(name, _functions(rel), f"{rel}::{name} artık yok — muafiyet bayatladı")
			self.assertTrue(reason.strip(), f"{rel}::{name} muafiyeti gerekçesiz")


class TestThePurchaseOrderPathIsDeliberatelyExcluded(unittest.TestCase):
	"""`api/imports.py` de `custom_boxes` yazar ama başka doctype'a — ve zaten yokluyor.

	Dışlama varsayım değil ölçüm olsun diye buradadır: gerekçe çürürse test kırmızı.
	"""

	def test_it_writes_to_purchase_order_item_not_sales_invoice_item(self):
		src = _source(PURCHASE_REL)
		self.assertIn("Purchase Order Item", src)

	def test_it_already_probes_with_has_column(self):
		src = _source(PURCHASE_REL)
		self.assertIn(
			'has_column(poi, "custom_boxes")',
			src,
			"satın alma yolu artık yoklamıyor — Satış Faturası korumasından muaf tutma gerekçesi düştü",
		)


if __name__ == "__main__":
	unittest.main()
