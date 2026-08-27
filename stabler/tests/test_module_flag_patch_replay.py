"""A module-flag patch must be safe to run a second time.

The patches under test seed `Stabler Company Modules` feature flags. They all
claim in their own docstrings to be re-runnable; some were not, and one's safety
came from a statement order rather than from a WHERE clause. (No count here: the
PATCHES dict below is the list, and a number in this sentence goes stale the next
time somebody adds a flag — as it had, silently, before v100.)

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
import re
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()

PATCHES = {
	"v62": "stabler.patches.v62_enable_direct_invoicing",
	"v63": "stabler.patches.v63_enable_dimensional_lines",
	"v64": "stabler.patches.v64_enable_sales_box_uom",
	"v65": "stabler.patches.v65_enable_modern_sales_order",
	"v100": "stabler.patches.v100_enable_pos",
}
FLAGS = {
	"v62": "enable_direct_invoicing",
	"v63": "enable_dimensional_lines",
	"v64": "enable_sales_box_uom",
	"v65": "enable_modern_sales_order",
	"v100": "enable_pos",
}


class FakeModulesTable:
	"""The `tabStabler Company Modules` rows, as a column of flag values.

	Applies the UPDATE statements the patches issue, honouring only the two
	WHERE shapes they use — `IS NULL`, and `!= 0`. An UPDATE with no WHERE
	writes every row, which is exactly the defect one of these tests exists to
	catch, so it is modelled faithfully rather than guarded against.
	"""

	def __init__(self, rows, companies=None, sales=None):
		self.rows = list(rows)
		# Only v62 decides per company; the others write one value for everybody.
		self.companies = list(companies) if companies else [f"Co {i}" for i in range(len(self.rows))]
		# v100 copies a sibling column instead of writing a literal, so the double
		# has to carry that column too. Default 1: `enable_sales` is one of the
		# four modules that ship on, which is the state v100 was written against.
		self.sales = list(sales) if sales is not None else [1] * len(self.rows)

	def _value_for(self, sql: str, index: int, flag: str, params=None):
		"""What this UPDATE writes into row `index`.

		Several shapes appear across these patches, and the double has to read
		the value out of the statement rather than assume one — a double that
		only recognised the inlined literal scored a parameterised UPDATE as
		"sets 0" and passed the replay tests for the wrong reason. The
		column-copy shape below is the same trap: without its branch the
		fallthrough would score `SET enable_pos = enable_sales` as "sets 0",
		and every v100 test would pass while asserting the opposite.
		"""
		case = re.search(
			rf"SET {flag} = CASE WHEN UPPER\(company\) LIKE %\((\w+)\)s THEN (\d) ELSE (\d) END", sql
		)
		if case:
			key, hit, miss = case.group(1), int(case.group(2)), int(case.group(3))
			pattern = str(params.get(key, "")).strip("%").upper() if isinstance(params, dict) else ""
			return hit if pattern in self.companies[index].upper() else miss
		if f"SET {flag} = enable_sales" in sql:
			return self.sales[index]
		if f"SET {flag} = %s" in sql:
			return int((params or (0,))[0])
		return 1 if f"SET {flag} = 1" in sql else 0

	def apply(self, sql: str, flag: str, params=None) -> None:
		if f"SET {flag} = " not in sql:
			return
		where = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
		for i, current in enumerate(self.rows):
			if self._where_matches(where, i, current, params):
				self.rows[i] = self._value_for(sql, i, flag, params)

	def _where_matches(self, where: str, index: int, current, params=None) -> bool:
		"""Evaluate the WHERE the way SQL would, not one branch of it.

		This started as a chain of `elif`s, one per predicate, which is an OR —
		and `UPPER(company) LIKE … AND flag IS NULL` is not an OR. The double then
		reported the naive repair of v62 as unsafe for a reason SQL would never
		have produced. A double that answers the right way for the wrong reason is
		worse than no double: it retires the question.
		"""
		if not where.strip():
			return True  # no WHERE: every tenant, decided or not
		# v63 binds positionally, v62 by name — only the latter carries a pattern.
		pattern = str(params.get("pattern", "")).strip("%").upper() if isinstance(params, dict) else ""

		def atom(term: str) -> bool:
			if "IS NULL" in term:
				return current is None
			if "!= 0" in term:
				return current not in (None, 0)
			if "LIKE" in term:
				return pattern in self.companies[index].upper()
			raise AssertionError(f"the double does not model this predicate: {term.strip()!r}")

		return any(all(atom(t) for t in disjunct.split(" AND ")) for disjunct in where.split(" OR "))


def _run_patch(
	key: str,
	*,
	rows,
	companies=None,
	sales=None,
	has_flag_column=True,
	has_item_column=True,
	dimensional_items=True,
):
	"""Execute one patch against a hand-built `frappe`. Returns the rows after."""
	flag = FLAGS[key]
	table = FakeModulesTable(rows, companies, sales)

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

	def test_v62_does_not_reopen_the_msa_tenant_the_operator_closed(self):
		"""v62's hole was the shape, not the clause: it seeded in TWO statements.

		Zero everyone whose flag is NULL, then set 1 wherever the company name
		matches `%MSA%` — and only the first statement looked at the flag. Each
		statement reads as safe on its own; the hole is in the order. On a replay
		the second one alone runs over a decided row and switches Direct Sales
		Invoicing back on for a tenant somebody had switched off, which is why
		`03ff23f` fixing its three siblings did not fix this one.

		Note that the naive repair — bolting `AND enable_direct_invoicing IS NULL`
		onto the second statement — makes the patch a no-op on its FIRST run too,
		because the first statement has already replaced every NULL with 0. That
		is what `FirstRunStillDecides` below exists to catch.
		"""
		after = _run_patch("v62", rows=[0, 1, 0], companies=["MSA Group", "Anjan", "Mikas"])
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

	def test_v100_does_not_reopen_pos_for_the_tenant_who_switched_it_off(self):
		"""v100 exists so one tenant can close POS from the Companies screen
		after deploy. Its source column `enable_sales` stays 1 for that tenant —
		POS was split off `sales` precisely because that tenant needs sales —
		so a replay without the IS NULL clause copies the 1 straight back over
		the operator's 0 and POS reappears in their sidebar. The row that must
		survive is exactly the row this patch was written to make possible."""
		after = _run_patch("v100", rows=[0, 1, None], sales=[1, 1, 1])
		self.assertEqual(after, [0, 1, 1])


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

	def test_v62_opens_the_msa_tenants_and_only_those_on_a_fresh_site(self):
		"""The rule this patch translates: `"MSA" in company.upper()`, nothing else.

		Both halves have to survive one pass. A repair that only stops the replay
		would leave every fresh tenant at 0 and quietly remove the capability from
		the one company that had it under the old name rule.
		"""
		after = _run_patch(
			"v62",
			rows=[None, None, None],
			companies=["MSA Group", "Anjan", "msa trading"],
		)
		self.assertEqual(after, [1, 0, 1])

	def test_v62_leaves_a_decided_row_alone_while_deciding_the_new_one(self):
		"""The realistic shape on a repaired site: one row added, the rest answered."""
		after = _run_patch("v62", rows=[0, None], companies=["MSA Group", "MSA Logistics"])
		self.assertEqual(after, [0, 1])

	def test_v64_closes_a_fresh_tenant(self):
		self.assertEqual(_run_patch("v64", rows=[None, None]), [0, 0])

	def test_v65_closes_a_fresh_tenant(self):
		self.assertEqual(_run_patch("v65", rows=[None, None]), [0, 0])

	def test_v100_hands_pos_to_exactly_whoever_had_it_before(self):
		"""The rule v100 replaces is "POS shows wherever sales is on". A literal
		1 would hand POS to a sales-off tenant that never had it; a literal 0
		would take it from the six that do. Only the copy is a translation
		rather than a new decision, so both halves have to survive one pass."""
		self.assertEqual(_run_patch("v100", rows=[None, None], sales=[1, 0]), [1, 0])

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
