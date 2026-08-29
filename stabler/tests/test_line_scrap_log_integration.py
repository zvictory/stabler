"""The scrap log against a live database.

`test_scrap_math` proves the arithmetic and the two double-count guards without a
bench. What it cannot see is the half that only exists once the doctypes are
real, and that half is the entire reason option B was chosen: **the record writes
a stock document.** A number that agrees with the ledger in a unit test and
writes nothing on a real site is exactly the split this feature exists to close.

So what is pinned here is: that a draft Material Transfer is actually created,
that it is a DRAFT and not a submitted one, that it moves the named item from the
order's WIP warehouse into the configured scrap warehouse, that an unconfigured
company is refused rather than recorded, and that the record and its draft cannot
be deleted apart from each other.

Measured on anjan 2026-08-27, which is why this exists: the floor ALREADY does
this by hand — 25 Stock Entries, 35 037 units, $3 941, into two scrap warehouses,
filed by three people, latest 2026-08-22, with the reason surviving only as a
free-text Uzbek paragraph in `remarks`. The movement is not new. The reason is.

    cd /path/to/frappe-bench && bench --site <site> run-tests \
        --module stabler.tests.test_line_scrap_log_integration
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, today

try:
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # newer frappe
	from frappe.tests import IntegrationTestCase as FrappeTestCase

from stabler.api.manufacturing import (
	list_line_scrap,
	list_stop_reasons,
	log_line_scrap,
	wo_scrap_options,
)

_LOSS_REASON = "Off-spec batch"
_STOP_ONLY_REASON = "Waiting for material"


def _an_order_with_material() -> dict | None:
	"""A Work Order that has a WIP warehouse and at least one required item.

	`transferred_qty` / `consumed_qty` are moved by the tests that need a
	ceiling, the same trick the stop log's tests use for a foreign company: a
	real row is nudged for the duration and restored, rather than requiring a
	site to happen to be in the right state. A test that skipped unless the floor
	had a half-consumed order would skip exactly where these guards matter.
	"""
	rows = frappe.db.sql(
		"""
		SELECT wo.name, wo.company, wo.wip_warehouse, woi.item_code
		FROM `tabWork Order` wo
		JOIN `tabWork Order Item` woi ON woi.parent = wo.name
		WHERE wo.wip_warehouse IS NOT NULL AND wo.wip_warehouse != ''
		LIMIT 1
		""",
		as_dict=True,
	)
	return rows[0] if rows else None


def _a_scrap_warehouse(company: str) -> str | None:
	rows = frappe.get_all("Warehouse", filters={"company": company, "is_group": 0}, pluck="name", limit=1)
	return rows[0] if rows else None


class ScrapCase(FrappeTestCase):
	"""Shared fixture: an order, a ceiling, and a configured scrap warehouse."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.order = _an_order_with_material()

	def setUp(self):
		if not self.order:
			self.skipTest("no Work Order with a WIP warehouse on this site")
		frappe.set_user("Administrator")
		self.company = self.order["company"]
		self.wo = self.order["name"]
		self.item = self.order["item_code"]
		self.wip = self.order["wip_warehouse"]

		self.scrap_warehouse = _a_scrap_warehouse(self.company)
		if not self.scrap_warehouse:
			self.skipTest("no non-group Warehouse on this company")
		self._configure(self.scrap_warehouse)
		self._set_ceiling(100.0, 0.0)

	def _configure(self, warehouse: str | None):
		"""Point the company's settings at a warehouse, restoring whatever was
		there. Created rather than assumed: most sites have never configured
		this, and a test that skipped without a settings row would skip on every
		site except the one it was written on."""
		name = self.company
		if frappe.db.exists("Stabler Manufacturing Settings", name):
			before = frappe.db.get_value("Stabler Manufacturing Settings", name, "scrap_warehouse")
			self.addCleanup(
				frappe.db.set_value, "Stabler Manufacturing Settings", name, "scrap_warehouse", before
			)
			frappe.db.set_value("Stabler Manufacturing Settings", name, "scrap_warehouse", warehouse)
			return
		doc = frappe.get_doc(
			{
				"doctype": "Stabler Manufacturing Settings",
				"company": self.company,
				"scrap_warehouse": warehouse,
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Stabler Manufacturing Settings", doc.name, force=True)

	def _set_ceiling(self, transferred: float, consumed: float):
		row = frappe.db.get_value("Work Order Item", {"parent": self.wo, "item_code": self.item}, "name")
		before = frappe.db.get_value(
			"Work Order Item", row, ["transferred_qty", "consumed_qty"], as_dict=True
		)
		self.addCleanup(
			frappe.db.set_value,
			"Work Order Item",
			row,
			{"transferred_qty": before.transferred_qty, "consumed_qty": before.consumed_qty},
		)
		frappe.db.set_value(
			"Work Order Item", row, {"transferred_qty": transferred, "consumed_qty": consumed}
		)

	def _scrap(self, **kwargs):
		payload = {
			"company": self.company,
			"work_order": self.wo,
			"item_code": self.item,
			"qty": 3,
			"reason": _LOSS_REASON,
		}
		payload.update(kwargs)
		out = log_line_scrap(**payload)
		self.addCleanup(self._forget, out["name"])
		return out

	def _forget(self, name: str):
		"""Delete the record and, with it, its draft — the record's own `on_trash`
		does the second half. Written as a helper because a submitted draft makes
		the delete refuse on purpose, and a test that left one behind would
		poison every later run."""
		if not frappe.db.exists("Stabler Line Scrap", name):
			return
		entry = frappe.db.get_value("Stabler Line Scrap", name, "stock_entry")
		if entry and frappe.db.get_value("Stock Entry", entry, "docstatus") == 1:
			frappe.get_doc("Stock Entry", entry).cancel()
		frappe.delete_doc("Stabler Line Scrap", name, force=True)
		# A draft is already gone — `on_trash` took it. What is left here is a
		# cancelled entry, and it is deliberately NOT deleted: `force=True` skips
		# the link check but not the Stock Ledger Entries, so the rows survive the
		# document. The test runner rolls the naming series back between tests, so
		# the next Stock Entry is issued the same name and inherits those stale
		# ledger rows — which is how deleting a *draft* three tests later failed
		# with "MAT-STE-2026-00049 is linked with Stock Ledger Entry". A cancelled
		# entry moved nothing; leaving it is what the product does too.


class TestTheRecordWritesADraftAndOnlyADraft(ScrapCase):
	"""Option B, and the whole reason the loss half was held back until now:
	"5 kg lost" as a bare number contradicts the stock ledger, because the 5 kg
	is still on hand. The record is only worth having if it moves the stock."""

	def test_a_draft_material_transfer_is_created(self):
		out = self._scrap()
		self.assertTrue(out["stock_entry"], "fire kaydı stok belgesi yazmamış")
		entry = frappe.get_doc("Stock Entry", out["stock_entry"])
		self.assertEqual(entry.purpose, "Material Transfer")
		self.assertEqual(entry.docstatus, 0, "operatör stok hareketini onaylamış olmamalı")

	def test_it_is_never_submitted_by_the_operator(self):
		"""Accounting submits in the Desk, exactly as they do today. An operator
		who could submit stock movement from a kiosk would be a new authority,
		not a faster one — and the three people filing these by hand are the
		people who own that decision."""
		out = self._scrap()
		self.assertEqual(
			frappe.db.get_value("Stock Entry", out["stock_entry"], "docstatus"),
			0,
			"taslak olmalıydı, onaylanmış",
		)

	def test_the_transfer_runs_from_the_line_to_the_configured_warehouse(self):
		"""Not a constant and not a tenant name: two scrap warehouses exist on
		anjan and none on most of the other six tenants."""
		out = self._scrap()
		entry = frappe.get_doc("Stock Entry", out["stock_entry"])
		row = entry.items[0]
		self.assertEqual(row.s_warehouse, self.wip)
		self.assertEqual(row.t_warehouse, self.scrap_warehouse)
		self.assertEqual(row.item_code, self.item)
		self.assertEqual(flt(row.qty), 3.0)

	def test_the_transfer_is_not_a_material_transfer_for_manufacture(self):
		"""`Material Transfer for Manufacture` increments
		`Work Order Item.transferred_qty` — it tells ERPNext that MORE material
		arrived in WIP, the exact opposite of what happened. The scrapped
		kilograms would then still count as available to scrap again."""
		out = self._scrap()
		self.assertNotEqual(
			frappe.db.get_value("Stock Entry", out["stock_entry"], "purpose"),
			"Material Transfer for Manufacture",
		)

	def test_the_reason_is_carried_in_words_as_well_as_in_a_link(self):
		"""The three people doing this by hand already read `remarks` — it is
		where the reason lives on all 25 of their entries. Writing it there means
		the habit keeps working on the day this ships, before anybody has been
		shown a new screen."""
		out = self._scrap()
		remarks = frappe.db.get_value("Stock Entry", out["stock_entry"], "remarks") or ""
		self.assertIn(out["name"], remarks)
		self.assertIn(_LOSS_REASON, remarks)

	def test_the_line_is_derived_from_the_order_and_not_typed(self):
		self.assertEqual(self._scrap()["line"], self.wip)

	def test_the_reporter_is_the_session_and_not_an_argument(self):
		out = self._scrap()
		self.assertEqual(
			frappe.db.get_value("Stabler Line Scrap", out["name"], "reported_by"), frappe.session.user
		)


class TestAnUnconfiguredCompanyIsRefused(ScrapCase):
	def test_no_scrap_warehouse_means_no_record_at_all(self):
		"""The decision this feature turns on. Recording the measurement and
		skipping the draft would recreate exactly the split option B was chosen
		to avoid — and it would do it silently: afterwards a record with no draft
		is indistinguishable from one whose draft somebody deleted."""
		self._configure(None)
		before = frappe.db.count("Stabler Line Scrap")
		with self.assertRaises(Exception):
			log_line_scrap(self.company, self.wo, self.item, 3, _LOSS_REASON)
		self.assertEqual(frappe.db.count("Stabler Line Scrap"), before, "yapılandırılmamışken yazılmış")

	def test_the_refusal_names_what_to_configure(self):
		self._configure(None)
		with self.assertRaises(Exception) as caught:
			log_line_scrap(self.company, self.wo, self.item, 3, _LOSS_REASON)
		self.assertIn("Stabler Manufacturing Settings", str(caught.exception))


class TestTheQuantityGuardsHoldOnTheDocument(ScrapCase):
	"""Every rule is enforced in `Stabler Line Scrap.validate`, so a Desk write is
	refused the same way an API write is. That is not theoretical: 3856 of 3856
	production entries on this site came from two Desk accounts."""

	def _doc(self, **kwargs):
		payload = {
			"doctype": "Stabler Line Scrap",
			"company": self.company,
			"work_order": self.wo,
			"item_code": self.item,
			"qty": 3,
			"reason": _LOSS_REASON,
			"reported_by": frappe.session.user,
		}
		payload.update(kwargs)
		return frappe.get_doc(payload)

	def test_a_zero_quantity_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._doc(qty=0).insert()

	def test_a_negative_quantity_is_refused(self):
		"""On a Material Transfer a negative quantity reverses the entry: the
		draft would carry stock INTO the line out of the scrap warehouse, and a
		record filed as a loss would read, in the ledger, as a gain."""
		with self.assertRaises(frappe.ValidationError):
			self._doc(qty=-3).insert()

	def test_more_than_wip_holds_is_refused(self):
		"""Negative stock is off on this site, so this would not mis-post — it
		would throw at submit, in the Desk, days after the bucket was emptied."""
		self._set_ceiling(5.0, 0.0)
		with self.assertRaises(frappe.ValidationError):
			self._doc(qty=6).insert()

	def test_an_item_the_order_never_carried_is_refused(self):
		"""A WIP warehouse holds five departments' worth of orders. Naming an
		item this order never carried would draft a transfer of somebody else's
		material out of it."""
		other = frappe.db.sql(
			"""SELECT name FROM `tabItem` WHERE name NOT IN
			   (SELECT item_code FROM `tabWork Order Item` WHERE parent = %s) LIMIT 1""",
			self.wo,
		)
		if not other:
			self.skipTest("every Item on this site is on this order")
		with self.assertRaises(frappe.ValidationError):
			self._doc(item_code=other[0][0]).insert()

	def test_scrap_already_filed_counts_against_the_ceiling(self):
		"""The guard ERPNext cannot make: a plain Material Transfer moves the
		stock without touching `transferred_qty`, so the kilograms already sent to
		scrap are still standing in ERPNext's arithmetic. Without this, two 5 kg
		records against 6 kg of stock both pass and the second fails at submit."""
		self._set_ceiling(5.0, 0.0)
		self._scrap(qty=4)
		with self.assertRaises(frappe.ValidationError):
			self._doc(qty=2).insert()
		# ...and what does still fit is still accepted.
		self._scrap(qty=1)


class TestTheRecordAndItsDraftCannotBeReadApart(ScrapCase):
	def test_deleting_the_record_takes_its_draft_with_it(self):
		"""Otherwise the Desk fills with drafts nobody can account for — a stock
		document whose only written reason has been deleted."""
		out = self._scrap()
		entry = out["stock_entry"]
		frappe.delete_doc("Stabler Line Scrap", out["name"], force=True)
		self.assertFalse(frappe.db.exists("Stock Entry", entry), "taslak öksüz kalmış")

	def test_the_draft_cannot_be_deleted_while_the_record_points_at_it(self):
		"""No code of ours: `stock_entry` is a Link field, so Frappe's own link
		check refuses. Pinned because it is load-bearing and invisible — nothing
		in this app would notice if a future edit made the field a Data column."""
		out = self._scrap()
		with self.assertRaises(Exception):
			frappe.delete_doc("Stock Entry", out["stock_entry"])
		self.assertTrue(frappe.db.exists("Stock Entry", out["stock_entry"]))

	def test_a_record_whose_transfer_was_submitted_cannot_be_deleted(self):
		"""The stock has moved and this record is its only written reason."""
		out = self._scrap()
		entry = frappe.get_doc("Stock Entry", out["stock_entry"])
		try:
			entry.submit()
		except Exception:
			self.skipTest("this item cannot be valued out of the WIP warehouse on this site")
		with self.assertRaises(Exception):
			frappe.delete_doc("Stabler Line Scrap", out["name"])
		self.assertTrue(frappe.db.exists("Stabler Line Scrap", out["name"]))

	def test_the_record_is_frozen_once_its_draft_exists(self):
		"""A record reading 5 kg beside a stock document moving 3 kg, filed
		together under one name, saying different things."""
		out = self._scrap()
		doc = frappe.get_doc("Stabler Line Scrap", out["name"])
		doc.qty = 1
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestTheTwoLossPathsCannotBothCount(ScrapCase):
	"""The double count. A Finish-time `scrap_qty` becomes `process_loss_qty`,
	which draws the lost units' raw material and receives it nowhere — the cost is
	absorbed into the good output. A scrap record moves that same material into
	the scrap warehouse. Both, for one order, charges it twice, and nothing
	throws because each number is individually correct."""

	def test_finish_refuses_rejects_once_a_scrap_record_exists(self):
		from stabler.api.manufacturing import make_work_order_stock_entry

		self._scrap()
		with self.assertRaises(Exception) as caught:
			make_work_order_stock_entry(self.wo, "Manufacture", qty=1, scrap_qty=1)
		self.assertIn("scrap record", str(caught.exception))

	def test_finish_without_rejects_is_not_touched_by_this_guard(self):
		"""The guard must not become a reason an order cannot be finished. It
		fires only when the SAME loss is about to be counted a second time."""
		from stabler.api.manufacturing import _assert_no_scrap_record

		self._scrap()
		with self.assertRaises(Exception):
			_assert_no_scrap_record(self.wo)
		# A different order is untouched.
		_assert_no_scrap_record("MFG-WO-BASKA-EMIR-0001")


class TestTheReasonComesFromTheCatalogueThatAlreadyExists(ScrapCase):
	def test_a_loss_reason_is_accepted(self):
		self.assertIn(_LOSS_REASON, {r["reason"] for r in list_stop_reasons(self.company, "Loss")})
		self._scrap(reason=_LOSS_REASON)

	def test_a_downtime_only_reason_is_refused(self):
		""" "Waiting for material" as the reason 30 kg went in the bin is a row
		that reads as data and is not."""
		with self.assertRaises(Exception):
			log_line_scrap(self.company, self.wo, self.item, 3, _STOP_ONLY_REASON)

	def test_an_unknown_reason_is_refused(self):
		with self.assertRaises(Exception):
			log_line_scrap(self.company, self.wo, self.item, 3, "Hech qanday sabab")


class TestWhatTheScreenReadsBack(ScrapCase):
	def test_the_options_carry_a_ceiling_per_item(self):
		"""What the kiosk needs before it can ask anything: the item list comes
		from the order, and each row carries its own ceiling, so a bad number can
		be refused before the server has to."""
		self._set_ceiling(40.0, 10.0)
		options = wo_scrap_options(self.wo)
		self.assertEqual(options["line"], self.wip)
		mine = [r for r in options["items"] if r["item_code"] == self.item]
		self.assertEqual(mine[0]["available"], 30.0)

	def test_a_filed_scrap_lowers_the_ceiling_the_screen_shows(self):
		"""Recomputed on every call rather than cached: a stale ceiling is wrong
		exactly when two people are working the same order."""
		self._set_ceiling(40.0, 10.0)
		self._scrap(qty=4)
		mine = [r for r in wo_scrap_options(self.wo)["items"] if r["item_code"] == self.item]
		self.assertEqual(mine[0]["available"], 26.0)

	def test_the_record_comes_back_in_its_window_with_its_draft_state(self):
		"""`stock_entry_docstatus` is read live. A mirrored column would say
		"awaiting accounting" about stock that moved last week — which is the
		entire life of these documents."""
		out = self._scrap()
		rows = [r for r in list_line_scrap(self.company, today(), today()) if r["name"] == out["name"]]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["stock_entry_docstatus"], 0)
		self.assertEqual(rows[0]["line"], self.wip)

	def test_a_backwards_window_is_refused_rather_than_returning_nothing(self):
		"""An empty list reads as "nothing was lost", which is an answer this log
		will honestly give for a while — so a malformed window must not be able to
		imitate it."""
		with self.assertRaises(frappe.ValidationError):
			list_line_scrap(self.company, today(), "2020-01-01")


class TestTheTenantBoundary(ScrapCase):
	def test_a_work_order_from_another_company_is_refused(self):
		"""`company` and `work_order` arrive as two independent arguments and
		nothing about the pair says they belong together. Same manufacturing trick
		as the stop log's tests: a real order is moved for the duration, so this
		does not skip on the single-company sites where the guard is least likely
		to have been thought about."""
		frappe.db.set_value("Work Order", self.wo, "company", "Baska Bir Sirket A.S.")
		self.addCleanup(frappe.db.set_value, "Work Order", self.wo, "company", self.company)
		before = frappe.db.count("Stabler Line Scrap")
		with self.assertRaises(Exception):
			log_line_scrap(self.company, self.wo, self.item, 3, _LOSS_REASON)
		self.assertEqual(frappe.db.count("Stabler Line Scrap"), before, "reddedilen kayıt yazılmış")

	def test_a_scrap_warehouse_from_another_company_cannot_be_configured(self):
		"""Mis-set, it would send one company's losses into another company's
		stock — and because the record filters on `company`, the tenant that owns
		the warehouse would never see the arrival."""
		frappe.db.set_value("Warehouse", self.scrap_warehouse, "company", "Baska Bir Sirket A.S.")
		self.addCleanup(frappe.db.set_value, "Warehouse", self.scrap_warehouse, "company", self.company)
		doc = frappe.get_doc("Stabler Manufacturing Settings", self.company)
		with self.assertRaises(frappe.ValidationError):
			doc.save()


if __name__ == "__main__":
	unittest.main()
