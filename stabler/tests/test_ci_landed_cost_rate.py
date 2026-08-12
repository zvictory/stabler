"""The CI landed-cost view must never invent an exchange rate.

`calculate_ci_landed_cost_uzs` used to default to a hardcoded **12800** when no
rate was supplied. That single number silently became `base_rate_uzs`,
`allocated_extra_uzs`, `final_landed_rate_per_kg_uzs` and `total_landed_uzs` —
the entire landed-cost table on the Commercial Invoice screen — and every figure
looked exactly like a real amount. `reports.py:2420` already made the opposite
decision; this module pins the same decision for the imports API and for the
screen that renders it.

The three things worth locking down, because each one alone would let the defect
come back unnoticed:

  * the constant itself must not be reachable as **code** anywhere in
    `api/imports.py` (a comment documenting the removal is fine, and one exists,
    which is exactly why this is tokenized rather than grepped);
  * "no rate" must travel to the client as `exchange_rate: None` with an empty
    `items` list — a table of zeros reads as "these costs are zero", a different
    and false statement;
  * the screen must render a distinct missing-rate state, otherwise the API's
    honesty is thrown away in the last 20 pixels.

Frappe-free: `api/imports.py` cannot be imported without a site, so it is parsed
and tokenized, the same class as the repo's other `_source` tests.
"""

from __future__ import annotations

import ast
import io
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORTS_PY = ROOT / "api/imports.py"
IMPORTS_SRC = IMPORTS_PY.read_text(encoding="utf-8")
IMPORTS_AST = ast.parse(IMPORTS_SRC)
CI_FORM = (ROOT / "public/js/pages/imports/CommercialInvoiceForm.vue").read_text(encoding="utf-8")


def _function(name: str) -> ast.FunctionDef:
	for node in ast.walk(IMPORTS_AST):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return node
	raise AssertionError(f"{name} is gone from api/imports.py")


class TheFabricatedRateIsNotReachableAsCodeTest(unittest.TestCase):
	def test_no_number_literal_12800_survives_in_imports_api(self):
		"""Tokenized, not grepped: the docstring that documents the removal names
		the number, and a grep-based guard would either fail on that docstring or
		have to be weakened until it stops guarding anything."""

		def is_the_constant(text: str) -> bool:
			# Compared as a value, not as text: 12800, 12_800 and 12800.0 are the
			# same defect, and `"12800".rstrip(".0")` would quietly yield "128".
			try:
				return float(text) == 12800.0
			except ValueError:
				return False

		offenders = [
			tok.start[0]
			for tok in tokenize.generate_tokens(io.StringIO(IMPORTS_SRC).readline)
			if tok.type == tokenize.NUMBER and is_the_constant(tok.string)
		]
		self.assertEqual(offenders, [], f"hardcoded 12800 is back as code at line(s) {offenders}")

	def test_the_endpoint_default_is_none(self):
		"""`exchange_rate: float = 12800.0` was the other half of the defect: a
		caller that passed nothing still got the made-up rate."""
		fn = _function("calculate_ci_landed_cost_uzs")
		names = [a.arg for a in fn.args.args]
		defaults = dict(zip(names[len(names) - len(fn.args.defaults) :], fn.args.defaults, strict=True))
		self.assertIn("exchange_rate", defaults)
		self.assertIsNone(defaults["exchange_rate"].value)

	def test_the_screen_seeds_no_rate_either(self):
		"""`ref(12800)` put the same invented number into the input box before the
		first server response ever arrived."""
		self.assertNotIn("12800", CI_FORM)
		self.assertIn("const usdToUzsRate = ref(null);", CI_FORM)


class TheRateIsResolvedFromRealDataTest(unittest.TestCase):
	def test_the_helper_asks_the_cbu_table(self):
		called = {
			node.func.id
			for node in ast.walk(_function("_ci_landed_cost_rate"))
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
		}
		self.assertIn("_cbu_rate_on_or_before", called)

	def test_the_pair_is_the_documents_own_currency_against_the_company_default(self):
		"""No currency name may be pinned in shared code — the same helper has to
		serve a UZS-book tenant and a USD-book tenant (CLAUDE.md: never branch on
		tenant, parametrize from company settings)."""
		src = ast.get_source_segment(IMPORTS_SRC, _function("_ci_landed_cost_rate"))
		body = src.split('"""', 2)[2]
		self.assertIn("default_currency", body)
		self.assertNotIn("UZS", body)

	def test_a_missing_rate_is_reported_as_missing(self):
		"""Each of these four is a figure the screen would otherwise print: a rate,
		two totals and the per-line table. None of them is computable without a
		rate, so none of them may carry a number."""
		src = ast.get_source_segment(IMPORTS_SRC, _function("calculate_ci_landed_cost_uzs"))
		guard = src[src.index("if rate is None:") :]
		guard = guard[: guard.index("\n\tci_items")]
		for line in (
			'"exchange_rate": None,',
			'"total_extra_uzs": None,',
			'"total_landed_uzs": None,',
			'"items": [],',
		):
			with self.subTest(line=line):
				self.assertIn(line, guard)

	def test_the_client_is_told_where_the_rate_came_from(self):
		"""`rate_source` is what lets the screen distinguish "no rate" from
		"nothing to allocate"; without it both collapse into an empty table."""
		src = ast.get_source_segment(IMPORTS_SRC, _function("calculate_ci_landed_cost_uzs"))
		self.assertEqual(src.count('"rate_source": rate_source,'), 2)


class TheScreenShowsTheMissingRateStateTest(unittest.TestCase):
	def test_the_missing_state_is_computed_from_the_server_answer(self):
		self.assertIn(
			'landedCostRateMissing = computed(() => landedCostUzs.value?.rate_source === "missing")', CI_FORM
		)

	def test_the_missing_state_wins_over_the_empty_state(self):
		"""Order matters: "nothing to allocate yet" is a claim about the invoice,
		not about the rate, and reporting it when the rate is missing tells the
		user to go fix the wrong thing."""
		missing = CI_FORM.index('v-if="landedCostRateMissing"')
		empty = CI_FORM.index('v-else-if="!uzsLandedTableItems.length"')
		self.assertLess(missing, empty)

	def test_the_first_load_is_allowed_to_ask_without_a_rate(self):
		"""With `ref(null)` an early `if (rate <= 0) return` would mean the server
		is never asked, so the CBU rate could never be resolved at all."""
		fn = CI_FORM[CI_FORM.index("async function fetchLandedCostUzs()") :]
		fn = fn[: fn.index("\nwatch([usdToUzsRate")]
		self.assertNotIn("if (rate <= 0) return", fn)
		self.assertIn("rate > 0 ? rate : null", fn)


if __name__ == "__main__":
	unittest.main()
