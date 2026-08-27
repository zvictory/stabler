"""POS'un görünürlüğü kiracı ayarından okunur, `sales`'e binmez.

POS ekranı 2026-08-27'ye kadar kendi modül anahtarına sahip değildi: rota
`meta: { module: "sales" }`, sidebar `canAccessModule("sales")` taşıyordu.
`sales` ise varsayılan-açık dört çekirdek modülden biri, ve POS kullanmayan bir
kiracının (tender/kassa) satış akışları ona bağlı — yani POS'u kapatmanın tek
yolu kiracıyı çalışamaz hâle getirmekti. Kapatılamayan bir ekran, kiracı ayarı
değil kod sabitidir; `.claude/rules/30-tenant-modules.md` tam olarak bunu
yasaklıyor ("Never branch on tenant name", kiracıya özel her davranış
module-gated olmalı).

Bu testin koruduğu şey: `pos` anahtarının beş noktanın hepsinde bağlı kalması.
Biri kopsa bayrak ya hiç okunmaz (rota `sales`'e geri döner) ya da hiç
açılıp kapanamaz (yönetici ekranı yazamaz) — ve her iki hâlde de kırılma
sessizdir, çünkü POS varsayılan olarak açık gelir ve altı kiracıda hiçbir şey
değişmemiş gibi görünür. Sessiz kırılmayı ancak bu bağlar yakalar.

Varsayılan AÇIK olması kasıtlı ve `modern_sales_order` bayrağının tersi:
POS yeni bir özellik değil, yedi kiracıda hâlihazırda çalışan bir ekran.
`v100_enable_pos` bugünkü kuralı (`enable_pos = enable_sales`) sadık biçimde
çeviriyor, yeni bir karar üretmiyor. Kapatma kararı tek bir kiracıda, deploy
sonrası yönetici ekranından veriliyor — repoda kiracı adı geçmiyor.

`modern_sales_order`'dan ayrıldığı ikinci nokta: bu bir tercih değil bir
erişim kapısı, o yüzden `_MODULE_ROLES`'e ve rota `meta.module`'üne girer.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "stabler/doctype/stabler_settings/stabler_settings.py").read_text(encoding="utf-8")
MODULES_JSON_TEXT = (ROOT / "stabler/doctype/stabler_company_modules/stabler_company_modules.json").read_text(
	encoding="utf-8"
)
ADMIN = (ROOT / "public/js/pages/admin/Companies.vue").read_text(encoding="utf-8")
CATALOG = (ROOT / "public/js/composables/modules.js").read_text(encoding="utf-8")
ROUTER = (ROOT / "public/js/router.js").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "public/js/components/Sidebar.vue").read_text(encoding="utf-8")
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")
PATCH = (ROOT / "patches/v100_enable_pos.py").read_text(encoding="utf-8")


def _pos_route_line() -> str:
	"""`/pos` rotasının tanımlandığı tek satır."""
	for line in ROUTER.splitlines():
		if re.search(r'path:\s*"/pos"', line):
			return line
	raise AssertionError("router.js içinde `/pos` rotası bulunamadı")


def _pos_sidebar_line() -> str:
	for line in SIDEBAR.splitlines():
		if re.search(r'name:\s*"pos"', line):
			return line
	raise AssertionError("Sidebar.vue içinde POS girdisi bulunamadı")


class TestPosNoLongerRidesOnSales(unittest.TestCase):
	"""Kopması en kolay ve en sessiz iki bağ: rota ve sidebar."""

	def test_the_route_is_gated_by_pos_not_sales(self):
		"""`meta.module` olmadan guard doğrudan-URL erişimini kesemez
		(router.js:681). `sales` kalırsa POS kapatılamaz olur."""
		line = _pos_route_line()
		self.assertIn('module: "pos"', line)
		self.assertNotIn('module: "sales"', line)

	def test_the_sidebar_entry_is_gated_by_pos_not_sales(self):
		line = _pos_sidebar_line()
		self.assertIn('canAccessModule("pos")', line)
		self.assertNotIn('canAccessModule("sales")', line)


class TestTheFlagIsWiredEndToEnd(unittest.TestCase):
	def test_the_module_key_maps_to_the_column(self):
		self.assertRegex(ORG, r'"pos":\s*"enable_pos"')

	def test_the_column_exists_on_the_doctype_and_in_field_order(self):
		self.assertIn('"fieldname": "enable_pos"', MODULES_JSON_TEXT)
		doc = json.loads(MODULES_JSON_TEXT)
		self.assertIn("enable_pos", doc["field_order"])

	def test_the_update_api_accepts_the_flag(self):
		"""Yazma yolu olmayan bayrak açılıp kapanamaz — mikas'ta kapatma
		işleminin tamamı bu parametreye dayanıyor."""
		fn = ORG[ORG.index("def update_company_modules(") :]
		fn = fn[: fn.index("\n@frappe.whitelist()")]
		self.assertRegex(fn, r"\n\tpos=None,")
		self.assertIn('"enable_pos": pos,', fn)

	def test_the_admin_screen_lists_the_flag(self):
		self.assertRegex(ADMIN, r'\{ key: "pos", label:')

	def test_the_user_override_drawer_knows_the_key(self):
		"""MODULE_CATALOG kullanıcı bazlı override çekmecesini besliyor;
		anahtar eksikse bir kullanıcıya POS ayrı ayrı verilemez."""
		self.assertRegex(CATALOG, r'\{ key: "pos", label:')


class TestItIsAPermissionNotAPreference(unittest.TestCase):
	def test_the_role_gate_grants_pos_to_sales_roles(self):
		"""`_MODULE_ROLES`'de olmayan anahtar least-privilege varsayılanına
		düşer (organization.py:114) — POS her kiracıda admin-only olurdu."""
		# Bildirime sabitle, adın ilk geçtiği yere değil: "_MODULE_ROLES"
		# ilk olarak _MODULE_FIELDS içindeki bir yorumda geçiyor ve oradan
		# dilimlemek yanlış sözlüğü okutur.
		roles = ORG[ORG.index("_MODULE_ROLES: dict[str, list[str]] = {") :]
		roles = roles[: roles.index("\n}")]
		self.assertIn('"pos":', roles)
		pos_entry = roles[roles.index('"pos":') :]
		pos_entry = pos_entry[: pos_entry.index("]")]
		self.assertIn("Sales User", pos_entry)
		self.assertIn("Sales Manager", pos_entry)


class TestTheDefaultChangesNothingForAnyone(unittest.TestCase):
	"""POS canlıda çalışan bir ekran; bayrağın gelişi kimseden onu almamalı."""

	def test_a_new_company_gets_pos(self):
		doc = json.loads(MODULES_JSON_TEXT)
		field = next(f for f in doc["fields"] if f["fieldname"] == "enable_pos")
		self.assertEqual(field.get("default"), "1")

	def test_the_no_row_fallback_gets_pos(self):
		"""`module_map_for` satır yoksa DEFAULT_MODULE_ENABLED'ı döndürür;
		ayrıca anahtar burada yoksa haritada hiç görünmez ve
		`canAccessModule` pre-boot default-open davranışına düşer."""
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {") :]
		block = block[: block.index("\n}")]
		self.assertIn('"pos": True', block)

	def test_the_patch_copies_the_rule_it_replaces_and_invents_nothing(self):
		"""Bugünkü kural "sales açıksa POS görünür". Patch bunu birebir
		çeviriyor; sabit bir 1 ya da 0 yazsaydı bir kiracının davranışını
		sessizce değiştirirdi."""
		self.assertIn("enable_pos = enable_sales", PATCH)
		self.assertNotIn("enable_pos = 1", PATCH)
		self.assertNotIn("enable_pos = 0", PATCH)


class TestThePatchIsRegisteredAndSafe(unittest.TestCase):
	def test_the_patch_is_registered(self):
		self.assertIn("stabler.patches.v100_enable_pos", PATCHES)

	def test_the_patch_guards_on_the_column(self):
		self.assertIn('has_column("Stabler Company Modules", "enable_pos")', PATCH)

	def test_the_patch_never_overwrites_a_decision(self):
		"""Replay gerçek bir senaryo (backup restore, elle patch koşturma).
		Operatörün kapattığı bayrak ikinci koşuda geri açılmamalı."""
		self.assertIn("WHERE enable_pos IS NULL", PATCH)


if __name__ == "__main__":
	unittest.main()
