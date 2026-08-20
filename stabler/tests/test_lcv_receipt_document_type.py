"""A landed cost must reach whatever document actually moved the goods.

ERPNext capitalizes a Landed Cost Voucher onto a receipt document, and it accepts
three kinds: Purchase Receipt, Stock Entry, and Purchase Invoice. The invoice is
accepted whenever `update_stock` is on -- `validate_receipt_documents`
(erpnext/stock/doctype/landed_cost_voucher/landed_cost_voucher.py:147-158) checks
exactly that and nothing else, and `get_pr_items` builds the child table name as
`receipt_document_type + " Item"`, so `Purchase Invoice Item` needs no special
case anywhere.

Stabler wrote "Purchase Receipt" as a constant in three places instead. On msa
that is not a limitation, it is a dead end: the Commercial Invoice is converted
straight into an `update_stock` Purchase Invoice and no Purchase Receipt is ever
created, so `_build_and_save_lcv` logged "no submitted Purchase Receipts --
skipping LCV" and returned None every time. Measured 2026-08-20 on
msa.erpstable.com: 0 Landed Cost Vouchers, 0 Purchase Receipts from the imports
route, 675 submitted purchase invoices. Freight was 76 separate ALN bills posted
straight to expense, never reaching item valuation at all.

These are source guards, not behaviour tests: the live resolution needs a site,
a GRN and a submitted stock document, and lives in the bench-only module. What
they defend is that the constant does not come back -- which is how it would
break again, silently, with the chain merely logging that it found nothing.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

HOOKS = os.path.join(_ROOT, "stabler", "imports_module", "hooks.py")
LCV_MATH = os.path.join(_ROOT, "stabler", "imports_module", "lcv_math.py")
API_LCV = os.path.join(_ROOT, "api", "lcv.py")
API_IMPORTS = os.path.join(_ROOT, "api", "imports.py")


def read(path):
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def signature(body):
	"""The def line through its closing `):` — signatures here span several lines."""
	return body[: body.index("):") + 2]


def func_body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TheBuilderTakesTheTypeFromItsCaller(unittest.TestCase):
	def setUp(self):
		self.body = func_body(read(LCV_MATH), "build_lcv_payload")

	def test_the_row_type_is_not_a_literal(self):
		# The whole defect in one line: `{"receipt_document_type": "Purchase
		# Receipt", ...}` inside the row comprehension.
		self.assertNotIn(
			'"receipt_document_type": "Purchase Receipt"',
			self.body,
			"the payload still pins every voucher row to Purchase Receipt",
		)

	def test_the_parameter_exists_and_keeps_the_old_default(self):
		sig = signature(self.body)
		self.assertIn("receipt_document_type", sig)
		self.assertIn('receipt_document_type="Purchase Receipt"', sig)


class TheGrnFindsWhicheverDocumentMovedTheStock(unittest.TestCase):
	def setUp(self):
		self.src = read(HOOKS)
		self.body = func_body(self.src, "_stock_receipts_for_grn")

	def test_it_still_prefers_a_purchase_receipt(self):
		# The truck-receipt route is live on other tenants and must be found first;
		# the invoice is the fallback, not a replacement.
		pr = self.body.find("Truck Receipt")
		pi = self.body.find("Purchase Invoice")
		self.assertNotEqual(pr, -1, "the truck-receipt route is gone")
		self.assertNotEqual(pi, -1, "the invoice route was never added")
		self.assertLess(pr, pi, "the invoice is being looked at before the purchase receipt")

	def test_the_invoice_must_actually_move_stock(self):
		# ERPNext refuses a Purchase Invoice with no stock impact, so handing it one
		# would trade a silent no-op for a loud one. Filter it out here instead.
		self.assertIn("update_stock", self.body)

	def test_it_returns_the_type_alongside_the_names(self):
		# A bare list of names cannot say which doctype they belong to, and every
		# consumer needs that: the payload row, the freeze-rule join, and the
		# review's child-table lookup all key on it.
		self.assertIn("-> tuple", signature(self.body))
		self.assertIn('return "Purchase Receipt", prs', self.body)
		self.assertIn('"Purchase Invoice", invoices', self.body)

	def test_the_only_caller_outside_this_module_moved_with_it(self):
		# stabler/api/imports.py reaches into this function by name to build the
		# accountant's review. The mapping is deliberately owned in one place; a
		# second copy is how the review would keep listing Purchase Receipts only.
		imports_src = read(API_IMPORTS)
		self.assertNotIn("_submitted_prs_for_grn", imports_src)
		self.assertIn("_stock_receipts_for_grn", imports_src)


class TheFreezeRuleSeesInvoiceBackedVouchers(unittest.TestCase):
	"""The basis lock is money math, so it must not quietly stop engaging.

	`_vouchers_on_receipts` is what `_locking_voucher` and `_restamp_drafts` are
	built on. Its join filtered `receipt_document_type = 'Purchase Receipt'`, so
	an invoice-backed voucher was invisible to it -- and an invisible submitted
	voucher freezes nothing, which is exactly the state the lock exists to
	prevent: a second voucher distributing on a different basis over stock the
	first already capitalized.
	"""

	def setUp(self):
		self.src = read(API_LCV)

	def test_the_join_no_longer_pins_one_type(self):
		self.assertNotIn(
			"lcpr.receipt_document_type = 'Purchase Receipt'",
			self.src,
			"the freeze-rule join still ignores invoice-backed vouchers",
		)

	def test_submit_does_not_drop_invoice_rows_before_checking_the_lock(self):
		body = func_body(self.src, "submit_landed_cost_voucher")
		self.assertNotIn(
			'row.receipt_document_type == "Purchase Receipt"',
			body,
			"submit still collects only Purchase Receipt rows, so the lock cannot fire",
		)


if __name__ == "__main__":
	unittest.main()
