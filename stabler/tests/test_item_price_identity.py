"""Which `Item Price` row an update is allowed to land on.

ERPNext identifies a price by more than the item and the list: uom, customer,
supplier, batch, packing unit and a validity window all discriminate — its own
`check_duplicates` (item_price.py) lists them. Stabler's price endpoints treat
`(item_code, price_list)` as the whole identity, on both sides:

  * `save_item_price` looks up ANY row for the pair and writes into it, and
    `frappe.db.get_value` returns the most recently modified one — so the row
    that gets overwritten is whichever was touched last.
  * `get_price_list_matrix` LEFT JOINs on the same pair, so a customer's
    negotiated rate is displayed in the column the operator reads as "the list
    price", and an item with several prices appears several times.

Measured on genesis-test 2026-08-27: with a list price of 100 and a customer
price of 111 on the same item, setting the list price to 250 left the 100 alone
and rewrote the customer's 111 to 250.

Real DB, because the defect is entirely in how rows are matched.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import add_days, flt, today

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from stabler.api.inventory import get_price_list_matrix, save_item_price

PRICE_LIST = "Standard Selling"


class _PriceFixture(FrappeTestCase):
	"""One throwaway item, plus prices each test creates for itself.

	`FrappeTestCase` rolls back once per CLASS, not per test (measured
	2026-08-26), so anything shared between tests has to be torn down by hand or
	the second test inherits the first one's rows.
	"""

	def setUp(self):
		super().setUp()
		self.item = self._an_item()
		self.customer = frappe.db.get_value("Customer", {}, "name")
		self.assertTrue(self.customer, "the site has no Customer to negotiate a price with")

	def _an_item(self):
		code = frappe.generate_hash("PRICE-ID", 10).upper()
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": f"Price identity probe {code}",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Item", doc.name, force=True, ignore_permissions=True)
		return doc.name

	def _price(self, rate, **kw):
		doc = frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": self.item,
				"price_list": kw.pop("price_list", PRICE_LIST),
				"price_list_rate": rate,
				**kw,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Item Price", doc.name, force=True, ignore_permissions=True)
		return doc.name

	def _rate(self, name):
		return flt(frappe.db.get_value("Item Price", name, "price_list_rate"))


class TestANegotiatedPriceIsNotTheListPrice(_PriceFixture):
	def test_updating_the_list_price_leaves_a_customer_price_alone(self):
		"""A price agreed with one customer is a commercial commitment. Raising
		the list price is not a decision to raise theirs, and whoever does it is
		given no indication that it did — the matrix has no customer column."""
		list_price = self._price(100)
		negotiated = self._price(111, customer=self.customer)  # touched last: the row get_value returns

		save_item_price(item_code=self.item, price_list=PRICE_LIST, price_list_rate=250)

		self.assertEqual(self._rate(negotiated), 111.0, "the customer's negotiated price was overwritten")
		self.assertEqual(self._rate(list_price), 250.0, "the list price is what the caller asked to change")

	def test_updating_the_list_price_leaves_a_dated_promotion_alone(self):
		"""Same rule, different discriminator: a price that is only valid for a
		window is not the standing one either. It matters more here — the
		promotion expires, and the rate written into it silently becomes nobody's
		price at all, so the loss is invisible until the window closes."""
		list_price = self._price(100)
		promo = self._price(80, valid_from=today(), valid_upto=add_days(today(), 7))

		save_item_price(item_code=self.item, price_list=PRICE_LIST, price_list_rate=250)

		self.assertEqual(self._rate(promo), 80.0, "the promotional price was overwritten")
		self.assertEqual(self._rate(list_price), 250.0)

	def test_an_item_whose_only_price_is_negotiated_gains_a_list_price(self):
		"""There is no list price to update, so one is created. The alternative —
		writing into the customer's row because it is the only one there — is the
		same defect with nothing to compare against."""
		negotiated = self._price(111, customer=self.customer)

		out = save_item_price(item_code=self.item, price_list=PRICE_LIST, price_list_rate=250)
		self.addCleanup(frappe.delete_doc, "Item Price", out["name"], force=True, ignore_permissions=True)

		self.assertNotEqual(out["name"], negotiated)
		self.assertEqual(self._rate(negotiated), 111.0)
		self.assertEqual(self._rate(out["name"]), 250.0)
		self.assertFalse(frappe.db.get_value("Item Price", out["name"], "customer"))

	def test_updating_a_buying_price_leaves_a_supplier_price_alone(self):
		"""The mirror of the customer case on the buying side, and the reason the
		rule is written per party rather than per screen: a supplier's agreed
		cost is the number purchase orders are checked against."""
		buying = "Standard Buying"
		self.assertTrue(frappe.db.exists("Price List", buying), "no default buying price list on this site")
		supplier = frappe.db.get_value("Supplier", {}, "name")
		self.assertTrue(supplier, "the site has no Supplier to agree a cost with")
		standing = self._price(100, price_list=buying)
		agreed = self._price(90, price_list=buying, supplier=supplier)

		save_item_price(item_code=self.item, price_list=buying, price_list_rate=250)

		self.assertEqual(self._rate(agreed), 90.0, "the supplier's agreed cost was overwritten")
		self.assertEqual(self._rate(standing), 250.0)

	def test_editing_a_named_row_still_targets_exactly_that_row(self):
		"""The item detail page passes `name` when the user edits a price they
		picked off the list — including a customer one. That is an explicit
		choice of row and must keep working; the guard is for the case where no
		row was chosen."""
		list_price = self._price(100)
		negotiated = self._price(111, customer=self.customer)

		save_item_price(item_code=self.item, price_list=PRICE_LIST, price_list_rate=99, name=negotiated)

		self.assertEqual(self._rate(negotiated), 99.0, "an explicitly named row must be the row that changes")
		self.assertEqual(self._rate(list_price), 100.0)


class TestThePriceMatrixShowsTheListPrice(_PriceFixture):
	def _matrix_rows(self):
		out = get_price_list_matrix(PRICE_LIST, search=self.item)
		return [r for r in out["items"] if r["item_code"] == self.item]

	def test_an_item_appears_once_however_many_prices_it_has(self):
		"""The matrix is an editing grid keyed by item — the SPA collects changes
		into `{item_code: rate}` (PriceLists.vue), so a second row for the same
		item is not just confusing, it is an edit that cannot be expressed.
		Duplicates also eat the row limit, pushing other items off the end."""
		self._price(100)
		self._price(111, customer=self.customer)
		self._price(80, valid_from=today(), valid_upto=add_days(today(), 7))

		self.assertEqual(len(self._matrix_rows()), 1)

	def test_the_rate_shown_is_the_list_price(self):
		self._price(100)
		self._price(111, customer=self.customer)

		self.assertEqual(flt(self._matrix_rows()[0]["price_list_rate"]), 100.0)

	def test_an_item_with_only_a_negotiated_price_is_shown_as_unpriced(self):
		"""Because it is: it has no price for anyone but that customer. Showing
		111 would invite the operator to 'correct' a number that was never the
		list price."""
		self._price(111, customer=self.customer)

		row = self._matrix_rows()[0]
		self.assertIsNone(row["price_list_rate"])
		self.assertIsNone(row["item_price_name"])
