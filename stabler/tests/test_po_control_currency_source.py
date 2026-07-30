"""Guards that `po_control_board` compares vendors in ONE currency.

The board's `quotation_total` / `delta_pct` are rendered by `PoControlBoard.vue`
with the company currency. Summing per-quotation `grand_total` mixes a USD SQ
with a UZS SQ into one meaningless number, and comparing it against the PO's own
`po_total` compounds the error. Both sides must use the base (company-currency)
amounts.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TENDER_API = os.path.normpath(os.path.join(_HERE, "..", "api", "tender.py"))


class TestPoControlCurrencySource(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with open(_TENDER_API, encoding="utf-8") as source:
			cls.api = source.read()
		start = cls.api.index("def po_control_board(")
		cls.board = cls.api[start : cls.api.index("\ndef ", start + 1)]

	def test_supplier_quotation_query_selects_the_base_total(self):
		self.assertIn('fields=["supplier", "grand_total", "base_grand_total"]', self.board)

	def test_quotation_totals_accumulate_base_amounts(self):
		"""Falls back to `grand_total` only when the base column is empty — a
		single-currency site stores the same number in both."""
		self.assertRegex(
			self.board,
			re.compile(
				r"q_by_supplier\[q\.supplier\]\s*=\s*q_by_supplier\.get\(q\.supplier,\s*0\.0\)\s*\+\s*\(\s*"
				r"flt\(q\.base_grand_total\)\s*or\s*flt\(q\.grand_total\)\s*\)",
				re.S,
			),
		)

	def test_vendor_delta_compares_base_po_total_against_the_quotation(self):
		self.assertIn('delta = ((s["base_po_total"] - qt) / qt * 100) if qt else None', self.board)
		self.assertNotIn('delta = ((s["po_total"] - qt) / qt * 100)', self.board)

	def test_response_shape_is_unchanged(self):
		"""The frontend contract stays put — this is a value fix, not an API change."""
		for key in ('"quotation_total": qt', '"delta_pct"', '"po_total": s["po_total"]'):
			self.assertIn(key, self.board)


if __name__ == "__main__":
	unittest.main()
