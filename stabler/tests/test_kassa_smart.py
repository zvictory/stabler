"""Unit tests for stabler.integrations.kassa._smart (WP-S3, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_smart -v
"""

from __future__ import annotations

import unittest

from stabler.integrations.kassa._smart import (
	detect_currency,
	detect_kassa,
	detect_op,
	detect_transfer_dirs,
	extract_amount,
	extract_counterparty,
	extract_purpose,
	extract_rate,
	parse_entry,
	parse_legs,
	parse_message,
)


class TestCurrency(unittest.TestCase):
	def test_letter_d(self):
		self.assertEqual(detect_currency("100d"), "USD")

	def test_word_dollar(self):
		self.assertEqual(detect_currency("100 dollar oldim"), "USD")

	def test_symbol(self):
		self.assertEqual(detect_currency("$100"), "USD")

	def test_letter_s(self):
		self.assertEqual(detect_currency("100ming s"), "UZS")

	def test_word_som(self):
		self.assertEqual(detect_currency("100 som keldi"), "UZS")

	def test_euro(self):
		self.assertEqual(detect_currency("500e"), "EUR")
		self.assertEqual(detect_currency("500 euro"), "EUR")

	def test_none(self):
		self.assertIsNone(detect_currency("100mln"))
		self.assertIsNone(detect_currency("besh yuz ming"))


class TestAmount(unittest.TestCase):
	def test_mln(self):
		self.assertEqual(extract_amount("100mln"), 100_000_000)

	def test_letter_currency_stripped(self):
		self.assertEqual(extract_amount("100d"), 100)

	def test_ming_with_currency(self):
		self.assertEqual(extract_amount("100ming s"), 100_000)

	def test_decimal_mln(self):
		self.assertEqual(extract_amount("1,5 mln"), 1_500_000)

	def test_word_dollar(self):
		self.assertEqual(extract_amount("500 dollar"), 500)

	def test_word_number(self):
		self.assertEqual(extract_amount("besh yuz ming"), 500_000)

	def test_plain_mln(self):
		self.assertEqual(extract_amount("2 mln"), 2_000_000)

	def test_empty(self):
		self.assertIsNone(extract_amount(""))

	def test_garbage(self):
		self.assertIsNone(extract_amount("salom dunyo"))


class TestOp(unittest.TestCase):
	def test_buy_foreign_is_conversion(self):
		self.assertEqual(detect_op("100d aldim", "USD"), "konversiya")

	def test_buy_uzs_is_kirim(self):
		self.assertEqual(detect_op("100mln aldim", None), "kirim")

	def test_chiqdi(self):
		self.assertEqual(detect_op("ijaraga chiqdi", "UZS"), "chiqim")

	def test_berdim(self):
		self.assertEqual(detect_op("100d berdim", "USD"), "chiqim")

	def test_aylantirdim(self):
		self.assertEqual(detect_op("somga aylantirdim", "UZS"), "konversiya")

	def test_transfer(self):
		self.assertEqual(detect_op("pk ga o'tkazdim", "UZS"), "kassalararo")

	def test_kirim_word(self):
		self.assertEqual(detect_op("mijozdan kirdi", None), "kirim")

	def test_none(self):
		self.assertIsNone(detect_op("salom", None))


class TestSlots(unittest.TestCase):
	def test_counterparty_from(self):
		self.assertEqual(extract_counterparty("100mln aldim aliyevdan", "kirim"), "Aliyev")

	def test_counterparty_from_spaced(self):
		# "Hursand dan" (space before 'dan') must resolve the same as "Hursanddan"
		self.assertEqual(extract_counterparty("Hursand dan oldim 4.5mln va 15mln p", "kirim"), "Hursand")

	def test_counterparty_not_a_kassa_word(self):
		# "naqddan" is a kassa direction, not a person's name
		self.assertIsNone(extract_counterparty("2 mln naqddan pk ga", "kassalararo"))

	def test_counterparty_none(self):
		self.assertIsNone(extract_counterparty("100mln aldim", "kirim"))

	def test_ga_is_not_counterparty(self):
		# "ijaraga" must NOT be read as a counterparty name
		self.assertIsNone(extract_counterparty("100ming s chiqdi ijaraga", "chiqim"))

	def test_purpose_uchun(self):
		self.assertEqual(extract_purpose("100mln ijara uchun berdim"), "ijara")

	def test_purpose_ga(self):
		self.assertEqual(extract_purpose("100ming s chiqdi ijaraga"), "ijara")

	def test_rate(self):
		self.assertEqual(extract_rate("500d somga aylantirdim 12900 kurs"), 12900)
		self.assertEqual(extract_rate("kurs 12950"), 12950)


class TestParseEntry(unittest.TestCase):
	def test_kirim_full_ready(self):
		r = parse_entry("100mln aldim aliyevdan")
		self.assertEqual(r["op"], "kirim")
		self.assertEqual(r["amount"], 100_000_000)
		self.assertEqual(r["currency"], "UZS")  # defaulted
		self.assertEqual(r["counterparty"], "Aliyev")
		self.assertTrue(r["ready"])
		self.assertIsNone(r["question"])

	def test_kirim_missing_counterparty(self):
		r = parse_entry("100mln aldim")
		self.assertEqual(r["op"], "kirim")
		self.assertEqual(r["amount"], 100_000_000)
		self.assertEqual(r["currency"], "UZS")
		self.assertFalse(r["ready"])
		self.assertEqual(r["missing"], "kirim_from")

	def test_buy_dollar_asks_source(self):
		r = parse_entry("100d aldim")
		self.assertEqual(r["op"], "konversiya")
		self.assertEqual(r["currency"], "USD")
		self.assertEqual(r["amount"], 100)
		self.assertFalse(r["ready"])
		self.assertEqual(r["missing"], "konv_source")

	def test_buy_dollar_with_source_ctx_ready(self):
		r = parse_entry("100d aldim", ctx={"konv_source": "PK"})
		self.assertEqual(r["op"], "konversiya")
		self.assertTrue(r["ready"])

	def test_chiqim_with_purpose_ready(self):
		r = parse_entry("100ming s chiqdi ijaraga")
		self.assertEqual(r["op"], "chiqim")
		self.assertEqual(r["amount"], 100_000)
		self.assertEqual(r["currency"], "UZS")
		self.assertEqual(r["purpose"], "ijara")
		self.assertTrue(r["ready"])

	def test_empty_asks_op(self):
		r = parse_entry("")
		self.assertIsNone(r["op"])
		self.assertEqual(r["missing"], "op")

	def test_amount_only_missing_amount(self):
		r = parse_entry("aldim")
		self.assertEqual(r["op"], "kirim")
		self.assertIsNone(r["amount"])
		self.assertEqual(r["missing"], "amount")

	def test_raw_preserved(self):
		r = parse_entry("100D Aldim")
		self.assertEqual(r["raw_text"], "100D Aldim")


class TestKassaKeyword(unittest.TestCase):
	def test_naqd(self):
		self.assertEqual(detect_kassa("2 mln naqd"), "nakit")

	def test_karta(self):
		self.assertEqual(detect_kassa("3 mln karta"), "pk")

	def test_dollar(self):
		self.assertEqual(detect_kassa("500 dollar"), "usd")

	def test_letters_spd(self):
		self.assertEqual(detect_kassa("2mln s"), "nakit")
		self.assertEqual(detect_kassa("3mln p"), "pk")
		self.assertEqual(detect_kassa("500 d"), "usd")

	def test_none(self):
		self.assertIsNone(detect_kassa("600 ming"))


class TestTransferDirs(unittest.TestCase):
	def test_dirs(self):
		self.assertEqual(detect_transfer_dirs("1mln naqddan pk ga"), ("nakit", "pk"))
		self.assertEqual(detect_transfer_dirs("somdan dollarga"), ("nakit", "usd"))
		self.assertEqual(detect_transfer_dirs("pkdan naqdga"), ("pk", "nakit"))

	def test_k2k_parse_no_questions(self):
		r = parse_message("1mln naqddan pk ga", op="kassalararo")
		self.assertEqual(r["from"], "nakit")
		self.assertEqual(r["to"], "pk")
		self.assertEqual(r["amount"], 1_000_000)


class TestMultiLeg(unittest.TestCase):
	def test_three_legs_one_kirim(self):
		r = parse_message("Mijozdan 2 mln naqd, 3 mln karta va 500 dollar oldim", op="kirim")
		self.assertEqual(r["op"], "kirim")
		self.assertEqual(r["counterparty"], "Mijoz")
		self.assertTrue(r["ready"])
		self.assertEqual(len(r["legs"]), 3)
		self.assertEqual(r["legs"][0], {"amount": 2_000_000, "kassa": "nakit", "currency": "UZS"})
		self.assertEqual(r["legs"][1], {"amount": 3_000_000, "kassa": "pk", "currency": "UZS"})
		self.assertEqual(r["legs"][2], {"amount": 500, "kassa": "usd", "currency": "USD"})

	def test_single_leg_from_ali(self):
		r = parse_message("Alidan 600 ming oldim", op="kirim")
		self.assertEqual(r["counterparty"], "Ali")
		self.assertTrue(r["ready"])
		self.assertEqual(r["legs"], [{"amount": 600_000, "kassa": "nakit", "currency": "UZS"}])

	def test_chiqim_purpose(self):
		r = parse_message("100ming s ijaraga", op="chiqim")
		self.assertEqual(r["op"], "chiqim")
		self.assertEqual(r["purpose"], "ijara")
		self.assertTrue(r["ready"])
		self.assertEqual(r["legs"], [{"amount": 100_000, "kassa": "nakit", "currency": "UZS"}])

	def test_multi_leg_missing_counterparty(self):
		r = parse_message("2mln naqd, 500d", op="kirim")
		self.assertEqual(len(r["legs"]), 2)
		self.assertFalse(r["ready"])
		self.assertEqual(r["missing"], "kirim_from")

	def test_parse_legs_direct(self):
		legs = parse_legs("2 mln naqd, 3 mln karta va 500 dollar")
		self.assertEqual([l["kassa"] for l in legs], ["nakit", "pk", "usd"])


if __name__ == "__main__":
	unittest.main()
