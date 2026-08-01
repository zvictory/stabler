"""`MoneyInput` biçimlendirme sözleşmesi — kaynaktan okunur.

Neden: bileşen UZS'yi tam sayı olarak gösterir (tiyin 1994'ten beri
dolaşımda değil). Birim fiyatlar için gelen `maxFractionDigits` override'ı
bu kuralı ezerse, UZS tutarları kullanıcının hiç yazamayacağı kuruşlarla
görünür — para alanında sessiz bir yanlışlık. Override'ın UZS dalından
**sonra** gelmesi bu yüzden bir sözleşme, üslup değil.

Bir JS bileşenini Frappe önyüklemesi olmadan çalıştıramayız; test kaynağı
okur. Bu zayıf bir doğrulama, ama korunan şey tek bir sıralama kuralı ve
onu bozan düzenleme tam olarak bu metni değiştirir.
"""

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "components" / "MoneyInput.vue"


class TestMoneyInputFractionContract(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_component(self):
		"""Çapa: yol kayarsa aşağıdaki iddialar boş metni doğrularlardı."""
		self.assertIn("const maxFractionDigits = computed(", self.body)

	def test_uzs_wins_over_the_unit_price_override(self):
		block = re.search(r"const maxFractionDigits = computed\(\(\) => \{(.*?)\n\}\);", self.body, re.S)
		self.assertIsNotNone(block, "computed bloğu okunamadı — regex kaymış")
		body = block.group(1)
		uzs = body.index("isUZS.value")
		override = body.index("props.maxFractionDigits")
		self.assertLess(
			uzs,
			override,
			"UZS dalı override'dan sonra geliyor — UZS tutarları kuruşlu görünür",
		)

	def test_the_grouped_display_follows_the_same_maximum(self):
		"""`liveGroup` yazarken kesen yer. Sabit 2'ye dönerse birim fiyat
		girişi tuşun altında kırpılır: 4,4150 yazılır, 4,41 kalır."""
		self.assertIn('parts.slice(1).join("").slice(0, maxFractionDigits.value)', self.body)


if __name__ == "__main__":
	unittest.main()
