"""The supplier-payment currency rule (pure).

A tenant that buys in exactly one foreign currency (msa: every supplier is USD)
asked that supplier payments come only from an account in that currency. The rule
is NOT "USD only" — a currency literal would be a tenant constant in shared code.
It is "the source account's currency must equal the supplier's payable account's
currency", which yields "USD only" on msa and "EUR only" on a EUR-payable company
without either name appearing anywhere.

Three boundaries matter enough to pin down, because each one, if crossed, would
block money that is legitimately moving:

  * only OUTGOING SUPPLIER payments — a customer receipt or an employee advance in
    a second currency is ordinary business (and anjan does 211 of the supplier kind
    itself, which is why the whole rule is opt-in per company);
  * unknown currency is never a violation — a blank `account_currency` must not
    become a reason to refuse a payment;
  * a real mismatch IS a violation, otherwise the guard is decoration.

Frappe-free: the per-company opt-in lives in `supplier_payment_guard.guard_enabled`
and needs a site; the rule itself does not, so it is asserted here directly. The
wiring around it — default OFF, every supplier-payment endpoint actually calling
the guard — is asserted from source text, the same class as the repo's other
`_flag` tests. Behaviour that only holds because a call site exists needs a test
that fails when the call site is deleted.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from stabler.api._supplier_payment import supplier_payment_currency_mismatch

ROOT = Path(__file__).resolve().parents[1]
GUARD = (ROOT / "api/supplier_payment_guard.py").read_text(encoding="utf-8")
MONEY = (ROOT / "api/money.py").read_text(encoding="utf-8")
INSTALLMENT = (ROOT / "api/installment.py").read_text(encoding="utf-8")
ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "stabler/doctype/stabler_settings/stabler_settings.py").read_text(encoding="utf-8")
MODULES_JSON_TEXT = (ROOT / "stabler/doctype/stabler_company_modules/stabler_company_modules.json").read_text(
	encoding="utf-8"
)
ADMIN = (ROOT / "public/js/pages/admin/Companies.vue").read_text(encoding="utf-8")


class SupplierPaymentCurrencyTest(unittest.TestCase):
	def test_uzs_account_paying_a_usd_supplier_is_a_violation(self):
		"""The case the rule exists for: msa's USD payable paid from a so'm account."""
		self.assertTrue(supplier_payment_currency_mismatch("Pay", "Supplier", "UZS", "USD"))

	def test_matching_currencies_pass(self):
		self.assertFalse(supplier_payment_currency_mismatch("Pay", "Supplier", "USD", "USD"))
		self.assertFalse(supplier_payment_currency_mismatch("Pay", "Supplier", "UZS", "UZS"))

	def test_customer_receipt_is_untouched(self):
		"""Selling in USD and banking in UZS is normal; the rule is about paying out."""
		self.assertFalse(supplier_payment_currency_mismatch("Receive", "Customer", "USD", "UZS"))

	def test_employee_advance_is_untouched(self):
		"""Only Supplier is in scope — an employee advance keeps converting."""
		self.assertFalse(supplier_payment_currency_mismatch("Pay", "Employee", "UZS", "USD"))

	def test_unknown_currency_is_never_a_violation(self):
		"""A blank account_currency is missing metadata, not evidence of a mismatch."""
		self.assertFalse(supplier_payment_currency_mismatch("Pay", "Supplier", None, "USD"))
		self.assertFalse(supplier_payment_currency_mismatch("Pay", "Supplier", "USD", ""))

	def test_rule_is_not_hardcoded_to_usd(self):
		"""A EUR-payable company gets 'EUR only' from the same code path."""
		self.assertTrue(supplier_payment_currency_mismatch("Pay", "Supplier", "USD", "EUR"))
		self.assertFalse(supplier_payment_currency_mismatch("Pay", "Supplier", "EUR", "EUR"))


class TheRuleIsOffUnlessACompanyAsksForItTest(unittest.TestCase):
	"""Default-OFF is the load-bearing part, so it is locked in source, not in prose.

	anjan makes 211 mixed-currency supplier payments on purpose. If this flag ever
	ships ON — by a doctype default, by DEFAULT_MODULE_ENABLED, or by `guard_enabled`
	being rewritten to fall back on the defaults map — anjan stops being able to pay
	its suppliers, and nothing else in the suite would notice.
	"""

	def test_the_doctype_column_defaults_to_off(self):
		doc = json.loads(MODULES_JSON_TEXT)
		field = next(f for f in doc["fields"] if f["fieldname"] == "enable_supplier_payment_currency_guard")
		self.assertEqual(field.get("default"), "0")
		self.assertIn("enable_supplier_payment_currency_guard", doc["field_order"])

	def test_the_defaults_map_is_off(self):
		block = SETTINGS[SETTINGS.index("DEFAULT_MODULE_ENABLED = {") :]
		block = block[: block.index("\n}")]
		self.assertIn('"supplier_payment_currency_guard": False', block)

	def test_guard_enabled_never_falls_back_to_the_defaults_map(self):
		"""`module_map_for` CREATES AND COMMITS a missing row. A payment endpoint
		must not write settings while validating, and a company with no row must
		read as OFF rather than inheriting a default it never chose.

		Parsed, not grepped: the docstring naming `module_map_for` as the thing
		deliberately avoided must not itself satisfy the test.
		"""
		called = {
			node.func.id
			for node in ast.walk(ast.parse(GUARD))
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
		}
		self.assertNotIn("module_map_for", called)
		self.assertNotIn("get_company_module_row", called)
		imported = {
			alias.name
			for node in ast.walk(ast.parse(GUARD))
			if isinstance(node, ast.ImportFrom)
			for alias in node.names
		}
		self.assertNotIn("module_map_for", imported)
		self.assertNotIn("DEFAULT_MODULE_ENABLED", imported)

	def test_the_rule_names_no_currency_and_no_tenant(self):
		for literal in ('"USD"', "'USD'", "msa", "anjan"):
			with self.subTest(literal=literal):
				self.assertNotIn(literal, GUARD.split('"""', 2)[2])


class EverySupplierPaymentPathIsGuardedTest(unittest.TestCase):
	"""Three endpoints create a supplier Payment Entry; a missed one is a bypass.

	Found by review: `installment.collect_payment(side="buy")` builds its PE from
	`payment_defaults_for_invoice`, so the literal `party_type="Supplier"` never
	appears there and a grep for it cleared the file wrongly.
	"""

	def test_both_money_endpoints_call_the_guard(self):
		"""create_payment_entry and create_payment_for_invoice — the import line
		carries no paren, so this counts call sites only."""
		self.assertEqual(MONEY.count("assert_supplier_payment_currency("), 2)

	def test_the_installment_collection_calls_the_guard(self):
		self.assertEqual(INSTALLMENT.count("assert_supplier_payment_currency("), 1)

	def test_the_guard_runs_before_the_payment_entry_is_built(self):
		fn = INSTALLMENT[INSTALLMENT.index("\tdefaults = payment_defaults_for_invoice(doc.company") :]
		fn = fn[: fn.index("pe.paid_amount = paid")]
		self.assertIn("assert_supplier_payment_currency(", fn)


class TheFlagIsTogglableTest(unittest.TestCase):
	def test_the_module_key_maps_to_the_column(self):
		self.assertRegex(
			ORG,
			r'"supplier_payment_currency_guard":\s*"enable_supplier_payment_currency_guard"',
		)

	def test_the_update_api_accepts_the_flag(self):
		fn = ORG[ORG.index("def update_company_modules(") :]
		fn = fn[: fn.index("\n@frappe.whitelist()")]
		self.assertRegex(fn, r"\n\tsupplier_payment_currency_guard=None,")
		self.assertIn('"enable_supplier_payment_currency_guard": supplier_payment_currency_guard,', fn)

	def test_the_admin_screen_lists_the_flag(self):
		"""A tenant setting with no UI is a code constant in practice
		(Companies.vue:42-44)."""
		self.assertRegex(ADMIN, r'\{ key: "supplier_payment_currency_guard", label:')


if __name__ == "__main__":
	unittest.main()
