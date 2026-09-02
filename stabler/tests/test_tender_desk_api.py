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
