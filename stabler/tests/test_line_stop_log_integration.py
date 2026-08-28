"""The stop log against a live database.

`test_downtime_catalogue` proves the arithmetic and the catalogue's shape
without a bench. What it cannot see is the half that only exists once the
doctypes are real: that the seed patch actually planted the list, that the
refusals hold on a `save()` and not merely in a helper the endpoint happens to
call, and that a stop cannot be filed against another company's Work Order.

That last one is the reason this file is not optional. `log_line_stop` takes a
`company` argument and a `work_order` argument, and nothing about the two says
they belong together. A tenant boundary that is only checked in the argument a
caller supplies is not checked at all.

Measured on anjan 2026-08-28, which is why the log exists: 0 Downtime Entry rows
against 3757 Manufacture entries, and ERPNext's own doctype unusable here — all
three of its required fields unmet (0 Workstations; 439 Employees of which 0
carry a `user_id`; a seven-option machine-shop Select).

    cd /path/to/frappe-bench && bench --site <site> run-tests \
        --module stabler.tests.test_line_stop_log_integration
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import add_days, today

try:
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # newer frappe
	from frappe.tests import IntegrationTestCase as FrappeTestCase

from stabler.api._downtime import SEED_REASONS
from stabler.api.manufacturing import list_line_stops, list_stop_reasons, log_line_stop

_STOP = "2026-08-28 09:00:00"
_END = "2026-08-28 09:35:00"


def _a_company() -> str | None:
	rows = frappe.get_all("Company", pluck="name", limit=1)
	return rows[0] if rows else None


def _a_warehouse(company: str) -> str | None:
	rows = frappe.get_all("Warehouse", filters={"company": company}, pluck="name", limit=1)
	return rows[0] if rows else None


class TestTheSeededCatalogueIsOnTheSite(FrappeTestCase):
	"""The patch is idempotent by `db.exists` on the name, which means a bug in
	it fails silently — every row skipped, nothing raised, an empty dropdown."""

	def test_every_seeded_reason_exists_as_a_record(self):
		missing = [r for r, _k in SEED_REASONS if not frappe.db.exists("Stabler Stop Reason", r)]
		self.assertEqual(missing, [], f"patch ekmemiş: {missing}")

	def test_the_escape_hatch_sorts_last(self):
		"""First is where a hurried thumb lands, and an "Other" at the top makes
		the other nineteen decorative."""
		orders = frappe.get_all(
			"Stabler Stop Reason", fields=["reason", "sort_order"], order_by="sort_order desc", limit=1
		)
		self.assertEqual(orders[0]["reason"], "Other")

	def test_the_picker_splits_the_two_questions(self):
		company = _a_company()
		if not company:
			self.skipTest("no Company on this site")
		frappe.set_user("Administrator")
		downtime = {r["reason"] for r in list_stop_reasons(company, "Downtime")}
		loss = {r["reason"] for r in list_stop_reasons(company, "Loss")}
		self.assertIn("Waiting for material", downtime)
		self.assertNotIn("Waiting for material", loss, "duruş sebebi fire listesinde")
		self.assertIn("Off-spec batch", loss)
		self.assertNotIn("Off-spec batch", downtime, "fire sebebi duruş listesinde")
		# "Both" rows answer either question.
		self.assertIn("Other", downtime)
		self.assertIn("Other", loss)

	def test_a_deactivated_reason_leaves_the_picker_but_not_the_table(self):
		"""Switched off rather than deleted, so a record filed years ago still
		names the reason it was filed under."""
		company = _a_company()
		if not company:
			self.skipTest("no Company on this site")
		frappe.set_user("Administrator")
		frappe.db.set_value("Stabler Stop Reason", "Spillage", "is_active", 0)
		self.addCleanup(frappe.db.set_value, "Stabler Stop Reason", "Spillage", "is_active", 1)
		self.assertNotIn("Spillage", {r["reason"] for r in list_stop_reasons(company, "Loss")})
		self.assertTrue(frappe.db.exists("Stabler Stop Reason", "Spillage"))


class TestAStopIsWrittenAndReadBack(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = _a_company()
		cls.line = _a_warehouse(cls.company) if cls.company else None

	def setUp(self):
		if not (self.company and self.line):
			self.skipTest("no Company/Warehouse on this site")
		frappe.set_user("Administrator")

	def _log(self, **kwargs):
		payload = {
			"company": self.company,
			"line": self.line,
			"reason": "Waiting for material",
			"from_time": _STOP,
			"to_time": _END,
		}
		payload.update(kwargs)
		out = log_line_stop(**payload)
		self.addCleanup(frappe.delete_doc, "Stabler Line Stop", out["name"], force=True)
		return out

	def test_the_minutes_are_derived_not_taken(self):
		"""A minutes column somebody can type apart from the stamps is one that
		disagrees with them, silently. Asserted as a read-back because that is
		where a `validate` that never fired would show."""
		out = self._log()
		self.assertEqual(out["minutes"], 35.0)
		self.assertEqual(frappe.db.get_value("Stabler Line Stop", out["name"], "minutes"), 35.0)

	def test_the_reporter_is_the_session_and_not_an_argument(self):
		"""Who saw the line stop is not something a caller gets to claim."""
		out = self._log()
		self.assertEqual(
			frappe.db.get_value("Stabler Line Stop", out["name"], "reported_by"), frappe.session.user
		)

	def test_a_stop_between_orders_is_allowed_to_have_no_order(self):
		"""A line stops between orders as often as during one. Requiring an order
		would either lose those rows or attach them to whichever came next."""
		out = self._log()
		self.assertIsNone(frappe.db.get_value("Stabler Line Stop", out["name"], "work_order"))

	def test_the_stop_comes_back_in_its_window(self):
		day = _STOP[:10]
		out = self._log()
		names = [r["name"] for r in list_line_stops(self.company, day, day)]
		self.assertIn(out["name"], names)

	def test_a_window_that_ends_before_the_stop_excludes_it(self):
		out = self._log()
		day = add_days(_STOP[:10], -1)
		self.assertNotIn(out["name"], [r["name"] for r in list_line_stops(self.company, day, day)])

	def test_the_line_filter_narrows_on_a_column_that_exists(self):
		day = _STOP[:10]
		out = self._log()
		self.assertIn(out["name"], [r["name"] for r in list_line_stops(self.company, day, day, self.line)])
		self.assertNotIn(
			out["name"],
			[r["name"] for r in list_line_stops(self.company, day, day, "Hicbir Yerde - ZZ")],
		)


class TestTheRefusalsHoldOnTheDocumentAndNotJustTheEndpoint(FrappeTestCase):
	"""Every rule here is enforced in `Stabler Line Stop.validate`, so a Desk
	write is refused the same way an API write is. Pinned against `save()`
	precisely because the endpoint is the path that is easy to remember and the
	Desk is the path this floor actually uses — 3856 of 3856 production entries
	came from two Desk accounts."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = _a_company()
		cls.line = _a_warehouse(cls.company) if cls.company else None

	def setUp(self):
		if not (self.company and self.line):
			self.skipTest("no Company/Warehouse on this site")
		frappe.set_user("Administrator")

	def _doc(self, from_time, to_time):
		return frappe.get_doc(
			{
				"doctype": "Stabler Line Stop",
				"company": self.company,
				"line": self.line,
				"reason": "Other",
				"from_time": from_time,
				"to_time": to_time,
				"reported_by": frappe.session.user,
			}
		)

	def test_a_backwards_stop_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._doc(_END, _STOP).insert()

	def test_a_zero_length_stop_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._doc(_STOP, _STOP).insert()

	def test_a_forgotten_timer_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._doc("2026-08-28 06:00:00", "2026-08-29 06:00:00").insert()

	def test_an_unknown_reason_is_refused_by_the_endpoint(self):
		with self.assertRaises(Exception):
			log_line_stop(self.company, self.line, "Hava sicakti", _STOP, _END)

	def test_a_foreign_company_is_refused(self):
		with self.assertRaises(Exception):
			log_line_stop("Not A Real Company", self.line, "Other", _STOP, _END)

	def test_a_work_order_from_another_company_is_refused(self):
		"""The tenant boundary this endpoint could actually leak. `company` and
		`work_order` arrive as two independent arguments, and nothing about the
		pair says they belong together — so the order's own company is read from
		the database rather than believed.

		The foreign order is manufactured by moving a real one for the duration of
		the test rather than by looking for a second company. Most sites have one,
		so a test that skipped without one would skip exactly where this guard is
		least likely to have been thought about."""
		order = frappe.get_all("Work Order", filters={"company": self.company}, pluck="name", limit=1)
		if not order:
			self.skipTest("no Work Order on this site")
		order = order[0]
		frappe.db.set_value("Work Order", order, "company", "Baska Bir Sirket A.S.")
		self.addCleanup(frappe.db.set_value, "Work Order", order, "company", self.company)

		before = frappe.db.count("Stabler Line Stop")
		with self.assertRaises(Exception):
			log_line_stop(self.company, self.line, "Other", _STOP, _END, work_order=order)
		self.assertEqual(frappe.db.count("Stabler Line Stop"), before, "reddedilen kayıt yazılmış")

	def test_a_line_from_another_company_is_refused(self):
		"""`line` is the second field on this row that points at another tenant's
		data, and it arrives the same way `work_order` does: as a bare name, with
		nothing in the pair saying it belongs to the company beside it.

		The endpoint used to check only that the Warehouse existed. That is the
		weaker half of the question — every tenant's warehouses exist. A stop
		filed against a foreign line lands as this company's row carrying another
		company's warehouse name, and because `list_line_stops` filters on
		`company`, the tenant that owns the line never sees it and the tenant that
		filed it cannot tell it apart from its own.

		Same manufacturing trick as the Work Order case above: a real warehouse is
		moved for the duration of the test rather than requiring a second company,
		so this does not skip on the single-company sites where the guard is least
		likely to have been thought about."""
		frappe.db.set_value("Warehouse", self.line, "company", "Baska Bir Sirket A.S.")
		self.addCleanup(frappe.db.set_value, "Warehouse", self.line, "company", self.company)

		before = frappe.db.count("Stabler Line Stop")
		with self.assertRaises(Exception):
			log_line_stop(self.company, self.line, "Other", _STOP, _END)
		self.assertEqual(frappe.db.count("Stabler Line Stop"), before, "reddedilen kayıt yazılmış")

	def test_an_unknown_work_order_is_refused_rather_than_stored_as_a_dangling_name(self):
		before = frappe.db.count("Stabler Line Stop")
		with self.assertRaises(Exception):
			log_line_stop(self.company, self.line, "Other", _STOP, _END, work_order="MFG-WO-YOK-0001")
		self.assertEqual(frappe.db.count("Stabler Line Stop"), before)

	def test_a_backwards_window_is_refused_rather_than_returning_nothing(self):
		"""An empty list reads as "no stops recorded", which is the answer this
		log will honestly give for a while — so a malformed window must not be
		able to imitate it."""
		with self.assertRaises(frappe.ValidationError):
			list_line_stops(self.company, today(), add_days(today(), -3))


if __name__ == "__main__":
	unittest.main()
