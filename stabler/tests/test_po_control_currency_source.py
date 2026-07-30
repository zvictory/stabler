"""Guards that `po_control_board` compares vendors in ONE currency.

The board's `quotation_total` / `delta_pct` are rendered by `PoControlBoard.vue`
with the company currency. Summing per-quotation `grand_total` mixes a USD SQ
with a UZS SQ into one meaningless number, and comparing it against the PO's own
`po_total` compounds the error. Both sides must use the base (company-currency)
amounts.

The same rule binds the board's own aggregates. `PoControlBoard.vue` says it out
loud (`t("Amounts in company currency") ({{ ccy }})`) and passes `ccy` to every
roll-up it prints: the KPI total (:348), each lane header (:371) and the vendor
table (:434-440). Only the per-PO card passes `c.currency` (:383), because that
one number is printed next to its own currency. So every aggregate the board
sums MUST be a base amount — a `grand_total` sum labelled with the company
currency reads as UZS while holding USD (prod showed `4 160 сўм` for a PO that
was `4 160,00 $` = `50 123 174 сўм`).

`received_pct` is a ratio, so it looks currency-immune — it is not. It is an
amount-weighted average, `Σ(amount × per_received) / Σ(amount)`, and mixing
currencies in the weights lets a 12 000× exchange rate decide which PO counts.
Its numerator and denominator must therefore move together with the KPI total;
this file keeps them wired to the same basis.
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

	def test_kpi_total_accumulates_base_amounts(self):
		"""`kpi.total` is printed with the company currency (`PoControlBoard.vue:348`)."""
		self.assertIn("total += base_gt", self.board)
		self.assertNotIn("total += gt", self.board)

	def test_received_percent_weights_by_the_same_basis_as_the_total(self):
		"""It divides by `total`; a numerator on another basis silently skews it."""
		self.assertIn("recv_weighted += base_gt * pr", self.board)
		self.assertNotIn("recv_weighted += gt * pr", self.board)
		self.assertIn("round(recv_weighted / total, 1) if total else 0", self.board)

	def test_lane_totals_sum_base_amounts(self):
		"""Each lane header prints its total with the company currency (:371)."""
		self.assertIn('sum(c["base_amount"] for c in lc)', self.board)
		self.assertNotIn('sum(c["amount"] for c in lc)', self.board)

	def test_board_currency_is_the_company_currency(self):
		"""`ccy` falls back to this key, and every roll-up above it is a base
		amount — labelling them with the first PO's currency mislabels them all.
		The empty-board early return already answers `base_ccy`."""
		self.assertIn('"currency": base_ccy,', self.board)
		self.assertNotIn("rows[0].currency", self.board)

	def test_per_po_cards_keep_their_own_currency(self):
		"""The card prints `c.amount` next to `c.currency` — it must NOT be based."""
		self.assertIn('"amount": gt,', self.board)
		self.assertIn('"currency": r.currency or base_ccy,', self.board)
		self.assertIn('"base_amount": base_gt,', self.board)

	def test_response_shape_is_unchanged(self):
		"""The frontend contract stays put — this is a value fix, not an API change."""
		for key in ('"quotation_total": qt', '"delta_pct"', '"po_total": s["po_total"]'):
			self.assertIn(key, self.board)


if __name__ == "__main__":
	unittest.main()
