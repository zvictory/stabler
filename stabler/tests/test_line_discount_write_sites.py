"""Every endpoint that stores a line discount must also bill it.

The sales order pair was fixed first, with the whole diagnosis in
api/_pricing.py: ERPNext only derives `rate` from the list rate and the discount
when `rate` is empty, and Stabler writes `rate` itself, so on every Stabler line
the discount fields sat in the database without touching a single amount. On
anjan that was 1 240 purchase invoice lines and 2 085 sales invoice lines
carrying a percentage that never came off the money (measured 2026-08-27).

Fixing two of the six call sites would have been the worse outcome: a discount
that works on the order and evaporates on the invoice made from it is harder to
notice than one that never works at all.

So this module pins the invariant at the level it actually has to hold —
**a function that assigns `discount_percentage` must derive its rate through
`net_rate`** — and then names each site, so adding a seventh endpoint that
quietly stores a discount fails here rather than in a customer's ledger.

Purchase Receipt and Quotation are deliberately absent: their line cleaners
carry no discount fields at all, so there is nothing to bill wrongly. The sweep
below reflects that by keying on the discount, not on the rate.
"""

import re
import unittest
from pathlib import Path
from typing import ClassVar

from stabler.api._pricing import gross_rate, net_rate

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
	"api/sales.py": (ROOT / "api/sales.py").read_text(encoding="utf-8"),
	"api/purchasing.py": (ROOT / "api/purchasing.py").read_text(encoding="utf-8"),
}
PRICING_JS = (ROOT / "public/js/composables/pricing.js").read_text(encoding="utf-8")


def _functions(src: str) -> dict[str, str]:
	"""Every top-level def in a module, mapped to its source."""
	starts = [(m.start(), m.group(1)) for m in re.finditer(r"^def (\w+)\(", src, flags=re.M)]
	out = {}
	for i, (pos, name) in enumerate(starts):
		end = starts[i + 1][0] if i + 1 < len(starts) else len(src)
		out[name] = src[pos:end]
	return out


FUNCS = {path: _functions(src) for path, src in SOURCES.items()}


def _body(path: str, name: str) -> str:
	return FUNCS[path][name]


class TestEveryDiscountWriterBillsIt(unittest.TestCase):
	"""The sweep. Keyed on the discount because that is what makes a rate wrong:
	a line that stores no discount has nothing to apply."""

	def test_a_function_that_stores_a_discount_derives_its_rate(self):
		found = 0
		for path, funcs in FUNCS.items():
			for name, body in funcs.items():
				if ".discount_percentage = " not in body:
					continue
				found += 1
				with self.subTest(module=path, function=name):
					self.assertIn(
						"net_rate(",
						body,
						f"{path}:{name} stores a discount it never takes off the rate",
					)
		self.assertGreaterEqual(found, 6, f"expected every discount writer to be seen, saw {found}")

	def test_both_modules_import_the_shared_arithmetic(self):
		for path, src in SOURCES.items():
			with self.subTest(module=path):
				self.assertIn("from stabler.api._pricing import", src)


class TestThePurchaseSideIsFixedToo(unittest.TestCase):
	"""A purchase order and the invoice made from it are separate builders and
	have to be corrected separately — the invoice does not inherit the fix."""

	SITES: ClassVar[tuple[tuple[str, str], ...]] = (
		("api/purchasing.py", "_apply_invoice_payload"),
		("api/purchasing.py", "create_purchase_order"),
		("api/purchasing.py", "update_purchase_order"),
	)

	def test_the_billed_rate_is_the_net_one(self):
		for path, name in self.SITES:
			with self.subTest(site=name):
				self.assertRegex(
					re.sub(r"\s+", " ", _body(path, name)),
					r"line\.rate = net_rate\(",
					f"{name} still bills the gross rate",
				)

	def test_the_gross_rate_is_kept_as_the_list_rate(self):
		"""Without it ERPNext fills `price_list_rate` from the buying list and
		then books the difference against the typed rate as a discount nobody
		entered — and reports it on every purchase analysis."""
		for path, name in self.SITES:
			with self.subTest(site=name):
				self.assertIn("line.price_list_rate = ", _body(path, name))

	def test_an_amount_that_swallows_the_rate_is_refused(self):
		"""Same reason as on the sales side: a net rate of zero sends ERPNext
		back to deriving the rate from the price list, restoring full price."""
		for name in ("_clean_invoice_items", "create_purchase_order", "update_purchase_order"):
			with self.subTest(cleaner=name):
				self.assertIn(
					"discount_amount must be less than the rate",
					_body("api/purchasing.py", name),
				)


class TestTheInvoiceOverrideRepricesTheLine(unittest.TestCase):
	"""`create_sales_invoice` patches lines ERPNext already mapped from the
	order. Setting `discount_percentage` on one of those does nothing at all
	— the line arrives with a rate, which is exactly the condition that makes
	ERPNext skip its own discount step."""

	BODY = _body("api/sales.py", "create_sales_invoice")

	def test_the_override_re_derives_the_rate(self):
		self.assertIn("line.rate = net_rate(", self.BODY)

	def test_it_only_reprices_a_line_whose_price_was_actually_patched(self):
		"""A patch that moves only the quantity must leave the price alone.
		Recomputing every line would restate the price of orders written before
		this fix, where the stored list rate is not the line's gross."""
		self.assertRegex(re.sub(r"\s+", " ", self.BODY), r"if any\( patch\.get\(k\)|if any\(patch\.get\(k\)")

	def test_it_takes_the_gross_from_the_shared_rule(self):
		self.assertIn("gross_rate(", self.BODY)


class TestTheBuyingFormsReadTheGrossRate(unittest.TestCase):
	"""The buying forms compute qty x rate x (1 - pct/100) exactly like the sales
	order form, so they need the same read mapping — otherwise fixing the write
	path turns a discount that was ignored into one that grows on every save.

	They also need the same protection the invoice form already carries: when the
	buying price list is quoted in the company's base currency and the document
	is not, ERPNext converts the list rate into the document currency and books
	the whole gap as a discount. On anjan that is every purchase order line that
	has a discount at all — three of three, all reading 99.992 % (measured
	2026-08-27). Trusting either field there would put a 236-million rate in a
	column the operator edits."""

	FORMS: ClassVar[dict[str, str]] = {
		"PurchaseOrderForm": (ROOT / "public/js/pages/purchasing/PurchaseOrderForm.vue").read_text(
			encoding="utf-8"
		),
		"PurchaseInvoiceForm": (ROOT / "public/js/pages/purchasing/PurchaseInvoiceForm.vue").read_text(
			encoding="utf-8"
		),
	}

	def test_both_forms_import_the_shared_helper(self):
		for name, src in self.FORMS.items():
			with self.subTest(form=name):
				self.assertIn('import { grossRate } from "../../composables/pricing.js"', src)

	def test_both_forms_load_the_gross_into_the_rate_column(self):
		for name, src in self.FORMS.items():
			with self.subTest(form=name):
				self.assertIn("grossRate({ rate, price_list_rate: listRate })", src)

	def test_both_forms_screen_out_a_mis_denominated_list_rate_first(self):
		"""`listRate` must be the POST-check value: running grossRate on the raw
		one is what would surface the 236-million rate."""
		for name, src in self.FORMS.items():
			with self.subTest(form=name):
				flat = re.sub(r"\s+", " ", src)
				self.assertRegex(
					flat, r"const isArtifact = cr > 0 && plr > 0 && Math\.abs\(plr \* cr - rate\) < 1;"
				)
				self.assertRegex(flat, r"const listRate = isArtifact \? 0 : plr;")

	def test_the_order_endpoint_hands_the_form_the_base_currency(self):
		"""The check needs to know when the document is already in base — where
		the conversion rate is 1 and the comparison would match every line."""
		self.assertIn('"base_currency"', _body("api/purchasing.py", "purchase_order_detail"))


class TestTheGrossRule(unittest.TestCase):
	"""One rule, stated twice — once for the server, once for the form. If they
	disagree the operator edits one price and the invoice bills another."""

	def test_the_list_rate_is_the_gross_when_it_is_the_higher_one(self):
		self.assertEqual(gross_rate(207360, 216000), 216000.0)

	def test_a_line_without_a_list_rate_is_its_own_gross(self):
		self.assertEqual(gross_rate(216000, 0), 216000.0)

	def test_a_list_rate_below_the_rate_is_not_trusted(self):
		"""The documents this bug already wrote look exactly like this."""
		self.assertEqual(gross_rate(192000, 191425.92), 192000.0)

	def test_the_server_and_the_form_agree(self):
		"""composables/pricing.js is the same three lines in JavaScript."""
		self.assertRegex(re.sub(r"\s+", " ", PRICING_JS), r"return listRate >= rate \? listRate : rate;")
		for rate, list_rate in ((207360, 216000), (216000, 0), (192000, 191425.92), (0, 0)):
			with self.subTest(rate=rate, list_rate=list_rate):
				expected = list_rate if list_rate >= rate else rate
				self.assertEqual(gross_rate(rate, list_rate), float(expected))

	def test_the_gross_rule_and_the_net_rule_are_inverses(self):
		"""Reopen, resave, reopen must not move the price. This is the pair that
		guarantees it: net_rate goes down, gross_rate comes back up."""
		gross = 216000.0
		net = net_rate(gross, discount_percentage=4)
		self.assertEqual(gross_rate(net, gross), gross)
		self.assertEqual(net_rate(gross_rate(net, gross), discount_percentage=4), net)


if __name__ == "__main__":
	unittest.main()
