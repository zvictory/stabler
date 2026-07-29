"""Static contracts ensuring dashboard drill-down lists share tender filters."""

from __future__ import annotations

import os
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _read(*parts: str) -> str:
	with open(os.path.join(_ROOT, *parts), encoding="utf-8") as source:
		return source.read()


class TestTenderListDrilldown(unittest.TestCase):
	def test_document_list_apis_accept_tender_only(self):
		purchasing = _read("api", "purchasing.py")
		sales = _read("api", "sales.py")
		for function in ("list_purchase_orders", "list_purchase_receipts", "list_purchase_invoices"):
			body = purchasing[purchasing.index(f"def {function}(") :]
			self.assertIn("tender_only", body[:3000])
		for function in ("list_sales_orders", "list_sales_invoices", "list_delivery_notes"):
			body = sales[sales.index(f"def {function}(") :]
			self.assertIn("tender_only", body[:3500])

	def test_list_pages_read_dashboard_query_filters(self):
		paths = (
			("public", "js", "pages", "sales", "SalesOrders.vue"),
			("public", "js", "pages", "sales", "SalesInvoices.vue"),
			("public", "js", "pages", "purchasing", "PurchaseOrders.vue"),
			("public", "js", "pages", "purchasing", "PurchaseReceipts.vue"),
			("public", "js", "pages", "purchasing", "PurchaseInvoices.vue"),
		)
		for path in paths:
			source = _read(*path)
			self.assertIn("useRoute", source)
			self.assertIn("route.query.from_date", source)
			self.assertIn("route.query.to_date", source)
			self.assertIn("tender_only", source)


if __name__ == "__main__":
	unittest.main()
