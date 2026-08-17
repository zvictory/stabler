"""A hand-built Purchase Invoice must be able to say what it settles.

`create_purchase_invoice` used to write item rows with no `purchase_receipt`,
`pr_detail`, `purchase_order` or `po_detail` at all, and every control ERPNext
has against paying twice for one delivery is keyed off exactly those fields:
the over-billing check joins Purchase Invoice Item to Purchase Order Item on
`po_detail`, `update_billing_status_in_pr` only touches rows carrying
`pr_detail`, and `set_expense_account` books the line to Stock Received But Not
Billed whenever `purchase_receipt` is empty. An unlinked bill is therefore not
a bill missing a reference — it is a bill nothing is allowed to argue with, and
the receipt it belongs to stays at `per_billed = 0` forever, which is also what
leaves the SRBNB balance permanently short of the unbilled-receipts report.

So these tests are about the links being written, being refused when they would
be a guess, and — the one that is easy to forget — surviving an edit. Rebuilding
`items` from the payload is what drops them, so without the carry-over an
operator could unlink a correctly linked draft just by saving it.

Bench-dependent: needs a site, a Company, a Supplier, a stock Item and a leaf
Warehouse. Run with
`bench run-tests --app stabler --module stabler.tests.test_pi_receipt_link`.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api.purchasing import (
	_receipt_links,
	create_purchase_invoice,
	update_purchase_invoice,
)


class TestPurchaseInvoiceReceiptLink(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		self.supplier = frappe.db.get_value("Supplier", {}, "name")
		if not all((self.company, self.supplier)):
			self.skipTest("Company and Supplier fixtures are required")

		# A stock item and a leaf warehouse, for the same reason the LCV suite
		# insists on them: ERPNext's receipt paths select on `is_stock_item`, and
		# a service item yields a receipt with no usable rows.
		self.item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1}, "name")
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not (self.item and self.warehouse):
			self.skipTest("A stock Item and a leaf Warehouse are required")

	def tearDown(self):
		frappe.db.rollback()

	# -- helpers ------------------------------------------------------------

	def _receipt(self, rows=1, supplier=None, submitted=True):
		"""A Purchase Receipt with `rows` lines of the same item.

		`db_set("docstatus", 1)` rather than `submit()` on purpose: these tests
		are about the link fields, not about the stock ledger, and a real submit
		would drag in valuation and GL setup that has nothing to do with what is
		being proved.
		"""
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = self.company
		pr.supplier = supplier or self.supplier
		for _ in range(rows):
			pr.append("items", {"item_code": self.item, "qty": 1, "rate": 100, "warehouse": self.warehouse})
		pr.insert(ignore_permissions=True)
		if submitted:
			pr.db_set("docstatus", 1)
		return pr

	def _other_stock_item(self):
		"""A second stock item, created rather than looked up.

		genesis-test.local carries exactly one enabled stock item, so a lookup
		would make the test that proves the warning is narrowed to the billed
		items skip — and a skipped test proves nothing about the narrowing.
		"""
		src = frappe.get_cached_doc("Item", self.item)
		item = frappe.new_doc("Item")
		item.item_code = f"TEST-OTHER-{frappe.generate_hash(length=8)}"
		item.item_group = src.item_group
		item.stock_uom = src.stock_uom
		item.is_stock_item = 1
		item.insert(ignore_permissions=True)
		return item.name

	def _payload(self, item_code=None, qty=1, rate=100):
		return [{"item_code": item_code or self.item, "qty": qty, "rate": rate}]

	def _create(self, **kwargs):
		kwargs.setdefault("items", self._payload())
		return create_purchase_invoice(company=self.company, supplier=self.supplier, **kwargs)

	def _lines(self, pi_name):
		return frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": pi_name},
			fields=[
				"name",
				"item_code",
				"qty",
				"purchase_receipt",
				"pr_detail",
				"purchase_order",
				"po_detail",
			],
			order_by="idx asc",
		)

	# -- (b) the links get written -----------------------------------------

	def test_a_named_receipt_puts_its_row_on_the_invoice_line(self):
		pr = self._receipt()
		res = self._create(purchase_receipt=pr.name)

		(line,) = self._lines(res["name"])
		self.assertEqual(line.purchase_receipt, pr.name)
		# The specific ROW, not merely the parent: `update_billing_status_in_pr`
		# and the over-billing check both work row-by-row, so a parent-only link
		# would still leave the receipt at per_billed = 0.
		self.assertEqual(line.pr_detail, pr.items[0].name)

	def test_without_a_receipt_the_line_stays_unlinked(self):
		# The old behavior, kept explicit: billing before receiving is a flow
		# ERPNext supports, so the absence of a link must remain legal.
		res = self._create()
		(line,) = self._lines(res["name"])
		self.assertFalse(line.purchase_receipt)
		self.assertFalse(line.pr_detail)

	def test_a_receipt_row_carrying_an_order_passes_the_order_link_through(self):
		pr = self._receipt()
		# po_detail is the field the over-billing check joins on. The mapping is
		# asserted at the resolver rather than through a saved invoice because
		# ERPNext's `validate_with_previous_doc` resolves po_detail against a real
		# Purchase Order Item — proving the pass-through would otherwise mean
		# building a whole order, and the order is not what this test is about.
		frappe.db.set_value(
			"Purchase Receipt Item",
			pr.items[0].name,
			{"purchase_order": "SOME-PO", "purchase_order_item": "SOME-PO-ITEM"},
		)

		links = _receipt_links(pr.name, [self.item])
		self.assertEqual(links[self.item]["pr_detail"], pr.items[0].name)
		self.assertEqual(links[self.item]["purchase_order"], "SOME-PO")
		self.assertEqual(links[self.item]["po_detail"], "SOME-PO-ITEM")

	# -- (b) the links are refused when they would be a guess ---------------

	def test_the_same_item_on_two_receipt_rows_is_refused_rather_than_guessed(self):
		pr = self._receipt(rows=2)
		# Picking either row would put the billed amount against the wrong one:
		# the over-billing check would then clear a line that is already fully
		# billed and block one that is not.
		with self.assertRaises(frappe.ValidationError):
			self._create(purchase_receipt=pr.name)

	def test_an_item_the_receipt_does_not_carry_is_refused(self):
		pr = self._receipt()
		other = frappe.db.get_value("Item", {"disabled": 0, "name": ("!=", self.item)}, "name")
		if not other:
			self.skipTest("a second Item is required")
		with self.assertRaises(frappe.ValidationError):
			self._create(items=self._payload(item_code=other), purchase_receipt=pr.name)

	def test_a_draft_receipt_cannot_be_billed(self):
		pr = self._receipt(submitted=False)
		with self.assertRaises(frappe.ValidationError):
			self._create(purchase_receipt=pr.name)

	def test_another_suppliers_receipt_cannot_be_billed(self):
		other = frappe.db.get_value("Supplier", {"name": ("!=", self.supplier)}, "name")
		if not other:
			self.skipTest("a second Supplier is required")
		pr = self._receipt(supplier=other)
		with self.assertRaises(frappe.ValidationError):
			self._create(purchase_receipt=pr.name)

	def test_an_unknown_receipt_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._create(purchase_receipt="PR-DOES-NOT-EXIST")

	def test_a_linked_invoice_may_not_also_update_stock(self):
		pr = self._receipt()
		# The receipt already took the goods in. Letting the invoice do it again
		# is the same delivery counted twice into stock.
		with self.assertRaises(frappe.ValidationError):
			self._create(purchase_receipt=pr.name, update_stock=1, set_warehouse=self.warehouse)

	# -- (b) the links survive an edit --------------------------------------

	def test_editing_a_linked_draft_does_not_silently_unlink_it(self):
		pr = self._receipt()
		res = self._create(purchase_receipt=pr.name)

		update_purchase_invoice(
			name=res["name"],
			supplier=self.supplier,
			items=self._payload(qty=2),
			modified=frappe.db.get_value("Purchase Invoice", res["name"], "modified"),
		)

		(line,) = self._lines(res["name"])
		self.assertEqual(line.qty, 2)  # the edit really did take
		self.assertEqual(line.purchase_receipt, pr.name)
		self.assertEqual(line.pr_detail, pr.items[0].name)

	# -- (a) the warning ----------------------------------------------------

	def test_an_unlinked_invoice_warns_when_the_goods_are_on_an_unbilled_receipt(self):
		pr = self._receipt()
		with patch.object(frappe, "msgprint") as msgprint:
			self._create()
		said = " ".join(str(call.args[0]) for call in msgprint.call_args_list if call.args)
		self.assertIn(pr.name, said)

	def test_no_warning_when_the_invoice_names_the_receipt(self):
		pr = self._receipt()
		with patch.object(frappe, "msgprint") as msgprint:
			self._create(purchase_receipt=pr.name)
		said = " ".join(str(call.args[0]) for call in msgprint.call_args_list if call.args)
		self.assertNotIn(pr.name, said)

	def test_no_warning_when_the_receipt_is_for_other_items(self):
		other = self._other_stock_item()
		pr = self._receipt()
		# Narrowed to the items actually being billed on purpose: a
		# supplier-wide warning fires on every invoice the moment one old
		# receipt is outstanding, and a warning that is always on is furniture.
		with patch.object(frappe, "msgprint") as msgprint:
			self._create(items=self._payload(item_code=other))
		said = " ".join(str(call.args[0]) for call in msgprint.call_args_list if call.args)
		self.assertNotIn(pr.name, said)

	def test_a_fully_billed_receipt_does_not_warn(self):
		pr = self._receipt()
		pr.db_set("per_billed", 100)
		with patch.object(frappe, "msgprint") as msgprint:
			self._create()
		said = " ".join(str(call.args[0]) for call in msgprint.call_args_list if call.args)
		self.assertNotIn(pr.name, said)
