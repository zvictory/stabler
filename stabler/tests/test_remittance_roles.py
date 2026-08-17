"""The remittance roles, and the permission rows that are allowed to name them.

Three failures this file exists to catch, all of them measured defects rather
than hypotheticals:

1. **A doctype naming a role nothing creates.** Vehicle Finance ships seven roles
   from ``v84_vehicle_finance_roles``; remittance shipped none, so every
   remittance doctype carried a single System-Manager row. Adding role rows to
   the JSON without adding the role to the patch produces a permission set that
   resolves to nobody — the same class of bug, inverted. So the JSONs and the
   patch are asserted against each other, not against a hand-copied list.

2. **A delete right on the money aggregate.** Remittance Transfer carries three
   Journal Entry links and an append-only Remittance Event trail. Deleting the
   master leaves the Journal Entries posted with nothing tying them together,
   and ``track_changes`` does not save it — Frappe deletes the Version rows with
   the document. No role gets delete, System Manager included.

3. **A role that can register but cannot record the event.**
   ``remittance_commands._append_event`` inserts the Remittance Event with a
   plain ``.insert()`` — no ``ignore_permissions`` — so a role with create on
   Remittance Transfer and no create on Remittance Event makes registration
   raise PermissionError halfway through the transaction. The two grants are
   coupled, and nothing else in the tree says so.

Bench-free on purpose: the bench set is not part of ``make check``, so a test
that needed one would not gate a push.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATCH_MODULE = "stabler.patches.v87_remittance_roles"
_PATCH_PATH = os.path.join(_PKG, "patches", "v87_remittance_roles.py")
_PATCHES_TXT = os.path.join(_PKG, "patches.txt")

# The four roles the plan names (docs/plans/2026-08-16-remittance-operations-center.md:456-460).
# Duplicated here on purpose: this list is the contract, and the patch is checked
# against it. Widening the module's role set must be a deliberate edit in two places.
PLANNED_ROLES = {
	"Remittance Viewer",
	"Remittance Cashier",
	"Remittance Finance Manager",
	"Remittance Auditor",
}

# Roles that exist without any stabler patch creating them.
CORE_ROLES = {"System Manager", "Stabler Admin", "All"}

REMITTANCE_DOCTYPES = (
	"remittance_settings",
	"remittance_cash_desk_account",
	"remittance_transfer",
	"remittance_event",
)

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def _load_doctype(name: str) -> dict:
	path = os.path.join(_PKG, "stabler", "doctype", name, f"{name}.json")
	with open(path, encoding="utf-8") as fh:
		return json.load(fh)


def _perms(name: str) -> list[dict]:
	return _load_doctype(name).get("permissions") or []


def _roles_with(name: str, right: str) -> set[str]:
	return {row["role"] for row in _perms(name) if row.get(right)}


# --- fake frappe for the patch ----------------------------------------------


class _FakeRole:
	def __init__(self, store: dict):
		self._store = store
		self.role_name = None
		self.desk_access = None

	def insert(self, ignore_permissions=False):
		self._store[self.role_name] = self


class _FakeDb:
	"""Just enough of ``frappe.db``: the role guard, the table probes, and a log
	of the SQL the DocPerm repair decided to run."""

	def __init__(self, *, existing_roles=(), missing_tables=()):
		self.roles: dict[str, _FakeRole] = {role: _FakeRole({}) for role in existing_roles}
		self.missing_tables = set(missing_tables)
		self.sql_calls: list[tuple[str, tuple]] = []

	def exists(self, doctype, name=None):
		if doctype == "Role":
			return name in self.roles
		return True

	def table_exists(self, doctype):
		# Never raises. ``has_column`` would raise TableMissingError here, which
		# is the whole reason the patch may not use it.
		return doctype not in self.missing_tables

	def has_column(self, doctype, column):  # pragma: no cover - must never be called
		raise AssertionError("the patch must probe with table_exists, not has_column")

	def sql(self, query, values=None, **_kwargs):
		self.sql_calls.append((" ".join(query.split()), values))
		return []


def _load_patch(db):
	_SANDBOX.evict(_PATCH_MODULE, "frappe")
	frappe = types.ModuleType("frappe")
	frappe.db = db
	frappe.new_doc = lambda doctype: _FakeRole(db.roles)
	_SANDBOX.install({"frappe": frappe})
	return importlib.import_module(_PATCH_MODULE)


# --- the roles exist where they are named ------------------------------------


class TestPatchCreatesTheRolesTheDoctypesName(unittest.TestCase):
	def setUp(self):
		self.source = _read(_PATCH_PATH)

	def test_patch_is_registered(self):
		self.assertTrue(os.path.exists(_PATCH_PATH))
		self.assertIn(_PATCH_MODULE, _read(_PATCHES_TXT))

	def test_patch_creates_exactly_the_roles_the_plan_names(self):
		db = _FakeDb()
		_load_patch(db).execute()
		self.assertEqual(set(db.roles), PLANNED_ROLES)

	def test_no_remittance_doctype_names_a_role_nobody_creates(self):
		"""The defect this bead was filed for, in reverse: a permission row whose
		role name resolves to nothing gives that doctype to no user at all."""
		db = _FakeDb()
		_load_patch(db).execute()
		creatable = set(db.roles) | CORE_ROLES
		for doctype in REMITTANCE_DOCTYPES:
			for row in _perms(doctype):
				with self.subTest(doctype=doctype, role=row["role"]):
					self.assertIn(row["role"], creatable)

	def test_every_planned_role_actually_reaches_a_doctype(self):
		"""A role no doctype grants anything is decoration; ``allowed_actions``
		(stabler-ljt6) would key its matrix on a name that opens nothing."""
		granted = set()
		for doctype in REMITTANCE_DOCTYPES:
			granted.update(row["role"] for row in _perms(doctype))
		self.assertEqual(PLANNED_ROLES - granted, set())

	def test_roles_are_spa_only(self):
		db = _FakeDb()
		_load_patch(db).execute()
		for role in PLANNED_ROLES:
			with self.subTest(role=role):
				self.assertEqual(db.roles[role].desk_access, 0)

	def test_rerunning_creates_nothing(self):
		db = _FakeDb(existing_roles=PLANNED_ROLES)
		before = dict(db.roles)
		_load_patch(db).execute()
		self.assertEqual(db.roles, before)


# --- the DocPerm repair ------------------------------------------------------


class TestTransferDeleteRepair(unittest.TestCase):
	def _updates(self, db):
		return [call for call in db.sql_calls if "tabDocPerm" in call[0]]

	def test_repair_clears_the_stale_delete_flag(self):
		db = _FakeDb()
		_load_patch(db).execute()
		updates = self._updates(db)
		self.assertEqual(len(updates), 1)
		query, values = updates[0]
		self.assertIn("set `delete` = 0", query)
		self.assertEqual(values, ("Remittance Transfer",))

	def test_repair_is_scoped_to_rows_that_still_carry_the_flag(self):
		"""Re-running must be a no-op, and the UPDATE must not touch a doctype
		that merely shares a role."""
		db = _FakeDb()
		_load_patch(db).execute()
		query, _values = self._updates(db)[0]
		self.assertIn("`delete` = 1", query)
		self.assertIn("parent = %s", query)

	def test_repair_skips_a_tenant_without_the_doctype(self):
		"""A site that does not carry Remittance Transfer must skip, not abort the
		migrate. ``has_column`` would raise TableMissingError instead of
		returning False, so the patch may only probe with ``table_exists``."""
		db = _FakeDb(missing_tables={"Remittance Transfer"})
		_load_patch(db).execute()
		self.assertEqual(self._updates(db), [])
		# roles still land: they are the app's capability layer, not per-tenant data
		self.assertEqual(set(db.roles), PLANNED_ROLES)

	def test_patch_source_never_reaches_for_has_column(self):
		"""Asserted over the parsed tree, not the text: the docstring names
		``has_column`` to explain why it is banned, and a substring check would
		make writing that explanation down impossible."""
		tree = ast.parse(_read(_PATCH_PATH))
		called = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
		self.assertNotIn("has_column", called)
		self.assertIn("table_exists", called)


# --- the permission matrix ---------------------------------------------------


class TestRemittanceTransferPermissions(unittest.TestCase):
	def test_nobody_can_delete_a_transfer(self):
		"""Three Journal Entry links and an append-only event trail hang off this
		record. Deleting it leaves the Journal Entries posted in the GL with
		nothing tying them together, and Frappe drops the Version rows with the
		document, so ``track_changes`` does not preserve what was erased. A wrong
		transfer is undone by a domain reversal, not by a row delete."""
		for row in _perms("remittance_transfer"):
			self.assertNotIn("delete", row, row)

	def test_only_the_two_operating_roles_can_move_a_transfer(self):
		# Viewer and Auditor are read-only by definition; if either gains write,
		# "masked list/detail" and "read-only over JE, event and reconciliation"
		# have stopped being true.
		self.assertEqual(
			_roles_with("remittance_transfer", "write"),
			{"Remittance Cashier", "Remittance Finance Manager", "System Manager"},
		)
		self.assertEqual(
			_roles_with("remittance_transfer", "read"),
			PLANNED_ROLES | {"System Manager"},
		)

	def test_transfer_is_not_submittable_so_no_row_claims_submit(self):
		# Permission keys Frappe ignores on a non-submittable doctype read as
		# intent that is not enforced anywhere.
		self.assertNotIn("is_submittable", _load_doctype("remittance_transfer"))
		for row in _perms("remittance_transfer"):
			for key in ("submit", "cancel", "amend"):
				self.assertNotIn(key, row, row)


class TestRemittanceEventPermissions(unittest.TestCase):
	def test_the_trail_stays_append_only(self):
		"""The controller throws on edit and on delete; granting either here
		would advertise a door the controller then slams, which is how a caller
		learns to retry rather than to stop."""
		for row in _perms("remittance_event"):
			self.assertNotIn("write", row, row)
			self.assertNotIn("delete", row, row)

	def test_whoever_can_mutate_a_transfer_can_append_its_event(self):
		"""``remittance_commands._append_event`` inserts with a bare ``.insert()``
		— no ``ignore_permissions`` — inside the same transaction as the transfer
		write. A role holding create on the transfer but not on the event turns
		registration into a mid-transaction PermissionError."""
		mutators = _roles_with("remittance_transfer", "create")
		appenders = _roles_with("remittance_event", "create")
		self.assertEqual(mutators - appenders, set())

	def test_read_only_roles_cannot_append(self):
		self.assertEqual(
			_roles_with("remittance_event", "create"),
			{"Remittance Cashier", "Remittance Finance Manager", "System Manager"},
		)


class TestRemittanceSettingsPermissions(unittest.TestCase):
	def test_only_the_finance_manager_edits_the_account_mapping(self):
		"""Settings decides which drawer the cash lands in. A Cashier who can
		rewrite it can redirect the money it is about to count."""
		self.assertEqual(
			_roles_with("remittance_settings", "write"),
			{"Remittance Finance Manager", "System Manager"},
		)

	def test_every_role_can_read_the_mapping(self):
		self.assertEqual(
			_roles_with("remittance_settings", "read"),
			PLANNED_ROLES | {"System Manager"},
		)


class TestCashDeskAccountIsUntouched(unittest.TestCase):
	def test_the_child_table_still_carries_no_permissions(self):
		"""Frappe resolves a child table's permissions through its parent, so a
		permissions array here is inert. Rows added to it would read as a grant
		that is not one — and would need maintaining forever."""
		dt = _load_doctype("remittance_cash_desk_account")
		self.assertEqual(dt["istable"], 1)
		self.assertEqual(dt["permissions"], [])


if __name__ == "__main__":
	unittest.main()
