"""`sourcing_my_tenders` (prompt 17, "My tenders") — two source-level defects.

Acceptance rows M10 and M16. Both are about the ONE endpoint behind
`/tender/my-tenders`, so they share this file the way test_tender_board_filter.py
covers one endpoint's C14. Source-level on purpose, same idiom: the claims below
are about what the FUNCTION BODY does (which key it sorts on, which field it
reads), and comparing source text needs no database. The DB-backed half --
that this actually orders/labels real seeded rows -- is `make test-bench`
territory and is NOT claimed here.

Registration note: this file imports nothing from `frappe` and passes under
`python3 -m unittest stabler.tests.test_tender_my_tenders_source`, so it
qualifies for `.github/frappe-free-tests.txt` by the header comment's own rule.
It is NOT added there -- that file is off-limits in this change (a parallel
agent owns it) -- so `make check` / `make test` do not run it yet. Verified
manually instead; a maintainer needs to add the one line.

M10 -- the sort. `_tender_deal_names` returns a `set` (no `sorted()`), and the
existing sort key was two-wide: (risk, delivery). Measured against
seed_tender_demo.py (17-my-tenders.md §7): ten of the thirteen seeded rows tie
on both keys, so their order is whatever the set's iteration produced -- stable
within one process, arbitrary across a restart. Prompt 14's `tender_director_board`
sorts the SAME shape of row on three keys, ending `r["deal"]`
(tender.py:2160-2166); this reuses that exact convention rather than inventing
a new one.

M16 -- the landed figure. `landed` is `Σ(PO.base_grand_total + charges)` --
zero until a Purchase Order exists, i.e. zero for every row this screen's
sourcing audience is still working on (11 of 13 seeded rows). Zafar's pre-win
costing rule (00-SETUP.md "The pre-win costing rule", prompt 03) says the
number a sourcing officer can act on before the win is the FIXED estimate they
type onto the deal's own bid pricing -- `CRM Deal.custom_bid_pricing.landed_goods`,
the same field `_bid_inputs` reads (tender.py:1151-1164) for the BidPricing
screen. `_deal_landed_estimate` reads that field for a list row without calling
the heavier `_bid_inputs` (which also resolves SO revenue -- unneeded here).
`landed` itself is untouched, so M1's two won-lot totals do not move.
"""

import os
import re
import unittest

API = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "tender.py")


def _body(src: str, name: str) -> str:
	"""Source of one top-level function, from its `def` to the next top-level one."""
	m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
	assert m, f"{name} not found in api/tender.py"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestMyTendersSort(unittest.TestCase):
	"""M10 -- two rows tied on risk and delivery must have a defined order."""

	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.src = fh.read()

	def _sort_key(self) -> str:
		body = _body(self.src, "sourcing_my_tenders")
		# Greedy .+ bounded to end-of-line, not [^)]* -- the risk key itself is a
		# call with its own `)` (`_RISK_ORDER.get(r["risk"], 3)`), so a
		# non-`)`-class stops at the WRONG paren and never sees delivery or deal.
		m = re.search(r"rows\.sort\(key=lambda r: \((.+)\)\)\s*$", body, re.M)
		self.assertIsNotNone(
			m,
			"sourcing_my_tenders no longer sorts rows with one `rows.sort(key=lambda r: (...))` "
			"call -- this test's anchor has moved",
		)
		return m.group(1)

	def test_sort_key_breaks_ties_on_the_deal_name(self):
		# WHAT WOULD MAKE THIS FAIL: the key staying two-wide. Ten of the thirteen
		# seeded rows tie on (risk, delivery) today, so without a third key their
		# order is _tender_deal_names' set iteration -- stable in one process,
		# different after a `bench restart`, with nothing on screen changed.
		key = self._sort_key()
		self.assertIn(
			'r["deal"]',
			key,
			f"sort key {key!r} has no tie-break on deal -- ties fall back to set order",
		)

	def test_sort_key_keeps_risk_and_delivery_as_the_first_two(self):
		# WHAT WOULD MAKE THIS FAIL: adding the tie-break by reordering the tuple,
		# e.g. (deal, risk, delivery) -- that would sort the WHOLE table
		# alphabetically by deal first, which is a different (and wrong) screen:
		# the risk grouping §3/§7 describe would be destroyed, not just its ties
		# broken.
		key = self._sort_key()
		self.assertRegex(
			key,
			r'^\s*_RISK_ORDER\.get\(r\["risk"\],\s*3\)\s*,\s*r\["delivery"\]\s*or\s*"9999-99-99"\s*,',
			f"risk and delivery must stay the first two sort keys, in order: {key!r}",
		)

	def test_matches_the_director_boards_own_three_key_convention(self):
		# WHAT WOULD MAKE THIS FAIL: inventing a different tie-break (e.g. label,
		# or assigned_to) instead of reusing what tender_director_board already
		# does for the identical (risk, delivery)-shaped row. S4 names this board
		# explicitly as the three-key precedent; a second, different rule for the
		# same tie would be two conventions for one problem.
		# tender_director_board itself only delegates (`_tender_director_payload`,
		# include_rows=True) -- the sort lives in the payload builder it calls.
		payload_body = _body(self.src, "_tender_director_payload")
		self.assertRegex(
			payload_body,
			r'_RISK_ORDER\.get\(r\["risk"\],\s*3\),\s*\n\s*r\["delivery"\]\s*or\s*"9999-99-99",\s*\n\s*r\["deal"\],',
			"_tender_director_payload's own sort shape has moved -- re-anchor before trusting the comparison",
		)


class TestMyTendersLandedEstimate(unittest.TestCase):
	"""M16 -- the landed figure shown must be one a sourcing user can act on
	before the win, not only the post-win Purchase Order sum."""

	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.src = fh.read()

	def test_deal_landed_estimate_helper_exists_and_reads_bid_pricing(self):
		# WHAT WOULD MAKE THIS FAIL: the helper missing, or reading anything other
		# than the stored bid-pricing field. custom_bid_pricing.landed_goods is
		# the field a sourcing officer actually types to price a bid (_bid_inputs,
		# tender.py:1151-1164) -- reusing it is the whole point; re-deriving a PO
		# sum here would just be `landed` again under a new name.
		# assertTrue(re.search(...)), not assertRegex(self.src, ...): a failed
		# assertRegex against the WHOLE file dumps ~140 KB into the failure
		# message, which nobody reads (this file's own rule -- see module intro).
		self.assertTrue(
			re.search(r"^def _deal_landed_estimate\(", self.src, re.M),
			"_deal_landed_estimate not found in api/tender.py",
		)
		body = _body(self.src, "_deal_landed_estimate")
		self.assertIn("custom_bid_pricing", body, "must read the deal's own bid-pricing field")
		self.assertIn("landed_goods", body, "must read landed_goods specifically, not another key")

	def test_landed_estimate_does_not_fall_back_to_the_post_win_sum(self):
		# WHAT WOULD MAKE THIS FAIL: defaulting to _deal_landed/po_landed the way
		# _bid_inputs does for its editor pre-fill (tender.py:1162-1164). That
		# default exists so an officer editing pricing on an ALREADY-won deal sees
		# the real number instead of 0 -- correct for an editor, wrong for this
		# list: it would make landed_estimate equal `landed` again on every won
		# row and prove nothing about the 11 pre-win rows this change is for.
		body = _body(self.src, "_deal_landed_estimate")
		self.assertNotIn(
			"_deal_landed(",
			body,
			"_deal_landed_estimate must not call _deal_landed -- that reintroduces the post-win sum",
		)

	def test_sourcing_my_tenders_calls_the_estimate_at_the_row_build_site(self):
		# WHAT WOULD MAKE THIS FAIL: the helper landing unused. Anchored to
		# sourcing_my_tenders' own body (not a bare string search) so a same-named
		# call somewhere unrelated in the file cannot pass this test by accident.
		body = _body(self.src, "sourcing_my_tenders")
		self.assertIn(
			"_deal_landed_estimate(deal)",
			body,
			"sourcing_my_tenders never calls _deal_landed_estimate",
		)
		self.assertRegex(
			body,
			r'"landed_estimate":\s*landed_estimate,',
			"the row dict has no landed_estimate key wired to the helper's result",
		)

	def test_the_existing_post_win_landed_field_is_untouched(self):
		# WHAT WOULD MAKE THIS FAIL: routing `landed` itself through the new
		# helper, or renaming/removing it. M1 (already passing) pins the two won
		# lots' `landed` at 1 769 000 000 / 1 182 000 000 -- both are Σ PO sums,
		# and this change must add a second figure beside them, not replace the
		# first.
		body = _body(self.src, "sourcing_my_tenders")
		self.assertIn(
			'"landed": po_landed,',
			body,
			"the landed field must stay sourced from po_landed (_deal_landed) -- M1 depends on it",
		)


if __name__ == "__main__":
	unittest.main()
