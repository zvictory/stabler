"""Ömür boyu ciro hangi para biriminde yazılıyor?

Müşteri ve tedarikçi kartlarındaki "Lifetime" rakamı, faturaların
`grand_total` toplamıdır. Bir taraf hem USD hem UZS fatura kesiyorsa,
`SUM(grand_total)` **hiçbir** para biriminde doğru olmayan bir sayı üretir —
ve kart onu tek bir sembolle etiketler. Kullanıcı bunu okuyamaz; daha kötüsü,
yanlış olduğunu da anlayamaz.

Kural iki dosyada birden yazılı olduğu için tek testte tutuluyor:

* tek para birimi varsa tutar o para biriminde gösterilir;
* birden fazlaysa baz kura düşülür ve **baz** para birimiyle etiketlenir.

`GROUP BY currency` bu kuralın taşıyıcısı: gruplama düşerse iki dal da
anlamsızlaşır, çünkü ayırt edecek satır kalmaz.

Frappe önyüklemesi yok: yalnız kaynak okur.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCES = {
	"sales.py": ROOT / "api" / "sales.py",
	"purchasing.py": ROOT / "api" / "purchasing.py",
}
# Kart tarafı iki ekranda ayrı ayrı yazılıydı; ikisi de PartyCenter kabuğuna
# indi. Tek dosya, ama hâlâ hem müşteri hem tedarikçi kartını koruyor.
SCREENS = {
	"PartyCenter.vue": ROOT / "public" / "js" / "components" / "party" / "PartyCenter.vue",
}

# `lifetime_by_currency = ( frappe.db.sql( """ … """ …` — sorgunun gövdesi.
_QUERY = re.compile(r'lifetime_by_currency = \(\s*frappe\.db\.sql\(\s*"""(.*?)"""', re.S)


class TestLifetimeCurrencyContract(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = {k: p.read_text(encoding="utf-8") for k, p in SOURCES.items()}
		cls.screen = {k: p.read_text(encoding="utf-8") for k, p in SCREENS.items()}

	def test_both_endpoints_group_the_lifetime_total_by_currency(self):
		"""Çapa: sorgu bulunamazsa aşağıdaki dal iddiaları neyi koruduğunu
		bilmeden geçerdi."""
		for name, src in self.body.items():
			with self.subTest(name):
				q = _QUERY.search(src)
				self.assertIsNotNone(q, "lifetime_by_currency sorgusu bulunamadı")
				self.assertIn("GROUP BY currency", q.group(1))

	def test_a_mixed_currency_party_falls_back_to_base_and_says_so(self):
		"""İki dal birlikte anlamlı: tek para biriminde o birim, karışıkta baz.
		Etiket dalla birlikte değişmezse kart yanlış sembol basar."""
		for name, src in self.body.items():
			with self.subTest(name):
				self.assertIn("if len(lifetime_by_currency) == 1:", src)
				self.assertIn('lifetime_currency = lifetime_by_currency[0]["currency"]', src)
				self.assertIn("lifetime_amount = lifetime_base", src)

	def test_the_card_labels_the_figure_with_the_currency_the_endpoint_resolved(self):
		"""`|| 'USD'` gibi sabit bir yedek, UZS kesen bir tedarikçinin
		rakamını dolar diye gösterirdi — ölçüldü, canlıdaydı."""
		for name, src in self.screen.items():
			with self.subTest(name):
				lines = src.splitlines()
				at = [i for i, ln in enumerate(lines) if "lifetime_amount" in ln]
				self.assertEqual(len(at), 1, "Lifetime kartı tek yerde bekleniyordu")
				# formatMoney(tutar, para_birimi, dil) — para birimi tutarın bir
				# altındaki argüman. Uçtan gelen `lifetime_currency` okunmalı ve
				# yedek asla sabit bir kod ('USD') olmamalı.
				currency_arg = lines[at[0] + 1]
				self.assertIn("lifetime_currency", currency_arg)
				self.assertNotRegex(currency_arg, r"""["'][A-Z]{3}["']""")


if __name__ == "__main__":
	unittest.main()
