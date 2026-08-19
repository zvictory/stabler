"""A module-flag patch must be safe to run a second time.

The three patches under test seed `Stabler Company Modules` feature flags. All
three claim in their own docstrings to be re-runnable; two of them were not, and
the third's safety came from a statement order rather than from a WHERE clause.

Why this matters more than it sounds. A patch normally runs once per site,
because Frappe records a Patch Log row. The second run in this repo has never
come from Frappe forgetting — it comes from an operator:

  * 16328bf — zuma's Patch Log showed all 94 patches applied while 206 Custom
    Fields were missing, and the repair was to run the modules by hand;
  * a site restored from backup, or a fresh site being brought up to parity.

That is the worst possible moment for a patch to change a flag, because the
operator is already mid-incident and is not watching a feature they did not
touch. And the flags these patches seed are not defaults — v64's own docstring
records that anjan is opened *by hand from Companies after deploy*, which is
precisely the row a replay must not touch.

So the rule these tests pin is not "the SQL looks right". It is: **a row that
already holds a decision keeps it.** Only a row with no decision yet — NULL —
may be written. Everything else is somebody's answer.
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()

PATCHES = {
	"v63": "stabler.patches.v63_enable_dimensional_lines",
	"v64": "stabler.patches.v64_enable_sales_box_uom",
	"v65": "stabler.patches.v65_enable_modern_sales_order",
}
FLAGS = {
	"v63": "enable_dimensional_lines",
	"v64": "enable_sales_box_uom",
	"v65": "enable_modern_sales_order",
}


class FakeModulesTable:
	"""The `tabStabler Company Modules` rows, as a column of flag values.

	Applies the UPDATE statements the patches issue, honouring only the two
	WHERE shapes they use — `IS NULL`, and `!= 0`. An UPDATE with no WHERE
	writes every row, which is exactly the defect one of these tests exists to
	catch, so it is modelled faithfully rather than guarded against.
	"""

	def __init__(self, rows):
		self.rows = list(rows)

	def apply(self, sql: str, flag: str, params=None) -> None:
		if f"SET {flag} = " not in sql:
			return
		# The value may be bound rather than inlined; a double that only reads
		# the literal would score a parameterised UPDATE as "sets 0" and pass
		# the replay tests for the wrong reason.
		if f"SET {flag} = %s" in sql:
			value = int((params or (0,))[0])
		else:
			value = 1 if f"SET {flag} = 1" in sql else 0
		where = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
		for i, current in enumerate(self.rows):
			if not where:
				self.rows[i] = value  # no WHERE: every tenant, decided or not
			elif "IS NULL" in where and current is None:
				self.rows[i] = value
			elif "!= 0" in where and current not in (None, 0):
				self.rows[i] = value
			elif "IS NULL" in where and "!= 0" in where and current is None:
				self.rows[i] = value


def _run_patch(key: str, *, rows, has_flag_column=True, has_item_column=True, dimensional_items=True):
	"""Execute one patch against a hand-built `frappe`. Returns the rows after."""
	flag = FLAGS[key]
	table = FakeModulesTable(rows)

	frappe = types.ModuleType("frappe")

	def _has_column(doctype, column):
		if doctype == "Stabler Company Modules":
			return has_flag_column
		return has_item_column

	def _sql(query, params=None, *args, **kwargs):
		if query.strip().upper().startswith("SELECT"):
			# The only SELECT any of these patches issues: does the catalogue
			# hold an item sold by size?
			return [[1]] if dimensional_items else []
		table.apply(query, flag, params)
		return []

	frappe.db = types.SimpleNamespace(has_column=_has_column, sql=_sql, commit=lambda: None)

	_SANDBOX.evict(PATCHES[key], "frappe")
	_SANDBOX.install({"frappe": frappe})
	importlib.import_module(PATCHES[key]).execute()
	return table.rows


def tearDownModule():
	_SANDBOX.restore()


class ReplayKeepsTheOperatorsDecision(unittest.TestCase):
	"""The headline rule, one test per patch. A row holding 0 or 1 is an answer."""

	def test_v63_does_not_reopen_a_tenant_the_operator_closed(self):
		"""v63 opens a tenant whose catalogue holds dimensional items. On the
		second run the catalogue still holds them — so an UPDATE without a WHERE
		switches the feature back on for a company someone deliberately closed,
		and the operator finds out from a seller, not from the deploy."""
		after = _run_patch("v63", rows=[0, 1, 0], dimensional_items=True)
		self.assertEqual(after, [0, 1, 0])

	def test_v64_does_not_close_the_tenant_the_owner_opened_by_hand(self):
		"""v64's docstring says anjan is opened by hand from Companies after
		deploy. `WHERE flag IS NULL OR flag != 0` matches exactly that row and
		writes 0 over it — the clause reads like a tidy-up and is in fact the
		only clause that can undo a human."""
		after = _run_patch("v64", rows=[0, 1, 0])
		self.assertEqual(after, [0, 1, 0])

	def test_v65_does_not_close_the_tenant_the_owner_opened_by_hand(self):
		after = _run_patch("v65", rows=[0, 1, 0])
		self.assertEqual(after, [0, 1, 0])


class FirstRunStillDecides(unittest.TestCase):
	"""Idempotency must not be bought by making the patch do nothing.

	A NULL flag is the dangerous state: it has no decision, and NULL must never
	read as permissive. Every one of these patches exists to close that gap, so
	a fix that stops writing NULLs would pass the tests above and defeat the
	patch.
	"""

	def test_v63_opens_a_fresh_tenant_whose_catalogue_sells_by_size(self):
		self.assertEqual(_run_patch("v63", rows=[None, None], dimensional_items=True), [1, 1])

	def test_v63_closes_a_fresh_tenant_with_no_dimensional_items(self):
		self.assertEqual(_run_patch("v63", rows=[None, None], dimensional_items=False), [0, 0])

	def test_v63_closes_a_fresh_tenant_when_the_item_column_does_not_exist_yet(self):
		"""Patches run before doctype sync, so the catalogue column can be
		absent. No catalogue means no evidence, and no evidence means closed —
		never left NULL, which is the state the patch was written to remove."""
		self.assertEqual(_run_patch("v63", rows=[None, None], has_item_column=False), [0, 0])

	def test_v64_closes_a_fresh_tenant(self):
		self.assertEqual(_run_patch("v64", rows=[None, None]), [0, 0])

	def test_v65_closes_a_fresh_tenant(self):
		self.assertEqual(_run_patch("v65", rows=[None, None]), [0, 0])

	def test_a_mixed_table_gets_both_halves_right_in_one_pass(self):
		"""The realistic shape on a repaired site: some tenants decided, one
		row newly added and still NULL."""
		self.assertEqual(_run_patch("v63", rows=[1, 0, None], dimensional_items=True), [1, 0, 1])
		self.assertEqual(_run_patch("v64", rows=[1, 0, None]), [1, 0, 0])


class TheColumnGuardStillHolds(unittest.TestCase):
	"""All three run before DDL sync may have created their column."""

	def test_no_patch_writes_when_its_column_is_missing(self):
		for key in PATCHES:
			with self.subTest(patch=key):
				self.assertEqual(_run_patch(key, rows=[None, 1], has_flag_column=False), [None, 1])


if __name__ == "__main__":
	unittest.main()
