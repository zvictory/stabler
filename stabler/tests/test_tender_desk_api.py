import os
import re
import unittest

API_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api", "tender_desk.py")


class TestTenderDeskApiSource(unittest.TestCase):
	def setUp(self):
		with open(API_FILE, encoding="utf-8") as f:
			self.source = f.read()

	def test_no_app_routes_in_source(self):
		self.assertNotIn("/app/", self.source, "tender_desk.py must not contain /app/ links")

	def test_list_pending_unwraps_requests(self):
		# list_pending returns {"requests": [...], "total": n, "can_approve": bool}.
		# Passing that envelope on as if it were the row list makes _desk_rules
		# iterate its three KEYS: measured 2026-08-01 on mikas, the desk showed
		# "Approval required: Document requests / total / can_approve", counted them
		# in due_today, and every real pending approval vanished. Both halves fail
		# silently -- no exception, no empty list, just wrong work on a work board --
		# so the call site is pinned here rather than left to review.
		for idx, line in enumerate(self.source.splitlines(), 1):
			if "list_pending(" in line and not line.lstrip().startswith(("#", "from ", "import ")):
				self.assertIn(
					"requests", line, f"Line {idx}: list_pending() returns an envelope; unwrap ['requests']"
				)

	def test_bid_deadline_falls_back_to_the_intake_json(self):
		# The bid deadline is the one fact a tender desk exists to say, and on a
		# real site it is NOT a column. Measured 2026-08-01 on mikas: CRM Deal has
		# no custom_bid_deadline, no bid_deadline and no expected_closing, so every
		# has_column() guard dropped all three and the lookup was unconditionally
		# None -- the desk emitted zero bid_due/bid_soon rows while the CRM board
		# read the same deadline out of custom_tender_intake and showed it fine.
		# The failure is silent: no error, no empty list, just a work board that
		# quietly omits every deadline. So both halves are pinned here -- the field
		# must be requested, and it must actually appear in the fallback chain.
		self.assertIn(
			"custom_tender_intake",
			self.source,
			"custom_tender_intake must be requested; it is where the deadline lives",
		)
		chain = re.search(r'"custom_bid_deadline": \(\n(.*?)\n\s*\),\n', self.source, re.S)
		self.assertIsNotNone(chain, "the bid_deadline fallback chain is gone")
		self.assertIn(
			'intake.get("bid_deadline")',
			chain.group(1),
			"intake must be one of the bid_deadline sources, not just fetched",
		)

	def test_every_missing_column_falls_back_to_the_intake_json(self):
		# The deadline was not alone. Four more facts this desk reasons with are
		# read from CRM Deal columns that no patch in stabler/patches/ creates:
		# custom_lot_no, custom_delivery_deadline, custom_tender_result and
		# assigned_to. Each lookup was unconditionally None, so each rule built on
		# it was dead code that still looked implemented -- the orphan-lot rule
		# never fired, no delivery row was ever emitted, team load counted won and
		# lost lots as open, and assignment collapsed onto the document owner.
		#
		# Pinned per field rather than as one blanket "intake appears somewhere",
		# because that weaker form passes as soon as ANY single fallback exists --
		# which is exactly the state this test was written to end.
		for column, intake_key in (
			("custom_lot_no", "lot_no"),
			("custom_delivery_deadline", "delivery_deadline"),
			("custom_tender_result", "result"),
			("assigned_to", "assigned_to"),
		):
			with self.subTest(column=column):
				self.assertIn(
					f'intake.get("{intake_key}")',
					self.source,
					f"{column} has no column on a real site; intake['{intake_key}'] "
					"must be in its fallback chain",
				)

	def test_the_lot_is_named_the_way_its_owner_would_name_it(self):
		# The board labelled every row with the deal id. On the demo pipeline four
		# lots share one buyer, so four rows read identically and none of them says
		# which tender it is. The lot number is the tender's own name; the buyer is
		# the fallback; the id says nothing to the person reading it.
		self.assertIn(
			'"label": lot_no or d.get("organization") or d["name"]',
			self.source,
			"the label chain must prefer the lot number, then the buyer",
		)
		self.assertNotIn(
			'"label": d.get("name")', self.source, "a row labelled by deal id is unreadable on a real board"
		)

	def test_orphan_lots_need_a_parent_to_exist_somewhere(self):
		# Reading the lot number out of intake woke this rule up. On a company that
		# files tenders flat -- no Tender Master anywhere -- it would then fire for
		# every single lot and bury the desk's real work. A rule that flags all
		# thirteen tells you nothing about any of them.
		self.assertIn(
			"company_uses_parents",
			self.source,
			"the orphan rule must require at least one linked lot in the company",
		)
		self.assertIn(
			'if company_uses_parents and d.get("custom_lot_no")',
			self.source,
			"the guard must be part of the orphan filter, not merely computed",
		)

	def test_intake_is_parsed_once_per_deal_not_per_lookup(self):
		# _parse_intake() runs json.loads. Calling it inside the fact-mapping
		# comprehension instead of once per deal would re-parse the same JSON for
		# every field read -- invisible on a demo, quadratic on a real pipeline.
		self.assertEqual(
			self.source.count("_parse_intake("),
			1,
			"_parse_intake must be called exactly once, per deal -- not per field read",
		)
		self.assertIsNotNone(
			re.search(r"intake = _parse_intake\(.*?\) if has_intake else \{\}", self.source),
			"the per-deal parse must stay guarded by has_intake, or sites without "
			"the column would parse a missing key on every row",
		)

	def test_the_two_approval_counters_partition_one_queue(self):
		# The cards state their own rules: "Awaiting my approval / decision is
		# yours" and "Waiting others / you requested, someone else answers".
		# Together they cover the queue exactly once. The old expression tested
		# an `assigned_to` key that Stabler Approval Request does not have, then
		# OR'd in `oversight` -- which swept a director's OWN requests into
		# "yours to decide" (they cannot approve those) and left waiting_others
		# structurally 0, because nothing can fall outside a set that already
		# holds everything.
		self.assertNotIn(
			'a.get("assigned_to")',
			self.source,
			"an approval request has no assigned_to; testing it is always False",
		)
		decisions = re.search(r"decisions = \[(.*?)\]", self.source, re.S)
		self.assertIsNotNone(decisions, "the decisions filter is gone")
		self.assertNotIn(
			"oversight",
			decisions.group(1),
			"oversight must not widen 'mine to decide' -- it swallows my own requests",
		)
		self.assertIn("not _mine_to_raise(a)", decisions.group(1))
		waiting = re.search(r"waiting_others = \[(.*?)\]", self.source, re.S)
		self.assertIsNotNone(waiting, "the waiting_others filter is gone")
		self.assertIn("_mine_to_raise(a)", waiting.group(1))
		self.assertNotIn(
			"a not in decisions",
			waiting.group(1),
			"deriving one card from the other is what made it always 0",
		)

	def test_mine_to_raise_reads_the_flag_list_pending_actually_sets(self):
		# list_pending marks every row with self_made; requested_by is the raw
		# field behind it. Reading only one of the two would break the moment a
		# caller hands the desk rows from somewhere else.
		helper = re.search(r"def _mine_to_raise\(a: dict\) -> bool:\n(.*?)\n\n", self.source, re.S)
		self.assertIsNotNone(helper, "_mine_to_raise is gone")
		self.assertIn("self_made", helper.group(1))
		self.assertIn("requested_by", helper.group(1))

	def test_the_payload_states_the_calendar_day_it_reasoned_with(self):
		# D18. The desk has two clocks and one word for them. Every severity, every
		# counter and the calendar window are derived here from frappe.utils.today()
		# in the SITE's timezone; the client re-filtered the identical predicate
		# with the browser's local date, because the server never said what its own
		# date was. Same predicate, different clock: between 00:00 and 05:00 in
		# Tashkent (UTC+5) against a UTC host the two disagree, the Today chip and
		# the list it filters to show different numbers, and each half is internally
		# consistent. `today` is the fact the client was missing.
		#
		# assertTrue over assertRegex: a failure of assertRegex prints all 370 lines
		# of tender_desk.py, which nobody reads.
		self.assertTrue(
			re.search(r'^\t\t"today": today_str,$', self.source, re.M),
			'the payload must carry "today": today_str',
		)

	def test_the_stated_day_is_the_one_the_counters_were_built_with(self):
		# WHAT WOULD MAKE THIS FAIL: stamping a second, freshly-read date onto the
		# payload — `"today": today()`. A request that straddles midnight would then
		# ship counters computed for one day labelled with the next, which is worse
		# than the seam it replaced: the client would trust it and have no way to
		# see the mismatch. One read, one variable, everything downstream from it.
		self.assertEqual(
			len(re.findall(r"^\ttoday_str = today\(\)$", self.source, re.M)),
			1,
			"today() must be read exactly once, into today_str",
		)
		self.assertNotIn('"today": today()', self.source)

	def test_the_calendar_partition_is_delegated_to_the_frappe_free_engine(self):
		# D13. The seven-day window used to be built inline here, which meant the
		# one property that matters -- that no dated plan row disappears between the
		# regions -- could only be pattern-matched, never executed: this module
		# imports frappe, so no frappe-free test can call it. The partition is pure
		# date arithmetic over the plan, so it moved to _desk_rules, where
		# test_desk_rules.py runs it against build_plan's own output.
		self.assertTrue(
			re.search(
				r"^\tcalendar = _desk_rules\.build_calendar\(plan_items, today_str, days_cnt\)$",
				self.source,
				re.M,
			),
			"the calendar must be built by _desk_rules.build_calendar(plan_items, today_str, days_cnt)",
		)

	def test_the_payload_carries_the_past_due_bucket(self):
		# WHAT WOULD MAKE THIS FAIL: computing the bucket and not sending it. The
		# seven cells would look identical to the day the overdue row was invisible,
		# and the engine's test would still be green -- the exact shape of a fix
		# that is real in the code and absent on the screen.
		self.assertTrue(
			re.search(r'^\t\t"calendar_past": calendar\["past"\],$', self.source, re.M),
			'the payload must carry "calendar_past"',
		)

	def test_a_failed_approval_read_is_not_swallowed_into_an_empty_queue(self):
		# D14, and the measurement that made this row real. The desk claimed "All
		# items in this view are up to date" -- a statement about the WORLD -- and
		# one of its inputs was:
		#
		#     except Exception:
		#         all_pending_approvals = []
		#
		# list_pending() throws frappe.PermissionError for anyone who is not an
		# approver (approvals.py:119-121), which on a real site is most of the
		# desk's readers. So the two approval counters read 0, the Decision box read
		# "No pending decisions" and the plan read "up to date" -- four confident
		# statements produced by a swallowed exception, indistinguishable from a
		# genuinely quiet queue.
		#
		# Three outcomes, three names: read, not_yours (the queue exists and is not
		# mine), unreadable (nobody knows). The first two are answers; only the third
		# is a gap.
		# assertTrue, not assertNotIn: a failing assertNotIn against this module
		# prints all 400 lines of it, which nobody reads.
		self.assertTrue(
			"\texcept Exception:\n\t\tall_pending_approvals = []\n\n" not in self.source,
			"a bare except that empties the queue makes a failure look like an answer",
		)
		block = self._approval_block()
		for state in ("read", "not_yours", "unreadable"):
			with self.subTest(state=state):
				self.assertTrue(f'approvals_state = "{state}"' in block, f"the {state} outcome is gone")
		# Not being an approver is a SCOPE ANSWER, not a computation failure. This
		# used to be pinned as `except frappe.PermissionError:` -- catching the
		# answer out of the failure path, which review showed was reading one
		# exception type as one cause. What the row actually requires is that the
		# answer is reached WITHOUT a failure, so that is what is pinned: the state
		# is set outside the try, from a role check.
		self.assertLess(
			block.index('approvals_state = "not_yours"'),
			block.index("try:"),
			"not being an approver is being discovered by failing again",
		)

	def test_the_rows_the_engine_could_not_date_reach_the_payload(self):
		# WHAT WOULD MAKE THIS FAIL: going back to reading only ["items"].
		# build_plan already counts every row it had to drop because a date would
		# not parse -- and the caller discarded that number, so a lot with a
		# malformed bid deadline vanished from the plan and the panel then asserted
		# the view was up to date. The count existed; nothing carried it.
		self.assertTrue(
			re.search(r'^\t\t"skipped": plan_res\["skipped"\],$', self.source, re.M),
			'the payload must carry "skipped": plan_res["skipped"]',
		)

	def test_the_payload_says_whether_team_load_is_the_readers_panel(self):
		# WHAT WOULD MAKE THIS FAIL: shipping team_load without saying who it is
		# for. The list is built only under `if oversight:`, so a sourcing user and
		# a director of a company with no lots receive the SAME empty list. Only
		# the server holds the roles; the client sees the consequence, and the
		# consequence is ambiguous. Without this flag the panel can do nothing but
		# guess, and the guess it made was to render nothing at all -- which reads
		# as "your colleagues are idle" to the one reader who is not entitled to
		# know either way.
		self.assertTrue(
			re.search(r'^\t\t"oversight": oversight,$', self.source, re.M),
			'the payload must carry "oversight": oversight',
		)

	def test_a_team_member_with_nothing_open_still_gets_a_row(self):
		# WHAT WOULD MAKE THIS FAIL: moving the users_map insert under the
		# open-lots guard. It is what makes the panel's empty state sayable: the
		# map takes a row for EVERY deal owner and only then counts the open ones,
		# so an empty list means the company has no lots at all -- not that nobody
		# is busy. Move the insert and the empty state starts claiming an idle team
		# on a company whose lots are simply all won, and the two sentences the
		# panel now distinguishes collapse back into one.
		body = self.source[self.source.index("\tteam_load = []") :]
		body = body[: body.index("\n\tcurr = ")]
		insert = body.index("users_map[owner] = {")
		guard = body.index("if owner not in users_map:")
		self.assertLess(guard, insert, "the row insert must be guarded by membership only")
		self.assertTrue(
			body.index('if result not in ("won", "lost", "cancelled"):') > insert,
			"the open-lots count must come after the row exists, never gate it",
		)

	def _approval_block(self) -> str:
		"""The approvals cohort as CODE -- comment lines dropped.

		Sliced rather than asserted against `self.source`: the module is 20 KB and
		an assertion that fails against the whole of it prints the whole of it.

		Comment-free because the section documents the construct it replaced -- the
		note explaining why a PermissionError must no longer be read as "not an
		approver" contains the words `except frappe.PermissionError`, and an
		assertion that scanned prose would be tripped by the explanation of the very
		thing it checks is gone. Same lesson as _code_only() in
		test_operations_desk_source.py.
		"""
		anchor = "\t# 7. Approvals Cohort"
		self.assertIn(anchor, self.source, "the approvals section moved")
		block = self.source[self.source.index(anchor) :]
		block = block[: block.index("\n\t# Map facts")]
		return "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))

	def test_not_being_an_approver_is_determined_not_inferred(self):
		# WHAT WOULD MAKE THIS FAIL: going back to `except frappe.PermissionError ->
		# not_yours`. That read one exception TYPE as one cause, and the type has at
		# least two: list_pending raises it for a non-approver (approvals.py:119-121)
		# AND for an approver whose role lacks read permission on Stabler Approval
		# Request. The second is a genuine gap and it was being answered with "you
		# are not an approver" -- after which `not_yours` is suppressed from the gap
		# list by design (it is an answer, not a gap), so the plan went on saying
		# everything was up to date over a queue it could not read.
		block = self._approval_block()
		self.assertTrue("is_approver(" in block, "the desk infers the approver instead of determining it")
		self.assertTrue(
			"except frappe.PermissionError" not in block,
			"a PermissionError is being read as 'not an approver' again",
		)
		self.assertTrue('approvals_state = "unreadable"' in block, "a failed read no longer reports a gap")
		self.assertTrue(
			'approvals_state = "not_yours"' in block, "the answer state disappeared with the guess"
		)

	def test_the_queue_is_not_even_asked_for_when_it_is_not_yours(self):
		# WHAT WOULD MAKE THIS FAIL: calling list_pending first and classifying
		# after. Most of this desk's readers are not approvers, so that is one
		# guaranteed-to-throw query per desk load, per reader -- and it only ever
		# produced the answer the role check already held.
		block = self._approval_block()
		self.assertLess(
			block.index('approvals_state = "not_yours"'),
			block.index("list_pending("),
			"the refusal is still discovered by making the call",
		)

	def test_no_sql_aggregation_functions_in_select(self):
		lines = self.source.splitlines()
		for idx, line in enumerate(lines, 1):
			if "frappe.db.sql" in line or "SELECT" in line.upper():
				lower_line = line.lower()
				if "select" in lower_line:
					self.assertNotIn(
						"count(", lower_line, f"Line {idx}: SQL count() in string SELECT is forbidden"
					)
					self.assertNotIn(
						"sum(", lower_line, f"Line {idx}: SQL sum() in string SELECT is forbidden"
					)

	def test_no_queries_in_loops(self):
		lines = self.source.splitlines()
		in_loop = False
		loop_indent = 0
		for idx, line in enumerate(lines, 1):
			stripped = line.strip()
			indent = len(line) - len(line.lstrip())
			if stripped.startswith(("for ", "while ")) and not stripped.endswith(":"):
				pass
			elif stripped.startswith(("for ", "while ")) and stripped.endswith(":"):
				in_loop = True
				loop_indent = indent
			elif in_loop and indent <= loop_indent and stripped:
				in_loop = False

			if in_loop:
				self.assertNotIn("frappe.get_all(", stripped, f"Line {idx}: DB query in loop")
				self.assertNotIn("frappe.db.sql(", stripped, f"Line {idx}: DB query in loop")
				self.assertNotIn("frappe.get_doc(", stripped, f"Line {idx}: DB query in loop")


if __name__ == "__main__":
	unittest.main()
