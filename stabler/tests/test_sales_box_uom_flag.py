"""Koli/kutu UOM tercihi kiracıya özgü bir bayrağa bağlanmalı, sabit bir string'e değil.

Antigravity'nin commit'i `preferredSalesUom()`'a `"korobka"` string aramasını
gömmüştü: bulamazsa `conversion_factor > 1` olan en büyük birimi seçiyordu.
Sonuç: her yeni SO satırı stok birimi yerine koli/kutu ile açılıyordu — anjan
(dondurma) için doğru, ama dts (kayış) ve horeca (hizmet) için sessiz bir
davranış değişikliği, modül kapısı olmadan yedi kiracıya birden gidiyordu.

Düzeltme `enable_dimensional_lines`'ın (`ee4b9a1`) aynı beş noktalı desenini
izliyor: doctype alanı, `_MODULE_FIELDS` eşlemesi, `DEFAULT_MODULE_ENABLED`
(gerçek tek doğruluk kaynağı — `module_map_for` buradan türüyor), yönetici
anahtarı, idempotent seed patch (v63'ten farklı olarak veriden türetmez,
herkesi 0'a kapatır). `"korobka"` sabiti tamamen silinir.

Bu dosya kaynaktan kilitliyor, render'ı değil — projenin diğer `_source.py`
testleriyle aynı sınıf.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = (ROOT / "public/js/pages/sales/SalesOrderFormModern.vue").read_text(encoding="utf-8")
# Klasik form `5e214ab`'den geri getirildi ve o dosya `"korobka"` sabitinin
# söküldüğü commit'ten (`f7e73dbd`) ÖNCEye ait — yani sabit geri gelme riski
# gerçekten burada. İki varyant da aynı kapıdan geçmek zorunda.
CLASSIC = (ROOT / "public/js/pages/sales/SalesOrderFormClassic.vue").read_text(encoding="utf-8")
FORMS = {"SalesOrderFormModern.vue": FORM, "SalesOrderFormClassic.vue": CLASSIC}
ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "stabler/doctype/stabler_settings/stabler_settings.py").read_text(encoding="utf-8")
MODULES_JSON_TEXT = (
	ROOT / "stabler/doctype/stabler_company_modules/stabler_company_modules.json"
).read_text(encoding="utf-8")
ADMIN = (ROOT / "public/js/pages/admin/Companies.vue").read_text(encoding="utf-8")
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")
PATCH = (ROOT / "patches/v64_enable_sales_box_uom.py").read_text(encoding="utf-8")


class TestTheKorobkaConstantIsGone(unittest.TestCase):
	def test_the_literal_appears_nowhere_in_either_form(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertNotIn("korobka", src)


class TestPreferredSalesUomGatesOnTheFlag(unittest.TestCase):
	def _body(self, src):
		fn = src[src.index("function preferredSalesUom("):]
		return fn[: fn.index("\n}\n")]

	def test_the_flag_is_read_from_session_modules(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				self.assertIn("session.modules?.sales_box_uom", self._body(src))

	def test_when_off_it_returns_the_stock_uom_directly(self):
		for name, src in FORMS.items():
			with self.subTest(form=name):
				body = self._body(src)
				i = body.index("session.modules?.sales_box_uom")
				guarded = body[i : body.index("\n\t}", i)]
				self.assertIn("u.uom === meta.stock_uom", guarded)


class TestTheTenantPreferenceIsWired(unittest.TestCase):
	def test_the_module_key_maps_to_the_column(self):
		self.assertRegex(ORG, r'"sales_box_uom":\s*"enable_sales_box_uom"')

	def test_the_key_exists_in_the_defaults(self):
		"""Anahtar DEFAULT_MODULE_ENABLED'da yoksa module_map_for onu hiç
		döndürmez ve session.modules?.sales_box_uom her zaman undefined kalır."""
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {"):]
		block = block[: block.index("\n}")]
		self.assertIn('"sales_box_uom": False', block)

	def test_the_column_exists_on_the_doctype(self):
		self.assertIn('"fieldname": "enable_sales_box_uom"', MODULES_JSON_TEXT)
		self.assertIn(
			'"enable_sales_box_uom"',
			MODULES_JSON_TEXT.split('"field_order"')[1][:900],
		)

	def test_the_default_is_off(self):
		doc = json.loads(MODULES_JSON_TEXT)
		field = next(f for f in doc["fields"] if f["fieldname"] == "enable_sales_box_uom")
		self.assertEqual(field.get("default"), "0")


class TestTheFlagIsActuallyTogglable(unittest.TestCase):
	def test_the_update_api_accepts_the_flag(self):
		fn = ORG[ORG.index("def update_company_modules("):]
		fn = fn[: fn.index("\n@frappe.whitelist()")]
		self.assertRegex(fn, r"\n\tsales_box_uom=None,")
		self.assertIn('"enable_sales_box_uom": sales_box_uom,', fn)

	def test_the_admin_screen_lists_the_flag(self):
		self.assertRegex(ADMIN, r'\{ key: "sales_box_uom", label:')


class TestThePatchIsRegisteredAndSafe(unittest.TestCase):
	def test_the_patch_is_registered(self):
		self.assertIn("stabler.patches.v64_enable_sales_box_uom", PATCHES)

	def test_the_patch_guards_on_the_column(self):
		self.assertIn('has_column("Stabler Company Modules", "enable_sales_box_uom")', PATCH)

	def test_the_patch_closes_everyone_it_does_not_invent_data(self):
		"""v63'ün aksine burada 'kim koli ile satar' diye bir olgu yok —
		patch yalnız 0'a kapatmalı, hiçbir yerde 1'e açmamalı."""
		self.assertIn("enable_sales_box_uom = 0", PATCH)
		self.assertNotIn("enable_sales_box_uom = 1", PATCH)


if __name__ == "__main__":
	unittest.main()
