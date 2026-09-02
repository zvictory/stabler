import unittest

from stabler.api._desk_rules import SEVERITY, build_calendar, build_plan


class TestDeskRules(unittest.TestCase):
	def test_empty_facts(self):
		res = build_plan({}, "2026-07-30")
		self.assertEqual(res["items"], [])
		self.assertEqual(res["skipped"], 0)

	def test_bid_due_overdue_and_today(self):
		facts = {
			"lots": [
				{
					"deal": "DEAL-001",
					"label": "Tender Lot A",
					"stage": "sourcing",
					"bid_deadline": "2026-07-28",  # 2 days past
					"sq_count": 5,
					"assigned_to": "user1@example.com",
				},
				{
					"deal": "DEAL-002",
					"label": "Tender Lot B",
					"stage": "sourcing",
					"bid_deadline": "2026-07-30",  # today
					"sq_count": 5,
					"assigned_to": "user2@example.com",
				},
			]
		}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 2)

		# Sorted by severity (overdue -> today)
		self.assertEqual(items[0]["kind"], "bid_due")
		self.assertEqual(items[0]["severity"], "overdue")
		self.assertEqual(items[0]["route"], "/tender/crm?deal=DEAL-001")
		self.assertIn("past by 2 days", items[0]["why"])

		self.assertEqual(items[1]["kind"], "bid_due")
		self.assertEqual(items[1]["severity"], "today")
		self.assertIn("deadline today", items[1]["why"])

	def test_policy_gap_rule(self):
		facts = {
			"lots": [
				{
					"deal": "DEAL-003",
					"label": "Tender Lot C",
					"stage": "sourcing",
					"bid_deadline": "2026-08-05",  # far future
					"sq_count": 3,
					"assigned_to": "user1@example.com",
				}
			]
		}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["kind"], "policy_gap")
		self.assertEqual(items[0]["severity"], "today")
		self.assertIn("3/5 quotes collected", items[0]["why"])

	def test_multiple_rules_on_same_lot(self):
		# A lot can trigger both bid_due and policy_gap
		facts = {
			"lots": [
				{
					"deal": "DEAL-004",
					"label": "Tender Lot D",
					"stage": "sourcing",
					"bid_deadline": "2026-07-29",
					"sq_count": 2,
					"assigned_to": "user1@example.com",
				}
			]
		}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 2)
		kinds = [i["kind"] for i in items]
		self.assertIn("bid_due", kinds)
		self.assertIn("policy_gap", kinds)

	def test_orphan_lot_rule(self):
		facts = {"orphan_lots": [{"name": "LOT-ORPHAN-1", "organization": "Acme Corp"}]}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["kind"], "no_parent")
		self.assertEqual(items[0]["severity"], "info")

	def test_won_no_po_rule(self):
		facts = {
			"won_without_po": [
				{"name": "DEAL-WON-1", "label": "Won Meat Lot", "assigned_to": "buyer1@example.com"}
			]
		}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["kind"], "won_no_po")
		self.assertEqual(items[0]["severity"], "today")

	def test_po_late_rule(self):
		facts = {
			"po_late": [
				{
					"po": "PUR-ORD-2026-00012",
					"supplier": "Fair Exports",
					"schedule_date": "2026-07-25",
					"per_received": 40.0,
				}
			]
		}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["kind"], "po_late")
		self.assertEqual(items[0]["severity"], "overdue")
		self.assertEqual(items[0]["route"], "/purchasing/orders/PUR-ORD-2026-00012")

	def test_invoice_due_rule(self):
		facts = {
			"unpaid": [
				{
					"doctype": "Purchase Invoice",
					"name": "ACC-PINV-2026-00045",
					"due_date": "2026-07-28",
					"outstanding": 5000.0,
				}
			]
		}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["kind"], "invoice_due")
		self.assertEqual(items[0]["severity"], "overdue")
		self.assertEqual(items[0]["route"], "/purchasing/invoices/ACC-PINV-2026-00045")

	def test_approval_pending_rule(self):
		facts = {
			"approvals": [
				{
					"name": "APP-001",
					"reference_doctype": "Purchase Order",
					"reference_name": "PUR-ORD-2026-00099",
					"requested_by": "john@example.com",
				}
			]
		}
		res = build_plan(facts, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["kind"], "approval_pending")
		self.assertEqual(items[0]["severity"], "today")

	def test_approvals_envelope_is_not_a_row_list(self):
		# approvals.list_pending returns the ENVELOPE {"requests": [...], "total": n,
		# "can_approve": bool}. Handing that envelope straight to build_plan (as
		# tender_desk.py did until 2026-08-01) iterates its three KEYS, so the desk
		# invented three "Approval required: Document <key>" rows, counted them as
		# due-today work, and dropped every real approval. This test pins the shape
		# contract: only the rows under "requests" are approvals, and a key name may
		# never surface as a reference. Caller-side enforcement lives in
		# test_tender_desk_api.test_list_pending_unwraps_requests.
		envelope = {
			"requests": [
				{
					"name": "APP-002",
					"reference_doctype": "Purchase Order",
					"reference_name": "PUR-ORD-2026-00100",
					"requested_by": "john@example.com",
				}
			],
			"total": 1,
			"can_approve": True,
		}
		res = build_plan({"approvals": envelope["requests"]}, "2026-07-30")
		items = res["items"]
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["reference_name"], "PUR-ORD-2026-00100")

		phantom = build_plan({"approvals": envelope}, "2026-07-30")["items"]
		phantom_refs = {i["reference_name"] for i in phantom}
		self.assertEqual(
			phantom_refs,
			set(envelope.keys()),
			"iterating the envelope yields its keys -- callers must unwrap ['requests']",
		)

	def test_malformed_date_skipped(self):
		facts = {
			"lots": [{"deal": "DEAL-BAD-DATE", "stage": "sourcing", "bid_deadline": "invalid-date-string"}]
		}
		res = build_plan(facts, "2026-07-30")
		self.assertEqual(res["skipped"], 1)


class TestCalendarPartition(unittest.TestCase):
	"""D13. A day cell counts `due == that day` and the window began at today, so
	nothing overdue -- whose due date is in the past by definition -- could ever
	appear in it. On seed data the desk's loudest row, a bid deadline that passed
	yesterday, was absent from all seven cells while the Overdue counter above them
	read 1: two regions of one screen, describing the same four items, unable to
	agree by construction.

	The input below is not a fixture of the calendar's expected output -- it is
	build_plan's own output from seed-shaped lots, so the plan and the calendar
	cannot drift apart in this file."""

	TODAY = "2026-09-02"

	def _seed_plan(self):
		"""The four rows seed_tender_demo produces: overdue, today, today, soon."""
		return build_plan(
			{
				"lots": [
					# UTY-2026-4305: deadline passed yesterday -> overdue
					{
						"deal": "d1",
						"label": "LOT-4305",
						"stage": "go",
						"bid_deadline": "2026-09-01",
						"sq_count": 1,
					},
					# UTY-2026-4308: deadline today
					{
						"deal": "d2",
						"label": "LOT-4308",
						"stage": "sourcing",
						"bid_deadline": "2026-09-02",
						"sq_count": 5,
					},
					# UTY-2026-4309: 3/5 quotes, deadline 25 days out -> policy gap
					{
						"deal": "d3",
						"label": "LOT-4309",
						"stage": "sourcing",
						"bid_deadline": "2026-09-27",
						"sq_count": 3,
					},
					# UTY-2026-4310: deadline in 2 days
					{
						"deal": "d4",
						"label": "LOT-4310",
						"stage": "priced",
						"bid_deadline": "2026-09-04",
						"sq_count": 6,
					},
				]
			},
			self.TODAY,
		)["items"]

	def test_the_row_the_desk_is_loudest_about_is_visible_in_the_calendar(self):
		# WHAT WOULD MAKE THIS FAIL: going back to seven cells and nothing else.
		# The Overdue chip reads 1 and the seven cells summed to 2 of the 4 items,
		# with the one that actually needed doing today missing from both regions
		# that claim to show the week.
		cal = build_calendar(self._seed_plan(), self.TODAY, 7)
		self.assertEqual(cal["past"]["count"], 1)
		self.assertIn("LOT-4305", cal["past"]["items"][0]["title"])

	def test_the_seven_days_still_count_what_they_counted(self):
		# WHAT WOULD MAKE THIS FAIL: solving the invisibility by widening a day's
		# predicate (`due <= that day`), which would smear every overdue item onto
		# every remaining cell. The bucket exists so the DAYS can stay exact.
		cal = build_calendar(self._seed_plan(), self.TODAY, 7)
		self.assertEqual([d["count"] for d in cal["days"]], [1, 0, 1, 0, 0, 0, 0])
		self.assertEqual(cal["days"][0]["date"], "2026-09-02")
		self.assertEqual(cal["days"][6]["date"], "2026-09-08")

	def test_nothing_is_counted_in_both_the_bucket_and_a_day(self):
		# WHAT WOULD MAKE THIS FAIL: `due <= today` for the bucket. Today's bid
		# deadline would then appear in the past pile AND in the today cell, so the
		# region's own numbers would add up to more work than the plan holds --
		# which is the same class of defect as hiding a row, with the opposite sign.
		cal = build_calendar(self._seed_plan(), self.TODAY, 7)
		in_days = sum(d["count"] for d in cal["days"])
		self.assertEqual(cal["past"]["count"] + in_days, 3, "3 of the 4 rows fall inside the window")

	def test_the_bucket_holds_an_item_older_than_any_lead_in_would_reach(self):
		# WHAT WOULD MAKE THIS FAIL: "fixing" S1 by starting the window a few days
		# earlier. Overdue is unbounded -- an invoice can be four months past due --
		# so every N-day lead-in still hides whatever is older than N, and it hides
		# it in a region that now looks like it covers the past. A bucket cannot.
		ancient = [{"kind": "invoice_due", "title": "Invoice payment due: PI-1", "due": "2025-05-04"}]
		cal = build_calendar(ancient, self.TODAY, 7)
		self.assertEqual(cal["past"]["count"], 1)

	def test_an_item_with_no_due_date_is_not_invented_into_the_past(self):
		# WHAT WOULD MAKE THIS FAIL: treating a missing due date as "" and letting
		# "" < today sort it into the pile. An item nobody dated is not late; the
		# calendar has nothing to say about it and must say nothing.
		cal = build_calendar([{"kind": "no_parent", "title": "Orphan lot", "due": None}], self.TODAY, 7)
		self.assertEqual(cal["past"]["count"], 0)
		self.assertEqual(sum(d["count"] for d in cal["days"]), 0)

	def test_every_dated_row_is_in_the_bucket_a_day_or_beyond_the_window(self):
		# WHAT WOULD MAKE THIS FAIL: any future partition that loses a row silently.
		# This is the property S1 broke -- not "the overdue one is missing", but
		# "the region's accounting does not add up to the plan" -- so it is asserted
		# as a partition rather than as three example counts.
		plan = self._seed_plan()
		cal = build_calendar(plan, self.TODAY, 7)
		window = {d["date"] for d in cal["days"]}
		beyond = [i for i in plan if i["due"] and i["due"] > max(window)]
		self.assertEqual(
			cal["past"]["count"] + sum(d["count"] for d in cal["days"]) + len(beyond),
			len([i for i in plan if i.get("due")]),
		)


if __name__ == "__main__":
	unittest.main()
