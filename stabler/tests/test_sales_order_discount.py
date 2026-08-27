"""A discount entered on a sales order line must reach the saved document.

Measured on anjan 2026-08-27. SAL-ORD-2026-15847 carried 4 % on all thirteen
lines and its grand total (4 684 000) was exactly the undiscounted sum. The
salesperson cancelled it, amended it, entered 4 % again on 15847-1 — same
result. The 4 % was in the database the whole time; it just never touched the
money, and nothing anywhere reported a failure.

Root cause is one condition in ERPNext: `calculate_item_values` derives
`rate = price_list_rate × (1 − discount_percentage/100)` only when `rate` is
empty (or a Pricing Rule is attached). Stabler always writes `rate` itself, so
that branch never ran. Worse, the same function then overwrites
`discount_amount` with `price_list_rate − rate`, so a per-unit discount was not
merely ignored — it was erased.

Three things have to hold together, one test class each:

  1. the arithmetic (api/_pricing.py) — percentage wins over amount, and the
     amount is per UNIT, exactly as the SPA states the rule;
  2. the write path hands ERPNext a NET `rate` and keeps the gross in
     `price_list_rate`, on the create AND the update endpoint (they are separate
     functions and have drifted apart before);
  3. the form reads the GROSS back into its rate column — without that, the fix
     is worse than the bug: reopening a discounted order would apply the
     discount a second time on screen, and every save would shave the price
     again.
"""

import re
import unittest
from pathlib import Path
from typing import ClassVar

from stabler.api._pricing import net_rate

ROOT = Path(__file__).resolve().parents[1]
SALES_API = (ROOT / "api/sales.py").read_text(encoding="utf-8")
PRICING_JS = (ROOT / "public/js/composables/pricing.js").read_text(encoding="utf-8")
CLASSIC = (ROOT / "public/js/pages/sales/SalesOrderFormClassic.vue").read_text(encoding="utf-8")
MODERN = (ROOT / "public/js/pages/sales/SalesOrderFormModern.vue").read_text(encoding="utf-8")


def _squash(text: str) -> str:
	return re.sub(r"\s+", " ", text)


def _endpoint(name: str) -> str:
	"""The source of one whitelisted endpoint, up to the next one."""
	start = SALES_API.index(f"def {name}(")
	rest = SALES_API[start:]
	end = rest.find("\n@frappe.whitelist", 1)
	return rest if end == -1 else rest[:end]


class TestTheDiscountArithmetic(unittest.TestCase):
	"""The numbers themselves. Same rule as SalesOrderLines.vue's lineAmount."""

	def test_no_discount_leaves_the_rate_alone(self):
		self.assertEqual(net_rate(216000), 216000.0)

	def test_a_percentage_comes_off_the_rate(self):
		"""The reported case: 4 % of 216 000 is 207 360, not 216 000."""
		self.assertEqual(net_rate(216000, discount_percentage=4), 207360.0)

	def test_an_amount_is_a_per_unit_reduction(self):
		"""Not a sum off the line total — a line of 10 at 80 000 less 500 bills
		795 000, not 799 500. Getting this backwards misprices every bulk line."""
		self.assertEqual(net_rate(80000, discount_amount=500), 79500.0)

	def test_the_percentage_wins_when_both_are_given(self):
		"""ERPNext's own precedence. If the two sides disagreed on which wins,
		the operator would see one number and the document would keep another."""
		self.assertEqual(net_rate(1000, discount_percentage=10, discount_amount=250), 900.0)

	def test_a_full_percentage_discount_makes_the_line_free(self):
		self.assertEqual(net_rate(1000, discount_percentage=100), 0.0)

	def test_a_discount_never_pushes_the_rate_below_zero(self):
		"""A negative rate would post a negative amount to the GL."""
		self.assertEqual(net_rate(1000, discount_amount=1500), 0.0)

	def test_blank_inputs_are_not_a_discount(self):
		self.assertEqual(net_rate(1000, discount_percentage=None, discount_amount=None), 1000.0)


class TestTheWritePathAppliesTheDiscount(unittest.TestCase):
	"""Both endpoints must hand ERPNext a net rate. Storing the discount field
	alone is what produced the bug — the field was set, the money was not."""

	ENDPOINTS = ("create_sales_order", "update_sales_order")

	def test_the_endpoints_use_the_shared_arithmetic(self):
		self.assertRegex(SALES_API, r"from stabler\.api\._pricing import [\w, ]*\bnet_rate\b")
		for name in self.ENDPOINTS:
			with self.subTest(endpoint=name):
				self.assertIn("net_rate(", _endpoint(name))

	def test_the_billed_rate_is_the_net_one(self):
		for name in self.ENDPOINTS:
			with self.subTest(endpoint=name):
				body = _squash(_endpoint(name))
				self.assertRegex(
					body,
					r'line\.rate = net_rate\( rate, row\["discount_percentage"\], row\["discount_amount"\] \)'
					r'|line\.rate = net_rate\(rate, row\["discount_percentage"\], row\["discount_amount"\]\)',
					"the line still bills the gross rate — the discount is decorative again",
				)

	def test_the_gross_rate_is_kept_as_the_list_rate(self):
		"""Somewhere has to hold the pre-discount price. If `price_list_rate` is
		left to ERPNext it fills in the catalogue price, and ERPNext's own
		`discount_amount = price_list_rate − rate` then reports a discount
		nobody entered — and the form reads that back as one."""
		for name in self.ENDPOINTS:
			with self.subTest(endpoint=name):
				self.assertIn("line.price_list_rate = rate", _endpoint(name))

	def test_no_endpoint_assigns_the_raw_rate_any_more(self):
		for name in self.ENDPOINTS:
			with self.subTest(endpoint=name):
				self.assertNotRegex(_squash(_endpoint(name)), r"line\.rate = rate\b")

	def test_an_amount_that_swallows_the_rate_is_refused(self):
		"""A net rate of zero sends ERPNext back to `not item.rate`, where it
		re-derives the rate from the price list and quietly restores full price.
		A give-away is 100 %, not an amount equal to the rate — so say so
		instead of accepting input that cannot be honoured."""
		for name in self.ENDPOINTS:
			with self.subTest(endpoint=name):
				self.assertIn("discount_amount must be less than the rate", _endpoint(name))


class TestTheFormReadsTheGrossRate(unittest.TestCase):
	"""The rate column is the PRE-discount price — SalesOrderLines.vue applies
	the discount on top of it. The document's `rate` is the POST-discount one.
	Loading one into the other compounds the discount on every reopen."""

	FORMS: ClassVar[dict[str, str]] = {
		"SalesOrderFormClassic": CLASSIC,
		"SalesOrderFormModern": MODERN,
	}

	def test_both_variants_import_the_shared_helper(self):
		for name, src in self.FORMS.items():
			with self.subTest(form=name):
				self.assertIn('import { grossRate } from "../../composables/pricing.js"', src)

	def test_both_variants_load_the_gross_into_the_rate_column(self):
		for name, src in self.FORMS.items():
			with self.subTest(form=name):
				self.assertIn("rate: grossRate(it),", src)

	def test_the_helper_prefers_the_list_rate_only_when_it_is_the_higher_one(self):
		"""On a line with no list rate — and on the already-wrong documents this
		bug left behind, where `rate` sits above `price_list_rate` — the rate
		itself is the only honest gross."""
		self.assertRegex(
			_squash(PRICING_JS),
			r"return listRate >= rate \? listRate : rate;",
		)


if __name__ == "__main__":
	unittest.main()
