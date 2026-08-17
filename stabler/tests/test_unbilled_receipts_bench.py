"""One receipt, one draft bill — proved against a live site.

The defect this pins: a DRAFT Purchase Invoice does not move ``per_billed``
(ERPNext writes that on submit), so the unbilled report kept returning the same
receipt with the same *Create invoice* button, and a double-click or a second
operator piled N drafts onto one receipt.

Why these live here and not in the frappe-free suite: the guard IS a SQL
predicate over ``docstatus`` on two real tables. A fake DB would only prove that
our model of the join behaves as we modelled it — the very thing that cannot
catch the widening this suite exists to catch. ``unbilled_receipts`` and
``create_purchase_invoice_from_pr`` had zero bench coverage before this file.

    cd ~/frappe-bench-local && bench --site <test-site> run-tests \\
        --module stabler.tests.test_unbilled_receipts_bench
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api.purchasing import (
	_draft_invoices_by_receipt,
	create_purchase_invoice_from_pr,
	create_purchase_return,
	unbilled_receipts,
)

#: A supplier of this suite's own, rolled back with every test. The report pages
#: 50 rows oldest-first, so a receipt filed against a shared supplier on a site
#: with history would not reliably be on the page under test.
SUPPLIER_NAME = "_Test Unbilled Receipts Supplier"


class UnbilledReceiptsDraftGuard(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("A Company fixture is required")

		# Same reason the receipt-link suite insists on both: ERPNext's receipt
		# paths select on `is_stock_item`, and a service item yields a receipt
		# with no usable rows.
		self.item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1}, "name")
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not (self.item and self.warehouse):
			self.skipTest("A stock Item and a leaf Warehouse are required")

		self.supplier = (
			frappe.get_doc({"doctype": "Supplier", "supplier_name": SUPPLIER_NAME})
			.insert(ignore_permissions=True)
			.name
		)

	def tearDown(self):
		frappe.db.rollback()

	# -- helpers ------------------------------------------------------------

	def _receipt(self, qty=10, rate=100):
		"""A submitted Purchase Receipt for this suite's supplier.

		``db_set("docstatus", 1)`` rather than ``submit()``, as in
		``test_pi_receipt_link``: what is under test is a docstatus predicate
		over the invoice tables, and a real submit would drag in valuation and
		GL setup that has nothing to do with it.
		"""
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = self.company
		pr.supplier = self.supplier
		pr.append("items", {"item_code": self.item, "qty": qty, "rate": rate, "warehouse": self.warehouse})
		pr.insert(ignore_permissions=True)
		pr.db_set("docstatus", 1)
		return pr

	def _bill(self, receipt: str) -> str:
		"""Raise the first draft the way the screen does."""
		return create_purchase_invoice_from_pr(receipt)["name"]

	def _submit(self, invoice: str) -> str:
		"""Mark a bill submitted at both levels, as a real submit does.

		The parent alone is not enough: ERPNext reads the CHILD docstatus when it
		works out what is already billed, so a parent-only flip would model a
		state the application cannot produce.
		"""
		frappe.db.set_value("Purchase Invoice", invoice, "docstatus", 1)
		frappe.db.sql(
			"UPDATE `tabPurchase Invoice Item` SET docstatus = 1 WHERE parent = %(parent)s",
			{"parent": invoice},
		)
		return invoice

	def _row(self, receipt: str) -> dict:
		payload = unbilled_receipts(company=self.company, supplier=self.supplier)
		matches = [row for row in payload["rows"] if row["name"] == receipt]
		self.assertEqual(len(matches), 1, f"{receipt} is not on the unbilled page")
		return matches[0]

	# -- the guard ----------------------------------------------------------

	def test_second_call_is_refused_while_a_draft_bill_is_outstanding(self):
		"""The button that a draft leaves behind must not raise a second bill.

		This is the whole defect: the draft moves no `per_billed`, the row comes
		back, and nothing downstream reconciles two bills against one receipt.
		"""
		pr = self._receipt()
		first = self._bill(pr.name)

		with self.assertRaises(frappe.ValidationError) as caught:
			create_purchase_invoice_from_pr(pr.name)

		self.assertIn(first, str(caught.exception), "the refusal must name the draft that blocks it")
		self.assertEqual(
			frappe.db.count("Purchase Invoice Item", {"purchase_receipt": pr.name, "docstatus": 0}),
			1,
			"the refused call must not have inserted a second draft",
		)

	def test_the_row_names_the_draft_that_blocks_it(self):
		"""A refusal the screen cannot see in advance is a dead-end button."""
		pr = self._receipt()
		self.assertIsNone(self._row(pr.name)["draft_invoice"], "nothing bills it yet")

		drafted = self._bill(pr.name)
		self.assertEqual(self._row(pr.name)["draft_invoice"], drafted)

	def test_a_partly_billed_receipt_can_still_be_billed_for_the_remainder(self):
		"""A SUBMITTED sibling is partial billing, not a blocker.

		Widening the predicate to ``docstatus < 2`` would stop this receipt from
		ever being billed for its remainder outside the Desk — and the remainder
		is exactly the population this report chases. This test is what fails if
		someone widens it.

		Partly billed for real, not just in the name of the test: the first bill
		is cut down to 4 of the 10 received before it is submitted, so ERPNext
		has 6 left to map. Billing the full quantity and calling it partial is
		how the first version of this test passed while proving nothing — it
		errored with "All items have already been Invoiced" the moment the
		submit was made faithful.
		"""
		pr = self._receipt(qty=10)
		first = self._bill(pr.name)
		frappe.db.sql(
			"UPDATE `tabPurchase Invoice Item` SET qty = 4 WHERE parent = %(parent)s",
			{"parent": first},
		)
		self._submit(first)

		self.assertEqual(
			_draft_invoices_by_receipt([pr.name]),
			{},
			"a submitted bill must not register as an outstanding draft",
		)
		self.assertIsNone(self._row(pr.name)["draft_invoice"], "the row must keep its button")

		remainder = create_purchase_invoice_from_pr(pr.name)["name"]
		self.assertEqual(
			frappe.db.get_value("Purchase Invoice Item", {"parent": remainder}, "qty"),
			6,
			"the second bill must cover the remainder, not the whole receipt again",
		)
		self.assertEqual(
			_draft_invoices_by_receipt([pr.name]),
			{pr.name: remainder},
			"the bill raised for the remainder becomes the blocker in its turn",
		)

	def test_a_draft_debit_note_does_not_block_the_bill(self):
		"""A credit document is not a bill, and must not stand in for one.

		ERPNext copies ``purchase_receipt`` onto the rows of a return, and
		``create_purchase_return`` leaves the debit note as a DRAFT by default —
		so a receipt that is partly billed and then partly returned would lose
		its Create-invoice button to a document that bills nothing, stranding the
		unbilled remainder with no path outside the Desk. That is the same dead
		end ``docstatus = 0`` exists to prevent, reached from the other side.
		"""
		pr = self._receipt()
		billed = self._submit(self._bill(pr.name))
		debit_note = create_purchase_return(purchase_invoice=billed)["name"]

		# If ERPNext ever stops carrying the link, this test must say so rather
		# than pass for the wrong reason: with no link there is nothing to skip.
		self.assertTrue(
			frappe.db.exists("Purchase Invoice Item", {"parent": debit_note, "purchase_receipt": pr.name}),
			"the debit note is expected to carry the receipt link — that is what makes it a blocker",
		)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", debit_note, "docstatus"), 0)

		self.assertEqual(_draft_invoices_by_receipt([pr.name]), {})
		self.assertIsNone(self._row(pr.name)["draft_invoice"], "the row must keep its button")

	def test_a_cancelled_bill_does_not_block_the_receipt(self):
		"""Cancelling the draft has to give the receipt its button back.

		Otherwise a mistaken bill strands the goods permanently — the same
		dead end the widened predicate would create, reached by the one route
		operators actually take to undo a mistake.
		"""
		pr = self._receipt()
		mistake = self._bill(pr.name)
		frappe.get_doc("Purchase Invoice", mistake).db_set("docstatus", 2)

		self.assertEqual(_draft_invoices_by_receipt([pr.name]), {})
		self.assertIsNone(self._row(pr.name)["draft_invoice"])

	def test_the_page_asks_once_for_every_receipt_it_shows(self):
		"""One query for the page, and none at all for an empty one.

		Counted, not asserted in prose: a per-receipt loop returns the same
		mapping and would leave a result-only test green, while putting a query
		per row behind a report that pages fifty of them. The empty case is
		load-bearing for a different reason — ``IN ()`` is a syntax error rather
		than an empty match.
		"""
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as spy:
			self.assertEqual(_draft_invoices_by_receipt([]), {})
			self.assertEqual(_draft_invoices_by_receipt(None), {})
		self.assertEqual(spy.call_count, 0, "an empty page must not reach the database")

		first, second = self._receipt(), self._receipt()
		drafted = self._bill(first.name)
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as spy:
			found = _draft_invoices_by_receipt([first.name, second.name])
		self.assertEqual(spy.call_count, 1, "one query for the page, not one per receipt")
		self.assertEqual(
			found,
			{first.name: drafted},
			"the batched lookup must answer for every receipt on the page at once",
		)
