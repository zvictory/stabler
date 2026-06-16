"""Unit tests for the 1C ClientBank Exchange parser (pure, no Frappe)."""
from __future__ import annotations

import unittest

from stabler.integrations.bank_statement.parser_1c import (
	DEPOSIT,
	WITHDRAWAL,
	dedupe_key,
	detect_encoding,
	is_1c_exchange,
	normalize_rows,
	parse_1c_exchange,
	parse_statement_bytes,
	statement_account,
)

OUR_ACCOUNT = "20208000900000000001"

SAMPLE = """1CClientBankExchange
ВерсияФормата=1.03
Кодировка=Windows
Отправитель=Bank-Client
ДатаНачала=01.01.2026
ДатаКонца=31.01.2026
РасчСчет=20208000900000000001
СекцияРасчСчет
РасчСчет=20208000900000000001
НачальныйОстаток=1000000.00
КонецРасчСчет
СекцияДокумент=Платежное поручение
Номер=123
Дата=15.01.2026
Сумма=5000000.00
ПлательщикСчет=20208000900000000001
Плательщик=ООО Стаблер
ПлательщикИНН=305123456
ПолучательСчет=20208000900000000999
Получатель=ООО Поставщик
ПолучательИНН=301654321
ПолучательБИК=00440
НазначениеПлатежа=Оплата за молоко по договору 7
ДатаСписано=15.01.2026
КонецДокумента
СекцияДокумент=Платежное поручение
Номер=456
Дата=20.01.2026
Сумма=12500000.50
ПлательщикСчет=20208000900000000777
Плательщик=ООО Клиент
ПлательщикИНН=302999888
ПолучательСчет=20208000900000000001
Получатель=ООО Стаблер
ПолучательИНН=305123456
НазначениеПлатежа=Оплата за мороженое
ДатаПоступило=20.01.2026
КонецДокумента
КонецФайла
"""


class SniffEncodingTest(unittest.TestCase):
	def test_is_1c_exchange(self):
		self.assertTrue(is_1c_exchange(SAMPLE))
		self.assertFalse(is_1c_exchange("date,amount\n2026-01-01,5"))

	def test_detect_cp1251_default(self):
		self.assertEqual(detect_encoding(SAMPLE.encode("cp1251")), "cp1251")

	def test_detect_utf8(self):
		txt = SAMPLE.replace("Кодировка=Windows", "Кодировка=UTF-8")
		self.assertEqual(detect_encoding(txt.encode("utf-8")), "utf-8")


class ParseTest(unittest.TestCase):
	def setUp(self):
		self.parsed = parse_1c_exchange(SAMPLE)

	def test_header_and_period(self):
		self.assertEqual(self.parsed["header"]["ДатаНачала"], "01.01.2026")
		self.assertEqual(self.parsed["header"]["РасчСчет"], OUR_ACCOUNT)

	def test_documents_and_accounts_counted(self):
		self.assertEqual(len(self.parsed["documents"]), 2)
		self.assertEqual(len(self.parsed["accounts"]), 1)

	def test_statement_account(self):
		self.assertEqual(statement_account(self.parsed), OUR_ACCOUNT)

	def test_doc_type_captured(self):
		self.assertEqual(self.parsed["documents"][0]["_type"], "Платежное поручение")


class NormalizeTest(unittest.TestCase):
	def setUp(self):
		self.rows = normalize_rows(parse_1c_exchange(SAMPLE), OUR_ACCOUNT)

	def test_two_rows(self):
		self.assertEqual(len(self.rows), 2)

	def test_withdrawal_when_we_are_payer(self):
		r = self.rows[0]
		self.assertEqual(r["direction"], WITHDRAWAL)
		self.assertEqual(r["withdrawal"], 5000000.00)
		self.assertEqual(r["deposit"], 0.0)
		self.assertEqual(r["date"], "2026-01-15")
		# Counterparty is the receiver.
		self.assertEqual(r["counterparty_inn"], "301654321")
		self.assertEqual(r["counterparty_name"], "ООО Поставщик")

	def test_deposit_when_we_are_receiver(self):
		r = self.rows[1]
		self.assertEqual(r["direction"], DEPOSIT)
		self.assertEqual(r["deposit"], 12500000.50)
		self.assertEqual(r["withdrawal"], 0.0)
		# Counterparty is the payer.
		self.assertEqual(r["counterparty_inn"], "302999888")

	def test_reference_and_description(self):
		self.assertEqual(self.rows[0]["reference_number"], "123")
		self.assertIn("молоко", self.rows[0]["description"])

	def test_dedupe_key_stable_and_distinct(self):
		k0, k1 = self.rows[0]["dedupe_key"], self.rows[1]["dedupe_key"]
		self.assertNotEqual(k0, k1)
		# Re-deriving the key from the same row is stable.
		self.assertEqual(k0, dedupe_key(self.rows[0]))


class AmountParsingTest(unittest.TestCase):
	def test_space_thousands_comma_decimal(self):
		doc = SAMPLE.replace("Сумма=5000000.00", "Сумма=5 000 000,00")
		rows = normalize_rows(parse_1c_exchange(doc), OUR_ACCOUNT)
		self.assertEqual(rows[0]["withdrawal"], 5000000.00)


class EndToEndBytesTest(unittest.TestCase):
	def test_parse_statement_bytes_cp1251(self):
		res = parse_statement_bytes(SAMPLE.encode("cp1251"))
		self.assertEqual(res["account"], OUR_ACCOUNT)
		self.assertEqual(res["period_from"], "2026-01-01")
		self.assertEqual(res["period_to"], "2026-01-31")
		self.assertEqual(res["count"], 2)


if __name__ == "__main__":
	unittest.main()
