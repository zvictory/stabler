"""The endpoint that writes a Stock Reconciliation, against real stock.

`test_stock_recon.py` covers `_stock_recon.py` — the pure prep logic, which
touches nothing. That is the whole of the coverage this feature had, and it is
the same shape that let seven P0s live in the manufacturing module: green over
the parts that cannot move money, empty over the parts that do.

A Stock Reconciliation is the most consequential document in ERPNext. It sets
absolute quantities and books the difference straight to a P&L account. These
tests run it for real and read the ledger back.
"""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils import flt

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from stabler.api.inventory import create_stock_reconciliation


def _a_valued_bin():
	"""A bin with stock and a real valuation — the ordinary case a warehouse count
	walks past a hundred times."""
	rows = frappe.get_all(
		"Bin",
		filters={"actual_qty": [">", 0], "valuation_rate": [">", 0]},
		fields=["item_code", "warehouse", "actual_qty", "valuation_rate"],
		limit=1,
	)
	return rows[0] if rows else None


@unittest.skipUnless(frappe.db.table_exists("Bin"), "no Bin table on this site")
class TestACountDoesNotSilentlyRevalueStock(FrappeTestCase):
	"""D-INV-1 — the SPA sends `valuation_rate` back on every line, and the
	endpoint wrote it onto the document. ERPNext then applies it, so a warehouse
	count restates the cost basis of everything it touches.

	Nobody has to do anything wrong. The count screen loads valuation when the
	warehouse is picked and the operator then walks the warehouse, which takes as
	long as counting a warehouse takes. Any receipt landing in that window moves
	valuation, and the count posts the page's older copy back over it.

	Measured on genesis-test 2026-08-27, PROBE-MILK / Stores - _TC, counting ONE
	extra unit while sending a rate of 0.5 against a real 1.0:

	    Bin.valuation_rate  1.0 -> 0.5
	    GL: Stock Adjustment  Dr 729.5 / Stock In Hand  Cr 729.5
	    endpoint summary:   total_value_delta 0.5

	729.5 written to expense, reported as 0.5, on a one-unit correction. The SPA
	shows the value impact nowhere at all: the toast says "Reconciled 1 item(s)"
	and the history table has columns for when, name, date and who.
	"""

	def setUp(self):
		self.bin = _a_valued_bin()
		if not self.bin:
			self.skipTest("no valued stock on this site to count")
		frappe.set_user("Administrator")
		self.company = frappe.db.get_value("Warehouse", self.bin["warehouse"], "company")

	def _count(self, delta, valuation_rate=None):
		row = {
			"item_code": self.bin["item_code"],
			"warehouse": self.bin["warehouse"],
			"current_qty": flt(self.bin["actual_qty"]),
			"counted_qty": flt(self.bin["actual_qty"]) + delta,
		}
		if valuation_rate is not None:
			row["valuation_rate"] = valuation_rate
		return create_stock_reconciliation(self.company, json.dumps([row]), submit=1)

	def _rate(self):
		return flt(
			frappe.db.get_value(
				"Bin",
				{"item_code": self.bin["item_code"], "warehouse": self.bin["warehouse"]},
				"valuation_rate",
			)
		)

	def test_a_stale_rate_from_the_page_does_not_reach_the_ledger(self):
		"""The one that matters. Half the real rate, sent the way the page sends
		it, on a count that only moved quantity."""
		before = self._rate()
		self._count(delta=1, valuation_rate=round(before / 2, 4))
		self.assertEqual(self._rate(), before, "the count restated the item's cost basis")

	def test_the_ledger_moves_by_the_count_at_the_rate_the_stock_already_had(self):
		"""Not just that valuation survived — that the money booked is the counted
		difference and nothing else. A fix that froze valuation but still booked
		the client's arithmetic would pass the test above."""
		rate = self._rate()
		out = self._count(delta=2, valuation_rate=round(rate / 2, 4))
		doc = frappe.get_doc("Stock Reconciliation", out["name"])
		self.assertAlmostEqual(flt(doc.difference_amount), 2 * rate, places=4)

	def test_an_item_with_no_valuation_is_still_refused_rather_than_priced_here(self):
		"""The behaviour that must NOT change. Found stock that never arrived
		needs a cost basis, and a blind warehouse count is not where one should be
		invented — ERPNext refuses by name and that refusal is correct.

		It is also why removing the write breaks nothing that works today: the
		endpoint only ever wrote a rate it considered truthy, so zero — the value
		the page sends for an unvalued line — was already dropped and already
		refused."""
		item = frappe.db.get_value("Item", {"is_stock_item": 1, "disabled": 0}, "name")
		wh = frappe.db.get_value(
			"Warehouse",
			{"company": self.company, "is_group": 0, "name": ["!=", self.bin["warehouse"]]},
			"name",
		)
		if not item or not wh:
			self.skipTest("no second warehouse on this site to find stock in")
		if frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "valuation_rate"):
			self.skipTest(f"{item} already carries a valuation in {wh}")
		with self.assertRaises(frappe.ValidationError) as cm:
			create_stock_reconciliation(
				self.company,
				json.dumps([{"item_code": item, "warehouse": wh, "current_qty": 0.0, "counted_qty": 3.0}]),
				submit=1,
			)
		self.assertIn("valuation rate", str(cm.exception).lower())


@unittest.skipUnless(frappe.db.table_exists("Bin"), "no Bin table on this site")
class TestTheReportedVarianceMatchesTheLedger(FrappeTestCase):
	"""D-INV-2 — `summary.total_value_delta` is computed from the request, so it
	never has to agree with what was posted, and measurably does not.

	Measured on genesis-test 2026-08-27, both directions on the same one-unit
	count: with a stale rate it reported 0.5 against a real 729.5; with no rate
	it reported 0.0 against a real 1.0. The document's own `difference_amount`
	matched the GL exactly in both cases, so there is a truthful number available
	and nothing had to be recomputed to find it.
	"""

	def setUp(self):
		self.bin = _a_valued_bin()
		if not self.bin:
			self.skipTest("no valued stock on this site to count")
		frappe.set_user("Administrator")
		self.company = frappe.db.get_value("Warehouse", self.bin["warehouse"], "company")

	def test_the_counted_difference_is_measured_against_the_real_stock(self):
		"""`current_qty` round-trips through the browser too, so the quantity
		delta was the caller's arithmetic as much as the value one. It matters on
		the ordinary path rather than the malicious one: the count screen loads
		the balances and the operator then walks the warehouse, so anything that
		moves in that window makes the page's copy wrong — and the operator is
		told a delta measured against a number that stopped being true before
		they finished counting.

		ERPNext writes the ledger's own `current_qty` onto each row, so the true
		difference is sitting on the document."""
		real = flt(
			frappe.db.get_value(
				"Bin",
				{"item_code": self.bin["item_code"], "warehouse": self.bin["warehouse"]},
				"actual_qty",
			)
		)
		out = create_stock_reconciliation(
			self.company,
			json.dumps(
				[
					{
						"item_code": self.bin["item_code"],
						"warehouse": self.bin["warehouse"],
						"current_qty": real - 500,  # a stale page, 500 units out of date
						"counted_qty": real + 1,
						"valuation_rate": flt(self.bin["valuation_rate"]),
					}
				]
			),
			submit=1,
		)
		self.assertAlmostEqual(flt(out["summary"]["total_qty_delta"]), 1.0, places=4)

	def test_the_summary_reports_what_was_actually_posted(self):
		out = create_stock_reconciliation(
			self.company,
			json.dumps(
				[
					{
						"item_code": self.bin["item_code"],
						"warehouse": self.bin["warehouse"],
						"current_qty": flt(self.bin["actual_qty"]),
						"counted_qty": flt(self.bin["actual_qty"]) + 1,
						"valuation_rate": 0.5 * flt(self.bin["valuation_rate"]),
					}
				]
			),
			submit=1,
		)
		doc = frappe.get_doc("Stock Reconciliation", out["name"])
		self.assertAlmostEqual(
			flt(out["summary"]["total_value_delta"]),
			flt(doc.difference_amount),
			places=4,
			msg="the number handed back to the operator is not the number that was booked",
		)
