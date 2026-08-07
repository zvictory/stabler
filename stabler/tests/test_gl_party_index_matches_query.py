"""Index tanımı ile onu kullanan sorgunun `WHERE`'i ayrışmamalı.

`v77_gl_entry_party_indexes` ANJAN prod'unda `list_customers_with_balances`'in
süresini ~1030 ms'den ~730 ms'ye indiriyor (2026-08-07, sorgu önbelleği kapalı).
Bu kazanç tamamen index kolonlarının sorgunun `WHERE`'iyle **birebir** örtüşmesine
bağlı: bir kolon eklenir ya da çıkarılırsa MariaDB index'i sessizce bırakır,
`party_type_party_index`'e döner ve 300 ms geri gelir.

Korunması gereken şey hız değil — **sessizliğin kendisi.** Ayrışma hiçbir hata
üretmez: sorgu aynı sonucu döndürür, testler geçer, ekranda yalnız daha yavaş
açılan bir liste kalır. Üretimde bunu yakalamanın yolu yok, çünkü kimse "biraz
daha yavaş"ı bir arıza olarak bildirmez.

İkinci değişmez: eşitlik kolonları (`company`, `party_type`, `is_cancelled`)
index'te aralık kolonundan (`party IN (...)`) **önce** gelmek zorunda. Sıra
bozulursa index yine "kullanılıyor" görünür ama tarama aralık kolonunda kesilir
ve kalan eşitlikler `WHERE` ile elenir — yani ölçülen kazanç yok olur, plan
hâlâ index adını gösterir. Bu, tek başına EXPLAIN'e bakan birinin göremeyeceği
sınıfta bir gerileme.

Frappe önyüklemesi yok: yalnız iki kaynağı ayrıştırır.
"""

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_SALES = (_ROOT / "api" / "sales.py").read_text(encoding="utf-8")
_PATCH = (_ROOT / "patches" / "v77_gl_entry_party_indexes.py").read_text(encoding="utf-8")

# `WHERE`/`AND` sonrası eşitlik veya IN ile süzülen kolon adları.
_FILTER = re.compile(r"\b(?:WHERE|AND)\s+(?:g\.)?(\w+)\s*(?:=\s*(?:%\(|'|\d)|IN\b)")


def _slice(text: str, start: str, end: str) -> str:
	i = text.index(start)
	return text[i : text.index(end, i)]


def _index_columns(name: str) -> tuple:
	"""Patch'teki INDEXES sözlüğünden `name`'in kolon sırasını çıkar."""
	body = _slice(_PATCH, f'"{name}": (', ")")
	return tuple(re.findall(r'"(\w+)"', body))


class TestGlPartyIndexMatchesQuery(unittest.TestCase):
	def test_balance_index_covers_the_gl_rows_filter(self):
		# `gl_rows`: WHERE ile GROUP BY arasi -- SELECT icindeki CASE WHEN
		# kosullari (voucher_type, against_voucher) filtre degil, onlari alma.
		where = _slice(
			_SALES,
			"FROM `tabGL Entry`\n\t\tWHERE company = %(company)s",
			"GROUP BY party",
		)
		filtered = set(_FILTER.findall(where))
		self.assertEqual(
			filtered,
			{"company", "party_type", "party", "is_cancelled"},
			"`gl_rows` WHERE'i değişti — v77 index'i artık bu sorguyla örtüşmüyor",
		)
		self.assertTrue(
			filtered.issubset(set(_index_columns("stabler_party_balance_idx"))),
			"filtre kolonu index'te yok — MariaDB index'i sessizce bırakır",
		)

	def test_voucher_index_covers_the_drift_subquery(self):
		# `drift_rows`'un ic sorgusu: tek satirlik Payment Entry fisleri.
		sub = _slice(_SALES, "SELECT voucher_no\n\t\t  FROM `tabGL Entry`", "HAVING COUNT(*) = 1")
		needed = set(_FILTER.findall(sub)) | {"voucher_no"}  # GROUP BY voucher_no
		self.assertEqual(
			needed,
			{"voucher_type", "company", "party_type", "party", "is_cancelled", "voucher_no"},
			"`drift_rows` iç sorgusunun WHERE'i değişti — v77 index'i kapsayıcı olmaktan çıkar",
		)
		self.assertTrue(
			needed.issubset(set(_index_columns("stabler_party_voucher_idx"))),
			"iç sorgu bir kolonu index dışından okuyor — `Using index` kaybolur",
		)

	def test_equality_columns_lead_the_range_column(self):
		"""`party` bir IN aralığı; index'te eşitliklerden önce gelirse tarama
		orada kesilir ve ölçülen kazanç EXPLAIN'i değiştirmeden yok olur."""
		for name, equalities in (
			("stabler_party_balance_idx", ("company", "party_type", "is_cancelled")),
			(
				"stabler_party_voucher_idx",
				("company", "party_type", "is_cancelled", "voucher_type"),
			),
		):
			cols = _index_columns(name)
			party_at = cols.index("party")
			for col in equalities:
				self.assertLess(
					cols.index(col),
					party_at,
					f"{name}: `{col}` aralık kolonu `party`'den sonra geliyor",
				)


if __name__ == "__main__":
	unittest.main()
