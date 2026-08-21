"""As-of bir tarihe kadar oynatılmış defterdir — kısmen oynatılmışı yoktur.

`list_customers_with_balances` bakiyeyi tek bir sorgudan çıkarmaz. `tabGL Entry`
üzerinde üç ayrı toplama koşar:

* kitap-geneli toplam (liste kesildiğinde),
* müşteri başına bakiye,
* tek bacaklı Payment Entry'lerin hesap-para-birimi sapmasını düzelten terim.

Üçü toplanarak tek bir rakam olur. Kesim tarihi bunlardan yalnız bazılarına
uygulanırsa sonuç *karışık* çıkar: bir terim 30 Haziran'a kadarki defteri, öteki
bugüne kadarki defteri anlatır. Böyle bir sayı hata vermez, boş da gelmez —
makul görünür ve yanlıştır. Bu testin koruduğu şey o eşitlik: `tabGL Entry`'ye
dokunan her toplama aynı sınırı taşımak zorunda.

İkinci koruma dürüstlükle ilgili. "Vadesi geçmiş", `Sales Invoice.outstanding_
amount` üzerinden hesaplanır; o alan faturanın **bugünkü** kalanıdır, geçmişe
dönük yeniden kurulamaz. Geçmiş bir tarihe "kimse gecikmemiş" demek, veri
olmadığını söylemekten daha kötüdür — o yüzden ikisi birlikte istendiğinde
reddedilir.

Üçüncüsü ekranda: rapor kullanıcıya dayanağını yazıyor ("Live receivable,
all-time"). Tarih seçiliyken o cümle yalan olur, dolayısıyla dallanmak zorunda.

Frappe önyüklemesi yok: yalnız kaynak okur.
"""

import ast
import re
import unittest
from pathlib import Path

APP = Path(__file__).parents[1]
SALES_SRC = APP / "api" / "sales.py"
REPORTS_SRC = APP / "api" / "reports.py"

# Üçlü tırnaklı SQL blokları — f-string öneki de eşleşir.
_SQL_BLOCK = re.compile(r'"""(.*?)"""', re.DOTALL)


def _function_source(path: Path, name: str) -> str:
	tree = ast.parse(path.read_text(encoding="utf-8"))
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
	raise AssertionError(f"{name} not found in {path.name}")


def _params(path: Path, name: str) -> list[str]:
	tree = ast.parse(path.read_text(encoding="utf-8"))
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
	raise AssertionError(f"{name} not found in {path.name}")


class TestCustomerBalanceAsOf(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.balances = _function_source(SALES_SRC, "list_customers_with_balances")
		cls.summary = _function_source(REPORTS_SRC, "customer_balance_summary")

	def test_the_balance_source_accepts_a_cutoff(self):
		self.assertIn("as_of", _params(SALES_SRC, "list_customers_with_balances"))

	def test_every_gl_aggregation_carries_the_same_cutoff(self):
		"""Bir terimi sınırlayıp diğerini bırakmak karışık bir bakiye üretir."""
		gl_blocks = [b for b in _SQL_BLOCK.findall(self.balances) if "tabGL Entry" in b]
		self.assertGreaterEqual(len(gl_blocks), 3, "expected at least three GL aggregations to bound")

		def _label(block: str) -> str:
			"""İlk anlamlı SELECT satırı — samanlığı değil, iğneyi bas."""
			return next((ln.strip() for ln in block.splitlines() if ln.strip()), "?")[:70]

		unbounded = [_label(b) for b in gl_blocks if "as_of" not in b]
		self.assertEqual(
			[],
			unbounded,
			"these GL aggregations ignore the as-of cutoff, so their term stays "
			f"all-time while the others do not: {unbounded}",
		)

	def test_overdue_is_refused_rather_than_answered_wrongly(self):
		"""`outstanding_amount` bugünkü kalandır; geçmişe dönük gecikme uydurulamaz."""
		self.assertTrue(
			re.search(r"if as_of and cint\(only_overdue\)[\s\S]{0,400}?frappe\.throw", self.balances),
			"as_of + only_overdue must be refused, not silently answered",
		)

	def test_overdue_is_not_reported_as_zero_when_a_cutoff_is_set(self):
		"""Boş bir overdue haritası herkesi 'gecikmemiş' gösterir — o da bir yalan."""
		self.assertTrue(
			re.search(r'r\["overdue_base"\]\s*=\s*None if as_of else', self.balances),
			"overdue_base must be None (unknown) under a cutoff, not 0.0 (not overdue)",
		)

	def test_the_report_forwards_the_cutoff(self):
		"""Rapor tarihi alıp kaynağa geçirmezse seçici hiçbir şey yapmaz."""
		self.assertIn("as_of", _params(REPORTS_SRC, "customer_balance_summary"))
		self.assertTrue(
			re.search(r"list_customers_with_balances\([\s\S]{0,300}?as_of=as_of", self.summary),
			"customer_balance_summary must pass as_of through",
		)

	def test_the_report_stops_calling_itself_all_time_when_it_is_not(self):
		"""Ekrandaki dayanak cümlesi tarih seçiliyken değişmek zorunda."""
		self.assertTrue(
			re.search(r'"basis":[\s\S]{0,200}?if as_of', self.summary),
			"the basis line must branch on as_of — otherwise it claims all-time while showing a cutoff",
		)


if __name__ == "__main__":
	unittest.main()
