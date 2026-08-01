"""`modern_sales_order` bayrağı beş noktanın hepsinde bağlı ve varsayılanı KAPALI.

Bayrak `enable_dimensional_lines` (`ee4b9a1`) ve `enable_sales_box_uom`
(`f7e73dbd`) ile aynı beş noktalı deseni izliyor: doctype alanı,
`DEFAULT_MODULE_ENABLED` (gerçek tek doğruluk kaynağı — `module_map_for`
buradan türüyor), `_MODULE_FIELDS` eşlemesi, yönetici anahtarı, idempotent seed
patch. Beşinden biri eksikse bayrak ya hiç okunmaz ya da hiç açılamaz.

Varsayılanın KAPALI olması bu bayrakta bir zevk meselesi değil: sahibi eski
formu geri istedi. Varsayılan `1` olsaydı yedi kiracı yine yeni tasarımda
uyanırdı ve talep karşılanmamış olurdu. Alan `default`'u *yeni* şirketi,
patch ise *mevcut* satırları (ve NULL'ı) belirler — ikisi de gerekli.

Bir izin değil, bir tercih: bu yüzden `_MODULE_ROLES`'e girmez ve rota
`meta.module` taşımaz. Rol kapısına eklenmesi, tercih bayrağını kazara bir
güvenlik sınırı gibi göstermek olurdu.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "stabler/doctype/stabler_settings/stabler_settings.py").read_text(encoding="utf-8")
MODULES_JSON_TEXT = (ROOT / "stabler/doctype/stabler_company_modules/stabler_company_modules.json").read_text(
	encoding="utf-8"
)
ADMIN = (ROOT / "public/js/pages/admin/Companies.vue").read_text(encoding="utf-8")
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")
PATCH = (ROOT / "patches/v65_enable_modern_sales_order.py").read_text(encoding="utf-8")


class TestTheDefaultIsOffOnEveryPath(unittest.TestCase):
	def test_a_new_company_gets_the_classic_form(self):
		doc = json.loads(MODULES_JSON_TEXT)
		field = next(f for f in doc["fields"] if f["fieldname"] == "enable_modern_sales_order")
		self.assertEqual(field.get("default"), "0")

	def test_the_no_row_fallback_gets_the_classic_form(self):
		"""`module_map_for` satır yoksa doğrudan DEFAULT_MODULE_ENABLED'ı
		döndürür — burası `True` olsaydı satırsız her şirket modern forma
		düşerdi."""
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {") :]
		block = block[: block.index("\n}")]
		self.assertIn('"modern_sales_order": False', block)

	def test_the_patch_closes_existing_rows_and_never_opens_one(self):
		self.assertIn("enable_modern_sales_order = 0", PATCH)
		self.assertNotIn("enable_modern_sales_order = 1", PATCH)


class TestTheFlagIsWiredEndToEnd(unittest.TestCase):
	def test_the_module_key_maps_to_the_column(self):
		self.assertRegex(ORG, r'"modern_sales_order":\s*"enable_modern_sales_order"')

	def test_the_column_exists_on_the_doctype_and_in_field_order(self):
		self.assertIn('"fieldname": "enable_modern_sales_order"', MODULES_JSON_TEXT)
		doc = json.loads(MODULES_JSON_TEXT)
		self.assertIn("enable_modern_sales_order", doc["field_order"])

	def test_the_update_api_accepts_the_flag(self):
		fn = ORG[ORG.index("def update_company_modules(") :]
		fn = fn[: fn.index("\n@frappe.whitelist()")]
		self.assertRegex(fn, r"\n\tmodern_sales_order=None,")
		self.assertIn('"enable_modern_sales_order": modern_sales_order,', fn)

	def test_the_admin_screen_lists_the_flag(self):
		"""Arayüzü olmayan bir kiracı ayarı pratikte bir kod sabitidir —
		kiracı yeni tasarıma kendi geçemezse bayrak bir seçenek değildir."""
		self.assertRegex(ADMIN, r'\{ key: "modern_sales_order", label:')


class TestThePatchIsRegisteredAndSafe(unittest.TestCase):
	def test_the_patch_is_registered(self):
		self.assertIn("stabler.patches.v65_enable_modern_sales_order", PATCHES)

	def test_the_patch_guards_on_the_column(self):
		"""patches.txt'de `[post_model_sync]` yok — her patch DDL sync'ten ÖNCE
		koşar, yani yeni sütuna guard'sız dokunan patch migrate'i düşürür."""
		self.assertIn('has_column("Stabler Company Modules", "enable_modern_sales_order")', PATCH)


class TestItIsAPreferenceNotAPermission(unittest.TestCase):
	def test_it_is_absent_from_the_role_gate(self):
		roles = ORG[ORG.index("_MODULE_ROLES") :]
		roles = roles[: roles.index("\n}")]
		self.assertNotIn("modern_sales_order", roles)


if __name__ == "__main__":
	unittest.main()
