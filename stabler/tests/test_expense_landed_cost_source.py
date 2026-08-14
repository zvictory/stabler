"""Guards for capitalizing a cash-paid Import Expense onto its containers (C5).

An Import Expense is the second source a landed cost can come from. Where a bill
reaches valuation through ``set_bill_import_refs``, a cash expense reaches it
through ``set_expense_landed_cost`` — same ``_capitalize_import_cost``, same
weight split, same ``Container Cost Line`` rows, only the provenance column
differs (``import_expense`` instead of ``purchase_invoice``).

Because the two paths write the same table, every way the bill path can go wrong
applies here too, plus two that are specific to cash:

* the expense's debit account has ALREADY hit the income statement unless it is
  an "Expenses Included In Valuation" account. Capitalizing anything else charges
  the goods a second time for money that was expensed once. ERPNext ships a
  near-miss sibling — "Expenses Included In Asset Valuation" — that capitalizes
  into a fixed asset instead of stock, so the string is pinned character for
  character, not matched loosely;
* an expense with NO account is billed through a supplier invoice, and that
  invoice is what the landed cost must be built from. Capitalizing here as well
  is the same double count from the other direction;
* ``cost_component`` decides what supersedes what. A wrong component silently
  DELETES real spend from the valuation (a later bill of that component
  supersedes the hand-typed line), so the category→component map is deliberately
  two entries long and everything else falls to "Other";
* ``Container Cost Line.import_expense`` ships as doctype JSON with no patch, and
  deploy rsyncs code before ``bench migrate`` runs. In that window Frappe would
  silently drop the unknown field and leave a cost line that reads as hand-typed
  — i.e. supersedable. The endpoint refuses instead.

Mostly frappe-free: the category map is exercised as a real unit test, the rest
are structural assertions on the source, so a refactor that quietly drops a gate
fails CI rather than production.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_expense_landed_cost_source -v
"""

from __future__ import annotations

import json
import os
import re
import unittest

from stabler.api import _imports_rules as rules
from stabler.stabler.imports_module import lcv_math

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
IMPORTS = os.path.join(_ROOT, "api", "imports.py")
COST_LINE_JSON = os.path.join(
	_ROOT,
	"stabler",
	"doctype",
	"container_cost_line",
	"container_cost_line.json",
)
EXPENSE_JSON = os.path.join(
	_ROOT,
	"stabler",
	"doctype",
	"import_expense",
	"import_expense.json",
)


def read(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def load(path: str) -> dict:
	with open(path, encoding="utf-8") as fh:
		return json.load(fh)


def field(doctype_json: dict, fieldname: str) -> dict:
	for f in doctype_json["fields"]:
		if f.get("fieldname") == fieldname:
			return f
	raise AssertionError(f"field {fieldname} not found")


def options(doctype_json: dict, fieldname: str) -> list[str]:
	raw = field(doctype_json, fieldname).get("options") or ""
	return [opt.strip() for opt in raw.split("\n") if opt.strip()]


def body(src: str, name: str) -> str:
	"""Extract a top-level function body (up to the next top-level def/decorator)."""
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"function {name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |#: |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


def code(src: str, name: str) -> str:
	"""Function body with its docstring removed — for 'must NOT appear' assertions."""
	text = body(src, name)
	m = re.search(r'"""', text)
	if not m:
		return text
	end = text.index('"""', m.end())
	return text[end + 3 :]


#: The component vocabulary the valuation actually understands, and every value
#: the Import Expense ``category`` Select can hold. Read off the doctypes rather
#: than retyped: a category added to the JSON without a mapping decision must
#: show up here, not in production.
COST_LINE_COMPONENTS = options(load(COST_LINE_JSON), "cost_component")
EXPENSE_CATEGORIES = options(load(EXPENSE_JSON), "category")


class ExpenseCostComponentMapTest(unittest.TestCase):
	"""The category→component prefill: what it says, and what it refuses to guess.

	This is the one part of C5 that is pure logic, so it is tested as logic rather
	than as source text.
	"""

	def test_the_two_unambiguous_categories_are_mapped(self):
		# These two are the only categories that name exactly one landed-cost
		# component with no further information. Mapping them is what keeps the
		# common case off "Other" and inside the supersede logic, where a later
		# transporter bill correctly replaces a hand-typed transport line.
		self.assertEqual(rules.expense_cost_component("Transport"), "Cross-Border Transport")
		self.assertEqual(rules.expense_cost_component("Insurance"), "Insurance")

	def test_every_other_category_falls_to_other(self):
		# "Handling" does not say which side of the border it happened on, and
		# "Customs" does not say Iran or Uzbekistan. Guessing picks a component
		# that participates in supersede/GTD precedence, and a wrong guess there
		# removes real spend from the valuation. "Other" is a true answer: it
		# supersedes nothing, nothing supersedes it, and it still reaches the
		# landed cost.
		for category in ("Border Crossing", "Handling", "Storage", "Documentation", "Customs", "Other"):
			with self.subTest(category=category):
				self.assertEqual(rules.expense_cost_component(category), "Other")

	def test_no_category_of_the_doctype_is_left_undecided(self):
		# The prefill must answer for every value the Select can actually hold.
		# A category added to the JSON without a decision here still lands on
		# "Other" — safe by construction, which is the point of the fallback.
		self.assertTrue(EXPENSE_CATEGORIES, "Import Expense.category has no options")
		for category in EXPENSE_CATEGORIES:
			with self.subTest(category=category):
				self.assertIn(rules.expense_cost_component(category), COST_LINE_COMPONENTS)

	def test_a_missing_category_still_returns_a_usable_component(self):
		# category is not `reqd` on Import Expense. Returning None here would
		# reach _resolve_expense_cost_component's "Unknown cost component" throw
		# and block capitalization of a perfectly ordinary blank-category expense.
		for empty in (None, "", "   "):
			with self.subTest(value=repr(empty)):
				self.assertEqual(rules.expense_cost_component(empty), "Other")

	def test_the_map_never_guesses_into_the_gtd_superseded_component(self):
		# Uzbekistan Customs Duty is REPLACED wholesale by a cleared GTD
		# (lcv_math.apply_gtd_customs_precedence). An expense prefilled into it
		# would vanish from the aggregate the moment a declaration clears, with
		# no warning that names the expense.
		for component in rules.EXPENSE_CATEGORY_COST_COMPONENT.values():
			with self.subTest(component=component):
				self.assertFalse(lcv_math.is_uzbekistan_customs_duty(component))

	def test_mapped_components_are_real_cost_line_options(self):
		# The component is written straight into Container Cost Line. A value the
		# child table does not know would never match anything downstream.
		for component in rules.EXPENSE_CATEGORY_COST_COMPONENT.values():
			with self.subTest(component=component):
				self.assertIn(component, COST_LINE_COMPONENTS)
		self.assertIn(rules.EXPENSE_DEFAULT_COST_COMPONENT, COST_LINE_COMPONENTS)

	def test_the_map_stays_small(self):
		# Not style: every entry is a claim that one word of Russian-office
		# shorthand determines a valuation component. Growing the map is a money
		# decision and must be made deliberately, not while adding a category.
		self.assertEqual(
			set(rules.EXPENSE_CATEGORY_COST_COMPONENT),
			{"Transport", "Insurance"},
		)


class SetExpenseLandedCostGateOrderTest(unittest.TestCase):
	"""The gates of set_expense_landed_cost, and the order they must run in."""

	def setUp(self):
		self.body = body(read(IMPORTS), "set_expense_landed_cost")

	def test_module_gate_runs_before_any_other_check(self):
		# Same reason as the bill path: imports is opt-in per company and owned by
		# one tenant. Any check before the module gate is a probe for a company
		# that does not have the module at all.
		gate = self.body.index("_assert_imports_access(company)")
		for later in (
			'_assert_can_write("Import Expense", import_expense)',
			"_assert_cost_visible()",
			"has_column(",
			"_assert_valuation_account(",
			"_capitalize_import_cost(",
			"frappe.db.set_value(",
		):
			self.assertLess(gate, self.body.index(later), f"{later} runs before the imports module gate")

	def test_record_level_write_permission_is_checked(self):
		# @frappe.whitelist() gates the METHOD, not the record.
		self.assertIn('_assert_can_write("Import Expense", import_expense)', self.body)

	def test_cost_visibility_is_required_to_author_a_landed_cost(self):
		# Amounts in this module are permission-masked; writing one into stock
		# valuation cannot be looser than reading one.
		self.assertIn("_assert_cost_visible()", self.body)

	def test_the_provenance_column_is_required_before_any_row_is_written(self):
		# THE deploy-window gate. Container Cost Line.import_expense ships as JSON
		# with no patch; rsync copies this endpoint minutes before `bench migrate`
		# adds the column. Frappe drops unknown fields from an insert silently, so
		# without this the rows land with no source — indistinguishable from
		# hand-typed, therefore supersedable by the next bill of that component.
		guard = self.body.index('has_column("Container Cost Line", "import_expense")')
		self.assertLess(guard, self.body.index("_capitalize_import_cost("))

	def test_double_capitalization_is_refused_on_both_the_flag_and_the_rows(self):
		# Either one alone can be the truth: the flag survives a hand-deleted row,
		# the rows survive a hand-cleared flag. Checking one would let the other
		# state through and charge the containers twice for the same money.
		self.assertIn("cint(expense.include_in_landed_cost)", self.body)
		self.assertIn('frappe.db.count("Container Cost Line", {"import_expense": import_expense})', self.body)

	def test_the_account_gate_runs_before_anything_is_written(self):
		self.assertLess(
			self.body.index("_assert_valuation_account("),
			self.body.index("_capitalize_import_cost("),
		)

	def test_the_goods_suppliers_own_money_is_still_refused(self):
		# CIF freight is already inside the agreed goods price. Paying it in cash
		# instead of on a bill does not make it a second cost.
		self.assertIn("_assert_not_ci_supplier(", self.body)

	def test_every_target_must_belong_to_the_same_company(self):
		# The expense's container/truck/CI are plain Links with no company filter
		# of their own, so without this a name from another tenant is chargeable.
		self.assertIn("_HAND_LINKABLE_REFS", self.body)
		self.assertIn("belongs to another company", self.body)

	def test_currency_must_be_one_the_cost_book_can_value(self):
		self.assertIn("_assert_capitalizable_currency(", self.body)

	def test_rows_are_stamped_with_the_expense_not_the_bill_column(self):
		# The whole point of C4's source-agnostic core: same table, different
		# provenance. Writing purchase_invoice here would attribute the cost to a
		# bill that does not exist.
		self.assertIn('source_field="import_expense"', self.body)
		self.assertIn("source_name=import_expense", self.body)
		self.assertNotIn('source_field="purchase_invoice"', self.body)

	def test_the_flag_is_only_set_after_rows_really_exist(self):
		# include_in_landed_cost is a receipt. Set it when every container refused
		# the line and the operator is told the cost is in the valuation when it
		# is not — and the unlink path then finds nothing to remove.
		refusal = self.body.index("if not row_names:")
		self.assertLess(refusal, self.body.index('"include_in_landed_cost": 1'))

	def test_a_costless_expense_is_refused_rather_than_silently_ignored(self):
		# Unlike the bill path, this endpoint does nothing BUT capitalize, so a
		# no-op has no value to fall back on and must be reported.
		self.assertIn("has no amount to add to the landed cost", self.body)
		self.assertIn("has no containers yet", self.body)

	def test_the_stamp_does_not_bump_modified(self):
		# An open expense form's next Save would fail check_concurrency. Pinned as
		# the keyword ARGUMENT (trailing comma), not as bare text: the comment that
		# explains the choice sits right above the call and names the kwarg too, so
		# a plain substring check stays green after the argument itself is dropped.
		self.assertIn("update_modified=False,\n", code(read(IMPORTS), "set_expense_landed_cost"))


class ValuationAccountGateTest(unittest.TestCase):
	"""The gate that replaces the bill path's supplier group."""

	def setUp(self):
		self.src = read(IMPORTS)
		self.body = body(self.src, "_assert_valuation_account")

	def test_the_account_type_is_pinned_to_the_stock_variant(self):
		# Read verbatim off the ERPNext Account doctype. The Select also contains
		# "Expenses Included In Asset Valuation", which capitalizes into a FIXED
		# ASSET, not into stock — accepting it would relieve the wrong account and
		# leave the LCV's credit stranded.
		self.assertIn('_VALUATION_ACCOUNT_TYPE = "Expenses Included In Valuation"', self.src)
		self.assertNotIn("Expenses Included In Asset Valuation", code(self.src, "_assert_valuation_account"))

	def test_the_comparison_is_exact(self):
		# A prefix/`in` match would accept the asset variant, which starts with
		# the same three words.
		self.assertIn("account_type != _VALUATION_ACCOUNT_TYPE", self.body)

	def test_the_wrong_type_message_names_the_account(self):
		# The operator's next move is to change the account; they cannot do that
		# from "the account is wrong".
		self.assertIn(".format(expense_account, _VALUATION_ACCOUNT_TYPE)", self.body)

	def test_an_empty_account_is_refused_separately(self):
		# No account = billed through a supplier Purchase Invoice. That invoice is
		# what the landed cost must be built from (set_bill_import_refs); doing
		# both counts the cost twice from the other direction. The message has to
		# say so, because "not a valuation account" would send the operator off to
		# change an account that is deliberately empty.
		self.assertIn("if not expense_account:", self.body)
		self.assertIn("billed through a supplier invoice", self.body)

	def test_the_gate_is_actually_wired_into_the_endpoint(self):
		self.assertIn(
			"_assert_valuation_account(import_expense, expense.expense_account)",
			body(self.src, "set_expense_landed_cost"),
		)


class ClearExpenseLandedCostTest(unittest.TestCase):
	"""Unlinking: reversible until a voucher consumed it, and never after."""

	def setUp(self):
		self.src = read(IMPORTS)
		self.body = body(self.src, "clear_expense_landed_cost")

	def test_the_same_gates_guard_the_undo(self):
		gate = self.body.index("_assert_imports_access(company)")
		for later in (
			'_assert_can_write("Import Expense", import_expense)',
			"_assert_cost_visible()",
			'frappe.db.delete("Container Cost Line"',
		):
			self.assertLess(gate, self.body.index(later), f"{later} runs before the imports module gate")

	def test_a_vouchered_cost_can_no_longer_be_removed(self):
		# Once an LCV consumed the lines the cost is inside stock valuation and
		# deleting the rows strands it there — the reversal is the accountant's,
		# not this endpoint's.
		body_ = code(self.src, "clear_expense_landed_cost")
		# The query alone is not the gate: it has to BRANCH and it has to throw.
		# Querying lcv_ref and then deleting anyway is exactly the bug this pins.
		branch = re.search(r"if vouchered:\s*\n\s*frappe\.throw\(", body_)
		self.assertTrue(branch, "the lcv_ref query does not gate anything")
		self.assertIn("already vouchered", body_)
		# ...and it must run BEFORE the delete, or the rows are gone when it fires.
		self.assertLess(branch.start(), body_.index('frappe.db.delete("Container Cost Line"'))

	def test_rows_are_deleted_only_for_this_expense(self):
		# A filter-less delete on this table would wipe every container's costs.
		self.assertIn(
			'frappe.db.delete("Container Cost Line", {"import_expense": import_expense})',
			self.body,
		)

	def test_the_flag_is_cleared_so_the_expense_can_be_capitalized_again(self):
		self.assertIn('"include_in_landed_cost": 0', self.body)

	def test_the_operators_component_choice_survives_the_undo(self):
		# cost_component is a classification of what the money IS, not a by-product
		# of the link. Clearing it here would make the operator re-decide — and
		# re-deciding is exactly where a wrong component comes from.
		self.assertNotIn('"cost_component": ""', self.body)
		self.assertNotIn('"cost_component": None', self.body)

	def test_the_provenance_column_is_required_here_too(self):
		# Same deploy window. Without the column the delete filter is unknown and
		# the flag would be cleared while nothing is removed.
		self.assertIn('has_column("Container Cost Line", "import_expense")', self.body)

	def test_nothing_to_undo_is_reported_rather_than_silently_succeeding(self):
		self.assertIn("is not included in the landed cost", self.body)


class ImportExpenseDoctypeTest(unittest.TestCase):
	"""The two fields C5 adds, and the invariants that make them safe."""

	def setUp(self):
		self.dt = load(EXPENSE_JSON)

	def test_both_fields_are_in_field_order(self):
		# A field missing from field_order exists in the DB but never renders, so
		# the operator cannot see or correct the component.
		for fieldname in ("include_in_landed_cost", "cost_component"):
			with self.subTest(fieldname=fieldname):
				self.assertIn(fieldname, self.dt["field_order"])

	def test_the_flag_is_read_only_and_starts_clear(self):
		# The flag is the receipt for Container Cost Line rows that already exist.
		# Hand-clearing it in the Desk would leave those rows behind and let the
		# expense be capitalized a second time.
		flag = field(self.dt, "include_in_landed_cost")
		self.assertEqual(flag["fieldtype"], "Check")
		self.assertEqual(flag.get("read_only"), 1)
		self.assertEqual(flag.get("default"), "0")

	def test_the_component_select_mirrors_container_cost_line_exactly(self):
		# The endpoint validates against Container Cost Line's own options, so any
		# extra option here is a value the operator can pick and then be refused
		# by, and any missing one is a real component they cannot reach.
		self.assertEqual(options(self.dt, "cost_component"), COST_LINE_COMPONENTS)

	def test_the_component_select_allows_blank(self):
		# Unlike Container Cost Line's, this field is not reqd: an expense that is
		# never capitalized has no component. The leading blank is what lets the
		# form show "nothing chosen" instead of silently defaulting to Freight.
		raw = field(self.dt, "cost_component").get("options") or ""
		self.assertTrue(raw.startswith("\n"), "cost_component has no blank first option")

	def test_the_component_is_not_read_only(self):
		# The whole design decision: the component is the operator's call, because
		# the prefill deliberately refuses to guess. A read-only field would make
		# "Other" final.
		self.assertNotEqual(field(self.dt, "cost_component").get("read_only"), 1)


if __name__ == "__main__":
	unittest.main()
