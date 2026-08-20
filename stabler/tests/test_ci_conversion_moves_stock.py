"""Converting a Commercial Invoice can also be the moment the goods arrive.

`convert_ci_to_purchase_invoice` opened the payable and stopped there: no
`update_stock`, no warehouse. On the truck route that is right — a Purchase
Receipt moves the stock and the bill only owes money. On msa there is no truck
route and no Purchase Receipt (measured 2026-08-20: 978 containers, 0 Truck
Receipts), so an invoice that does not move stock means the goods never enter a
warehouse at all.

That left the two halves of one chain disagreeing in a way neither could see:

    convert_ci_to_purchase_invoice   writes an invoice with update_stock = 0
    _stock_receipts_for_grn          finds invoices with update_stock = 1

So the converter produced exactly the document the landed-cost builder is
blind to, and the chain ended with a log line saying it found nothing. The
coupling is asserted here in both directions, because it is invisible in either
file alone — each one is self-consistent and only the pair is wrong.

The warehouse is a parameter rather than a default. When the goods enter stock
is a real decision: a CI is dated when the supplier invoiced, which on this
route is months before the container is discharged, and `posting_date` is the CI
date — so turning stock on unconditionally would value the goods at a rate from
before they existed here. Passing no warehouse keeps the historical behaviour
exactly, which is also what every existing caller does.

Source guards: the converter needs a site, a supplier, items and a warehouse,
so its behaviour test is bench-only (`make test-bench`). What runs on every push
is the agreement between the two files.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

API_IMPORTS = os.path.join(_ROOT, "api", "imports.py")
HOOKS = os.path.join(_ROOT, "stabler", "imports_module", "hooks.py")
PURCHASING = os.path.join(_ROOT, "api", "purchasing.py")


def read(path: str) -> str:
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def func_body(src: str, name: str) -> str:
	match = re.search(rf"^def {name}\(", src, re.M)
	assert match, f"{name} not found"
	tail = src[match.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


def signature(body: str) -> str:
	return body[: body.index("):") + 2]


class TheConverterCanPutTheGoodsInAWarehouse(unittest.TestCase):
	def setUp(self):
		self.body = func_body(read(API_IMPORTS), "convert_ci_to_purchase_invoice")

	def test_it_takes_a_warehouse_and_defaults_to_not_moving_stock(self):
		# Optional, and defaulting to None: every existing caller passes two
		# arguments and must keep building the payable-only invoice it built
		# before. A default warehouse would back-date stock into a warehouse
		# nobody chose, at the CI's rate.
		sig = signature(self.body)
		self.assertIn("warehouse", sig)
		self.assertRegex(sig, r"warehouse[^,)]*=\s*None")

	def test_a_warehouse_turns_the_stock_flag_on(self):
		self.assertIn("doc.update_stock = 1", self.body)
		self.assertIn("doc.set_warehouse = warehouse", self.body)

	def test_the_rows_carry_the_warehouse_too(self):
		# ERPNext values each line against the line's own warehouse; a header
		# `set_warehouse` with bare rows throws at submit, which is the failure
		# this route would hit only after the accountant pressed the button.
		self.assertRegex(self.body, r'\[?"warehouse"\]?\s*[:=]\s*warehouse')

	def test_a_bad_warehouse_is_refused_before_anything_is_written(self):
		# Same three questions `_validate_invoice_inputs` already asks, and one
		# more this route needs: the converter is company-scoped end to end (it
		# throws on a CI from another company), so a warehouse from another
		# company would be the one cross-company hole left in it.
		lookup = re.search(r'frappe\.db\.(?:exists|get_value)\(\s*"Warehouse"', self.body)
		self.assertIsNotNone(lookup, "the warehouse is never looked up at all")
		self.assertIn("is_group", self.body)
		self.assertIn("company", self.body)
		creation = self.body.index('doc = frappe.new_doc("Purchase Invoice")')
		self.assertLess(lookup.start(), creation, "the warehouse is checked after the invoice is built")

	def test_the_dry_run_says_what_it_would_do_with_the_stock(self):
		# The preview is what the accountant reads before committing. An invoice
		# that moves stock and one that does not are different documents with
		# different consequences, so the preview must not describe both the same.
		preview = self.body[: self.body.index("if cint(dry_run):")]
		self.assertIn("update_stock", preview)


class TheConverterAndTheLandedCostAgree(unittest.TestCase):
	"""The two halves of the chain must key on the same fact.

	Neither file can see this on its own: the converter is self-consistent, the
	resolver is self-consistent, and the chain is broken. Asserting it here is
	the only place the disagreement is visible.
	"""

	def setUp(self):
		self.converter = func_body(read(API_IMPORTS), "convert_ci_to_purchase_invoice")
		self.resolver = func_body(read(HOOKS), "_stock_receipts_for_grn")

	def test_the_flag_the_converter_writes_is_the_flag_the_resolver_filters_on(self):
		self.assertIn("update_stock", self.converter)
		self.assertIn("update_stock", self.resolver)

	def test_the_link_the_converter_writes_is_the_link_the_resolver_joins_on(self):
		# `custom_commercial_invoice` is what ties the invoice back to its CI.
		# The resolver reaches the invoice through it; if the converter ever
		# stopped writing it, the resolver would find nothing and log that the
		# GRN has no stock document — with the invoice sitting right there.
		self.assertIn("custom_commercial_invoice", self.converter)
		self.assertIn("custom_commercial_invoice", self.resolver)


class TheHouseRuleForStockBearingBillsIsNotForked(unittest.TestCase):
	def test_purchasing_already_refuses_stock_without_a_warehouse(self):
		# The rule already exists — `_validate_invoice_inputs` in purchasing.py.
		# This test does not duplicate it; it pins that the rule is there, so the
		# converter's own check reads as conforming to a house rule rather than
		# inventing a second, divergent one.
		body = func_body(read(PURCHASING), "_validate_invoice_inputs")
		self.assertIn("update_stock and not set_warehouse", body)


if __name__ == "__main__":
	unittest.main()
