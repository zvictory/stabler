"""Ölçü sütunu kiracı bayrağı: bir TERCIH, bir kapı değil.

Kullanıcı "ekleyelim ama toggle olsun" dedi ve bayrağın tehlikesi tam burada.
Stabler'daki diğer enable_* bayrakları bir yeteneği açıp kapatıyor. Bu bayrak
onlardan farklı: ölçüden miktar üretme kararı KALEME ait (Item.custom_dimension_mode)
ve sunucu kancası kayıtta o karara göre qty'yi yeniden hesaplıyor. Bayrak
hesaba karışırsa iki doğruluk kaynağı olur — görev 25'te tam olarak bunu
temizledik.

Bu dosya bayrağı görünürlük tarafında tutuyor:
  * hesap yolunda (dimensions_hook, _dimensions) bayrağın adı bile geçmemeli,
  * satırda ölçülü kalem varsa sütun bayraktan BAĞIMSIZ açılmalı,
  * bayrak yönetici arayüzünden gerçekten değiştirilebilmeli — yazma yolu
    olmayan bir kiracı ayarı pratikte kod sabitidir.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = (ROOT / "stabler/doctype/stabler_settings/stabler_settings.py").read_text(encoding="utf-8")
ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
MODULES_JSON = (ROOT / "stabler/doctype/stabler_company_modules/stabler_company_modules.json").read_text(
	encoding="utf-8"
)
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")
PATCH = (ROOT / "patches/v63_enable_dimensional_lines.py").read_text(encoding="utf-8")
HOOK = (ROOT / "api/dimensions_hook.py").read_text(encoding="utf-8")
MATH = (ROOT / "api/_dimensions.py").read_text(encoding="utf-8")
FORM = (ROOT / "public/js/pages/sales/SalesOrderFormModern.vue").read_text(encoding="utf-8")
LINES = (ROOT / "public/js/pages/sales/SalesOrderLines.vue").read_text(encoding="utf-8")
ADMIN = (ROOT / "public/js/pages/admin/Companies.vue").read_text(encoding="utf-8")


def _squash(text: str) -> str:
	return re.sub(r"\s+", " ", text)


class TestTheFlagNeverReachesTheMath(unittest.TestCase):
	"""Asıl regresyon testi. Bayrak hesabı etkilerse, kapalıyken girilen ölçüler
	yok sayılır ama sunucu yine ölçüden hesaplar — kullanıcı ekranda bir sayı
	görüp belgede başkasını bulur."""

	def test_the_server_side_calculation_does_not_know_the_flag(self):
		for name, src in (("dimensions_hook.py", HOOK), ("_dimensions.py", MATH)):
			with self.subTest(module=name):
				self.assertNotIn("dimensional_lines", src)
				self.assertNotIn("module_map_for", src)

	def test_the_hook_still_decides_per_item(self):
		"""Karar kalemin kendi modundan çıkmalı — kiracıdan değil."""
		self.assertIn('frappe.get_cached_value("Item", it.item_code, "custom_dimension_mode")', HOOK)


class TestTheColumnCannotBeHiddenWhenALineNeedsIt(unittest.TestCase):
	"""Tercih zorunluluğu ezemez: o satırın miktarı ölçüden türüyor."""

	def test_visibility_is_preference_or_line_reality(self):
		self.assertRegex(
			_squash(LINES),
			r"const hasDims = computed\(\(\) => props\.showDims \|\| props\.items\.some\(isDim\)\)",
		)

	def test_the_toggle_is_disabled_when_a_line_forces_the_column(self):
		"""Basıldığında hiçbir şey olmayan bir düğme bozuk bir düğmedir."""
		self.assertRegex(_squash(FORM), r':disabled="dimsForced"')
		self.assertRegex(
			_squash(FORM),
			r"const dimsForced = computed\(\(\) => \(form\.value\?\.items \|\| \[\]\)"
			r'\.some\(\(l\) => \["Linear", "Area", "Volume"\]\.includes\(l\.dimension_mode\)\)',
		)

	def test_the_disabled_toggle_explains_itself(self):
		self.assertIn("priced by size, so the measurement columns cannot be hidden", FORM)


class TestTheTenantPreferenceIsWired(unittest.TestCase):
	def test_the_form_seeds_the_toggle_from_the_tenant_flag(self):
		self.assertRegex(
			_squash(FORM), r"const showDims = ref\(Boolean\(session\.modules\?\.dimensional_lines\)\)"
		)

	def test_the_key_exists_in_the_defaults(self):
		"""Anahtar DEFAULT_MODULE_ENABLED'da yoksa module_map_for onu hiç
		döndürmez ve tercih her kiracıda kapalı görünür."""
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {") :]
		block = block[: block.index("\n}")]
		self.assertIn('"dimensional_lines": False', block)

	def test_the_module_key_maps_to_the_column(self):
		self.assertRegex(ORG, r'"dimensional_lines":\s*"enable_dimensional_lines"')

	def test_the_column_exists_on_the_doctype(self):
		self.assertIn('"fieldname": "enable_dimensional_lines"', MODULES_JSON)
		self.assertIn('"enable_dimensional_lines"', MODULES_JSON.split('"field_order"')[1][:900])

	def test_the_doctype_description_says_it_is_display_only(self):
		"""Yöneticiye "bu bir hesap ayarı" izlenimi verirsek, kapalıyken
		ölçülerin çalışmayacağını sanar. Alanı fieldname üzerinden bul —
		field_order listesindeki ilk geçiş alan tanımı değil."""
		import json

		doc = json.loads(MODULES_JSON)
		field = next(f for f in doc["fields"] if f["fieldname"] == "enable_dimensional_lines")
		self.assertIn("DISPLAY preference only", field.get("description", ""))


class TestTheFlagIsActuallyTogglable(unittest.TestCase):
	"""Okuma eşlemesine eklenip yazma yoluna eklenmeyen bir bayrak yalnız yama
	ile set edilebilir — direct_invoicing tam olarak bu durumdaydı."""

	FLAGS = ("dimensional_lines", "direct_invoicing")

	def test_the_update_api_accepts_the_flag(self):
		fn = ORG[ORG.index("def update_company_modules(") :]
		fn = fn[: fn.index("\n@frappe.whitelist()")]
		for flag in self.FLAGS:
			with self.subTest(flag=flag):
				self.assertRegex(fn, rf"\n\t{flag}=None,", f"{flag} parametre listesinde yok")
				self.assertIn(f'"enable_{flag}": {flag},', fn)

	def test_the_admin_screen_lists_the_flag(self):
		for flag in self.FLAGS:
			with self.subTest(flag=flag):
				self.assertRegex(ADMIN, rf'\{{ key: "{flag}", label:')


class TestThePatchDerivesFromDataNotNames(unittest.TestCase):
	def test_the_patch_is_registered(self):
		self.assertIn("stabler.patches.v63_enable_dimensional_lines", PATCHES)

	def test_patch_guards_on_both_columns(self):
		"""Yamalar doctype senkronundan ÖNCE çalışıyor; iki sütun da yok olabilir."""
		self.assertIn('has_column("Stabler Company Modules", "enable_dimensional_lines")', PATCH)
		self.assertIn('has_column("Item", "custom_dimension_mode")', PATCH)

	def test_patch_asks_the_catalogue_instead_of_listing_tenants(self):
		"""Kiracı adı yazmak, v62'de temizlediğimiz hatanın aynısını yeni bir
		yere koymak olurdu."""
		for token in ("MSA", "ANJAN", "LAMINOR", "MIKAS", "HORECA", "SMARTBOX", "DTS"):
			with self.subTest(token=token):
				self.assertNotIn(token, PATCH)
		self.assertRegex(PATCH, r"custom_dimension_mode IN \('Linear', 'Area', 'Volume'\)")

	def test_patch_only_ever_writes_a_row_that_has_no_answer_yet(self):
		"""Bu patch eskiden iki ifadeydi — önce NULL'ları 0'a kapatan, sonra
		KOŞULSUZ herkesi 1'e açan. Güvenliği bir WHERE'den değil ifade
		sırasından geliyordu, ve ikinci koşuda katalog hâlâ ölçülü ürün
		taşıdığı için operatörün bilerek kapattığı şirketi sessizce geri
		açıyordu. Artık tek geçiş, ve tek yazdığı satır cevabı olmayan satır.
		Davranışın kendisi `test_module_flag_patch_replay.py`'de sabitli."""
		for statement in PATCH.split("frappe.db.sql")[1:]:
			if "SET enable_dimensional_lines" not in statement:
				continue
			self.assertIn("WHERE enable_dimensional_lines IS NULL", statement)

	def test_the_default_is_off(self):
		"""Kiracıların çoğu (horeca, smartbox, msa) hiç ölçülü ürün satmıyor."""
		self.assertRegex(MODULES_JSON, r'"default": "0",\s*"description": "Show the measurement columns')


if __name__ == "__main__":
	unittest.main()
