"""Doğrudan faturalama kapısı: şirket ADI değil, kiracı bayrağı.

Kural: Satış Faturası normalde gönderilmiş bir Satış Siparişi'nden çıkar.
Bunu atlamak bir istisna ve kiracı başına açılır. Eskiden bu istisna şirket
adının içinde "MSA" geçip geçmediğine bakılarak veriliyordu — Stabler'daki
diğer ~40 yeteneğin hiçbiri böyle kapılanmıyor.

Bu dosya iki şeyi kilitliyor. Yenisinin çalıştığını göstermek yetmez; asıl
kanıt ESKİ davranışın öldüğü: adında MSA geçen ama bayrağı kapalı bir şirket
artık geçememeli.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SALES = (ROOT / "api/sales.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "stabler/doctype/stabler_settings/stabler_settings.py").read_text(encoding="utf-8")
ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
MODULES_JSON = (
	ROOT / "stabler/doctype/stabler_company_modules/stabler_company_modules.json"
).read_text(encoding="utf-8")
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")
PATCH = (ROOT / "patches/v62_enable_direct_invoicing.py").read_text(encoding="utf-8")

_RAW_GATE = SALES[SALES.index("def create_direct_sales_invoice"):][:2600]


def _code_only(src: str) -> str:
	"""Yorumları ve docstring'leri at.

	Testin sorusu "kodda şirket adına göre karar veriliyor mu"; eski kuralı
	ANLATAN bir yorum o karara ait değil. Ham metni taramak, değişikliği
	açıklayan yorumu ihlal sayardı — ki bu, yorum yazmayı cezalandırırdı."""
	out = []
	for line in src.split("\n"):
		stripped = line.lstrip()
		if stripped.startswith("#"):
			continue
		out.append(line.split(" #")[0] if " #" in line else line)
	body = "\n".join(out)
	# tek docstring bloğu
	if body.count('"""') >= 2:
		a = body.index('"""')
		b = body.index('"""', a + 3) + 3
		body = body[:a] + body[b:]
	return body


GATE = _code_only(_RAW_GATE)


class TestTheNameRuleIsGone(unittest.TestCase):
	"""Asıl regresyon testi. Bayrak eklenip isim kontrolü YERİNDE bırakılırsa
	iki kapı birden olur ve kiracı bayrağı kapatınca hiçbir şey değişmez."""

	def test_the_gate_does_not_test_the_company_name(self):
		self.assertNotIn('"MSA"', GATE, "kapı hâlâ şirket adına bakıyor")
		self.assertNotRegex(
			GATE,
			r'company[^\n]*\.upper\(\)',
			"kapı hâlâ şirket adını büyütüp karşılaştırıyor",
		)

	def test_no_company_name_literal_survives_anywhere_in_the_gate(self):
		"""Marka adının kod akışında hiç geçmemesi gerek — geçiyorsa bir yerde
		hâlâ karar veriyordur."""
		for token in ("MSA", "ANJAN", "MIKAS"):
			with self.subTest(token=token):
				self.assertNotIn(token, GATE)


class TestTheGateReadsTheTenantFlag(unittest.TestCase):
	def test_gate_reads_module_map(self):
		self.assertRegex(
			GATE,
			r'module_map_for\(company\)\.get\(\s*"direct_invoicing"\s*\)',
			"kapı module_map_for üzerinden direct_invoicing okumuyor",
		)

	def test_gate_uses_the_module_key_not_the_column_name(self):
		"""module_map_for anahtarları DEFAULT_MODULE_ENABLED'dan türetir ve
		sütunu `enable_{key}` olarak okur. Sütun adıyla sorgulamak her zaman
		None döndürür — yani bayrağı AÇIK olan kiracıda bile kapı kapanır."""
		self.assertNotIn('get("enable_direct_invoicing")', GATE)

	def test_the_key_exists_in_the_defaults(self):
		"""Anahtar DEFAULT_MODULE_ENABLED'da yoksa module_map_for onu hiç
		döndürmez ve kapı herkese kapanır."""
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {"):]
		block = block[: block.index("\n}")]
		self.assertRegex(block, r'"direct_invoicing":\s*(False|0)\b')

	def test_the_default_is_off(self):
		"""Fatura normalde SO'dan çıkar. Varsayılan açık olsaydı yeni bir
		kiracı kuralı hiç istemeden atlardı."""
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {"):]
		block = block[: block.index("\n}")]
		self.assertIn('"direct_invoicing": False', block)


class TestTheFlagIsWiredEndToEnd(unittest.TestCase):
	def test_the_column_exists_on_the_doctype(self):
		self.assertIn('"fieldname": "enable_direct_invoicing"', MODULES_JSON)
		self.assertIn("enable_direct_invoicing", MODULES_JSON)

	def test_the_module_key_maps_to_the_column(self):
		self.assertRegex(ORG, r'"direct_invoicing":\s*"enable_direct_invoicing"')

	def test_the_patch_is_registered(self):
		self.assertIn("stabler.patches.v62_enable_direct_invoicing", PATCHES)


class TestThePatchIsSafeAndFaithful(unittest.TestCase):
	def test_patch_guards_on_the_column_existing(self):
		"""Yamalar doctype senkronundan ÖNCE çalışıyor. Guard olmadan bu
		yamayı taşıyan ilk migrate eksik sütunda patlar."""
		self.assertIn('has_column("Stabler Company Modules", "enable_direct_invoicing")', PATCH)
		self.assertRegex(PATCH, r"if not frappe\.db\.has_column\([^)]*\):\s*\n\s*return")

	def test_patch_reproduces_the_old_rule_rather_than_deciding_anew(self):
		"""Geçiş hiçbir kiracıda davranış değiştirmemeli: eski kuralın
		geçirdiği kim ise bayrağı açık olan o olmalı."""
		self.assertIn("%MSA%", PATCH)
		self.assertRegex(PATCH, r"UPPER\(company\)\s+LIKE")

	def test_patch_closes_nulls_before_opening_anyone(self):
		"""NULL bir bayrak izin veriyormuş gibi okunmamalı; önce herkes
		kapatılıp sonra eşleşenler açılıyor."""
		zero = PATCH.index("SET enable_direct_invoicing = 0")
		one = PATCH.index("SET enable_direct_invoicing = 1")
		self.assertLess(zero, one, "önce sıfırlama, sonra açma sırası bozulmuş")


class TestTheErrorStillExplainsTheRule(unittest.TestCase):
	def test_message_names_the_company_and_the_alternative(self):
		"""Hata mesajı kullanıcıya ne yapacağını söylemeli: bu şirkette
		kapalı, fatura gönderilmiş bir SO'dan çıkar."""
		self.assertIn("{0}", GATE)
		self.assertIn("submitted Sales Order", GATE)


if __name__ == "__main__":
	unittest.main()
