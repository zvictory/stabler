"""Static guard (WP-310): every transactional item picker must scope its search.

Root cause of "item not found in Purchase Invoice / Stock Transfer": the shared
inventory.list_items endpoint defaults to is_sales_item, so a purchase/transfer
picker silently hid purchase-only / raw-material items. The fix routes every
picker through composables/items.js `itemSearcher(context)` (or passes an explicit
`context:` to list_items). This test fails if any of the transactional forms below
regress to a context-less list_items call.

Parsed as text (no build needed).
"""

from __future__ import annotations

import os
import re
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler
_PAGES = os.path.join(_APP_ROOT, "public", "js", "pages")

# file -> expected context token that must appear.
_REQUIRED = {
	# SalesOrderForm.vue is a ~25-line variant switcher with no picker of its
	# own; both variants it selects between must carry the context.
	"sales/SalesOrderFormClassic.vue": "sales",
	"sales/SalesOrderFormModern.vue": "sales",
	"sales/QuotationForm.vue": "sales",
	"sales/SalesReturnForm.vue": "sales",
	"purchasing/PurchaseOrderForm.vue": "purchase",
	"purchasing/PurchaseInvoiceForm.vue": "purchase",
	"purchasing/PurchaseReceipts.vue": "purchase",
	"inventory/StockEntries.vue": "stock",
	"inventory/StockLedger.vue": "stock",
}

# a list_items(...) call that does NOT contain the word "context" before its close
_BARE_LIST_ITEMS = re.compile(r"list_items\"\s*,\s*\{(?:(?!context)[^{}])*\}", re.DOTALL)


class TestItemPickerContext(unittest.TestCase):
	def test_transactional_pickers_are_context_scoped(self):
		for rel, ctx in _REQUIRED.items():
			path = os.path.join(_PAGES, rel)
			with open(path, encoding="utf-8") as fh:
				src = fh.read()

			# Must declare its intent: either via the central itemSearcher(context)
			# or an explicit context: on a list_items call.
			has_searcher = f'itemSearcher("{ctx}"' in src
			has_ctx_literal = f'context: "{ctx}"' in src
			self.assertTrue(
				has_searcher or has_ctx_literal,
				f'{rel} must pick items with context \'{ctx}\' (itemSearcher("{ctx}") or context: "{ctx}").',
			)

			# Must NOT contain a context-less list_items call (the regression).
			bare = _BARE_LIST_ITEMS.search(src)
			self.assertIsNone(
				bare,
				f"{rel} still calls list_items without a context: {bare.group(0)[:80] if bare else ''}",
			)


if __name__ == "__main__":
	unittest.main()
