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

4. **A DocPerm write right on the unfrozen money aggregate.** No command needs
   one — every mutation runs through ``db_set``, which checks no permission —
   so the grant serves only the callers that went around the command layer.
   Remittance Transfer has neither a submit freeze nor a controller-level
   immutability guard, so those callers can rewrite anything. Write and a
   freeze are asserted as a pair.

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

# Administrator-tier roles. Narrowing what these may do is a whole-app decision,
# not a remittance one, so the write assertions below exclude them rather than
# pretending this module gets to rule on them.
ADMIN_ROLES = {"System Manager", "Stabler Admin"}

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
	"""Roles holding a DOCUMENT right, which is a permlevel-0 question only.

	`frappe/permissions.py:315` filters the permission rows with
	`cint(perm.permlevel) == 0` before it computes read/write/create/delete, so a
	row at a higher level contributes nothing to what a caller may do to the
	record — it is read exclusively by `Document.get_permlevel_access`, which
	decides which FIELDS survive a save or a projection. Counting a permlevel-1
	row here would report a `PUT /api/resource` hole that Frappe does not open,
	and the tests below are all about document rights.
	"""
	return {row["role"] for row in _perms(name) if row.get(right) and not row.get("permlevel")}


def _controller_source(name: str) -> str:
	return _read(os.path.join(_PKG, "stabler", "doctype", name, f"{name}.py"))


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

	def test_no_operating_role_holds_a_docperm_write_on_a_transfer(self):
		"""Write is not how a transfer moves, so a write grant only opens a side door.

		Every server-side mutation of a transfer runs through
		``transfer.db_set(...)`` — remittance_accounting.py:260/288/311 and
		remittance_commands.py:329 — and ``db_set`` writes the column directly
		with no permission check at all. The single permission-checked write in
		the command layer is ``transfer.insert()``, which consumes ``create``.

		So a DocPerm ``write`` row is unreachable from inside the command layer
		*by construction*: the only callers it can ever serve are the ones that
		went around it — ``PUT /api/resource/Remittance Transfer/<name>`` and
		``frappe.client.set_value``, both of which Frappe honours straight off
		the DocPerm row. Those callers get no row lock, no ``client_request_id``
		replay guard, no Journal Entry and no Remittance Event.

		Concretely, a Cashier holding write could rewrite ``pickup_code_hash``
		to the digest of a code they chose and collect someone else's payout,
		reset ``code_attempts`` to defeat the lockout, set ``operational_status``
		to Paid Out with no Journal Entry behind it, or repoint ``company``.
		``read_only`` on those fields does not help: it is a form property, and
		the REST API ignores it.
		"""
		self.assertEqual(_roles_with("remittance_transfer", "write") - ADMIN_ROLES, set())

	def test_the_field_level_write_grant_is_not_a_document_write(self):
		"""`pickup_code_hash` is permlevel 1, and that grant must stay field-level.

		Cashier and Finance Manager hold `write` at permlevel 1 so Frappe does not
		blank the digest on insert — `Document.validate_higher_perm_levels` resets a
		permlevel field the saver cannot write, which would store NULL and leave the
		transfer unpayable. That grant is invisible to `PUT /api/resource`:
		`frappe/permissions.py:315` computes document rights from permlevel-0 rows
		only, so the side door the test above guards stays shut.

		Pinned as its own assertion rather than left to `_roles_with`'s filter,
		because the next person to see this failure will be tempted to widen the
		helper, and the reason it is safe to is this line and not that one.
		"""
		rows = _perms("remittance_transfer")
		level_one = [row for row in rows if row.get("permlevel") == 1]
		self.assertTrue(level_one, "the digest grant is gone — check remittance_transfer.json")
		for row in level_one:
			self.assertTrue(row.get("write"), row)
			# Read at that level would hand the digest back to /api/resource, which
			# is the whole thing the permlevel was raised to prevent.
			self.assertFalse(row.get("read"), row)
			self.assertNotIn("delete", row, row)
		# And the roles that hold it hold no document write of any kind.
		self.assertEqual(
			{row["role"] for row in level_one} - ADMIN_ROLES - _roles_with("remittance_transfer", "write"),
			{row["role"] for row in level_one} - ADMIN_ROLES,
		)

	def test_a_write_grant_may_only_arrive_paired_with_a_freeze(self):
		"""The tripwire for whoever next decides they need write.

		This asserts an implication, not an absence — write may come back the
		day something freezes the record alongside it. What must not happen is
		write arriving alone and silently.

		Vehicle Finance is the precedent these permissions were modelled on, and
		it survives its write grants only because ``vehicle_agreement.json`` and
		``vehicle_finance_payment_application.json`` are submittable: submit
		freezes the document and any later write needs ``allow_on_submit`` per
		field. Remittance Transfer has no equivalent. It carries no
		``is_submittable``, and ``RemittanceTransfer.validate`` enforces three
		arithmetic invariants and nothing else — no state-transition guard, no
		field immutability, no ``on_update``. Copying the vehicle-finance
		permission shape without copying its freeze is what made the grant a
		hole rather than a convenience.

		If this fails, either pair the grant with a real freeze or drop it.
		Editing the test to accept a third kind of freeze is fine — that edit is
		the deliberate act this exists to force.
		"""
		writers = _roles_with("remittance_transfer", "write") - ADMIN_ROLES
		freezes = {
			# Submit freezes the document; later writes need allow_on_submit.
			"is_submittable": bool(_load_doctype("remittance_transfer").get("is_submittable")),
			# The Frappe idiom for per-field immutability on update.
			"controller change guard": any(
				idiom in _controller_source("remittance_transfer")
				for idiom in ("has_value_changed", "get_doc_before_save")
			),
		}
		self.assertTrue(
			not writers or any(freezes.values()),
			f"{sorted(writers)} now hold DocPerm write on Remittance Transfer, which "
			"Frappe honours on PUT /api/resource and frappe.client.set_value — outside "
			"the command layer's row lock, idempotency key, Journal Entry and event "
			"trail. Nothing freezes the record against those callers: "
			f"{freezes}. Pair the grant with a freeze, or drop it.",
		)

	def test_every_role_can_read_a_transfer(self):
		# Viewer and Auditor are read-only by definition; read is the whole of
		# what "masked list/detail" and "read-only over JE, event and
		# reconciliation" are built on.
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
