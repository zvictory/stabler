"""POS'un kiracı kapısı sunucuda da duruyor mu.

2026-08-27'de POS kendi modül anahtarını aldı ve rota/sidebar `pos`'a bağlandı.
O kapı yalnızca SPA erişim katmanıydı — `.claude/rules/30-tenant-modules.md`'nin
kendi ifadesiyle "a UX access layer, not a security boundary". Yani POS'u
kapatmış bir kiracıda menü boştu ama `stabler.api.pos.create_pos_invoice`
doğrudan HTTP çağrısıyla hâlâ gönderilmiş bir POS faturası kesebiliyordu.
Kapatılmış bir ekranın arkasından fatura çıkması, kapatmanın kendisini
anlamsız kılar.

Bu dosyanın asıl işi bugünü kanıtlamak değil, yarını tutmak: **`api/pos.py`'ye
eklenen HER yeni whitelisted uç kapıdan geçmek zorunda.** Sessizce açık kalan
bir uç, tam da kimsenin bakmadığı yerde ortaya çıkar — sekizinci ucu yazan kişi
diğer yedisinin gate'li olduğunu bilmek zorunda kalmasın diye test biliyor.

`_ALLOWLIST` bilerek boş: bir ucun kapısız kalması için gerekçe yazmak gerekir,
ve gerekçe yazmak zorunda kalmak bu dosyanın tek zorlama gücü.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POS_PATH = ROOT / "api/pos.py"
POS_SRC = POS_PATH.read_text(encoding="utf-8")
TREE = ast.parse(POS_SRC)

# Kapıya sayılan çağrılar. `_require_pos` company argümanı alan uçlar için;
# `_require_pos_for_session` company'yi oturum belgesinden türetenler için.
_GATE_TOKENS = ("_require_pos", "_require_pos_for_session")

# Kapısız kalması meşru olan uçlar. Boş bırakıldı: bugün istisna yok.
# Ekleyecek olan, YANINA tek satır gerekçe yazsın — kontrolü zayıflatmasın.
_ALLOWLIST: dict[str, str] = {}


def _is_whitelisted(fn: ast.FunctionDef) -> bool:
	for dec in fn.decorator_list:
		node = dec.func if isinstance(dec, ast.Call) else dec
		if isinstance(node, ast.Attribute) and node.attr == "whitelist":
			return True
	return False


def _calls_in(fn: ast.FunctionDef) -> set[str]:
	names = set()
	for node in ast.walk(fn):
		if isinstance(node, ast.Call):
			f = node.func
			if isinstance(f, ast.Name):
				names.add(f.id)
			elif isinstance(f, ast.Attribute):
				names.add(f.attr)
	return names


WHITELISTED = [n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and _is_whitelisted(n)]


class TestEveryEndpointIsGated(unittest.TestCase):
	def test_the_module_actually_ships_endpoints(self):
		"""Ayrıştırma bozulursa aşağıdaki döngü boş küme üzerinde döner ve
		dosya "hepsi kapılı" diye yeşil kalır. Sıfır uç bir geçiş değildir."""
		self.assertGreaterEqual(len(WHITELISTED), 7, "api/pos.py'de whitelisted uç bulunamadı")

	def test_no_whitelisted_endpoint_reaches_pos_without_the_gate(self):
		for fn in WHITELISTED:
			with self.subTest(endpoint=fn.name):
				if fn.name in _ALLOWLIST:
					self.assertTrue(_ALLOWLIST[fn.name].strip(), "istisnanın gerekçesi boş")
					continue
				calls = _calls_in(fn)
				self.assertTrue(
					calls & set(_GATE_TOKENS),
					f"{fn.name} POS kapısını çağırmıyor — kapalı bir kiracıda erişilebilir kalır",
				)

	def test_the_session_endpoints_derive_the_company_they_gate_on(self):
		"""`pos_gateway_status`/`_cancel` yalnız bir oturum adı alıyor. Company
		argümanı olmadığı için `_require_pos(company)` çağıramazlar; kapının
		delik kalmaması şirketi belgeden türetmelerine bağlı."""
		for name in ("pos_gateway_status", "pos_gateway_cancel"):
			fn = next(f for f in WHITELISTED if f.name == name)
			with self.subTest(endpoint=name):
				self.assertIn("_require_pos_for_session", _calls_in(fn))


class TestTheGateStaysOffTheWebhookPath(unittest.TestCase):
	"""Kapı, sağlayıcı geri çağrısının geçtiği yola ASLA sızmamalı.

	Click/Payme/Uzum ödemeyi onayladığında `integrations/uzpay/common.py:193`
	`build_paid_pos_invoice`'i çağırıyor — `allow_guest=True` bir webhook
	bağlamında, yani `frappe.session.user == "Guest"`. `_can_access_module`
	Guest'e "pos" vermez. Kapıyı bu yola eklemek (doğrudan, ya da paylaşılan
	`_pos_profile_doc` üzerinden dolaylı) müşterinin parasını almış ama
	faturasını kesmemiş bir sistem üretir; hata da kullanıcının göremediği
	webhook loguna düşer.

	Bu yüzden test bugünkü hâli değil, KAPANIŞI tarıyor: yarın birileri
	`_pos_profile_doc`'a kapı eklerse — ki oradan geçen üç uç zaten kapılı
	olduğu için zararsız görünür — bu düşer."""

	def test_the_paid_invoice_builder_is_not_reachable_from_the_gate(self):
		fns = {n.name: n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)}
		self.assertIn("build_paid_pos_invoice", fns, "webhook'un çağırdığı builder kayboldu")
		self.assertFalse(
			_is_whitelisted(fns["build_paid_pos_invoice"]),
			"builder whitelisted olursa kapı zorunlu olur ve webhook yolu kapıya girer",
		)
		seen, stack = set(), ["build_paid_pos_invoice"]
		while stack:
			cur = stack.pop()
			if cur in seen or cur not in fns:
				continue
			seen.add(cur)
			stack.extend(_calls_in(fns[cur]))
		self.assertFalse(
			seen & set(_GATE_TOKENS),
			f"webhook yolu kapıya ulaşıyor: {sorted(seen & set(_GATE_TOKENS))} — ödeme alınır, fatura kesilmez",
		)


class TestTheGateAsksBothQuestions(unittest.TestCase):
	"""Rol VE kiracı. Biri eksikse kapı yarım: yalnız rol sorulursa POS'u
	kapatmış kiracının Sales User'ı geçer; yalnız kiracı sorulursa rolü
	olmayan herkes geçer."""

	def _fn_src(self, name: str) -> str:
		fn = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)
		return ast.get_source_segment(POS_SRC, fn) or ""

	def test_the_gate_checks_the_users_role(self):
		self.assertRegex(self._fn_src("_require_pos"), r'_can_access_module\([^)]*"pos"')

	def test_the_gate_checks_the_companys_flag(self):
		src = self._fn_src("_require_pos_enabled")
		self.assertIn("module_map_for", src)
		self.assertRegex(src, r'\.get\("pos"\)')

	def test_the_gate_raises_permission_error_not_validation_error(self):
		"""ValidationError bir form hatasıdır ve çağıran tarafta yeniden
		denenebilir görünür; kapalı bir modül bir izin cevabıdır."""
		for name in ("_require_pos", "_require_pos_enabled"):
			with self.subTest(fn=name):
				self.assertIn("PermissionError", self._fn_src(name))

	def test_the_gate_never_branches_on_a_tenant_name(self):
		"""30-tenant-modules.md: karar Stabler Company Modules satırında yaşar."""
		src = self._fn_src("_require_pos") + self._fn_src("_require_pos_enabled")
		for token in ("MIKAS", "Mikas", "ANJAN", "MSA"):
			self.assertNotIn(token, src)


if __name__ == "__main__":
	unittest.main()
