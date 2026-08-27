"""A sales return must offer the items that are OUT of stock — that is the point.

`list_items` joins `tabBin` and, when given a warehouse, keeps only rows with
`actual_qty > 0`. That is right for a sales order or an invoice — you cannot ship
what you do not have — and backwards for a return, where the goods are coming
back INTO the warehouse and are therefore not in it yet. An item that sold out
could not be returned at all, and nothing said why: the search simply came up
empty.

Measured on anjan 2026-08-27, in `Tayyor mahsulot - A` — the warehouse all 229 of
its direct returns actually use:

    sellable items ever stocked there (Bin rows)   243
    ... of them in stock right now                 137
    ... hidden from the return picker              106

So a third of the returnable catalogue was invisible on the one screen that
needs it most.

The fix is NOT to drop the warehouse scope. Perpetual inventory is on and
ERPNext's valuation fallback for an incoming line reads the last ledger entry
**in that same warehouse**, then Item.valuation_rate / standard_rate / a buying
price — it never looks at the item's stock elsewhere. Only 55 of anjan's 319
sellable stock items carry any of those fallbacks, so offering the whole
catalogue would trade an empty picker for "Valuation Rate Missing" at submit,
which is worse: the operator has typed the whole credit note by then.

Scoping to "ever stocked here" is what both cases want, and it is what
`list_items`' own docstring already claimed it did. Residual, deliberately not
chased: 5 of the 243 Bin rows have no ledger entry behind them (rows opened by a
reservation that never moved stock), so those five can still hit the valuation
error. Five is not worth an EXISTS over the ledger on every keystroke.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETURN_FORM = (ROOT / "public/js/pages/sales/SalesReturnForm.vue").read_text(encoding="utf-8")
ITEMS_JS = (ROOT / "public/js/composables/items.js").read_text(encoding="utf-8")
INVENTORY_API = (ROOT / "api/inventory.py").read_text(encoding="utf-8")


def _list_items_body() -> str:
	start = INVENTORY_API.index("def list_items(")
	rest = INVENTORY_API[start:]
	end = rest.find("\n@frappe.whitelist", 1)
	return rest if end == -1 else rest[:end]


BODY = _list_items_body()


class TestTheReturnPickerAsksForEverStocked(unittest.TestCase):
	def test_the_return_screen_opts_in(self):
		searcher = re.search(r"const searchItems = itemSearcher\([^;]*\);", RETURN_FORM, flags=re.S)
		self.assertIsNotNone(searcher, "the return form no longer builds an item searcher")
		self.assertIn(
			"everStocked: true",
			re.sub(r"\s+", " ", searcher.group(0)),
			"without it the picker hides every item the warehouse has none of — which is "
			"every item a return is about",
		)

	def test_it_still_scopes_to_the_return_warehouse(self):
		"""Dropping the warehouse instead would offer items that have never been
		in it, and those fail at submit on a missing valuation rate."""
		searcher = re.search(r"const searchItems = itemSearcher\([^;]*\);", RETURN_FORM, flags=re.S)
		self.assertIn("warehouse:", re.sub(r"\s+", " ", searcher.group(0)))

	def test_it_is_still_a_sales_picker(self):
		"""A return is a sales document and has no business offering raw materials
		— `create_direct_sales_return` rejects a non-sales item anyway."""
		self.assertRegex(RETURN_FORM, r'itemSearcher\(\s*"sales"')

	def test_the_shared_searcher_passes_the_flag_through(self):
		self.assertIn("ever_stocked: opts.everStocked ? 1 : undefined", ITEMS_JS)


class TestTheDefaultStaysStrict(unittest.TestCase):
	"""Every other picker must keep the in-stock filter. Relaxing it globally is
	the one change that would make this fix look unnecessary while quietly letting
	a sales order promise stock that is not there."""

	def test_a_warehouse_scoped_search_still_requires_stock_by_default(self):
		self.assertIn('conds.append("b.actual_qty > 0")', BODY)

	def test_the_relaxation_is_opt_in(self):
		self.assertRegex(re.sub(r"\s+", " ", BODY), r"if not cint\(ever_stocked\): conds\.append")

	def test_the_flag_is_named_in_the_signature(self):
		self.assertRegex(BODY, r"ever_stocked: int = 0")

	def test_no_other_picker_opts_in(self):
		"""One caller, on purpose. If a second screen ever needs it, that is a
		decision to take deliberately, not to inherit."""
		callers = [
			p for p in (ROOT / "public/js").rglob("*.vue") if "everStocked" in p.read_text(encoding="utf-8")
		]
		self.assertEqual(
			[p.name for p in callers],
			["SalesReturnForm.vue"],
			"everStocked has spread beyond the return screen",
		)


if __name__ == "__main__":
	unittest.main()
