"""Unit tests for stabler.integrations.uzex._parse (WP-302, Frappe-free).

Fixtures are the real shapes captured in the WP-300 discovery report.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_uzex_parse -v
"""

from __future__ import annotations

import unittest

from stabler.integrations.uzex._parse import (
	lot_id_from_url,
	matches_keywords,
	parse_trade_row,
	parse_uzex_dt,
	status_from_detail,
	to_float,
)

# Real TradeList item (docs/plans/uzex-api-discovery-2026-07-08.md §2.1).
_LIST_ROW = {
	"rn": 1,
	"id": 497638,
	"display_no": "26111006497638",
	"name": "\"Yangi O'zbekiston\" gazetalarini chop etish bo'yicha elektron tender",
	"start_date": "2026-06-22T11:47:09",
	"end_date": "2026-07-08T11:47:09",
	"cost": 6300000000,
	"seller_name": "Янги Узбекистон газета",
	"seller_tin": "201140445",
	"currency_codeabc": "UZS",
}


class TestToFloat(unittest.TestCase):
	def test_int_str_none(self):
		self.assertEqual(to_float(6300000000), 6300000000.0)
		self.assertEqual(to_float("162975654"), 162975654.0)
		self.assertIsNone(to_float(None))
		self.assertIsNone(to_float(""))
		self.assertIsNone(to_float("abc"))


class TestParseDt(unittest.TestCase):
	def test_iso_t_separator(self):
		self.assertEqual(parse_uzex_dt("2026-07-08T11:47:09"), "2026-07-08 11:47:09")

	def test_date_only_padded(self):
		self.assertEqual(parse_uzex_dt("2026-07-08"), "2026-07-08 00:00:00")

	def test_strips_fraction_and_zone(self):
		self.assertEqual(parse_uzex_dt("2026-07-08T11:47:09.500+05:00"), "2026-07-08 11:47:09")

	def test_garbage(self):
		self.assertIsNone(parse_uzex_dt(None))
		self.assertIsNone(parse_uzex_dt(""))
		self.assertIsNone(parse_uzex_dt(12345))


class TestParseTradeRow(unittest.TestCase):
	def test_maps_all_fields(self):
		n = parse_trade_row(_LIST_ROW)
		self.assertEqual(n["lot_id"], 497638)
		self.assertEqual(n["lot_no"], "26111006497638")
		self.assertEqual(n["deadline"], "2026-07-08 11:47:09")
		self.assertEqual(n["start_price"], 6300000000.0)
		self.assertEqual(n["customer_org"], "Янги Узбекистон газета")
		self.assertEqual(n["currency"], "UZS")

	def test_empty_row_safe(self):
		n = parse_trade_row({})
		self.assertEqual(n["lot_no"], "")
		self.assertIsNone(n["deadline"])
		self.assertIsNone(n["start_price"])

	def test_non_dict_safe(self):
		self.assertEqual(parse_trade_row(None)["lot_no"], "")


class TestMatchesKeywords(unittest.TestCase):
	def test_flood_guard_empty_keywords_is_false(self):
		# The core invariant: no keywords => never ingest a new lot.
		self.assertFalse(matches_keywords("anything at all", []))
		self.assertFalse(matches_keywords("x", None))

	def test_case_insensitive_substring(self):
		self.assertTrue(matches_keywords("Elektron TENDER bosmaxona", ["tender"]))
		self.assertTrue(matches_keywords("bosmaxona xizmati", ["bosmaxona", "boshqa"]))

	def test_no_match(self):
		self.assertFalse(matches_keywords("mebel yetkazish", ["tender", "bosmaxona"]))

	def test_string_keyword_coerced(self):
		self.assertTrue(matches_keywords("elektron tender", "tender"))

	def test_none_name(self):
		self.assertFalse(matches_keywords(None, ["tender"]))


class TestStatusFromDetail(unittest.TestCase):
	def test_prefers_name(self):
		self.assertEqual(
			status_from_detail({"status_id": 5, "status_name": "Bekor qilingan"}),
			"Bekor qilingan",
		)

	def test_falls_back_to_id(self):
		self.assertEqual(status_from_detail({"status_id": 5}), "5")

	def test_empty(self):
		self.assertIsNone(status_from_detail({}))
		self.assertIsNone(status_from_detail(None))


class TestLotIdFromUrl(unittest.TestCase):
	def test_full_url(self):
		self.assertEqual(lot_id_from_url("https://etender.uzex.uz/lot/500606"), 500606)

	def test_url_with_query(self):
		self.assertEqual(lot_id_from_url("https://etender.uzex.uz/lot/500606?tab=info"), 500606)

	def test_bare_id(self):
		self.assertEqual(lot_id_from_url("500606"), 500606)
		self.assertEqual(lot_id_from_url(500606), 500606)

	def test_gettrade_url(self):
		self.assertEqual(lot_id_from_url("https://apietender.uzex.uz/api/common/GetTrade/500606/0"), 500606)

	def test_none_and_empty(self):
		self.assertIsNone(lot_id_from_url(None))
		self.assertIsNone(lot_id_from_url(""))
		self.assertIsNone(lot_id_from_url("no digits here"))


if __name__ == "__main__":
	unittest.main()
