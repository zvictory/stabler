"""Kitap toplamı sorgusu ile onu ekranda gösteren bayrak aynı değer olmalı.

`list_customers_with_balances` içindeki kitap-geneli toplam sorgusu tam bir
`tabGL Entry` taramasıdır — ANJAN prod'unda 2026-08-07'de ölçüldü: uç noktanın
2,6–3,4 sn'lik SQL süresinin 0,9–2,1 sn'si. Ama arayüz bu rakamı **yalnız liste
`limit` ile kırpıldığında** gösteriyor (`PartyCenter.vue` → `showGrandTotals`,
`listTruncated`'a bağlı). ANJAN'da 1328 müşteri / limit 2500, yani kırpma hiç
olmuyor ve o iki saniye her açılışta hesaplanıp çöpe gidiyordu.

Bu yüzden sorgu artık bir bayrağın arkasında. Korunması gereken şey performans
değil — **para rakamının doğruluğu**: sorguyu tetikleyen bayrak ile yanıtta
`truncated` olarak dönen bayrak *aynı değer* olmak zorunda. Ayrışırlarsa liste
gerçekten kırpılır, arayüz kitap toplamını göstermeye çalışır ve elinde boş
liste bulur; kullanıcı eksik bir toplamı tam sanır. Bunu üretimde yakalamanın
yolu yok, çünkü ekranda hata değil yalnız **daha küçük bir sayı** görünür.

Frappe önyüklemesi yok: yalnız kaynağı ayrıştırır.
"""

import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "api" / "sales.py"

# Kitap toplamı sorgusunu SQL'inden tanı: müşteri başına toplayıp para birimine
# göre gruplayan tek sorgu bu.
_FINGERPRINT = "HAVING SUM(p.bal_acc) != 0"


def _function(name):
	tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return node
	raise AssertionError(f"{name} kaynakta bulunamadı")


def _contains_fingerprint(node):
	return any(
		isinstance(child, ast.Constant) and isinstance(child.value, str) and _FINGERPRINT in child.value
		for child in ast.walk(node)
	)


class TestCustomerListGrandTotalGate(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.fn = _function("list_customers_with_balances")

	def _gates(self):
		return [
			node for node in ast.walk(self.fn) if isinstance(node, ast.If) and _contains_fingerprint(node)
		]

	def test_the_grand_total_query_sits_behind_a_gate(self):
		"""Çapa: sorgu koşulsuz koşarsa aşağıdaki eşitlik iddiası hiç
		çalışmayan bir dal üzerinden sessizce geçerdi."""
		self.assertEqual(
			len(self._gates()),
			1,
			"kitap toplamı sorgusu tek bir `if` bloğunun içinde olmalı — "
			"koşulsuz koşarsa her açılışta gereksiz tam GL taraması olur",
		)

	def test_the_gate_and_the_reported_flag_are_the_same_value(self):
		gates = self._gates()
		self.assertTrue(gates, "kitap toplamı sorgusu bir kapının arkasında değil")
		gate = gates[0]
		self.assertIsInstance(
			gate.test,
			ast.Name,
			"kapı doğrudan bir değişken olmalı; kopyalanmış bir ifade `truncated` ile sessizce ayrışabilir",
		)
		gate_flag = gate.test.id

		returned = {
			key.value: value
			for node in ast.walk(self.fn)
			if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
			for key, value in zip(node.value.keys, node.value.values, strict=True)
			if isinstance(key, ast.Constant) and key.value == "truncated"
		}
		self.assertTrue(returned, "yanıtta `truncated` anahtarı yok")
		for value in returned.values():
			self.assertIsInstance(value, ast.Name, "`truncated` hesaplanmış bir ifade dönüyor")
			self.assertEqual(
				value.id,
				gate_flag,
				f"kapı `{gate_flag}` ile dönen `truncated` ayrıştı — kırpılmış "
				"listede arayüz kitap toplamını boş bulur",
			)

	def test_the_grand_total_defaults_to_empty_when_the_gate_is_shut(self):
		"""Kapı kapalıyken değişken tanımsız kalırsa uç nokta `NameError`
		ile düşer — arayüz için boş liste, "toplam yok" demektir."""
		defaults = [
			node
			for node in self.fn.body
			if isinstance(node, (ast.Assign, ast.AnnAssign))
			and isinstance(node.value, ast.List)
			and not node.value.elts
			and any(
				isinstance(t, ast.Name) and t.id == "grand_totals"
				for t in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
			)
		]
		self.assertTrue(
			defaults,
			"`grand_totals` kapının dışında boş listeye kurulmuyor",
		)


if __name__ == "__main__":
	unittest.main()
