"""What a genealogy panel may claim when no batch was ever recorded.

Measured on anjan, 2026-08-28, read-only:

    material-transfer detail rows                 23 851
    …carrying a `batch_no`                             0
    submitted Work Orders                          3 789
    …carrying a `custom_batch_no`                      0
    consumed rows sourced from another order's
      finished-goods warehouse                    23 848

So the structure a genealogy tree would walk is real — at anjan almost every
input to an order was itself produced by an earlier order, mostly through
`Yarim tayyor` (semi-finished) and `Ishlab chiqarish` — while the link that
would resolve *which* earlier order is absent. Without a batch the question
"who produced this input" has, per item, a mean of 14.9 candidate orders and a
maximum of 171.

That is why this module exists, and why it is mostly about what the panel must
NOT say. Picking the nearest preceding order would render a tree that looks
exactly like a resolved one and is a guess. In a food factory the moment that
tree is read is a recall, and a traceability answer that guesses is worse than
one that says it does not know — the guess ends the search.

So the rule pinned here: mark the origin, count the candidates, and never name
a parent. The panel's job is to make the missing batch visible, next to the
button that records one (`set_wo_batch`, which has existed all along and was
only ever reachable from the kiosk).

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_genealogy_origin -v
"""

from __future__ import annotations

import unittest

from stabler.api._wo_genealogy import annotate_consumed_origin

_PRODUCTION_WAREHOUSES = {"Yarim tayyor  - A", "Ishlab chiqarish - A"}
_CANDIDATES = {"MUZ-BAZA": 171, "SUT-YARIM": 3}


def _rows(*rows):
	return annotate_consumed_origin(list(rows), _PRODUCTION_WAREHOUSES, _CANDIDATES)


class TestAnInHouseInputIsMarkedAsOne(unittest.TestCase):
	def test_a_row_from_a_production_warehouse_is_flagged(self):
		"""23 848 of 23 851 consumed rows at anjan come from a warehouse some
		order produces into. Not flagging them would render the floor's actual
		multi-level production as if every input were bought in."""
		row = _rows({"item_code": "MUZ-BAZA", "warehouse": "Yarim tayyor  - A"})[0]
		self.assertTrue(row["from_production"])

	def test_a_row_from_a_raw_material_store_is_not(self):
		row = _rows({"item_code": "SEKER", "warehouse": "Asosiy hom ashyo - A"})[0]
		self.assertFalse(row["from_production"])

	def test_a_row_with_no_warehouse_is_not_guessed_into_production(self):
		row = _rows({"item_code": "MUZ-BAZA", "warehouse": None})[0]
		self.assertFalse(row["from_production"])


class TestTheCandidateCountIsShownAndNeverCollapsed(unittest.TestCase):
	"""The count is the honesty. A panel that showed "produced in-house" without
	it reads as though the chain were known and merely unlabelled."""

	def test_the_count_comes_from_the_item(self):
		row = _rows({"item_code": "MUZ-BAZA", "warehouse": "Yarim tayyor  - A"})[0]
		self.assertEqual(row["producer_candidates"], 171)

	def test_a_single_candidate_is_still_not_named(self):
		"""The tempting special case, and the one that would do the damage.
		One candidate today is one candidate *so far*: orders keep being
		created, and a panel that named the parent whenever the count happened
		to be 1 would silently start lying on the day a second order for that
		item is opened — after the label is printed, not before."""
		row = _rows({"item_code": "SUT-YARIM", "warehouse": "Yarim tayyor  - A"})[0]
		self.assertEqual(row["producer_candidates"], 3)
		self.assertNotIn("parent_work_order", row)
		self.assertNotIn("producer", row)

	def test_an_item_nobody_produces_reports_zero(self):
		row = _rows({"item_code": "SEKER", "warehouse": "Asosiy hom ashyo - A"})[0]
		self.assertEqual(row["producer_candidates"], 0)


class TestTheOriginalRowSurvives(unittest.TestCase):
	def test_the_measured_fields_are_untouched(self):
		"""Annotation, not replacement: the qty and the voucher are what a
		recall actually follows, and they come from submitted Stock Entries."""
		row = _rows(
			{
				"item_code": "MUZ-BAZA",
				"warehouse": "Yarim tayyor  - A",
				"qty": 12.5,
				"stock_entry": "MAT-STE-2026-00042",
			}
		)[0]
		self.assertEqual(row["qty"], 12.5)
		self.assertEqual(row["stock_entry"], "MAT-STE-2026-00042")

	def test_the_input_list_is_not_reordered_or_filtered(self):
		"""Every consumed line is shown, in the order the Stock Entries were
		posted. Dropping the ones with no known origin would hide exactly the
		bought-in materials a contamination trace starts from."""
		out = _rows(
			{"item_code": "SEKER", "warehouse": "Asosiy hom ashyo - A"},
			{"item_code": "MUZ-BAZA", "warehouse": "Yarim tayyor  - A"},
			{"item_code": "SUT-YARIM", "warehouse": "Ishlab chiqarish - A"},
		)
		self.assertEqual([r["item_code"] for r in out], ["SEKER", "MUZ-BAZA", "SUT-YARIM"])


if __name__ == "__main__":
	unittest.main()
