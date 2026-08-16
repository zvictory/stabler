"""Safety and honesty contract for the Vehicle Finance demo seeder.

Two halves, and the second is the one that earns its keep.

SAFETY — the script writes to a live site. Two mistakes there are unrecoverable:
deleting a record that was not ours, and leaving half a portfolio behind.

HONESTY — the harder failure, and a silent one: seeding data that is *pretty*.
If every row is comfortably in the future and nothing is late, the queues all
render and none of them is proven. The seeder's whole purpose is to produce the
DISTINCTIONS the Operations screen claims to draw, so this file checks the date
arithmetic against the real `work_policy.row_views` — no database, no bench.
A seeder whose offsets quietly drift into the wrong bucket would otherwise look
exactly like a working one.

Frappe-free by construction: the seeder itself imports frappe, so it is read as
source text and parsed, never imported.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from stabler.api.vehicle_finance.work_policy import (
	DEFAULT_ESCALATION_THRESHOLD_DAYS,
	UPCOMING_WINDOW_DAYS,
	VIEW_CRITICAL_OVERDUE,
	VIEW_DUE_TODAY,
	VIEW_MONITORING,
	VIEW_NEXT_7_DAYS,
	VIEW_OVERDUE,
	row_views,
)

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "maintenance/seed_vehicle_finance_demo.py"
SEED = SEED_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SEED)


def _fn(name: str) -> str:
	"""The source of one top-level function, so an assertion about `unseed` cannot
	be satisfied by a line that happens to live in `seed`."""
	node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
	return ast.get_source_segment(SEED, node) or ""


_POLICY_NAMES = {
	"DEFAULT_ESCALATION_THRESHOLD_DAYS": DEFAULT_ESCALATION_THRESHOLD_DAYS,
	"UPCOMING_WINDOW_DAYS": UPCOMING_WINDOW_DAYS,
}


def _arith(node: ast.AST) -> int:
	"""Evaluate integer arithmetic over the policy constants — no eval().

	Deliberately understands four node types and nothing else, so a constant that
	grows into anything cleverer fails loudly here instead of being executed.
	"""
	if isinstance(node, ast.Constant) and isinstance(node.value, int):
		return node.value
	if isinstance(node, ast.Name):
		return _POLICY_NAMES[node.id]
	if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
		return -_arith(node.operand)
	if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
		left, right = _arith(node.left), _arith(node.right)
		return left + right if isinstance(node.op, ast.Add) else left - right
	raise AssertionError(f"offset constant uses an unsupported expression: {ast.dump(node)}")


def _const(name: str) -> int:
	"""A module-level offset constant, resolved against the real policy numbers.

	Reading them textually would pass whatever the seeder wrote; binding the
	actual `work_policy` values means the test fails if the policy moves and the
	seeder does not follow it.
	"""
	node = next(
		n
		for n in TREE.body
		if isinstance(n, ast.Assign) and any(t.id == name for t in n.targets if isinstance(t, ast.Name))
	)
	return _arith(node.value)


TODAY = 0  # offsets are expressed in days from today, so "today" is the origin


def _views_for(offset: int, **kw) -> frozenset[str]:
	"""row_views for a row `offset` days from today, using real dates."""
	import datetime

	today = datetime.date(2026, 6, 15)
	return row_views(today + datetime.timedelta(days=offset), today, **kw)


class SeederSafetyContract(unittest.TestCase):
	def test_the_marker_is_a_single_constant(self):
		"""Two spellings of the marker means unseed misses one of them."""
		self.assertIn('DEMO_SUFFIX = " [DEMO]"', SEED)
		# The literal must not be retyped anywhere else.
		literal_uses = len(re.findall(r'"\s*\[DEMO\]\s*"', SEED))
		self.assertEqual(literal_uses, 1, "the [DEMO] literal appears more than once")

	def test_unseed_filters_on_the_marker_for_every_doctype_it_deletes(self):
		"""An unfiltered delete on a live site is unrecoverable data loss."""
		unseed = _fn("unseed")
		# Every get_all that feeds a delete is scoped either by the marker itself
		# or by the agreements already selected by the marker.
		self.assertIn('"remarks": ["like", f"%{DEMO_SUFFIX}%"]', unseed)
		self.assertIn('"condition_notes": ["like", f"%{DEMO_SUFFIX}%"]', unseed)
		self.assertIn('{"agreement": ["in", agreements]}', unseed)

	def test_unseed_never_deletes_a_shared_master(self):
		"""Accounts, items, the company and the parties may predate this script."""
		unseed = _fn("unseed")
		for doctype in (
			"Account",
			"Item",
			"Company",
			"Customer",
			"Supplier",
			"Serial No",
			"Currency Exchange",
			"Stabler Settings",
			"Vehicle Finance Settings",
		):
			self.assertNotIn(f'delete_doc("{doctype}"', unseed, f"unseed must not delete {doctype}")

	def test_the_raw_delete_is_scoped_to_the_marked_agreements(self):
		"""Follow-up logs are append-only — on_trash refuses to delete them — so the
		teardown drops them with SQL. Without the WHERE this single statement would
		erase every contact record on the site, demo or not."""
		unseed = _fn("unseed")
		self.assertRegex(
			unseed,
			r"DELETE FROM `tabVehicle Finance Follow-up Log` WHERE agreement IN %\(agreements\)s",
		)
		# And it must be unreachable when nothing carried the marker.
		self.assertIn("if agreements:", unseed)

	def test_unseed_removes_children_before_parents(self):
		"""Logs and versions are reachable only through the agreement; delete the
		agreement first and they are orphaned on the site forever."""
		unseed = _fn("unseed")
		logs = unseed.index("tabVehicle Finance Follow-up Log")
		versions = unseed.index('_cancel_then_delete("Vehicle Finance Schedule Version"')
		parent = unseed.index('_cancel_then_delete("Vehicle Agreement"')
		self.assertLess(logs, parent)
		self.assertLess(versions, parent)

	def test_the_circular_link_is_broken_before_anything_is_cancelled(self):
		"""The agreement points at its active version and the version points back.
		Frappe refuses to cancel either while that stands, so the link is cleared
		from the agreement side FIRST — before the version is touched."""
		unseed = _fn("unseed")
		clear = unseed.index('"active_schedule_version", None')
		cancel = unseed.index('_cancel_then_delete("Vehicle Finance Schedule Version"')
		self.assertLess(clear, cancel)

	def test_a_submitted_document_is_cancelled_before_it_is_deleted(self):
		"""force=True skips the link check, not the docstatus check."""
		helper = _fn("_cancel_then_delete")
		self.assertIn("doc.docstatus == 1", helper)
		self.assertLess(helper.index("doc.cancel()"), helper.index("frappe.delete_doc"))

	def test_the_teardown_reports_a_number_it_actually_measured(self):
		"""frappe.db.sql returns [] for a DELETE. Reporting that as the count would
		be a teardown that lies about what it removed."""
		unseed = _fn("unseed")
		counted = unseed.index('removed["Vehicle Finance Follow-up Log"] = frappe.db.count')
		deleted = unseed.index("DELETE FROM `tabVehicle Finance Follow-up Log`")
		self.assertLess(counted, deleted)

	def test_seeding_twice_is_guarded(self):
		seed = _fn("seed")
		self.assertIn("already present", seed)
		self.assertIn('frappe.db.exists("Vehicle Agreement"', seed)

	def test_a_missing_prerequisite_raises_instead_of_half_seeding(self):
		self.assertIn("def _require(", SEED)
		self.assertIn("frappe.throw", _fn("_require"))
		self.assertIn('_require(frappe.db.exists("Company"', _fn("_ensure_prerequisites"))

	def test_it_never_fabricates_an_allocation(self):
		"""Vehicle Finance Payment Application.payment_entry is reqd=1 — the schema
		refuses money that did not move. Writing one anyway would make the screens
		look complete while proving nothing, which is the one thing this file must
		not do."""
		self.assertNotIn("Vehicle Finance Payment Application", SEED.split('"""', 2)[2])


class SeederHonestyContract(unittest.TestCase):
	"""The offsets must land in the buckets the module docstring claims."""

	def test_the_late_rows_cross_the_escalation_threshold_in_both_directions(self):
		past = _const("LATE_PAST_THRESHOLD")
		inside = _const("LATE_INSIDE_THRESHOLD")
		self.assertIn(VIEW_CRITICAL_OVERDUE, _views_for(past))
		self.assertIn(VIEW_OVERDUE, _views_for(past))
		# Late, but not late enough to escalate. Without this row the threshold is
		# never shown to be a threshold — everything late would look critical.
		self.assertIn(VIEW_OVERDUE, _views_for(inside))
		self.assertNotIn(VIEW_CRITICAL_OVERDUE, _views_for(inside))

	def test_the_upcoming_row_is_inside_the_window_and_the_monitoring_row_is_not(self):
		within = _const("WITHIN_UPCOMING")
		beyond = _const("BEYOND_UPCOMING")
		self.assertIn(VIEW_NEXT_7_DAYS, _views_for(within))
		# The trap this test exists for: row_views only adds `monitoring` when NO
		# other view fired. A monitoring row dated inside the upcoming window
		# silently becomes a next_7_days row and the monitoring queue is never
		# exercised — while the seeder still reports success.
		self.assertNotIn(VIEW_NEXT_7_DAYS, _views_for(beyond))
		self.assertEqual(frozenset(), _views_for(beyond))
		self.assertEqual(frozenset({VIEW_MONITORING}), _views_for(beyond, has_open_followup=True))

	def test_due_today_is_seeded_at_the_origin(self):
		self.assertIn(VIEW_DUE_TODAY, _views_for(0))
		self.assertIn("offsets=[0, 40, 70]", SEED)

	def test_a_broken_promise_escalates_a_row_that_is_not_late(self):
		"""Agreement 5's row is 20 days out. If it were also late the promise
		branch would be masked by the date branch and never proven."""
		self.assertIn("offsets=[20, 50, 80]", SEED)
		self.assertEqual(frozenset(), _views_for(20))
		self.assertIn(VIEW_CRITICAL_OVERDUE, _views_for(20, has_broken_promise=True))

	def test_the_promise_is_dated_in_the_past(self):
		"""A promise whose date has not passed is not broken."""
		promise = _fn("_make_broken_promise")
		self.assertIn("add_days(today(), -days_ago)", promise)

	def test_both_directions_and_both_currencies_are_present(self):
		seed = _fn("seed")
		self.assertIn('direction="Acquisition"', seed)
		self.assertIn('direction="Disposition"', seed)
		self.assertIn('currency="USD"', seed)
		self.assertIn('currency="UZS"', seed)

	def test_agreements_are_left_collectible(self):
		"""The read side filters on agreement_status in ("Active", "Restructured").
		The bench fixtures stop at "Approved", which is right for what they assert
		and would produce a silently empty queue here."""
		self.assertIn('agreement.agreement_status = "Active"', _fn("_make_agreement"))

	def test_row_zero_exists_and_is_zero(self):
		"""validate_rows requires the schedule to open with a down-payment row and
		allows it to be zero. Zero is deliberate: an unpaid non-zero row 0 would
		put an overdue item on every agreement and flatten the whole matrix."""
		make = _fn("_make_agreement")
		self.assertIn('"sequence": 0', make)
		self.assertIn('"row_type": "Down Payment"', make)
		self.assertIn("agreement.down_payment = 0", make)

	def test_the_known_gap_is_written_down_rather_than_hidden(self):
		"""If the down-payment FIFO branch is not exercised, the file has to say so."""
		docstring = ast.get_docstring(TREE) or ""
		self.assertIn("KNOWN GAP", docstring)
		self.assertIn("NOT exercised", docstring)


if __name__ == "__main__":
	unittest.main()
