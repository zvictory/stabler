"""`sourcing_my_tenders` (prompt 17, "My tenders") — source-level defects.

Acceptance rows M10 and M16, plus a P1-3 evidence-gate regression the
coordinator's review caught later (TestMyTendersResultGate, below). All three
are about the ONE endpoint behind `/tender/my-tenders`, so they share this file
the way test_tender_board_filter.py covers one endpoint's C14. Source-level on
purpose, same idiom: the claims below are about what the FUNCTION BODY does
(which key it sorts on, which field it reads), and comparing source text needs
no database. The DB-backed half -- that this actually orders/labels real
seeded rows -- is `make test-bench` territory and is NOT claimed here.

Registration note: this file imports nothing from `frappe` and passes under
`python3 -m unittest stabler.tests.test_tender_my_tenders_source`, so it
qualifies for `.github/frappe-free-tests.txt` by the header comment's own rule.
It is now added there (2026-09-02, coordinator review) -- an earlier claim that
a parallel agent already owned that registration did not hold, and the gap was
not cosmetic: with this file outside `make check`, the docstring-vacuity defect
below (P1-5) stayed invisible to the push gate for an entire review round.

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


def _code(src: str, name: str) -> str:
	"""`_body`, minus the function's own leading docstring.

	The coordinator's review (P1-5, 2026-09-02) found that `_body` includes the
	docstring, and a docstring naming the right field/key in PROSE satisfies an
	`assertIn` meant for the executable code: three in-memory mutants (body
	replaced by `return 0.0`, a wrong dict key, a wrong field name) all left
	the original version of this test green, because only the docstring --
	unchanged by any of the three -- was what the assertions actually matched.
	Use this instead of `_body` wherever an assertion is about what the CODE
	does, not what it is documented to do."""
	body = _body(src, name)
	return re.sub(r'"""[\s\S]*?"""\n?', "", body, count=1)


class TestMyTendersSort(unittest.TestCase):
	"""M10 -- two rows tied on risk and delivery must have a defined order."""

	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.src = fh.read()

	def _sort_key(self) -> str:
		# _code, not _body (P1-5 follow-up, coordinator review, 2026-09-02): the
		# coordinator's own mutation proved this class of bug isn't confined to
		# one function -- sourcing_my_tenders carries a real docstring, so a
		# _body-based search over it is exposed the same way _deal_landed_estimate
		# was, docstring prose and all.
		code = _code(self.src, "sourcing_my_tenders")
		# Greedy .+ bounded to end-of-line, not [^)]* -- the risk key itself is a
		# call with its own `)` (`_RISK_ORDER.get(r["risk"], 3)`), so a
		# non-`)`-class stops at the WRONG paren and never sees delivery or deal.
		m = re.search(r"rows\.sort\(key=lambda r: \((.+)\)\)\s*$", code, re.M)
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
		# WHAT WOULD MAKE THIS FAIL: sourcing_my_tenders' key actually
		# DISAGREEING with _tender_director_payload's -- not just one side, in
		# isolation, matching a fixed expected shape. P3-11 (coordinator review,
		# 2026-09-02): the original version of this test hardcoded
		# _tender_director_payload's own pattern and never looked at
		# sourcing_my_tenders at all, so it passed for any value of the thing
		# it was named after -- reverting THIS file's key to two-wide left it
		# green. Fixed by extracting both keys and comparing them by VALUE
		# (whitespace-normalized, since one call is one-line and the other is
		# formatted across four).
		# tender_director_board itself only delegates (`_tender_director_payload`,
		# include_rows=True) -- the sort lives in the payload builder it calls.
		# _code, not _body: _tender_director_payload has no docstring as of this
		# writing, but nothing pins that down -- switching anyway is the same
		# P1-5 hygiene the coordinator asked applied everywhere in this file,
		# not just where a docstring happens to exist today.
		mine = re.sub(r"\s+", " ", self._sort_key()).strip().rstrip(",")
		payload_code = re.sub(r"\s+", " ", _code(self.src, "_tender_director_payload"))
		m = re.search(r"key=lambda r: \( (.+?) \)\s*\)", payload_code)
		self.assertIsNotNone(
			m,
			"_tender_director_payload's own sort key has moved -- re-anchor before comparing",
		)
		theirs = m.group(1).strip().rstrip(",")
		self.assertEqual(
			mine,
			theirs,
			"sourcing_my_tenders' sort key no longer matches _tender_director_payload's -- "
			"two different tie-break conventions for the identical row shape",
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
		#
		# P1-5 (coordinator review, 2026-09-02): the original version of this
		# test asserted against `_body`, which INCLUDES the function's own
		# docstring -- and the docstring itself names both strings in prose, so
		# `assertIn("custom_bid_pricing", body)` / `assertIn("landed_goods", body)`
		# passed on documentation, not code. Three in-memory mutants (body
		# replaced by `return 0.0`, a wrong dict key, a wrong field name) all
		# left it green. Fixed with `_code` (docstring stripped) and exact
		# call-site anchors instead of bare substrings.
		#
		# assertTrue(re.search(...)), not assertRegex(self.src, ...): a failed
		# assertRegex against the WHOLE file dumps ~140 KB into the failure
		# message, which nobody reads (this file's own rule -- see module intro).
		self.assertTrue(
			re.search(r"^def _deal_landed_estimate\(", self.src, re.M),
			"_deal_landed_estimate not found in api/tender.py",
		)
		code = _code(self.src, "_deal_landed_estimate")
		self.assertIn(
			'frappe.db.get_value("CRM Deal", deal, "custom_bid_pricing")',
			code,
			"must read the deal's own bid-pricing field via this exact call",
		)
		self.assertIn(
			'stored.get("landed_goods")',
			code,
			"must read landed_goods specifically, not another key",
		)

	def test_landed_estimate_does_not_fall_back_to_the_post_win_sum(self):
		# WHAT WOULD MAKE THIS FAIL: defaulting to _deal_landed/po_landed the way
		# _bid_inputs does for its editor pre-fill (tender.py:1162-1164). That
		# default exists so an officer editing pricing on an ALREADY-won deal sees
		# the real number instead of 0 -- correct for an editor, wrong for this
		# list: it would make landed_estimate equal `landed` again on every won
		# row and prove nothing about the 11 pre-win rows this change is for.
		# Docstring stripped (_code, not _body) as a matter of the same P1-5
		# hygiene as the test above -- this docstring does not currently contain
		# "_deal_landed(", but nothing stops a future edit from adding it in
		# prose, and this is the one place that would go quietly vacuous again.
		code = _code(self.src, "_deal_landed_estimate")
		self.assertNotIn(
			"_deal_landed(",
			code,
			"_deal_landed_estimate must not call _deal_landed -- that reintroduces the post-win sum",
		)

	def test_sourcing_my_tenders_calls_the_estimate_at_the_row_build_site(self):
		# WHAT WOULD MAKE THIS FAIL: the helper landing unused. Anchored to
		# sourcing_my_tenders' own body (not a bare string search) so a same-named
		# call somewhere unrelated in the file cannot pass this test by accident.
		#
		# _code, not _body (P1-5 follow-up, coordinator review, 2026-09-02): this
		# was one of the two tests the coordinator named directly. sourcing_my_tenders
		# carries a real docstring ("""Sourcing window: ...""", tender.py:2506), and
		# the coordinator proved it exploitable in this worktree: deleted the real
		# `landed_estimate = _deal_landed_estimate(deal)` call, replaced it with
		# `landed_estimate = None`, and added a second docstring line naming
		# "_deal_landed_estimate(deal)" in prose -- `_body` (docstring included)
		# left this test green with the helper gone from the executable code.
		code = _code(self.src, "sourcing_my_tenders")
		self.assertIn(
			"_deal_landed_estimate(deal)",
			code,
			"sourcing_my_tenders never calls _deal_landed_estimate",
		)
		self.assertRegex(
			code,
			r'"landed_estimate":\s*landed_estimate,',
			"the row dict has no landed_estimate key wired to the helper's result",
		)

	def test_the_existing_post_win_landed_field_is_untouched(self):
		# WHAT WOULD MAKE THIS FAIL: routing `landed` itself through the new
		# helper, or renaming/removing it. M1 (already passing) pins the two won
		# lots' `landed` at 1 769 000 000 / 1 182 000 000 -- both are Σ PO sums,
		# and this change must add a second figure beside them, not replace the
		# first.
		#
		# _code, not _body (P1-5 follow-up, coordinator review, 2026-09-02): the
		# other of the two tests the coordinator named directly -- the same
		# mutation (helper call deleted, docstring extended with the literal
		# `"landed": po_landed,` text) left this one green too, for the same
		# reason: `_body` includes sourcing_my_tenders' own docstring.
		code = _code(self.src, "sourcing_my_tenders")
		self.assertIn(
			'"landed": po_landed,',
			code,
			"the landed field must stay sourced from po_landed (_deal_landed) -- M1 depends on it",
		)


class TestMyTendersResultGate(unittest.TestCase):
	"""P1-3 (coordinator review, 2026-09-02) -- the result chip must not bypass
	the submission-evidence gate the rest of the module enforces.

	`_has_submission_evidence`'s own docstring: "a result is not proof of
	participation." `_tender_director_payload` already gates the identical
	field before it reaches its own row (tender.py: `_res = intake.get("result")
	if verified else ""`, then `"result": _res`). sourcing_my_tenders instead
	wrote `"result": intake.get("result") or ""` -- raw, unverified -- so a
	user who sets Result = Won without a submitted bid got a green "Won" chip
	on this screen and an amber "Unverified" chip on DirectorBoard, for the
	same deal.
	"""

	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.src = fh.read()

	def test_result_is_gated_on_submitted_evidence_like_the_director_board(self):
		# WHAT WOULD MAKE THIS FAIL: `"result": intake.get("result") or "",` --
		# the original defect -- or any gate that is not this exact evidence
		# flag. sourcing_my_tenders already computes `evidence =
		# _tender_filter_evidence(...)` two lines above the row dict, and
		# evidence["lifecycle"]["submitted"] IS `_has_submission_evidence(intake)`
		# (tender.py: `"submitted": verified,`) -- reusing it, rather than
		# calling _has_submission_evidence a second time, is what keeps this
		# gate from being able to drift apart from _tender_filter_evidence's own
		# definition of "verified".
		#
		# _code, not _body (P1-5 follow-up, coordinator review, 2026-09-02): this
		# test was added in the same round as the docstring-vacuity fix and still
		# read the docstring-bearing sourcing_my_tenders through _body -- exactly
		# the class of gap the coordinator flagged, just not one of the two
		# instances they demonstrated by hand.
		code = _code(self.src, "sourcing_my_tenders")
		self.assertRegex(
			code,
			r'"result":\s*intake\.get\("result"\)\s+if\s+evidence\["lifecycle"\]\["submitted"\]\s+else\s+"",',
			'result must be gated on evidence["lifecycle"]["submitted"], not read raw',
		)


if __name__ == "__main__":
	unittest.main()
