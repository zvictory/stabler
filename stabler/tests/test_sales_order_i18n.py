"""F1 ve F5'in eklediği yeni ekran metinleri, beş dilin hepsinde bir satıra
sahip olmalı.

Antigravity'nin commit'i Satış Siparişi formuna 11 yeni `t(...)` metni getirdi
(aksiyon çubuğu, stok uyarıları, rezervasyon sayaçları) ama hiçbiri `en/ru/uz/
uzc/tr.csv`'ye eklenmemişti (B4). Bu paketin kendi ekleri de var: F1'in kur
uyarısı metni ve F5'in "Sales Box/Case UOM Preference" yönetici anahtarı.
Toplam 13 anahtar.

Kasıtlı olarak **sabit liste** — dosyadaki her `t()` çağrısını tarayan geniş
bir versiyon burada yanlış olur: uygulamada zaten ~338 çeviri anahtarı hiçbir
CSV'de yok (eski, bu işten önce var olan bir birikinti — kapsam dışı). O
genişlikte bir test hiç geçmez ve bu paketin gerçek regresyonunu, geniş bir
gürültünün içinde kaybeder.
"""

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANGS = ("en", "ru", "uz", "uzc", "tr")

# B4 (Antigravity'nin commit'i, hiçbir CSV'de yoktu) + F1 (kur uyarısı) + F5
# (Sales Box/Case UOM Preference yönetici anahtarı).
NEW_KEYS = (
	"Force allow over-stock submit (Admin)",
	"Some lines exceed available stock. Adjust quantities or warehouse before submitting.",
	"Stock and reservations are read from this warehouse",
	"Stock insufficient — cannot submit",
	"item to reserve",
	"items to reserve",
	"lines blocked",
	"no date set",
	"not saved",
	"short stock",
	"unsaved changes",
	"Exchange rate unavailable — line prices were not converted. Enter the rate manually.",
	"Sales Box/Case UOM Preference",
)


def _read_csv(lang):
	path = ROOT / "translations" / f"{lang}.csv"
	rows = {}
	with path.open(encoding="utf-8") as f:
		for row in csv.reader(f):
			if row and row[0]:
				rows[row[0]] = row[1] if len(row) > 1 else ""
	return rows


class TestNewSalesOrderKeysArePresentInEveryLanguage(unittest.TestCase):
	"""Her yeni anahtar, beş dilin hepsinde bir satıra sahip ve boş değil —
	yalnız İngilizce'de değil, ru/uz/uzc/tr'de de gerçek bir çeviri var."""

	def test_every_new_key_has_a_non_empty_target_in_every_language(self):
		for lang in LANGS:
			rows = _read_csv(lang)
			for key in NEW_KEYS:
				with self.subTest(lang=lang, key=key):
					self.assertIn(key, rows, f"{lang}.csv: eksik anahtar {key!r}")
					self.assertTrue(rows[key], f"{lang}.csv: {key!r} için boş çeviri")


if __name__ == "__main__":
	unittest.main()
