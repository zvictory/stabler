"""The per-kg card's contract between `get_landed_cost_review` and the SPA.

The card divides money by weight, and the only thing keeping those two from
describing different sets of goods is that the backend ships them on the SAME
`purchase_receipts` row. That agreement is a wire contract across two languages,
so nothing in either half can see it break: the JS spec builds its own fixtures
and would pass whatever the backend emits, and the endpoint that emits it is
DB-dependent, so `make check` never executes it.

This is the cheapest guard that does run on every push — it reads the source. It
cannot prove the query returns the right number; it proves the key still exists,
still comes off the same loop as `base_grand_total`, and is still summed from a
stock-UOM quantity rather than a transaction one. The arithmetic is proved by
`public/js/tests/landedCostPerKg.spec.js`; the live query needs
`make test-bench` (`stabler.tests.test_lcv_integration`).

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_landed_cost_per_kg_source
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
COMPOSABLE = os.path.join(_ROOT, "public", "js", "composables", "landedCostPerKg.js")
VUE = os.path.join(_ROOT, "public", "js", "pages", "purchasing", "LandedCostReview.vue")

KEY = "costed_qty_kg"


def read(path: str) -> str:
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def body(src: str, name: str) -> str:
	match = re.search(rf"^def {name}\(", src, re.M)
	assert match, f"{name} not found"
	tail = src[match.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TheWireContractTest(unittest.TestCase):
	def setUp(self):
		self.api = read(API)
		self.review = body(self.api, "get_landed_cost_review")

	def test_the_review_payload_still_carries_the_costed_weight(self):
		# Drop the key and the composable's own `costedKg <= 0` guard hides the
		# whole card. That is the safe direction to fail in, but it is silent — the
		# accountant simply stops being shown a cost per kg and nothing says why.
		self.assertIn(f'"{KEY}"', self.review)

	def test_the_weight_and_the_money_are_emitted_on_one_row(self):
		# The defect this fixes was a numerator and a denominator describing
		# different goods. They are safe only while they are the same row, so the
		# two keys must sit in one dict literal — close enough that a future edit
		# cannot move one without seeing the other.
		# The dict ENTRY, not the field list handed to `get_value` further up — that
		# one names `base_grand_total` too, and matching it would compare the wrong
		# pair of positions and pass on a diff that had pulled the two apart.
		money = self.review.index('"base_grand_total": flt(')
		weight = self.review.index(f'"{KEY}": flt(')
		between = self.review[min(money, weight) : max(money, weight)]
		self.assertNotIn("append(", between)
		self.assertLess(between.count("\n"), 4)

	def test_the_tally_sums_a_stock_quantity_not_a_transaction_one(self):
		# `qty` is the line's transaction UOM — boxes or pieces on the purchasing
		# route. Only `stock_qty` is guaranteed to be the stock UOM, which is Kg
		# here (receipt_math.STOCK_UOM, conversion_factor 1).
		self.assertIn('"stock_qty"', self.review)
		self.assertRegex(self.review, r"costed_kg\[[^\]]+\]\s*=\s*costed_kg\.get\(")

	def test_the_tally_is_one_query_and_never_an_sql_function_in_a_string(self):
		# Frappe v16 refuses a SQL function spelled as a string in SELECT — it
		# parses fine and 500s on the live site, which is how the imports board went
		# down on msa. The sum is therefore done in Python, and one query serves
		# every receipt rather than one per receipt.
		self.assertNotRegex(self.review, r'"\s*sum\s*\(')
		# This counted the literal `"Purchase Receipt Item"` until the child table
		# became `f"{receipt_type} Item"` — the LCV route now capitalizes onto a
		# Purchase Invoice too. A literal that no longer appears counts zero, and a
		# guard that counts zero occurrences of a vanished string forbids nothing:
		# it would have passed a rewrite that put the read back inside the loop.
		# So the count moved onto the expression that is actually there, and the
		# `in` filter — the mechanism that makes it one query — is asserted with it.
		self.assertEqual(1, self.review.count('f"{receipt_type} Item"'))
		self.assertIn('"parent": ["in", pr_names]', self.review)


class TheClientReadsWhatIsSentTest(unittest.TestCase):
	def test_both_legs_are_summed_off_the_same_array(self):
		src = read(COMPOSABLE)
		self.assertIn('sumField(receipts, "base_grand_total")', src)
		self.assertIn(f'sumField(receipts, "{KEY}")', src)

	def test_the_card_no_longer_divides_by_the_all_condition_weight(self):
		# `received_total_kg` counts every condition and is still read — it is what
		# the uncosted sub-line reconciles against — but it must never be a divisor
		# again. `costedKg` is the only denominator in the module.
		src = read(COMPOSABLE)
		self.assertNotIn("/ receivedKg", src)
		self.assertIn("/ costedKg", src)

	def test_the_sub_line_does_not_assert_a_cause_the_data_lacks(self):
		# Uncosted weight is not evidence of damage: a truck whose supplier could
		# not be resolved never gets a Purchase Receipt at all, and a cancelled
		# receipt leaves its kilos on the GRN. A fabricated "N kg damaged" printed
		# above the Submit button is what starts a supplier claim.
		vue = read(VUE)
		self.assertNotIn("damaged or rejected", vue)
		self.assertIn("not on a purchase receipt", vue)


if __name__ == "__main__":
	unittest.main()
