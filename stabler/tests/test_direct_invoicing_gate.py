"""Doğrudan faturalama kapısı: şirket ADI değil, kiracı bayrağı.

Kural: Satış Faturası normalde gönderilmiş bir Satış Siparişi'nden çıkar.
Bunu atlamak bir istisna ve kiracı başına açılır. Eskiden bu istisna şirket
adının içinde "MSA" geçip geçmediğine bakılarak veriliyordu — Stabler'daki
diğer ~40 yeteneğin hiçbiri böyle kapılanmıyor.

Bu dosya iki şeyi kilitliyor. Yenisinin çalıştığını göstermek yetmez; asıl
kanıt ESKİ davranışın öldüğü: adında MSA geçen ama bayrağı kapalı bir şirket
artık geçememeli.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SALES = (ROOT / "api/sales.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "stabler/doctype/stabler_settings/stabler_settings.py").read_text(encoding="utf-8")
ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
MODULES_JSON = (ROOT / "stabler/doctype/stabler_company_modules/stabler_company_modules.json").read_text(
	encoding="utf-8"
)
PATCHES = (ROOT / "patches.txt").read_text(encoding="utf-8")
PATCH = (ROOT / "patches/v62_enable_direct_invoicing.py").read_text(encoding="utf-8")

_RAW_GATE = SALES[SALES.index("def create_direct_sales_invoice") :][:2600]


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
			r"company[^\n]*\.upper\(\)",
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
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {") :]
		block = block[: block.index("\n}")]
		self.assertRegex(block, r'"direct_invoicing":\s*(False|0)\b')

	def test_the_default_is_off(self):
		"""Fatura normalde SO'dan çıkar. Varsayılan açık olsaydı yeni bir
		kiracı kuralı hiç istemeden atlardı."""
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {") :]
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


class TestEveryWriterCarriesTheSameGate(unittest.TestCase):
	"""Kapı bir uca değil, YETENEĞE ait.

	`create_direct_sales_invoice` bayrağı okuyordu, `update_sales_invoice`
	okumuyordu — ikisi de aynı paylaşılan satır kurucusundan yazdığı hâlde. Yani
	bayrağı kapalı bir kiracıda doğrudan fatura yaratılamıyor, ama var olan bir
	taslağın bütün satırları değiştirilebiliyordu.

	Yukarıdaki testlerin hiçbiri bunu göremezdi: hepsi `_RAW_GATE` üzerinden
	çalışıyor, o da kaynağın yalnızca `create_direct_sales_invoice`'tan başlayan
	2600 karakterlik bir dilimi. Bir dilim, dilimin dışındaki eksikliği
	tanımlayamaz.

	Bu yüzden burada uç ADI sayılmıyor. Kural yapısal: `_direct_invoice_item_rows`
	çağıran her fonksiyon doğrudan faturalama yazma yolundadır ve bayrağı okumak
	zorundadır. Sonradan eklenecek üçüncü bir uç da kendiliğinden yakalanır.
	"""

	WRITER = "_direct_invoice_item_rows"
	GATE = "module_map_for"

	@classmethod
	def setUpClass(cls):
		cls.tree = ast.parse(SALES)

	def _def(self, name: str) -> ast.FunctionDef:
		for node in ast.walk(self.tree):
			if isinstance(node, ast.FunctionDef) and node.name == name:
				return node
		raise AssertionError(f"{name} bulunamadı")

	def _writers(self) -> dict[str, set[str]]:
		"""Satır kurucusunu çağıran fonksiyonlar → gövdelerinde çağrılan isimler."""
		found = {}
		for node in ast.walk(self.tree):
			if not isinstance(node, ast.FunctionDef) or node.name == self.WRITER:
				continue
			called = {
				(c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
				for c in ast.walk(node)
				if isinstance(c, ast.Call)
			}
			if self.WRITER in called:
				found[node.name] = called
		return found

	def test_at_least_two_endpoints_call_the_row_builder(self):
		# Bu testin boşa çalışmadığının kanıtı. Kurucu yeniden adlandırılır ya da
		# satır içine alınırsa aşağıdaki döngüler sıfır kez döner ve yeşil kalırdı —
		# kapsamı daralan bir test, kapsamı geniş bir testten daha tehlikelidir,
		# çünkü kanıt diye gösterilir.
		writers = self._writers()
		self.assertGreaterEqual(
			len(writers),
			2,
			f"{self.WRITER} çağıran uç sayısı beklenenden az: {sorted(writers)} — "
			"kurucu yeniden adlandırıldıysa bu sınıfın tamamı sessizce boşa döner",
		)

	def test_every_writing_endpoint_reads_the_module_map(self):
		for name, called in sorted(self._writers().items()):
			with self.subTest(uc=name):
				self.assertIn(
					self.GATE,
					called,
					f"{name} doğrudan faturalama satırı yazıyor ama {self.GATE} okumuyor — "
					"bayrağı kapalı kiracıda bu uç açık kalır",
				)

	def test_every_writing_endpoint_reads_the_same_module_key(self):
		# Aynı yeteneğin iki ucu iki farklı anahtar okursa kapı kapı olmaktan çıkar.
		for name in sorted(self._writers()):
			with self.subTest(uc=name):
				body = ast.get_source_segment(SALES, self._def(name)) or ""
				self.assertIn(
					'"direct_invoicing"',
					body,
					f"{name} modül haritasını okuyor ama direct_invoicing anahtarını değil",
				)


if __name__ == "__main__":
	unittest.main()


class TestTheImporterCarriesTheGateToo(unittest.TestCase):
	"""Excel içe aktarma ucu da aynı bayrağa bakmalı.

	`execute_sales_import` yalnızca `has_permission("Sales Invoice", "create")` ve
	şirket kapsamı istiyordu — modül kapısı yoktu. Yani doğrudan faturalamaya
	sahip olmayan altı kiracıda da çağrılabiliyordu, üstelik `doc.submit()`
	ettiği için sonuç taslak değil kesinleşmiş faturaydı: özelliği olmayan bir
	kiracı, olmadığı bir yetenek üzerinden muhasebe kaydı doğurabiliyordu.

	Kapı ayrıca koli korumasının iddiasını doğru kılıyor: kapı olmadan koruma,
	bayrağı kapalı kiracılarda HER içe aktarmayı reddederdi — v94'ün bilerek
	hiçbir şey yaratmadığı yerde. Kapıyla birlikte koruma yalnızca kendi
	anlattığı tek durum için ateşler: bayrağı v94 koştuktan SONRA açan kiracı.
	"""

	SOURCE = (ROOT / "stabler/api/sales_import.py").read_text(encoding="utf-8")
	ENDPOINT = "execute_sales_import"

	def _body(self) -> str:
		start = self.SOURCE.index(f"def {self.ENDPOINT}(")
		end = self.SOURCE.find("\ndef ", start + 1)
		return _code_only(self.SOURCE[start : end if end != -1 else len(self.SOURCE)])

	def test_the_importer_reads_the_tenant_flag(self):
		self.assertIn(
			"module_map_for",
			self._body(),
			"içe aktarma ucu modül bayrağına bakmıyor — özelliği olmayan kiracı da fatura submit edebilir",
		)

	def test_it_reads_the_same_flag_name_the_patch_is_gated_on(self):
		self.assertIn(
			"direct_invoicing",
			self._body(),
			"başka bir bayrağa bakıyor — patch ile içe aktarma farklı kapılara bağlı olamaz",
		)

	def test_the_gate_runs_before_the_file_is_even_read(self):
		body = self._body()
		gate_at = body.index("module_map_for")
		read_at = body.index("_get_file_content")
		self.assertLess(
			gate_at,
			read_at,
			"kapı dosya okunduktan sonra — sahibi olmayan kiracının dosyası boşuna işlenir",
		)
