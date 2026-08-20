"""A bill posted on the day the goods arrived must stay on that day.

`create_purchase_invoice` and `update_purchase_invoice` both take a
`posting_date`, and `_apply_invoice_payload` writes it onto the document — but
ERPNext throws it away again unless `set_posting_time` is set: `validate_posting_time`
(erpnext/utilities/transaction_base.py) overwrites `posting_date` with *now* for
any document that does not carry the flag. The API therefore accepted a date and
silently posted today's, which is not a cosmetic difference:

  * the exchange rate is validated and applied against the posting date, so a
    six-month-old import bill was being valued at today's rate — measured on
    msa.erpstable.com 2026-08-20, USD/UZS 12 187.68 on the arrival date versus
    11 820.40 that morning, a 163 million UZS gap on one 380 420 USD invoice;
  * with `update_stock`, the posting date IS the stock movement's date, so the
    goods entered the ledger months after they physically arrived, and every
    sale in between had no stock to consume.

The whole point of these tests is that the date survives the round trip. They
would pass just as well against a document that never left the draft state, and
that is deliberate: the bug is in what the API stores, not in what submit does.

Bench-dependent: needs a site, a Company and a Supplier. Run with
`bench run-tests --app stabler --module stabler.tests.test_purchase_invoice_posting_date`.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from stabler.api.purchasing import create_purchase_invoice, update_purchase_invoice


class TestPurchaseInvoicePostingDate(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		self.supplier = frappe.db.get_value("Supplier", {}, "name")
		if not all((self.company, self.supplier)):
			self.skipTest("Company and Supplier fixtures are required")
		self.item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1}, "name")
		if not self.item:
			self.skipTest("A stock Item is required")
		# Far enough back that nothing could mistake it for a rounding of "now",
		# and inside a period no fixture is likely to have closed.
		self.back_date = getdate(add_days(today(), -60))

	def tearDown(self):
		frappe.db.rollback()

	def _payload(self, qty=1, rate=100):
		return [{"item_code": self.item, "qty": qty, "rate": rate}]

	# The bills below stay in the company's own currency on purpose: this is
	# about the date the API stores, and a foreign-currency bill would drag the
	# CBU rate validation into a test that is not about rates.

	def test_a_new_bill_keeps_the_date_it_was_given(self):
		res = create_purchase_invoice(
			company=self.company,
			supplier=self.supplier,
			items=self._payload(),
			posting_date=str(self.back_date),
		)
		stored = getdate(frappe.db.get_value("Purchase Invoice", res["name"], "posting_date"))
		self.assertEqual(
			stored,
			self.back_date,
			"the API accepted a posting date and stored a different one",
		)

	def test_editing_a_bill_can_move_its_date_into_the_past(self):
		# The realistic shape of the bug: a draft opened at today's date, then
		# corrected to the day the goods actually landed.
		res = create_purchase_invoice(
			company=self.company,
			supplier=self.supplier,
			items=self._payload(),
		)
		update_purchase_invoice(
			name=res["name"],
			supplier=self.supplier,
			items=self._payload(),
			posting_date=str(self.back_date),
			modified=frappe.db.get_value("Purchase Invoice", res["name"], "modified"),
		)
		stored = getdate(frappe.db.get_value("Purchase Invoice", res["name"], "posting_date"))
		self.assertEqual(
			stored,
			self.back_date,
			"editing a draft could not move its posting date off today",
		)

	def test_a_bill_with_no_date_given_still_posts_today(self):
		# The flag must not turn "no opinion" into some other day: an omitted
		# posting_date has always meant today and callers rely on it.
		res = create_purchase_invoice(
			company=self.company,
			supplier=self.supplier,
			items=self._payload(),
		)
		stored = getdate(frappe.db.get_value("Purchase Invoice", res["name"], "posting_date"))
		self.assertEqual(stored, getdate(today()))
