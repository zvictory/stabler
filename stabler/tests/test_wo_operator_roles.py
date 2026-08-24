"""A Work Order has two operator roles, and exactly one rule decides who may touch it.

Until v97 a Work Order carried a single `operator` field. The shop floor it models
does not: anjan runs 11 pouring operators and 10 packaging operators, and both work
the same order. So `operator` became the production role and `packaging_operator`
joined it — which turns a one-field comparison into a set membership question.

The reason this file exists is what happened the last time that question was answered
in more than one place. The production engineer's React prototype derived "whose loss
is this" twice: `xomashyolar.json` carries an `operatorTuri` per material, and
`ishlabChiqarish.js:55` derives the same thing from the unit of measure. Nothing read
the first one. Cross-checking the two rules over the 669 BOM lines in that prototype's
own seed data: 190 lines (28%) disagree — 55 of the 112 materials in use land on the
wrong operator, and that number feeds the KPI that feeds the bonus.

`manufacturing.py` was one edit away from the same shape. The assignee check lived in
three places already — `_require_own_work_order` plus two hand-inlined comparisons in
`work_order_detail` and `wo_genealogy` — and adding a second role to two of the three
is how a packaging operator ends up able to open an order they cannot finish. So the
rule lives in `_is_wo_assignee` and the field list in `_WO_OPERATOR_FIELDS`, and this
test fails the moment a fourth call site re-derives either one.

Shape only — no bench, no DB. The behaviour is covered in test_manufacturing_kiosk.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_operator_roles -v
"""

from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "api" / "manufacturing.py"
PATCHES = ROOT / "patches"

#: The one helper allowed to compare an operator field against the session user.
ASSIGNEE_HELPER = "_is_wo_assignee"

#: The one name allowed to enumerate the operator fields.
FIELD_LIST = "_WO_OPERATOR_FIELDS"

OPERATOR_FIELDS = {"operator", "packaging_operator"}


def _tree() -> ast.Module:
	return ast.parse(API.read_text(encoding="utf-8"))


def _enclosing_function(tree: ast.Module, node: ast.AST) -> str:
	"""Name of the innermost function containing `node`, or '<module>'."""
	best = "<module>"
	for fn in ast.walk(tree):
		if not isinstance(fn, ast.FunctionDef):
			continue
		if fn.lineno <= node.lineno <= (fn.end_lineno or fn.lineno):
			best = fn.name
	return best


def _reads_operator_field(node: ast.AST) -> bool:
	"""True when `node` pulls an operator field off a doc or row.

	Covers the two shapes this module actually uses: `doc.get("operator")` and
	`row["operator"]`. Attribute access (`doc.operator`) is deliberately NOT
	matched — on a submitted doc it raises for a missing custom field, so the
	codebase does not use it here, and matching it would flag the patch file.
	"""
	if isinstance(node, ast.Call):
		fn = node.func
		is_get = isinstance(fn, ast.Attribute) and fn.attr == "get"
		if is_get and node.args and isinstance(node.args[0], ast.Constant):
			return node.args[0].value in OPERATOR_FIELDS
	if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
		return node.slice.value in OPERATOR_FIELDS
	return False


def _is_session_user(node: ast.AST) -> bool:
	"""`frappe.session.user`."""
	return (
		isinstance(node, ast.Attribute)
		and node.attr == "user"
		and isinstance(node.value, ast.Attribute)
		and node.value.attr == "session"
	)


class TestWorkOrderOperatorRoles(unittest.TestCase):
	def test_assignee_rule_is_not_re_derived_at_call_sites(self):
		"""No function outside the helper compares an operator field to the session user.

		This is the regression that matters: three call sites, someone updates two.
		The order opens for a packaging operator and then refuses their finish, and
		nothing raises — it just behaves differently in two screens.
		"""
		tree = _tree()
		offenders = []
		for node in ast.walk(tree):
			if not isinstance(node, ast.Compare):
				continue
			sides = [node.left, *node.comparators]
			touches_field = any(_reads_operator_field(s) for s in sides)
			touches_user = any(_is_session_user(s) for s in sides)
			if touches_field and touches_user:
				fn = _enclosing_function(tree, node)
				if fn != ASSIGNEE_HELPER:
					offenders.append(f"{fn}() at manufacturing.py:{node.lineno}")

		self.assertEqual(
			offenders,
			[],
			"the two-role assignee rule is re-derived outside "
			f"{ASSIGNEE_HELPER}(): {offenders}. Route them through the helper — "
			"a rule spelled out twice is a rule that drifts.",
		)

	def test_operator_fields_are_enumerated_once(self):
		"""`_WO_OPERATOR_FIELDS` exists, is written out once, and names both roles.

		Duplication one level down is the same bug: a helper that carries its own
		tuple leaves the access check and the `list_work_orders` SQL filter free to
		disagree about which fields count — an operator assigned to an order they
		cannot find in their own list.
		"""
		tree = _tree()
		assigned = [
			n
			for n in tree.body
			if isinstance(n, ast.Assign)
			and any(isinstance(t, ast.Name) and t.id == FIELD_LIST for t in n.targets)
		]
		self.assertEqual(
			len(assigned),
			1,
			f"expected exactly one module-level {FIELD_LIST} in manufacturing.py, found {len(assigned)}",
		)
		value = assigned[0].value
		self.assertIsInstance(
			value,
			(ast.Tuple, ast.List),
			f"{FIELD_LIST} must be a literal tuple/list so this test can read it",
		)
		names = {e.value for e in value.elts if isinstance(e, ast.Constant)}
		self.assertEqual(
			names,
			OPERATOR_FIELDS,
			f"{FIELD_LIST} must name both operator roles, got {sorted(names)}",
		)

	def test_packaging_operator_field_is_created_by_a_patch(self):
		"""The column the access rule reads has to exist before the rule can read it.

		Custom Fields exist only because patch code creates them — there is no
		doctype JSON for them. A site that never ran the patch answers
		`doc.get("packaging_operator")` with None for everyone, which fails open
		to "not assigned" rather than closed. Cheap to assert, so assert it.
		"""
		declared = set()
		for path in sorted(PATCHES.glob("*.py")):
			tree = ast.parse(path.read_text(encoding="utf-8"))
			for node in ast.walk(tree):
				if not isinstance(node, ast.Dict):
					continue
				for key, val in zip(node.keys, node.values, strict=True):
					if isinstance(key, ast.Constant) and key.value == "fieldname":
						if isinstance(val, ast.Constant):
							declared.add(val.value)

		self.assertIn(
			"packaging_operator",
			declared,
			"no patch under stabler/patches/ creates the `packaging_operator` Custom Field on Work Order",
		)


if __name__ == "__main__":
	unittest.main()
