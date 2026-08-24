"""WP-T3 wiring guards for the tender landed-charge currency (Frappe-free).

`stabler.tests.test_tender_landed_math` proves the conversion itself. These
guard the two structural decisions around it, which a refactor can undo without
any arithmetic changing:

  1. The derivation lives in `_parse_landed`. That function is the single
     chokepoint every read AND every write passes through (7 call sites, one of
     them in api/lcv.py), so deriving there is what stops the company-currency
     `amount` and the typed `amount_original` from ever disagreeing. Move it into
     the save path alone and a legacy row re-read after a rate correction keeps
     the old figure.

  2. The refusal lives in `save_po_landed_charges`, not in `_parse_landed`.
     A line naming a currency with no usable rate must never be STORED, because
     its money would silently leave the total that decides which vendor wins.
     But reading must never throw: `_parse_landed` also serves the board, and a
     hand-edited JSON blob must render rather than take a screen down.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_landed_currency_source -v
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TENDER = os.path.normpath(os.path.join(_HERE, "..", "api", "tender.py"))


def _read() -> str:
	with open(_TENDER, encoding="utf-8") as f:
		return f.read()


def _func_body(src: str, name: str) -> str:
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"function {name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestParseLandedCarriesTheQuote(unittest.TestCase):
	def setUp(self):
		self.body = _func_body(_read(), "_parse_landed")

	def test_round_trips_the_three_quote_fields(self):
		# Drop any one and the line still renders, but its provenance is gone:
		# nobody can tell which day's rate produced the company-currency figure.
		for field in ("currency", "fx_rate", "rate_date"):
			self.assertIn(f'"{field}"', self.body, f"_parse_landed drops {field}")

	def test_keeps_the_typed_original_beside_the_converted_figure(self):
		self.assertIn("amount_original", self.body)
		self.assertIn("actual_original", self.body)

	def test_derives_through_the_shared_rule(self):
		self.assertIn(
			"converted_amount",
			self.body,
			"_parse_landed must convert through tender_landed_math.converted_amount, "
			"not with arithmetic of its own — the missing-rate stance lives there",
		)

	def test_a_customs_line_is_not_converted(self):
		"""A customs line's amount comes from the CIF calculator, not from typing.

		Converting it here would give it a SECOND writer, and the conversion would
		also be wrong: the ГТД declares the customs value in company currency at
		the rate customs itself applied, so re-deriving it from a CBU quote
		produces a figure that does not match the declaration.
		"""
		self.assertRegex(
			self.body,
			r'ctype\s*!=\s*"customs"',
			"_parse_landed converts every line type — a customs line must be left "
			"to applyCustoms/customsCalc",
		)

	def test_reading_never_throws_on_an_unusable_rate(self):
		self.assertNotIn(
			"frappe.throw",
			self.body,
			"_parse_landed also serves reads; a hand-edited blob must render, not 500",
		)


class TestSaveRefusesAnUnvaluableLine(unittest.TestCase):
	def setUp(self):
		self.body = _func_body(_read(), "save_po_landed_charges")

	def _between_parse_and_store(self) -> str:
		"""The window in which a refusal still prevents anything being written."""
		start = self.body.index("cleaned = _parse_landed")
		end = self.body.index("frappe.db.set_value")
		self.assertLess(start, end, "the payload is stored before it is parsed")
		return self.body[start:end]

	def test_refuses_a_currency_with_no_usable_rate_before_storing(self):
		window = self._between_parse_and_store()
		self.assertIn(
			"frappe.throw",
			window,
			"save_po_landed_charges stores the payload without refusing a line it "
			"cannot value — a throw placed after db.set_value refuses nothing",
		)
		self.assertRegex(
			window,
			r'fx_rate"?\]?\s*<=\s*0',
			"the refusal must key on a non-positive rate, not merely a missing field",
		)

	def test_the_refusal_walks_the_parsed_lines(self):
		# Validating the raw payload instead would miss the normalisation
		# `_parse_landed` performs (upper-casing, flt coercion).
		self.assertRegex(self._between_parse_and_store(), r"\n\t*for \w+ in cleaned:")


if __name__ == "__main__":
	unittest.main()
