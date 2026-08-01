import unittest

from stabler.api._desk_rules import SEVERITY, build_plan


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


if __name__ == "__main__":
	unittest.main()
