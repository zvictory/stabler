"""Guards the child-table columns the tender document chain queries.

`tender_workspace` walks Sales/Purchase Orders to their downstream documents with
ONE child-table query per hop, so the column it selects must be the one that child
DocType actually carries:

* `Delivery Note Item` links its order as **`against_sales_order`** — a bare
  `sales_order` column does not exist there, and selecting it made the whole
  workspace answer 500 `OperationalError (1054) Unknown column 'sales_order'`,
  which in turn left the PO control board stuck on its empty state (the SPA awaits
  both calls in one `Promise.all`).
* `Sales Invoice Item` and `Purchase Invoice Item` DO carry `sales_order` /
  `purchase_order`, so those hops legitimately differ from the delivery hop.

The queried column and the key emitted to the SPA are NOT the same thing:
`TenderDocumentChain.vue` reads `row.sales_order`, so the delivery rows must keep
that key while querying `against_sales_order`.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TENDER_API = os.path.normpath(os.path.join(_HERE, "..", "api", "tender.py"))


def _slice(source: str, name: str) -> str:
	start = source.index(f"def {name}(")
	return source[start : source.index("\ndef ", start + 1)]


class TestTenderDocumentChainSource(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with open(_TENDER_API, encoding="utf-8") as source:
			cls.api = source.read()
		cls.helper = _slice(cls.api, "_linked_document_rows")
		cls.sales = _slice(cls.api, "_sales_document_chain")
		cls.purchase = _slice(cls.api, "_purchase_document_chain")

	def test_the_queried_column_can_differ_from_the_emitted_key(self):
		"""`link_field` names the key the SPA reads; `item_link_field` names the
		column the child table really has."""
		self.assertIn("item_link_field: str | None = None", self.helper)
		self.assertIn("column = item_link_field or link_field", self.helper)
		self.assertRegex(
			self.helper, re.compile(r'filters=\{"parent": \["in", parent_names\], column:', re.S)
		)
		self.assertIn('fields=["parent", column]', self.helper)
		self.assertIn("link.get(column)", self.helper)

	def test_delivery_hop_queries_against_sales_order(self):
		"""`Delivery Note Item.sales_order` does not exist — selecting it 500s."""
		self.assertIn("Delivery Note Item", self._deliveries())
		self.assertIn('item_link_field="against_sales_order"', self._deliveries())

	def test_delivery_rows_keep_the_sales_order_key_for_the_spa(self):
		"""`TenderDocumentChain.vue` keys rows on `row.sales_order`."""
		self.assertIn('"sales_order"', self._deliveries())

	def _deliveries(self) -> str:
		# rindex: the early return also mentions both keys.
		return self.sales[self.sales.rindex('"deliveries"') : self.sales.rindex('"invoices"')]

	def test_invoice_hops_query_their_own_order_column(self):
		"""These child tables really do carry the bare column — no override."""
		sales_invoices = self.sales[self.sales.rindex('"invoices"') :]
		self.assertIn("Sales Invoice Item", sales_invoices)
		self.assertIn('"sales_order"', sales_invoices)
		self.assertNotIn("item_link_field", sales_invoices)
		self.assertIn('"purchase_order"', self.purchase)
		self.assertNotIn("item_link_field", self.purchase)


if __name__ == "__main__":
	unittest.main()
