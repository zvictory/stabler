"""Kanban kartının okuduğu her şey, sanitizer'ın gerçekten ürettiği bir şey olmalı.

`_clean_intake` bir temizleyici değil, fiilen şemadır: whitelist'te olmayan anahtar
intake JSON'una hiç giremez (2026-08-24'ten beri gönderilirse `frappe.throw`). Buna
rağmen `crm_board` kart değerini `contract_value` / `budget` anahtarlarından okuyordu
ve ikisi de o whitelist'te yok — yani okuma her zaman `None` dönüyor, kart değeri,
şerit toplamı ve KPI şeridi kalıcı olarak **0** görünüyordu. Yedek yol
(`CRM Deal.annual_revenue`) hiçbir Stabler kodunun yazmadığı bir kolon.

Hata tek bir yanlış anahtar değil, bir sınıf: sözleşmenin bir tarafı değişince
diğer taraf sessizce boş okumaya başlıyor ve hiçbir şey hata vermiyor. O yüzden test
tek anahtarı değil, ilişkiyi sabitliyor.

Kaynak okumasıdır — `crm_board` frappe/DB ister, davranış teyidi `make test-bench`.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "api/tender.py").read_text(encoding="utf-8")


def _tuple_keys(name: str) -> set[str]:
	m = re.search(rf"^{name} = \(\n(.*?)^\)", SRC, re.S | re.M)
	assert m, f"{name} bulunamadı"
	return set(re.findall(r'"([^"]+)"', m.group(1)))


def _function_body(name: str) -> str:
	start = SRC.index(f"\ndef {name}(")
	nxt = SRC.find("\ndef ", start + 1)
	return SRC[start : nxt if nxt != -1 else len(SRC)]


def _producible_keys() -> set[str]:
	"""_clean_intake çıktısında görünebilecek anahtarlar."""
	keys = _tuple_keys("_INTAKE_KEYS_STR") | _tuple_keys("_INTAKE_KEYS_NUM")
	# Damga çiftleri (`*_at` / `*_by`) döngüyle türetiliyor; hiçbir okuyucu şu an
	# onlara dokunmuyor. Biri dokunursa bu test uyarır ve liste genişletilir —
	# yanlış tarafa hata veren bir test, hiç hata vermeyenden iyidir.
	keys |= set(re.findall(r'out\["([^"]+)"\]\s*=', _function_body("_clean_intake")))
	return keys


class TenderCrmBoardContract(unittest.TestCase):
	def test_card_reads_only_keys_the_sanitizer_can_produce(self):
		"""Kartın okuduğu her intake anahtarı sözleşmede olmalı.

		Olmayan bir anahtarı okumak hata vermez, sessizce 0/boş döner — ve ekranda
		"bu ihalenin değeri yok" ile "bu alanı kimse yazmıyor" birbirinden
		ayırt edilemez hâle gelir.
		"""
		read = set(re.findall(r'intake\.get\("([^"]+)"', _function_body("crm_board")))
		self.assertTrue(read, "crm_board intake'ten hiçbir şey okumuyor — test yanlış yere bakıyor")

		orphans = sorted(read - _producible_keys())
		self.assertEqual(orphans, [], f"sözleşmede olmayan anahtarlar okunuyor: {orphans}")

	def test_readiness_is_computed_in_one_place(self):
		"""Hazırlık yüzdesini kart ve belge merkezi ayrı ayrı hesaplamamalı.

		Kart `d["status"] == "ready"` sayıyordu; normalize edilmiş satırlarda o
		anahtar yok (tamamlanma `done`), üstelik eski `status: "ready"` artık
		bilinçli olarak `unverified`'e besleniyor, `done`'a değil. Sonuç: belge
		satırı olan her kartta %0, hiç satırı olmayanda sabit bir sayı — yani boş
		kontrol listesi tamamlanmış olandan iyi görünüyordu. Aynı ihale için iki
		ekran iki farklı yüzde gösteriyordu; doğrusu `docs_summary` içinde.
		"""
		body = _function_body("crm_board")
		self.assertNotIn('"status") == "ready"', body)
		self.assertIn("docs_summary(", body)
