"""Koli alanlarını YARATAN patch — çünkü bu repo onları hiç yaratmıyordu.

`custom_boxes` ve `custom_box_kg`, MSA prod'da yalnızca ayrı bir Django
uygulaması tarafından yaratılmış Custom Field'lar (`erpnext_integration/push.py`,
`ErpNextPusher.ensure_custom_fields`). Stabler tarafında hiçbir patch, fixture ya
da install hook onları yaratmıyor. `test_si_box_fields.py` canlı MSA sitesinde
21.129 dolu satır sayabildiği için bu görünmüyordu: alanlar orada var, ama repo
sayesinde değil.

Sonucu şu: MSA dışındaki her sitede — yeni kurulum, başka kiracı, ve Django
uygulaması emekliye ayrıldığı gün MSA'nın kendisi dahil — kolon yoktur.
`sales.py`'deki yazım `has_column` ile korunmadığı için Frappe bilinmeyen
anahtarı `get_valid_dict()`e hiç ulaştırmadan sessizce atar. Yani koli sayısı
hatasız kaybolur; dalın düzeltmek için var olduğu üç haftalık sessiz kaybın ta
kendisi.

Bu dosya patch'in ŞEKLİNİ kilitliyor, davranışını değil. Davranış bench işi
(kolon gerçekten belirdi mi, ikinci koşu no-op mu) ve orada ölçüldü.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_si_box_field_patch -v
"""

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH_NAME = "v94_sales_invoice_box_fields"
PATCH = ROOT / "patches" / f"{PATCH_NAME}.py"
PATCHES_TXT = (ROOT / "patches.txt").read_text(encoding="utf-8")
SALES = (ROOT / "api/sales.py").read_text(encoding="utf-8")

#: Django uygulamasının prod'da yarattığı tanım, birebir. Kaynak:
#: /Users/zafar/Documents/MSAERP/erpnext_integration/push.py — ErpNextPusher.
#: ensure_custom_fields. Buradaki tanım ondan SAPARSA iki taraf aynı adı farklı
#: şekilde tanımlar; MSA'da alanlar zaten var olduğu için patch atlar ve sapma
#: fark edilmez, ta ki alanların sıfırdan yaratıldığı bir sitede iki sistem
#: birbirinin verisini okuyana kadar.
DJANGO_DEFS = {
	"custom_boxes": {"fieldtype": "Float", "label": "Boxes", "insert_after": "item_name"},
	"custom_box_kg": {"fieldtype": "Float", "label": "Box Weight (kg)", "insert_after": "custom_boxes"},
}


class TestThePatchExistsAndIsRegistered(unittest.TestCase):
	def test_the_patch_file_is_present(self):
		self.assertTrue(PATCH.exists(), f"{PATCH_NAME}.py yok — alanları kimse yaratmıyor")

	def test_the_patch_is_registered(self):
		self.assertIn(
			f"stabler.patches.{PATCH_NAME}",
			PATCHES_TXT,
			"patch dosyası var ama patches.txt'de yok — hiçbir sitede çalışmaz",
		)

	def test_it_is_registered_after_model_sync(self):
		# Custom Field yaratmak DocType tablolarının senkronlanmış olmasını ister.
		post = PATCHES_TXT.index("[post_model_sync]")
		self.assertGreater(
			PATCHES_TXT.index(f"stabler.patches.{PATCH_NAME}"),
			post,
			"patch pre_model_sync yarısında — Custom Field yaratmak için erken",
		)


class TestTheDefinitionMatchesProduction(unittest.TestCase):
	"""Prod'da alanlar zaten var; patch onları atlar. Sapma sessiz kalır."""

	@classmethod
	def setUpClass(cls):
		cls.src = PATCH.read_text(encoding="utf-8") if PATCH.exists() else ""
		cls.defs = cls._extract(cls.src)

	@staticmethod
	def _extract(src: str) -> dict:
		"""Modül düzeyindeki alan tanımlarını `ast` ile oku."""
		out = {}
		if not src:
			return out
		for node in ast.walk(ast.parse(src)):
			if not isinstance(node, ast.Dict):
				continue
			d = {}
			for k, v in zip(node.keys, node.values, strict=True):
				if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
					d[k.value] = v.value
			if "fieldname" in d:
				out[d["fieldname"]] = d
		return out

	def test_both_fields_are_defined(self):
		self.assertEqual(set(DJANGO_DEFS), set(self.defs) & set(DJANGO_DEFS))

	def test_each_field_matches_the_django_definition(self):
		for name, expected in DJANGO_DEFS.items():
			with self.subTest(alan=name):
				got = self.defs.get(name, {})
				for key, value in expected.items():
					self.assertEqual(
						got.get(key),
						value,
						f"{name}.{key} prod'daki tanımdan sapıyor — iki sistem aynı adı "
						f"farklı şekilde tanımlar ve bunu kimse fark etmez",
					)

	def test_the_weight_field_is_not_the_purchase_order_spelling(self):
		# v42 aynı kavramı Purchase Order Item üzerinde `custom_box_weight_kg`
		# diye yazıyor. Satış tarafı `custom_box_kg`; ikisini karıştırmak,
		# doğru görünen ve hiçbir şey yazmayan bir patch üretir.
		self.assertNotIn("custom_box_weight_kg", self.src)

	def test_it_targets_sales_invoice_item(self):
		self.assertIn("Sales Invoice Item", self.src)


class TestThePatchIsSafeToRunAnywhere(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.src = PATCH.read_text(encoding="utf-8") if PATCH.exists() else ""

	def test_it_is_idempotent_on_the_field_itself(self):
		# İkinci koşu hiçbir şey yaratmamalı. `create_custom_fields` var olanı
		# GÜNCELLER, atlamaz — yani varlık kontrolü patch'in kendisinde olmalı.
		self.assertIn(
			'frappe.db.exists("Custom Field"',
			self.src,
			"var olan alan kontrolü yok: ikinci koşu prod'daki tanımın üzerine yazar",
		)

	def test_it_is_gated_on_the_tenant_flag(self):
		# Kiracı disiplini: bayrağı kapalı altı kiracının fatura kalem ızgarasına
		# kullanmadıkları iki sütun eklenmez.
		self.assertIn("direct_invoicing", self.src)

	def test_it_probes_the_table_before_the_column(self):
		# .claude/rules/20-backend-migrations.md: `has_column` tablo yoksa
		# TableMissingError fırlatır, False dönmez.
		self.assertIn("table_exists", self.src)


class TestThePatchIsNotAloneAnymore(unittest.TestCase):
	"""Patch tek başına yetmez; yetmediği yer artık ölçülüyor.

	Patch alanları, doğrudan faturalama BUGÜN açık olan sitelerde yaratır.
	Bayrağı patch koştuktan sonra açan kiracıda alan yoktur, çünkü patch'ler bir
	kez çalışır; `execute_sales_import` ise hiçbir modül kapısı taşımadığı için
	kapalı altı kiracıda da çağrılabilir. O boşluğu sessizden sesliye çeviren
	koruma `api/_common.py::_assert_box_columns`, ayrıntılı testi
	`test_si_box_write_guard.py`. Burada yalnızca patch'in yalnız olmadığını
	kilitliyoruz — bu iddia düşerse patch sessiz kayba geri döner.
	"""

	def test_the_write_path_calls_the_guard(self):
		self.assertIn('row["custom_boxes"] = boxes', SALES)
		self.assertIn(
			"_assert_box_columns()",
			SALES,
			"yazım yolu yeniden korumasız — patch tek başına yeni kiracıyı kurtarmaz",
		)


if __name__ == "__main__":
	unittest.main()
