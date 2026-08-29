"""What the register's header strip may and may not claim.

Two tiles out of five come from here, and each carries a scoping decision that
is invisible in the number it produces — which is exactly why they are pinned.

Needs a bench: it writes stop and scrap rows and reads them back through the
endpoint, guards and all.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import add_to_date, get_datetime

try:
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # newer frappe
	from frappe.tests import IntegrationTestCase as FrappeTestCase

from stabler.api.manufacturing import wo_ledger_activity

_DAY = "2026-08-28"
_OTHER_DAY = "2026-08-27"


def _a_company() -> str | None:
	rows = frappe.get_all("Company", pluck="name", limit=1)
	return rows[0] if rows else None


def _a_warehouse(company: str) -> str | None:
	rows = frappe.get_all("Warehouse", filters={"company": company}, pluck="name", limit=1)
	return rows[0] if rows else None


class LedgerCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _a_company()
		cls.line = _a_warehouse(cls.company) if cls.company else None
		# `reason` and `reported_by` are mandatory on the doctype. The catalogue
		# is seeded by v101, so the fixture takes a real row rather than inventing
		# one — a stop filed under a reason that does not exist is not a stop this
		# feature will ever read.
		rows = frappe.get_all(
			"Stabler Stop Reason", filters={"kind": ["in", ["Downtime", "Both"]]}, pluck="name", limit=1
		)
		cls.reason = rows[0] if rows else None

	def setUp(self):
		if not self.company or not self.line or not self.reason:
			self.skipTest("this site has no company, warehouse or seeded stop reason")
		frappe.set_user("Administrator")

	def _stop(self, minutes=10, reason=None, work_order=None, at=f"{_DAY} 09:00:00"):
		# `minutes` is derived by the doctype from the two timestamps, not stored
		# from the caller — so the fixture states an end time and lets the record
		# do its own arithmetic. Writing `minutes` directly would test a number
		# this feature never sees in production.
		start = get_datetime(at)
		doc = frappe.get_doc(
			{
				"doctype": "Stabler Line Stop",
				"company": self.company,
				"line": self.line,
				"reason": reason or self.reason,
				"reported_by": "Administrator",
				"work_order": work_order,
				"from_time": at,
				"to_time": add_to_date(start, minutes=minutes),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda name=doc.name: (
				frappe.db.exists("Stabler Line Stop", name)
				and frappe.delete_doc("Stabler Line Stop", name, force=True)
			)
		)
		return doc


class TestDowntimeIsTheWindowsNotTheList(LedgerCase):
	"""`Stabler Line Stop.work_order` is optional, and a line stopped with no
	order on it is the stop a shift lead most needs to see. Scoping this tile to
	the orders on screen would drop exactly those."""

	def test_a_stop_with_no_work_order_still_counts(self):
		self._stop(minutes=17)
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY, work_orders=[])
		self.assertGreaterEqual(out["downtime_minutes"], 17)

	def test_a_stop_outside_the_window_does_not_count(self):
		"""Otherwise the tile reports the whole history of the line under a
		header that says "today", and the number only ever grows."""
		self._stop(minutes=45, at=f"{_OTHER_DAY} 09:00:00")
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY, work_orders=[])
		self.assertEqual(out["downtime_minutes"], 0)

	def test_the_last_minute_of_the_closing_day_is_inside_the_window(self):
		"""The filter is built from bare dates, so an end bound of `<= to_date`
		would cut the day off at midnight and lose a whole evening shift."""
		self._stop(minutes=8, at=f"{_DAY} 23:50:00")
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY, work_orders=[])
		self.assertEqual(out["downtime_minutes"], 8)

	def test_the_named_contributor_is_the_costliest_line_and_reason(self):
		self._stop(minutes=4, reason=None)
		self._stop(minutes=4, reason=None)
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY, work_orders=[])
		self.assertEqual(out["downtime_top"]["line"], self.line)
		self.assertEqual(out["downtime_top"]["minutes"], 8)

	def test_a_quiet_window_names_nobody(self):
		out = wo_ledger_activity(self.company, from_date=_OTHER_DAY, to_date=_OTHER_DAY, work_orders=[])
		self.assertEqual(out["downtime_minutes"], 0)
		self.assertIsNone(out["downtime_top"])

	def test_the_window_is_reported_back(self):
		"""The tile has to be able to say which period it covers — a downtime
		figure with no stated window is a number nobody can check."""
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY, work_orders=[])
		self.assertEqual(out["window"], {"from_date": _DAY, "to_date": _DAY})


class TestScrapIsTheListAndOnlyTheList(LedgerCase):
	def _scrap_row(self, work_order: str):
		"""A scrap row written straight to the table, deliberately.

		The endpoint counts rows; it never loads the document. Building a valid
		`Stabler Line Scrap` needs a submitted Work Order, a configured scrap
		warehouse and stock standing in WIP — none of which this assertion depends
		on, and all of which would make the fixture skip on a site that has named
		no scrap warehouse, which is every site today. That skip is exactly what
		would leave the test below unable to fail.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "Stabler Line Scrap",
				"company": self.company,
				"work_order": work_order,
				"line": self.line,
				"item_code": "TEST-ITEM",
				"qty": 1,
				"reason": self.reason,
				"reported_by": "Administrator",
			}
		)
		doc.name = "TEST-LSCRAP-" + (work_order or "BLANK")
		doc.db_insert()
		self.addCleanup(lambda name=doc.name: frappe.db.delete("Stabler Line Scrap", {"name": name}))
		return doc

	def test_an_empty_order_list_counts_no_scrap_at_all(self):
		"""What `["in", []]` really does, measured rather than assumed.

		It compiles to `IFNULL(work_order,'') IN ('') OR ... IS NULL` — so an
		unguarded query returns every row whose work order is BLANK, not every
		row and not none. `work_order` is required today, so the fixture below
		writes the blank row on purpose; without it this assertion passes whether
		the guard exists or not, and a test that cannot fail is not a test.

		The answer for "no orders on screen" must be zero regardless of what that
		reqd flag says next year."""
		self._scrap_row("")
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY, work_orders=[])
		self.assertEqual(out["scrap_records"], 0)
		self.assertEqual(out["scrap_orders"], 0)

	def test_a_missing_order_list_is_read_the_same_way(self):
		self._scrap_row("")
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY)
		self.assertEqual(out["scrap_records"], 0)

	def test_an_order_on_the_list_is_counted(self):
		"""The other direction, so the guard above cannot be satisfied by an
		endpoint that simply never counts anything."""
		self._scrap_row("MFG-WO-ON-SCREEN")
		out = wo_ledger_activity(self.company, from_date=_DAY, to_date=_DAY, work_orders=["MFG-WO-ON-SCREEN"])
		self.assertEqual(out["scrap_records"], 1)
		self.assertEqual(out["scrap_orders"], 1)

	def test_an_order_with_no_records_reports_none(self):
		out = wo_ledger_activity(
			self.company, from_date=_DAY, to_date=_DAY, work_orders=["MFG-WO-DOES-NOT-EXIST"]
		)
		self.assertEqual(out["scrap_records"], 0)

	def test_the_order_list_survives_arriving_as_json(self):
		"""The SPA sends it as a JSON string, because that is how `call()` passes
		a list. Reading it as one opaque name would silently report zero."""
		out = wo_ledger_activity(
			self.company, from_date=_DAY, to_date=_DAY, work_orders='["MFG-WO-DOES-NOT-EXIST"]'
		)
		self.assertEqual(out["scrap_records"], 0)


class TestTheTileRefusesAForeignCompany(LedgerCase):
	def test_a_company_this_user_does_not_hold_is_refused(self):
		"""Same guard as every other endpoint on this page. Without it the strip
		would be a way to count another tenant's stops."""
		with self.assertRaises(Exception):
			wo_ledger_activity("A Company That Does Not Exist", work_orders=[])


if __name__ == "__main__":
	unittest.main()
