"""The date a stock document is posted on, when the caller names one.

`create_stock_entry` and `create_stock_reconciliation` both accept a
`posting_date` and both assign it to the document — and ERPNext then throws it
away. `set_posting_time` is a Check on the doctype meaning "the date and time I
gave you are deliberate"; left at 0, the controller resets both to now. Neither
endpoint sets it, so the parameter is accepted, written and discarded, and the
caller is told nothing.

Measured on genesis-test 2026-08-27: a Material Receipt requested for 2026-08-22
was stored as 2026-08-27, and its Stock Ledger Entry with it.

This is not an API-only path. StockEntries.vue puts a DateInput on the form
(line ~762) and sends what the operator picked, so a receipt entered the morning
after the goods arrived is dated the morning after — and stock valuation is
computed in date order, so the entry is not merely mislabelled: it is sequenced
wrong against everything that moved in between, and a period close that takes
"everything up to the 31st" takes it in the wrong period.

Honouring the date is what the ERPNext desk does with the same checkbox, and it
hands the decision to ERPNext's own controls (`stock_frozen_upto`, the role
allowed to make back-dated entries), which refuse with a message rather than in
silence.
"""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils import add_days, flt, getdate, today

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from stabler.api.inventory import create_stock_entry, create_stock_reconciliation


def _a_valued_bin():
	rows = frappe.get_all(
		"Bin",
		filters={"actual_qty": [">", 0], "valuation_rate": [">", 0]},
		fields=["item_code", "warehouse", "actual_qty", "valuation_rate"],
		limit=1,
	)
	return rows[0] if rows else None


class _StockDateFixture(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.bin = _a_valued_bin()
		self.assertTrue(self.bin, "no valued stock on this site to post against")
		self.company = frappe.db.get_value("Warehouse", self.bin["warehouse"], "company")
		self.back = add_days(today(), -5)

	def _cancel_later(self, name, doctype):
		def undo():
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus == 1:
				doc.cancel()

		self.addCleanup(undo)


class TestAStockEntryIsPostedOnTheDateItWasGiven(_StockDateFixture):
	def _receipt(self, **kw):
		out = create_stock_entry(
			self.company,
			"Material Receipt",
			json.dumps([{"item_code": self.bin["item_code"], "qty": 1, "basic_rate": 10}]),
			to_warehouse=self.bin["warehouse"],
			submit=1,
			**kw,
		)
		self._cancel_later(out["name"], "Stock Entry")
		return frappe.get_doc("Stock Entry", out["name"])

	def test_a_backdated_receipt_keeps_the_date_it_was_given(self):
		doc = self._receipt(posting_date=self.back)
		self.assertEqual(getdate(doc.posting_date), getdate(self.back))

	def test_the_stock_ledger_carries_that_date_too(self):
		"""The document field on its own proves nothing — valuation is computed
		from the ledger, in date order."""
		doc = self._receipt(posting_date=self.back)
		dates = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": doc.name}, pluck="posting_date")
		self.assertTrue(dates)
		self.assertEqual({getdate(d) for d in dates}, {getdate(self.back)})

	def test_the_time_is_not_reset_to_midnight(self):
		"""Same-day entries are sequenced by time, so a document that quietly
		posted at 00:00:00 would sort ahead of everything already booked that day
		— a different way to get the valuation order wrong."""
		doc = self._receipt(posting_date=today())
		self.assertNotEqual(str(doc.posting_time)[:8], "00:00:00")

	def test_asking_for_no_date_still_means_today(self):
		doc = self._receipt()
		self.assertEqual(getdate(doc.posting_date), getdate(today()))


class TestACountIsPostedOnTheDateItWasGiven(_StockDateFixture):
	def _first_move(self):
		"""The earliest date this stock existed at all. A reconciliation cannot be
		valued before it, so it is the floor for any backdating here — and it is
		read from the data rather than assumed, because a site whose stock was
		loaded last week has no room for an arbitrary "five days ago"."""
		return frappe.db.sql(
			"""SELECT MIN(posting_date) FROM `tabStock Ledger Entry`
			   WHERE item_code = %s AND warehouse = %s AND is_cancelled = 0""",
			(self.bin["item_code"], self.bin["warehouse"]),
		)[0][0]

	def _count(self, posting_date):
		out = create_stock_reconciliation(
			self.company,
			json.dumps(
				[
					{
						"item_code": self.bin["item_code"],
						"warehouse": self.bin["warehouse"],
						"current_qty": flt(self.bin["actual_qty"]),
						"counted_qty": flt(self.bin["actual_qty"]) + 1,
					}
				]
			),
			posting_date=posting_date,
			submit=1,
		)
		self._cancel_later(out["name"], "Stock Reconciliation")
		return out

	def test_a_backdated_count_keeps_the_date_it_was_given(self):
		"""A reconciliation writes an absolute quantity, so its date decides
		which movements it is deemed to have counted."""
		back = add_days(self._first_move(), 1)
		self.assertLess(getdate(back), getdate(today()), "no room to backdate on this site")

		out = self._count(back)

		self.assertEqual(
			getdate(frappe.db.get_value("Stock Reconciliation", out["name"], "posting_date")), getdate(back)
		)

	def test_a_count_dated_before_the_stock_existed_is_refused_by_name(self):
		"""The other half of honouring the date. ERPNext cannot value stock at a
		date it did not exist, and now says so — where before it moved the count
		to today and posted it against a valuation from a different week. A
		refusal the operator can read beats a success they cannot question."""
		with self.assertRaises(frappe.ValidationError):
			self._count(add_days(self._first_move(), -1))
