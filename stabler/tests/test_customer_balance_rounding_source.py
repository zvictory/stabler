"""Aynı yuvarlama kuralı iki yerde yazılı — ikisi ayrı düşerse para yanlış okunur.

ERPNext, USD borç/alacağını denkleştirmek için Ödeme Girişi'ne kuruş altı
yuvarlama satırları yazar. Baz kura çevrildiklerinde UZS defterine anlamsız
bir kalıntı bırakırlar, o yüzden iki yerde birden sıfırlanırlar:

* `list_customers_with_balances` içindeki toplu SQL — müşteri listesinde
  görünen bakiye;
* `_fetch_party_ledger_rows` içindeki Python dalı — o bakiyeye tıklayınca
  açılan defter dökümü.

İkisi aynı satırı elemek zorunda. Eşik yalnız birinde değişirse liste bir
rakam, döküm başka bir rakam gösterir — ve kullanıcı hangisinin doğru
olduğunu bilemez. Bu testin koruduğu şey tam olarak o eşitlik; iki tarafın
*ne* eledigi degil, **aynı** şeyi elediği.

Frappe önyüklemesi yok: yalnız kaynak okur.
"""

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "api" / "sales.py"

# SQL: CASE WHEN voucher_type = 'Payment Entry' AND against_voucher IS NULL
#      AND debit <= 0.05 AND credit <= 0.05
_SQL = re.compile(
	r"CASE WHEN voucher_type = 'Payment Entry'\s+AND against_voucher IS NULL"
	r"\s+AND debit <= ([\d.]+) AND credit <= ([\d.]+)"
)
# Python: if not r.get("against_voucher") and flt(r["debit"]) <= 0.05 and ...
_PY = re.compile(
	r'if not r\.get\("against_voucher"\)\s+and flt\(r\["debit"\]\) <= ([\d.]+)'
	r'\s+and flt\(r\["credit"\]\) <= ([\d.]+)'
)


class TestCustomerBalanceRoundingThreshold(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")
		cls.sql = _SQL.search(cls.body)
		cls.py = _PY.search(cls.body)

	def test_both_predicates_are_present(self):
		"""Çapa: biri kaybolursa aşağıdaki eşitlik iddiası `None == None`
		üzerinden sessizce geçerdi."""
		self.assertIsNotNone(self.sql, "liste toplamındaki SQL yuvarlama koşulu bulunamadı")
		self.assertIsNotNone(self.py, "defter dökümündeki Python yuvarlama koşulu bulunamadı")

	def test_the_list_total_and_the_ledger_drill_down_share_one_threshold(self):
		thresholds = {float(x) for x in self.sql.groups() + self.py.groups()}
		self.assertEqual(
			len(thresholds), 1,
			f"eşikler ayrıştı: {sorted(thresholds)} — liste ile döküm farklı bakiye gösterir",
		)

	def test_the_threshold_stays_below_one_cent_of_a_real_payment(self):
		"""Eşik gerçek bir ödemeyi yutacak kadar büyürse, tahsilatlar
		bakiyeden sessizce düşer. 0,05 kuruş-altı kalıntı için; 1,00 bir
		ödemedir."""
		self.assertLess(float(self.sql.group(1)), 1.0)


if __name__ == "__main__":
	unittest.main()
