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

No bench and no DB — which is why this file is in the push gate and
test_manufacturing_kiosk is not. Two kinds of test live here: the structural ones
that keep a rule from being written down twice, and the pure role-split rule the
28% above is about. Anything needing a Work Order document belongs in
test_manufacturing_kiosk.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_operator_roles -v
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from typing import ClassVar

from stabler.api.manufacturing import (
	_SE_CONSUMPTION,
	_SE_PURPOSES,
	_rows_for_role,
	_unassigned_rows,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "api" / "manufacturing.py"
PATCHES = ROOT / "patches"

#: The one helper allowed to compare an operator field against the session user.
ASSIGNEE_HELPER = "_is_wo_assignee"

#: The one name allowed to enumerate the operator fields.
FIELD_LIST = "_WO_OPERATOR_FIELDS"

OPERATOR_FIELDS = {"operator", "packaging_operator"}

#: The one name allowed to map an operator field to the material role it answers for.
FIELD_ROLE_MAP = "_WO_FIELD_ROLE"

#: The Item Custom Field carrying which role a material belongs to (patch v98).
ITEM_ROLE_FIELD = "custom_operator_role"

#: The one name allowed to spell the consumption purpose.
CONSUMPTION_CONST = "_SE_CONSUMPTION"


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


def _patch_custom_fields() -> list[dict]:
	"""Every Custom Field literal declared under stabler/patches/, as plain dicts.

	Only constant keys and values survive — enough to assert a fieldname and its
	Select options, which is all these tests read.
	"""
	out = []
	for path in sorted(PATCHES.glob("*.py")):
		tree = ast.parse(path.read_text(encoding="utf-8"))
		for node in ast.walk(tree):
			if not isinstance(node, ast.Dict):
				continue
			d = {
				k.value: v.value
				for k, v in zip(node.keys, node.values, strict=True)
				if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
			}
			if "fieldname" in d:
				out.append(d)
	return out


def _module_dict(tree: ast.Module, name: str) -> dict:
	"""A module-level dict literal, by name. Constant keys and values only."""
	for n in tree.body:
		if not isinstance(n, ast.Assign):
			continue
		if not any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
			continue
		if not isinstance(n.value, ast.Dict):
			raise AssertionError(f"{name} must be a literal dict so this test can read it")
		return {
			k.value: v.value
			for k, v in zip(n.value.keys, n.value.values, strict=True)
			if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
		}
	raise AssertionError(f"no module-level {name} in manufacturing.py")


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


class TestMaterialRoleIsMasterData(unittest.TestCase):
	"""Which role a material belongs to is a fact about the item, not about its unit.

	This is the prototype's defect written as a test. `ishlabChiqarish.js:55` answers
	"whose material is this" with `uom === 'kg' ? raw : packaging`, and the item
	catalogue it ships answers it with a stored `operatorTuri`. Over its own 669 BOM
	lines the two disagree on 190. The unit cannot decide: sugar is in kg and belongs
	to pouring, packing film is in kg and belongs to packing.

	So the role is stored on the Item and these tests keep the two vocabularies —
	the role a person holds and the role a material carries — from drifting apart.
	"""

	def test_field_role_map_covers_exactly_the_operator_fields(self):
		"""`_WO_FIELD_ROLE` names every operator field and invents none.

		A field missing here is an operator whose material sheet comes back empty
		while the order still opens for them — assigned, and holding nothing.
		"""
		mapping = _module_dict(_tree(), FIELD_ROLE_MAP)
		self.assertEqual(
			set(mapping),
			OPERATOR_FIELDS,
			f"{FIELD_ROLE_MAP} must key on exactly {sorted(OPERATOR_FIELDS)}, "
			f"got {sorted(mapping)} — the two enumerations have drifted apart",
		)
		self.assertEqual(
			len(set(mapping.values())),
			len(mapping),
			f"{FIELD_ROLE_MAP} gives two operator fields the same role: {mapping}",
		)

	def test_item_role_field_is_created_by_a_patch(self):
		"""The column the material filter reads has to exist before it can be read."""
		declared = {d["fieldname"] for d in _patch_custom_fields()}
		self.assertIn(
			ITEM_ROLE_FIELD,
			declared,
			f"no patch under stabler/patches/ creates the `{ITEM_ROLE_FIELD}` Custom Field on Item",
		)

	def test_item_role_options_are_the_roles_the_code_asks_for(self):
		"""The Select the storekeeper picks from, and the value the filter compares.

		These are two literals in two files, and nothing but this test connects them.
		Get them out of step — "Packaging" in the code, "packaging" in the patch —
		and every packing line silently belongs to nobody: no error, an empty sheet,
		and the finish quietly absorbing the lot.
		"""
		fields = [d for d in _patch_custom_fields() if d["fieldname"] == ITEM_ROLE_FIELD]
		self.assertTrue(fields, f"`{ITEM_ROLE_FIELD}` is not declared by any patch")
		options = {o.strip() for o in (fields[0].get("options") or "").split("\n") if o.strip()}
		self.assertEqual(
			options,
			set(_module_dict(_tree(), FIELD_ROLE_MAP).values()),
			f"the `{ITEM_ROLE_FIELD}` Select options and {FIELD_ROLE_MAP} disagree",
		)


class TestMaterialRoleFilter(unittest.TestCase):
	"""Which material lines belong to which operator — the pure part.

	The rule is stored on the Item (`custom_operator_role`, v98) and never derived
	from the unit of measure. Two of the rows below exist only to hold that line:
	sugar is in kg and belongs to pouring, packing film is in kg and belongs to
	packing. A unit-based rule puts both on the same person and is wrong about one
	of them every time.
	"""

	ROWS: ClassVar = [
		{"item_code": "RAW-MLK", "uom": "L"},
		{"item_code": "RAW-SGR", "uom": "Kg"},
		{"item_code": "PKG-FLM", "uom": "Kg"},
		{"item_code": "PKG-LBL", "uom": "Nos"},
		{"item_code": "RAW-NEW", "uom": "Kg"},
	]
	ROLES: ClassVar = {
		"RAW-MLK": "Production",
		"RAW-SGR": "Production",
		"PKG-FLM": "Packaging",
		"PKG-LBL": "Packaging",
		"RAW-NEW": "",  # catalogued, role not decided yet
	}

	def test_each_role_gets_only_its_own_lines(self):
		pour = [r["item_code"] for r in _rows_for_role(self.ROWS, self.ROLES, "Production")]
		pack = [r["item_code"] for r in _rows_for_role(self.ROWS, self.ROLES, "Packaging")]
		self.assertEqual(pour, ["RAW-MLK", "RAW-SGR"])
		self.assertEqual(pack, ["PKG-FLM", "PKG-LBL"])
		self.assertFalse(set(pour) & set(pack), "a line landed on both operators")

	def test_kilograms_land_on_both_roles(self):
		"""The assertion the prototype's rule cannot satisfy.

		`uom === 'kg' ? raw : packaging` would put sugar and film on the same
		operator. They are on different ones, and only stored data knows that.
		"""
		kg = [r["item_code"] for r in self.ROWS if r["uom"] == "Kg" and self.ROLES[r["item_code"]]]
		roles = {self.ROLES[c] for c in kg}
		self.assertEqual(roles, {"Production", "Packaging"})

	def test_an_undecided_line_belongs_to_neither_operator(self):
		"""Empty role means undecided, and undecided must not default to a person.

		It goes to the shift lead's list and gets counted out loud instead — silence
		here is how an unowned material ends up absorbed by whoever finishes.
		"""
		for role in ("Production", "Packaging"):
			codes = [r["item_code"] for r in _rows_for_role(self.ROWS, self.ROLES, role)]
			self.assertNotIn("RAW-NEW", codes, f"undecided line leaked into {role}")
		self.assertEqual([r["item_code"] for r in _unassigned_rows(self.ROWS, self.ROLES)], ["RAW-NEW"])

	def test_a_caller_with_no_role_gets_nothing(self):
		"""The fails-open case: `roles.get(code)` is None for an undecided line, and
		a caller holding no role is also None. Compared naively the two match, and a
		stranger to the order is handed exactly the lines nobody owns."""
		self.assertEqual(_rows_for_role(self.ROWS, self.ROLES, None), [])
		self.assertEqual(_rows_for_role(self.ROWS, self.ROLES, ""), [])

	def test_an_item_missing_from_the_catalogue_is_undecided_not_crashing(self):
		"""A site that has not migrated v98 yet answers with an empty role map."""
		self.assertEqual(_rows_for_role(self.ROWS, {}, "Production"), [])
		self.assertEqual(len(_unassigned_rows(self.ROWS, {})), len(self.ROWS))


if __name__ == "__main__":
	unittest.main()


class TestConsumptionPurposeHasOneSpelling(unittest.TestCase):
	"""ERPNext decides what a Stock Entry is by matching `purpose` character for
	character — `stock_entry.py` alone branches on this string in a dozen places.

	A near miss does not fail loudly. The entry inserts, submits, and posts stock,
	and only the work-order bookkeeping quietly skips it: `consumed_qty` never moves,
	so the operator sees material leave the warehouse while their own write-off total
	stays at zero and the finish entry sweeps the same lines a second time.

	Which is why the spelling lives in one constant and these tests keep it there.
	"""

	def test_the_endpoint_accepts_the_consumption_purpose(self):
		"""Without this the split has no way in — `make_work_order_stock_entry`
		refuses every purpose outside `_SE_PURPOSES`, and an operator write-off comes
		back as "Unsupported purpose" from an endpoint that was built to support it."""
		self.assertIn(
			_SE_CONSUMPTION,
			_SE_PURPOSES,
			"the consumption purpose is not on the endpoint's whitelist",
		)

	def test_the_purpose_string_is_written_exactly_once(self):
		"""Three call sites read this purpose: the whitelist, the role guard and the
		warehouse fix-up. Spelled inline they are three chances to typo one and two
		chances for a later rename to miss one — the same shape as the prototype
		defect v98 records, where the stored rule and the computed rule disagreed on
		190 of 669 lines because both existed.
		"""
		tree = _tree()
		literals = [
			node
			for node in ast.walk(tree)
			if isinstance(node, ast.Constant) and node.value == _SE_CONSUMPTION
		]
		self.assertEqual(
			len(literals),
			1,
			f"{_SE_CONSUMPTION!r} is spelled inline at line(s) "
			f"{sorted(n.lineno for n in literals)} — read {CONSUMPTION_CONST} instead",
		)
		assigned_at = [
			target.id
			for node in ast.walk(tree)
			if isinstance(node, ast.Assign)
			for target in node.targets
			if isinstance(target, ast.Name)
			and isinstance(node.value, ast.Constant)
			and node.value.value == _SE_CONSUMPTION
		]
		self.assertEqual(
			assigned_at,
			[CONSUMPTION_CONST],
			f"the single spelling must be the definition of {CONSUMPTION_CONST}, found {assigned_at}",
		)
