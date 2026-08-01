"""Beş çeviri CSV'si de her satırda tam olarak 2 alan (msgid, msgstr) taşımalı.

Antigravity'nin commit'i yeni bir msgid ekledi:
`Type a product code in the search above — stock status shows in the list,
picking adds it as a line.` — hem İngilizce kaynak hem her dildeki çeviri bu
tümceyi virgülle ayrılmış iki yan cümle olarak yazıyor, ama satır CSV'ye
tırnaksız yazılmıştı. `csv.reader` virgülü alan ayıracı sanıp satırı 4 alana
bölüyordu (`en/ru/uz/uzc/tr` — hepsinde tek satır, aynı msgid): çeviri asla
çözülmüyordu, `row[0]` "...in the list" diye yarıda kesiliyordu.

Düzeltme: o satırdaki hem msgid hem msgstr çift tırnağa alındı. Bu test tek
satırın ötesini kapatıyor — dosyanın *tamamında* alan sayısı çoğunluğa
(2) eşit olmayan başka bir satır kalmadığını doğruluyor.
"""

import csv
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANGS = ("en", "ru", "uz", "uzc", "tr")


def _rows(lang):
	path = ROOT / "translations" / f"{lang}.csv"
	with path.open(encoding="utf-8") as f:
		return list(csv.reader(f))


class TestEveryRowHasTheMajorityFieldCount(unittest.TestCase):
	"""Çoğunluk alan sayısından sapan herhangi bir satır, tırnaksız bir virgül
	yüzünden bölünmüş demektir — msgid ya da msgstr'nin içinde."""

	def test_no_row_deviates_from_the_majority_field_count(self):
		for lang in LANGS:
			with self.subTest(lang=lang):
				rows = _rows(lang)
				counts = Counter(len(r) for r in rows)
				majority = counts.most_common(1)[0][0]
				offenders = [i for i, r in enumerate(rows, start=1) if len(r) != majority]
				self.assertEqual(offenders, [], f"{lang}.csv: bozuk satır(lar): {offenders}")


class TestTheKnownBrokenLineIsFixed(unittest.TestCase):
	"""Regresyonun asıl kanıtı: bu belirli msgid artık her dilde tek bir
	msgstr'ye çözülüyor, dörde bölünmüyor."""

	MSGID = (
		"Type a product code in the search above — stock status shows in the "
		"list, picking adds it as a line."
	)

	def test_the_msgid_resolves_to_exactly_one_row_with_two_fields(self):
		for lang in LANGS:
			with self.subTest(lang=lang):
				rows = _rows(lang)
				matches = [r for r in rows if r and r[0] == self.MSGID]
				self.assertEqual(len(matches), 1)
				self.assertEqual(len(matches[0]), 2)


if __name__ == "__main__":
	unittest.main()
