"""The item picker prices the unit it actually sells.

The product dropdown on the Sales Order form shows a price per selling unit
("1 Korobka = 24 Dona · 130 800 сўм"). Items routinely carry two Item Price rows
— one per piece, one per box — so picking the wrong row is not a rounding error:
it misquotes the line by the conversion factor. `_apply_item_prices` is the rule
behind that column, and it must reproduce what `sales._lookup_item_price` does on
a single pick.

Pure unit test: the rule is split from its query, so this needs no site.
"""

from __future__ import annotations

import unittest

from stabler.api.inventory import _apply_item_prices

# What the bulk Item Price query returns for one page of picker results.
_PRICES = [
	{"item_code": "AE603", "uom": "Korobka", "price_list_rate": 130800.0, "currency": "UZS"},
	{"item_code": "AE603", "uom": "Dona", "price_list_rate": 5450.0, "currency": "UZS"},
	# AE603 also carries a uom-less row — the list's default price. Both branches of the
	# preference therefore have something to return for it, which is the only way this
	# fixture can tell "selling unit first" apart from "generic first".
	{"item_code": "AE603", "uom": "", "price_list_rate": 5450.0, "currency": "UZS"},
	{"item_code": "SE669", "uom": "", "price_list_rate": 2500.0, "currency": "UZS"},
]


def _rows():
	return [
		# sells by the box, and has a box price
		{"name": "AE603", "stock_uom": "Dona", "sales_uom": "Korobka"},
		# no selling unit of its own — falls back to the stock unit
		{"name": "SE669", "stock_uom": "Dona", "sales_uom": None},
		# priced nowhere on this list
		{"name": "AQ511", "stock_uom": "Dona", "sales_uom": None},
	]


class ApplyItemPricesTest(unittest.TestCase):
	def test_selling_unit_price_wins_over_the_per_piece_row(self):
		# AE603 sells by the Korobka. Handing back the 5 450 Dona rate would price a
		# box at one twenty-fourth of its value on every line the picker creates.
		rows = _rows()
		_apply_item_prices(rows, _PRICES)
		self.assertEqual(rows[0]["price_list_rate"], 130800.0)
		self.assertEqual(rows[0]["price_list_currency"], "UZS")

	def test_generic_row_covers_an_item_with_no_selling_unit(self):
		# SE669's only row carries no uom. Requiring an exact match would leave a
		# priced item showing no price at all.
		rows = _rows()
		_apply_item_prices(rows, _PRICES)
		self.assertEqual(rows[1]["price_list_rate"], 2500.0)

	def test_unpriced_item_reports_none_not_zero(self):
		# Zero is a price ("free"); None is "this list doesn't price it", which is what
		# lets the column fall back to standard_rate instead of quoting nothing.
		rows = _rows()
		_apply_item_prices(rows, _PRICES)
		self.assertIsNone(rows[2]["price_list_rate"])
		self.assertIsNone(rows[2]["price_list_currency"])

	def test_a_foreign_items_price_never_leaks_onto_another_row(self):
		# Grouping is by item_code; without it the first row of the page would win
		# every lookup and the whole dropdown would quote one product's price.
		rows = [{"name": "AQ511", "stock_uom": "Dona", "sales_uom": None}]
		_apply_item_prices(rows, _PRICES)
		self.assertIsNone(rows[0]["price_list_rate"])


if __name__ == "__main__":
	unittest.main()
