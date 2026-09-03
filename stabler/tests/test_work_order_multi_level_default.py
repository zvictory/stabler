"""`use_multi_level_bom` must arrive at 0, and it must arrive there in time.

ERPNext ships `Work Order.use_multi_level_bom` defaulting to 1. With 1,
`work_order.py:1558-1560` passes `fetch_exploded=self.use_multi_level_bom` into
`get_bom_items_as_dict`, which at `bom.py:1427` reads `BOM Explosion Item`
instead of `BOM Item` — so a sub-assembly that is produced by its own Work Order
(anjan's ice-cream mix, "смесь") is blown apart into flour, sugar and milk on
the order that is supposed to *consume* the mix. The operator is then asked to
issue raw materials for a thing they already made.

Measured on anjan, read-only, 2026-09-03: 197 of 4 271 Work Orders carry 1
(167 of them submitted, the most recent 2026-09-02 09:31), and 34 items had
been made both ways. Two creation paths produce 1 unless a human remembers to
untick a box: the Desk dialog on the BOM form, and Stabler's own
`create_work_order`, which never wrote the flag at all — `frappe.new_doc`
handed it the meta default.

Two things must hold, and only one of them is about the value:

  1. `create_work_order` sets the flag to 0 explicitly, instead of trusting a
     default that a Property Setter could be reset away from (Customize Form's
     "Reset to defaults" deletes it) or that a site could migrate late.
  2. It sets it BEFORE the BOM is read. `work_order.py:1559` passes
     `fetch_exploded=self.use_multi_level_bom` at the moment
     `get_items_and_operations_from_bom()` is called, and `:405-406`
     (`reset_use_multi_level_bom`) returns early for a new document, so
     `insert()` never re-derives the material list. An assignment placed after
     that call sets a field nobody reads again: the saved Work Order says
     `use_multi_level_bom = 0` and carries exploded materials anyway. That is
     the failure this file exists to catch, because it is invisible in the
     stored flag and only shows up in `required_items`.

Ordering is asserted on the parse tree rather than on behaviour because the
behaviour needs a bench, a site, a BOM and a sub-assembly; the bench half lives
in `test_work_order_multi_level_default_bench.py`. This half runs anywhere:

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_work_order_multi_level_default -v
"""

from __future__ import annotations

import ast
import pathlib
import unittest

_APP_ROOT = pathlib.Path(__file__).resolve().parents[1]  # .../stabler
_MANUFACTURING_API = _APP_ROOT / "api" / "manufacturing.py"
_PATCH = _APP_ROOT / "patches" / "v102_work_order_multi_level_bom_default.py"
_PATCHES_TXT = _APP_ROOT / "patches.txt"

_PATCH_ENTRY = "stabler.patches.v102_work_order_multi_level_bom_default"

#: The Property Setter the patch must actually write, field by field. ERPNext's
#: own BOM form looks up {doc_type, field_name, property} (`bom.py:232-241`) to
#: decide what the Desk dialog shows, `frappe.new_doc` reads the same value
#: through the doctype meta, and `meta.py:437-444` applies the row to a *field*
#: only when `doctype_or_field` says DocField. Get any one of these wrong and the
#: patch inserts a row that is real, valid, and read by nobody — the worst
#: outcome, because migrate stays green.
_EXPECTED_SETTER = {
	"doctype": "Property Setter",
	"doctype_or_field": "DocField",
	"doc_type": "Work Order",
	"field_name": "use_multi_level_bom",
	"property": "default",
	# Customize Form writes `default` as Text (`customize_form.py:800`). The
	# in-repo helper in v20_cost_field_perm_level.py hardcodes "Int"; copying it
	# would store a type Frappe never writes for this property.
	"property_type": "Text",
	"value": "0",
}


# --------------------------------------------------------------------------- #
# Everything below reads the patch's PARSE TREE, never its text.
#
# The first version of this file grepped the source for each expected literal.
# Every one of those literals also appears in the module docstring, which
# explains the design — so the pin was satisfiable by prose. Measured: with the
# grep version, four separate mutations of v102 all stayed green — VALUE "0"→"1",
# FIELDNAME→"wrong_field", PROPERTY_TYPE "Text"→"Int", and replacing execute()'s
# whole body with clear_cache+commit so it wrote no setter at all. A test whose
# subject is a docstring is not a test.
# --------------------------------------------------------------------------- #
def _patch_tree() -> tuple[ast.Module, dict[str, object]]:
	"""The patch's AST plus its module-level string/number constants."""
	tree = ast.parse(_PATCH.read_text(encoding="utf-8"))
	constants = {
		target.id: node.value.value
		for node in tree.body
		if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
		for target in node.targets
		if isinstance(target, ast.Name)
	}
	return tree, constants


def _resolve(node: ast.expr, constants: dict[str, object]) -> object:
	"""A literal, or the module constant a Name refers to. Unresolvable → None.

	The patch names its values through constants, so a checker that only
	understood literals would read the real code as empty and pass on nothing.
	"""
	if isinstance(node, ast.Constant):
		return node.value
	if isinstance(node, ast.Name):
		return constants.get(node.id)
	return None


def _execute_fn(tree: ast.Module) -> ast.FunctionDef:
	for node in tree.body:
		if isinstance(node, ast.FunctionDef) and node.name == "execute":
			return node
	raise AssertionError(f"no `def execute()` in {_PATCH} — Frappe would fail to run this patch")


def _inserted_setter_fields() -> dict[str, object]:
	"""The Property Setter dict literal `execute()` hands to `frappe.get_doc`.

	Scoped to execute() and matched on the resolved `"doctype"` key, so a dict
	somewhere else in the module cannot stand in for the one that is written.
	"""
	tree, constants = _patch_tree()
	for node in ast.walk(_execute_fn(tree)):
		if not isinstance(node, ast.Dict):
			continue
		fields = {
			key.value: _resolve(value, constants)
			for key, value in zip(node.keys, node.values, strict=True)
			if isinstance(key, ast.Constant) and isinstance(key.value, str)
		}
		if fields.get("doctype") == "Property Setter":
			return fields
	return {}


def _write_calls() -> list[str]:
	"""The names of the persisting calls inside execute() — `insert` / `save`.

	`frappe.get_doc({...})` on its own builds a document and throws it away. The
	dict being correct is not the same claim as the row reaching the database.
	"""
	tree, _ = _patch_tree()
	return [
		node.func.attr
		for node in ast.walk(_execute_fn(tree))
		if isinstance(node, ast.Call)
		and isinstance(node.func, ast.Attribute)
		and node.func.attr in {"insert", "save"}
	]


def _clear_cache_doctypes() -> list[str]:
	"""The doctype every `frappe.clear_cache(doctype=...)` in v102 clears.

	Resolved rather than grepped: the patch names the doctype through a module
	constant, and a test that demanded the literal string would go red on a
	rename that changed nothing, while a test that only grepped for
	`clear_cache` would stay green if the call were pointed at another doctype.
	What must be true is the effective argument.
	"""
	tree, constants = _patch_tree()
	cleared = []
	for node in ast.walk(tree):
		if not (
			isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr == "clear_cache"
		):
			continue
		for kw in node.keywords:
			if kw.arg == "doctype":
				cleared.append(_resolve(kw.value, constants))
	return cleared


def _create_work_order_body() -> list[ast.stmt]:
	"""The statements of `create_work_order`, or fail loudly if it moved."""
	tree = ast.parse(_MANUFACTURING_API.read_text(encoding="utf-8"))
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and node.name == "create_work_order":
			return node.body
	raise AssertionError(
		f"no `def create_work_order` in {_MANUFACTURING_API} — this guard is pointed at nothing"
	)


def _flag_assignment_lines() -> list[int]:
	"""Line numbers of every `<...>.use_multi_level_bom = 0` in create_work_order."""
	lines = []
	for node in _create_work_order_body():
		for sub in ast.walk(node):
			if not isinstance(sub, ast.Assign):
				continue
			for target in sub.targets:
				if not (isinstance(target, ast.Attribute) and target.attr == "use_multi_level_bom"):
					continue
				if isinstance(sub.value, ast.Constant) and sub.value.value in (0, False):
					lines.append(sub.lineno)
	return lines


def _bom_read_lines() -> list[int]:
	"""Line numbers of the calls that read the flag and freeze the material list."""
	lines = []
	for node in _create_work_order_body():
		for sub in ast.walk(node):
			if (
				isinstance(sub, ast.Call)
				and isinstance(sub.func, ast.Attribute)
				and sub.func.attr == "get_items_and_operations_from_bom"
			):
				lines.append(sub.lineno)
	return lines


class CreateWorkOrderPinsTheFlagBeforeReadingTheBom(unittest.TestCase):
	def test_the_scan_finds_the_bom_read(self):
		"""Without this, deleting or renaming the BOM call would leave the
		ordering test comparing against an empty list and passing silently —
		green for the one reason that proves nothing."""
		self.assertEqual(
			len(_bom_read_lines()),
			1,
			"expected exactly one get_items_and_operations_from_bom() call in "
			"create_work_order; the ordering assertion below is only meaningful "
			"against a single, known read point",
		)

	def test_create_work_order_sets_the_flag_to_zero(self):
		"""Stabler's modal offers no multi-level control (ADR-602), so every
		order it creates must be single-level. Relying on the Property Setter
		alone would make that true only until somebody hits Customize Form →
		Reset, or until a tenant's migrate lags; the explicit assignment is what
		makes the API's own behaviour independent of site state."""
		self.assertEqual(
			len(_flag_assignment_lines()),
			1,
			"create_work_order must assign use_multi_level_bom = 0 exactly once; "
			"without it frappe.new_doc supplies ERPNext's default of 1 and the "
			"sub-assembly is exploded into raw materials (anjan: 197 such orders "
			"as of 2026-09-03)",
		)

	def test_the_assignment_comes_before_the_bom_is_read(self):
		"""The one ordering that cannot be inferred from the saved record.

		`get_items_and_operations_from_bom()` reads the flag as it runs
		(`work_order.py:1559`), and `reset_use_multi_level_bom` returns early on
		a new document (`:405-406`), so `insert()` does not re-derive anything.
		Assign after the call and the Work Order stores 0 while its
		`required_items` are still the exploded list — the flag says one thing,
		the materials another, and no test that only reads the flag can tell.
		"""
		assignment = _flag_assignment_lines()
		bom_read = _bom_read_lines()
		self.assertTrue(assignment, "no use_multi_level_bom = 0 assignment to order")
		self.assertTrue(bom_read, "no get_items_and_operations_from_bom() call to order against")
		self.assertLess(
			assignment[0],
			bom_read[0],
			f"use_multi_level_bom = 0 is assigned at line {assignment[0]}, after "
			f"get_items_and_operations_from_bom() at line {bom_read[0]}. The BOM has "
			"already been exploded by then; the flag is never read again on a new "
			"document, so the order ships with the mix blown apart into its raw "
			"materials while the stored flag claims otherwise.",
		)


class ThePatchWritesTheKeyErpnextReads(unittest.TestCase):
	"""Source-level pins on v102. The behaviour needs a bench; the key does not.

	Every value below is load-bearing somewhere in Frappe or ERPNext: get one
	wrong and the patch inserts a Property Setter that is real, valid, and read
	by nobody — the worst outcome, because migrate stays green.
	"""

	def test_the_patch_module_exists(self):
		self.assertTrue(
			_PATCH.is_file(),
			f"{_PATCH} is missing — patches.txt would name a module that cannot import, "
			"and migrate fails on every tenant",
		)

	def test_execute_actually_writes_a_setter(self):
		"""The assertion the field-by-field one cannot make on its own.

		Delete execute()'s body and leave only the cache clear and the commit, and
		a checker that inspects "the dict the patch writes" has no dict to inspect
		— it reports nothing wrong about nothing. Migrate then runs clean on every
		tenant, records a Patch Log row saying this ran, and no default changes.
		Both halves have to be asserted: that a Property Setter dict is built, and
		that something persists it.
		"""
		self.assertTrue(
			_inserted_setter_fields(),
			"execute() builds no Property Setter dict at all — the patch is a no-op "
			"that migrate will mark as applied, so it never gets a second chance",
		)
		self.assertTrue(
			_write_calls(),
			"execute() never calls .insert() or .save(); frappe.get_doc({...}) alone "
			"builds a document in memory and discards it",
		)

	def test_the_inserted_setter_carries_the_key_erpnext_reads(self):
		"""Field by field, against the parse tree, so the docstring cannot help.

		A wrong `field_name` or `doc_type` makes the row invisible to the BOM
		dialog's lookup (`bom.py:232-241`) and to the meta; a wrong
		`doctype_or_field` makes `meta.py:437-444` apply it to the doctype instead
		of the field; a wrong `value` sets the opposite default while looking
		entirely correct in a diff.
		"""
		fields = _inserted_setter_fields()
		for key, expected in _EXPECTED_SETTER.items():
			with self.subTest(field=key):
				self.assertEqual(
					fields.get(key),
					expected,
					f"v102's Property Setter sets {key}={fields.get(key)!r}, expected "
					f"{expected!r}. A setter keyed even slightly differently is a valid "
					"row that nothing reads, and migrate stays green.",
				)

	def test_the_patch_clears_the_work_order_meta_cache(self):
		"""`frappe.db.set_value` on an existing Property Setter skips
		`PropertySetter.validate`, and with it the `frappe.clear_cache(doctype)`
		that makes the new default visible (`property_setter.py:39-45`). Every
		already-running worker would keep serving 1 out of its cached meta until
		the next restart — a migrate that reports success and changes nothing.
		The explicit clear at the end of the patch is what removes that
		dependency on which write path the code happened to take.
		"""
		self.assertIn(
			"Work Order",
			_clear_cache_doctypes(),
			'v102 must call frappe.clear_cache(doctype="Work Order") explicitly; '
			"without it the cached meta in live processes keeps handing out the old "
			f"default. Cleared doctypes found: {_clear_cache_doctypes()!r}",
		)


class ThePatchIsRegistered(unittest.TestCase):
	def test_patches_txt_appends_the_new_entry(self):
		"""A patch module that nothing in patches.txt names never runs, on any
		site, ever — and leaves no trace of not having run. Appending at the end
		is also the only edit `test_patches_pin.py` allows: Frappe keys Patch Log
		by dotted module path, so renaming or reordering an existing line makes
		every tenant re-run that patch on its next migrate.

		This asserted `entries[-1]` until 2026-09-03, which was true only while
		v102 WAS the newest patch: the next patch appended — v103, the tender
		accounting dimension — turned it red by doing exactly what this docstring
		tells the next author to do. What the guard is actually for is that the
		entry EXISTS and sits after its predecessor rather than being spliced into
		the middle of the file; the "is the last line" half was a fact about the
		day it was written, not a rule anyone can keep.
		"""
		entries = [
			line.strip()
			for line in _PATCHES_TXT.read_text(encoding="utf-8").splitlines()
			if line.strip() and not line.strip().startswith("[")
		]
		self.assertIn(_PATCH_ENTRY, entries, f"{_PATCH_ENTRY!r} is not in stabler/patches.txt")
		self.assertEqual(
			entries.index(_PATCH_ENTRY),
			entries.index("stabler.patches.v101_seed_stop_reasons") + 1,
			f"{_PATCH_ENTRY!r} was moved out of its appended position",
		)


if __name__ == "__main__":
	unittest.main()
