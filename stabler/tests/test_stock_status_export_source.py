"""Kayıt defterindeki sütun adları, satırı üreten kodla aynı sözlüğü konuşmak zorunda.

`export_report_xlsx`, `REPORT_EXPORTS` kaydındaki `columns` listesini alır ve her
sütunun `key`'ini satır sözlüğünde arar. `list_source` kullanan kayıtlarda o
sütun listesi **elle** yazılır — kaynağın gerçekte hangi anahtarları döndürdüğüne
bağlayan hiçbir şey yoktur. Yanlış yazılmış tek bir anahtar hata vermez:

* sütun adı tutmazsa Excel'de o sütun **boş** çıkar;
* `rows_key` tutmazsa dosya **hiç satır içermez**.

İkisi de sunucuda sessizdir, testlerde sessizdir, ve ancak kullanıcı dosyayı
açtığında görünür. Bu testin koruduğu şey tam olarak o bağ: kaydın konuştuğu
anahtarlar, `warehouse_stock`'ın gerçekten ürettiği anahtarlar olmalı.

Üçüncü bağ ekranda: düğme, kayıt defterinde var olmayan bir `report_key`
gönderirse uç `Unknown report` diye patlar. Bu yüzden `.vue` dosyasının
kullandığı anahtar da burada doğrulanır.

Frappe önyüklemesi yok: yalnız kaynak okur (`export.py` frappe import eder).
"""

import ast
import unittest
from pathlib import Path

APP = Path(__file__).parents[1]
EXPORT_SRC = APP / "api" / "export.py"
INVENTORY_SRC = APP / "api" / "inventory.py"
SCREEN_SRC = APP / "public" / "js" / "pages" / "inventory" / "StockStatus.vue"

REPORT_KEY = "warehouse_stock"


def _module(path: Path) -> ast.Module:
	return ast.parse(path.read_text(encoding="utf-8"))


def _registry_entry(key: str) -> dict:
	"""The `REPORT_EXPORTS[key]` literal, as a plain dict."""
	for node in ast.walk(_module(EXPORT_SRC)):
		# The registry is annotated (`REPORT_EXPORTS: dict[str, dict] = {...}`),
		# which parses as AnnAssign, not Assign — accept either so a later
		# annotation change cannot turn this whole test green-by-absence.
		if isinstance(node, ast.AnnAssign):
			targets = [node.target]
		elif isinstance(node, ast.Assign):
			targets = node.targets
		else:
			continue
		if not any(isinstance(t, ast.Name) and t.id == "REPORT_EXPORTS" for t in targets):
			continue
		if not isinstance(node.value, ast.Dict):
			continue
		for k, v in zip(node.value.keys, node.value.values, strict=True):
			if isinstance(k, ast.Constant) and k.value == key:
				return ast.literal_eval(v)
	return {}


def _returned_dict_keys(path: Path, func_name: str) -> set[str]:
	"""Keys of the dict literal a function returns."""
	for node in ast.walk(_module(path)):
		if not isinstance(node, ast.FunctionDef) or node.name != func_name:
			continue
		for sub in ast.walk(node):
			if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
				return {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
	return set()


class TestStockStatusExportRegistry(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.entry = _registry_entry(REPORT_KEY)

	def test_the_report_is_registered_at_all(self):
		"""Without an entry the Excel button answers `Unknown report`."""
		self.assertTrue(self.entry, f"REPORT_EXPORTS has no '{REPORT_KEY}' entry")

	def test_rows_key_names_something_warehouse_stock_actually_returns(self):
		"""A wrong `rows_key` exports a workbook with headers and no rows."""
		rows_key = self.entry.get("rows_key")
		self.assertTrue(rows_key, "entry declares no rows_key")
		returned = _returned_dict_keys(INVENTORY_SRC, "warehouse_stock")
		self.assertIn(
			rows_key,
			returned,
			f"rows_key '{rows_key}' is not among warehouse_stock's return keys {sorted(returned)}",
		)

	def test_every_column_key_is_a_key_the_row_builder_emits(self):
		"""A column naming a key nothing produces exports a blank column."""
		columns = {c["key"] for c in self.entry.get("columns", [])}
		self.assertTrue(columns, "entry declares no columns")
		produced = _returned_dict_keys(INVENTORY_SRC, "_format_warehouse_stock_row")
		self.assertTrue(produced, "could not read _format_warehouse_stock_row's row shape")
		self.assertEqual(
			set(),
			columns - produced,
			f"columns name keys the row builder never emits: {sorted(columns - produced)}",
		)

	def test_the_screen_asks_for_the_key_that_is_registered(self):
		"""The button's report_key and the registry key are one contract."""
		self.assertIn(
			f'"{REPORT_KEY}"',
			SCREEN_SRC.read_text(encoding="utf-8"),
			f"StockStatus.vue does not send report_key '{REPORT_KEY}'",
		)


if __name__ == "__main__":
	unittest.main()
