"""`tender_only` narrows the contract board on ONE axis, and it is the funnel's.

Prompt 18, acceptance row C14 — "the board's filter matches the number that
navigated to it". The funnel's execution buckets count Sales Orders that are
submitted AND tagged to a deal:

    filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": 1}

`so_board` answered with a different set on both of its settings. Measured
2026-09-02:

    tender_only=0  ->  docstatus: 1,      no deal restriction   (every contract)
    tender_only=1  ->  docstatus: ["<",2] + deal restriction    (DRAFTS INCLUDED)

So the flag was narrower on one axis and wider on the other, and neither setting
was the funnel's set. Prompt 18's S1 named that as "two surprises in one
parameter"; this test is what stops the second one coming back.

Nothing in the SPA produced `tender_only=1` before this change (measured across
public/js: six sibling drill-downs read `tender_only`, the board read a
differently-named `tender`, and no screen wrote either), so removing the draft
branch regressed no reachable behaviour.

Source-level on purpose: the claim is about the FILTER the endpoint builds, and
comparing two filter dicts needs no database. Same idiom as
test_tender_generated_at.py — see .github/frappe-free-tests.txt for why a
frappe-free test has to stay frappe-free. The DB-backed half (that the two
queries return the same rows against real data) is `make test-bench` territory
and is NOT claimed here.
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


def _docstatus(filters: str) -> str:
	"""The docstatus clause of a filter dict literal, whitespace-normalised."""
	m = re.search(r'"docstatus"\s*:\s*([^,}]+)', filters)
	assert m, f"no docstatus clause in: {filters[:120]}"
	return re.sub(r"\s+", "", m.group(1))


class TestContractBoardFilterMatchesTheFunnel(unittest.TestCase):
	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.src = fh.read()

	def _board_filters(self) -> str:
		body = _body(self.src, "so_board")
		m = re.search(r"so_filters\s*=\s*(\{[^}]*\})", body)
		self.assertIsNotNone(
			m,
			"so_board must assign so_filters ONE dict literal. Until 2026-09-02 it assigned a\n"
			"conditional pair — the tender_only branch swapped in a WIDER docstatus — which is\n"
			"exactly the shape this test exists to keep out.",
		)
		return m.group(1)

	def _funnel_so_filters(self) -> str:
		body = _body(self.src, "tender_funnel")
		m = re.search(r'"Sales Order",\s*\n\s*filters=(\{[^}]*\})', body)
		self.assertIsNotNone(m, "tender_funnel no longer queries Sales Order by a filter dict")
		return m.group(1)

	def test_the_board_and_the_funnel_agree_on_docstatus(self):
		# WHAT WOULD MAKE THIS FAIL: either side moving alone. This is the whole
		# point of C14 — the number the user clicks and the list they land on must
		# be drawn from the same set. Asserting the RELATIONSHIP rather than the
		# literal means a future change to the funnel's docstatus fails here until
		# the board follows it, and vice versa. A draft Sales Order is not a
		# contract on a board of contracts, and the funnel has never counted one.
		self.assertEqual(
			_docstatus(self._board_filters()),
			_docstatus(self._funnel_so_filters()),
			"so_board and tender_funnel must read Sales Orders at the same docstatus, "
			"or the funnel's count and the board's cards are two different sets",
		)

	def test_tender_only_no_longer_widens_docstatus(self):
		# WHAT WOULD MAKE THIS FAIL: restoring the conditional that swapped in
		# {"docstatus": ["<", 2]} under the flag. That is the defect stated as
		# "narrower on one axis and wider on the other": turning the tender filter
		# ON used to ADD rows — the drafts — which is the opposite of what a filter
		# named "tender only" promises.
		#
		# assertNotIn on the extracted dict, not on the file: a failure prints the
		# filter literal, not all of tender.py.
		filters = self._board_filters()
		self.assertNotIn('["<", 2]', filters, f"tender_only widens docstatus again: {filters}")
		self.assertEqual(len(re.findall(r'"docstatus"', filters)), 1, filters)

	def test_tender_only_still_restricts_to_deal_linked_orders(self):
		# WHAT WOULD MAKE THIS FAIL: dropping the deal restriction along with the
		# draft branch. `tender_only` would then mean nothing at all, and the funnel
		# click would land on every contract in the company — the original C14
		# symptom, reached by over-correcting the fix.
		body = _body(self.src, "so_board")
		self.assertTrue(
			re.search(r"if int\(tender_only or 0\) and not so\.custom_crm_deal:\s*\n\s*continue", body),
			"so_board must still drop orders with no custom_crm_deal when tender_only is set",
		)

	def test_the_deal_axis_is_the_funnel_s_deal_axis(self):
		# WHAT WOULD MAKE THIS FAIL: the funnel widening to untagged orders while
		# the board keeps requiring a deal, or the reverse. Both sides express it
		# differently — the funnel as a query filter, the board as a post-filter,
		# because the board reads the same rows for both settings — so this asserts
		# that each still names custom_crm_deal, not that they share a literal.
		self.assertIn('"custom_crm_deal": ["is", "set"]', self._funnel_so_filters())
		self.assertIn("custom_crm_deal", _body(self.src, "so_board"))


if __name__ == "__main__":
	unittest.main()
