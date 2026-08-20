"""J2: two sealers reading the same `prev_hash` fork the audit chain.

`seal_audit_log` reads the last seal to learn `prev_seq` and `prev_hash`, spends
a while hashing every Version row since then, and only then inserts the new
seal. `seq` carries no unique flag in the doctype JSON, so nothing at the
database level refuses a second seal claiming the same number. The nightly
scheduler tick and an operator's `bench execute` overlapping is a narrow window
— but the damage is the one thing this table exists to prevent: a tamper-evident
chain that forks is a chain that proves nothing, and it stays forked forever
because every later seal chains onto one of the two branches.

The complete fix is a unique index on `seq`. That is a doctype change and
per-site DDL on seven tenants, so the board deferred it and took the half that
costs nothing: read the row the chain is anchored to `FOR UPDATE`, inside the
same transaction that writes the next one.

What that does and does not buy, stated because a half-guard described as a
whole one is worse than no guard:

* A chain that already has seals: covered. The second sealer blocks on the row
  until the first commits, then reads the seal it just wrote.
* An empty table: `seq` has no index, so the read is a full scan and InnoDB's
  next-key locking under REPEATABLE READ does hold the gap — but that is a
  property of the isolation level and of an index NOT existing, neither of which
  this code controls. Do not rely on it; the unique index is still owed.

Bench-free: what is asserted is which statement is issued and in what order.

  PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_audit_seal_lock -v
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()
_MODULE = "stabler.api.audit"


def tearDownModule():
	_SANDBOX.restore()


class _FakeSeal:
	"""What `frappe.get_doc({...}).insert()` stands for here."""

	def __init__(self, fields, trace):
		self.__dict__.update(fields)
		self.__dict__["_trace"] = trace
		self.name = "SEAL-2026-000002"

	def insert(self, **kwargs):
		self._trace.append("insert-seal")


def _load_audit(*, seals=(), version_rows=()):
	"""Import `stabler.api.audit` against a hand-built frappe.

	Returns `(module, ctx)`; `ctx.trace` is the ordered record of every
	statement issued, which is the whole subject of these tests.
	"""
	_SANDBOX.evict(
		_MODULE,
		"frappe",
		"frappe.utils",
		"stabler.api._approval_rules",
	)

	trace: list[str] = []
	ctx = types.SimpleNamespace(trace=trace, sql=[])

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.whitelist = lambda *a, **k: lambda fn: fn
	frappe.get_roles = lambda _user=None: ["System Manager"]
	frappe.session = types.SimpleNamespace(user="auditor@example.com")

	def _throw(message, exc=None, *args, **kwargs):
		raise (exc or Exception)(str(message))

	frappe.throw = _throw

	def _sql(query, params=None, **kwargs):
		ctx.sql.append(query)
		if "Stabler Audit Seal" in query:
			trace.append("read-seal FOR UPDATE" if "FOR UPDATE" in query else "read-seal")
			return [dict(seals[0])] if seals else []
		if "tabVersion" in query:
			trace.append("read-versions")
			return [types.SimpleNamespace(**row) for row in version_rows]
		raise AssertionError(f"unexpected sql: {query[:60]!r}")

	def _get_all(doctype, **kwargs):
		trace.append(f"get_all:{doctype}")
		if doctype == "Stabler Audit Seal":
			return [dict(s) for s in seals]
		return []

	frappe.db = types.SimpleNamespace(sql=_sql, commit=lambda: trace.append("commit"))
	frappe.get_all = _get_all
	frappe.get_doc = lambda fields: _FakeSeal(fields, trace)

	utils = types.ModuleType("frappe.utils")
	utils.get_fullname = lambda user: user
	utils.now_datetime = lambda: "2026-08-20 03:00:00"
	frappe.utils = utils

	rules = types.ModuleType("stabler.api._approval_rules")
	rules.IGNORE_FIELDS = frozenset()
	rules.summarize_version = lambda *a, **k: []

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._approval_rules": rules,
		}
	)
	return importlib.import_module(_MODULE), ctx


_EXISTING_SEAL = {
	"name": "SEAL-2026-000001",
	"seq": 1,
	"hash": "a" * 64,
	"sealed_at": "2026-08-19 03:00:00",
}

_NEW_VERSION_ROW = {
	"name": "VER-0001",
	"ref_doctype": "Journal Entry",
	"docname": "JV-0001",
	"owner": "accountant@example.com",
	"creation": "2026-08-19 12:00:00",
}


class TheChainIsAnchoredUnderALock(unittest.TestCase):
	def test_the_row_the_new_seal_chains_from_is_read_for_update(self):
		module, ctx = _load_audit(seals=[_EXISTING_SEAL], version_rows=[_NEW_VERSION_ROW])

		module.seal_audit_log()

		self.assertIn("read-seal FOR UPDATE", ctx.trace)
		self.assertNotIn("read-seal", ctx.trace, "the anchor was read without a lock")

	def test_the_lock_is_taken_before_the_new_seal_is_written(self):
		"""Order is the guard. A lock taken after `prev_hash` has been read
		guards nothing — the fork has already been decided by then."""
		module, ctx = _load_audit(seals=[_EXISTING_SEAL], version_rows=[_NEW_VERSION_ROW])

		module.seal_audit_log()

		self.assertLess(
			ctx.trace.index("read-seal FOR UPDATE"),
			ctx.trace.index("insert-seal"),
		)

	def test_the_lock_is_still_held_when_the_seal_commits(self):
		"""The lock lives until the transaction ends, so the commit must come
		after the insert and nothing may commit between the two."""
		module, ctx = _load_audit(seals=[_EXISTING_SEAL], version_rows=[_NEW_VERSION_ROW])

		module.seal_audit_log()

		self.assertEqual(
			[t for t in ctx.trace if t in ("read-seal FOR UPDATE", "insert-seal", "commit")],
			["read-seal FOR UPDATE", "insert-seal", "commit"],
		)

	def test_a_first_seal_on_an_empty_table_still_asks_for_the_lock(self):
		"""The empty case is the one the lock covers least well (see the module
		docstring), but asking is free and asking conditionally would mean a
		branch nobody exercises."""
		module, ctx = _load_audit(seals=[], version_rows=[_NEW_VERSION_ROW])

		module.seal_audit_log()

		self.assertIn("read-seal FOR UPDATE", ctx.trace)


class ReadingTheChainBackTakesNoLock(unittest.TestCase):
	"""A compliance report is read-only and runs whenever an auditor asks.

	If it locked the anchor row it would block the nightly seal for as long as
	it ran — turning a verification tool into an availability problem, which is
	how guards get switched off.
	"""

	def test_verifying_the_chain_does_not_lock_the_row(self):
		module, ctx = _load_audit(seals=[_EXISTING_SEAL], version_rows=[_NEW_VERSION_ROW])

		module.verify_audit_integrity()

		self.assertNotIn("read-seal FOR UPDATE", ctx.trace)
		self.assertIn("read-seal", ctx.trace)


if __name__ == "__main__":
	unittest.main()
