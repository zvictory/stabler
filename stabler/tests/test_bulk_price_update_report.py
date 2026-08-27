"""What the bulk price grid is told about the lines it did not save.

`bulk_update_item_prices` applies the lines it can and skips the rest with a
bare `continue`, reporting only how many it applied. The screen then papers
over even that: PriceLists.vue renders `res.updated_count || priceUpdates.length`,
so a batch where every line was skipped reports the number of lines SENT as the
number saved.

Measured 2026-08-27: the grid's `MoneyInput` is used with no `min`, and
`parseMoneyInput("-5")` returns -5 — so a negative rate reaches the endpoint,
is dropped by `rate < 0: continue`, and the operator is told it was saved. The
single-item path refuses the same value by name ("Price list rate cannot be
negative."), so the two ways of setting a price disagree about whether it is
allowed.

Partial application is the right behaviour for a grid — one typo should not
discard two hundred good edits. Reporting it as success is not.
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

from stabler.api.inventory import bulk_update_item_prices

PRICE_LIST = "Standard Selling"


class TestABatchSaysWhichLinesItRefused(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.items = [self._an_item() for _ in range(2)]

	def _an_item(self):
		code = frappe.generate_hash("BULK-PRICE", 10).upper()
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": f"Bulk price probe {code}",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Item", doc.name, force=True, ignore_permissions=True)
		return doc.name

	def _cleanup_prices(self, item_code):
		for n in frappe.get_all("Item Price", filters={"item_code": item_code}, pluck="name"):
			self.addCleanup(frappe.delete_doc, "Item Price", n, force=True, ignore_permissions=True)

	def _post(self, updates):
		out = bulk_update_item_prices(PRICE_LIST, json.dumps(updates))
		for u in updates:
			self._cleanup_prices(u["item_code"])
		return out

	def test_a_negative_rate_is_named_rather_than_dropped(self):
		"""The operator typed something the endpoint will not store. They are the
		only person who can correct it, and they cannot correct what they are not
		told about."""
		good, bad = self.items
		out = self._post(
			[
				{"item_code": good, "price_list_rate": 120},
				{"item_code": bad, "price_list_rate": -5},
			]
		)
		self.assertEqual(out["updated_count"], 1)
		self.assertEqual(out["rejected"], [bad])

	def test_the_good_lines_in_a_batch_are_still_saved(self):
		"""Refusing the whole batch over one typo would be the other way to be
		honest, and it is the wrong one for a two-hundred-row grid."""
		good, bad = self.items
		self._post(
			[
				{"item_code": good, "price_list_rate": 120},
				{"item_code": bad, "price_list_rate": -5},
			]
		)
		self.assertEqual(
			flt(
				frappe.db.get_value(
					"Item Price", {"item_code": good, "price_list": PRICE_LIST}, "price_list_rate"
				)
			),
			120.0,
		)
		self.assertFalse(frappe.db.exists("Item Price", {"item_code": bad, "price_list": PRICE_LIST}))

	def test_a_batch_that_saved_nothing_says_so(self):
		"""The case the screen currently reports as full success."""
		out = self._post([{"item_code": self.items[0], "price_list_rate": -1}])
		self.assertEqual(out["updated_count"], 0)
		self.assertEqual(out["rejected"], [self.items[0]])

	def test_an_ordinary_batch_reports_nothing_refused(self):
		out = self._post([{"item_code": c, "price_list_rate": 42} for c in self.items])
		self.assertEqual(out["updated_count"], 2)
		self.assertEqual(out["rejected"], [])
