"""Cancelling a remittance stage voucher: refused, and told what to do instead.

Three layers, because each one alone passes on a broken guard:

* **Behaviour** — the handler refuses a register / payout / legacy voucher and
  lets an unrelated Journal Entry through untouched.
* **Registration** — `hooks.py` is read with `ast` and the handler must appear in
  `doc_events["Journal Entry"]["before_cancel"]`. A guard nobody registered is
  the exact state this bead found: the module could be perfect and the Money
  screen's Cancel button would still un-post a paid-out transfer. The behavioural
  tests cannot see that, because they call the handler directly.
* **Source** — the module must never consult the session user or the request.
  `desk_write_guard` exempts System Managers and headless callers; inheriting
  either exemption here would gut the rule (every Money-screen operator on these
  tenants is a System Manager, and "headless" is every background job). Only an
  explicit per-document flag opens the door, so a future edit that adds an admin
  bypass turns this red.

Bench-free: registered in `.github/frappe-free-tests.txt`, so it gates a push.
The ledger consequence it protects — a cancelled register entry being mirrored
into the later stages — is exercised on a real ledger in
`test_remittance_accounting_bench.py`.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_remittance_cancel_guard -v
"""

from __future__ import annotations

import ast
import importlib
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.remittance_cancel_guard"
_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_APP, "api", "remittance_cancel_guard.py")
_HOOKS = os.path.join(_APP, "hooks.py")

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


class _Doc:
	"""The fields a Journal Entry doc-event handler is allowed to read."""

	def __init__(self, name: str, **fields):
		self.name = name
		self._fields = fields
		self.flags = {}

	def get(self, field, default=None):
		return self._fields.get(field, default)


def _load():
	_SANDBOX.evict(_MODULE, "frappe")

	frappe = types.ModuleType("frappe")

	def _throw(message, exc=None):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.ValidationError = _Thrown

	_SANDBOX.install({"frappe": frappe})
	return importlib.import_module(_MODULE)


def _doc_events() -> dict:
	"""Read hooks.py without importing it — it needs a bench, ast does not."""
	with open(_HOOKS, encoding="utf-8") as fh:
		tree = ast.parse(fh.read())
	for node in tree.body:
		if isinstance(node, ast.Assign) and any(
			isinstance(target, ast.Name) and target.id == "doc_events" for target in node.targets
		):
			return ast.literal_eval(node.value)
	raise AssertionError("hooks.py has no doc_events assignment")


class RemittanceCancelHookRegistrationTest(unittest.TestCase):
	"""The gap this bead closed was registration, not logic."""

	@classmethod
	def setUpClass(cls):
		cls.events = _doc_events()["Journal Entry"]

	def test_the_guard_runs_on_before_cancel(self):
		self.assertIn(
			"stabler.api.remittance_cancel_guard.assert_not_a_remittance_stage",
			self.events["before_cancel"],
		)

	def test_it_runs_after_the_desk_guard_and_before_on_cancel_side_effects(self):
		"""before_cancel is the last point where refusing still costs nothing.

		By `on_cancel` the docstatus is already 2 and the GL entries are gone, so a
		throw there would have to unwind a completed cancel.
		"""
		before = self.events["before_cancel"]
		self.assertLess(
			before.index("stabler.api.desk_write_guard.assert_write_via_stabler"),
			before.index("stabler.api.remittance_cancel_guard.assert_not_a_remittance_stage"),
		)
		self.assertNotIn(
			"stabler.api.remittance_cancel_guard.assert_not_a_remittance_stage",
			self.events.get("on_cancel", []),
		)


class RemittanceCancelGuardSourceTest(unittest.TestCase):
	"""No exemption may be inherited from the desk guard sitting next to it."""

	@classmethod
	def setUpClass(cls):
		with open(_SRC, encoding="utf-8") as fh:
			source = fh.read()
		# Only the code — the docstring names both exemptions to explain them.
		cls.code = source[source.index('"""', source.index('"""') + 3) + 3 :]

	def test_the_guard_does_not_consult_the_user(self):
		for exemption in ("frappe.session", "get_roles", "System Manager", "Administrator"):
			self.assertNotIn(exemption, self.code)

	def test_the_guard_does_not_exempt_headless_callers(self):
		for exemption in ("frappe.local", "request", "form_dict"):
			self.assertNotIn(exemption, self.code)


class RemittanceCancelGuardTest(unittest.TestCase):
	def setUp(self):
		self.guard = _load()

	def test_an_unrelated_journal_entry_is_left_alone(self):
		# The hook fires on every Journal Entry cancel in the app; a payroll or
		# purchase voucher must pass through as if it were not registered.
		self.guard.assert_not_a_remittance_stage(_Doc("ACC-JV-2026-00001"))

	def test_the_register_entry_cannot_be_cancelled(self):
		doc = _Doc(
			"ACC-JV-2026-00002",
			stabler_remittance_id="REM-2026-00007",
			stabler_remittance_stage="Register",
		)

		with self.assertRaises(_Thrown) as caught:
			self.guard.assert_not_a_remittance_stage(doc)

		# accounting_status would stay Posted pointing at a cancelled voucher, and
		# every later stage reads its amounts back off that row.
		self.assertIn("REM-2026-00007", str(caught.exception))
		self.assertIn("Register", str(caught.exception))

	def test_the_payout_entry_cannot_be_cancelled(self):
		doc = _Doc(
			"ACC-JV-2026-00003",
			stabler_remittance_id="REM-2026-00008",
			stabler_remittance_stage="Payout",
		)

		with self.assertRaises(_Thrown):
			self.guard.assert_not_a_remittance_stage(doc)

	def test_a_legacy_entry_with_no_stage_is_still_refused(self):
		"""The JE-only model has no master row — it must not fall through the gap."""
		doc = _Doc("ACC-JV-2026-00004", stabler_remittance_id="REM-2025-00001")

		with self.assertRaises(_Thrown) as caught:
			self.guard.assert_not_a_remittance_stage(doc)

		self.assertIn("REM-2025-00001", str(caught.exception))

	def test_a_blank_remittance_id_is_not_a_remittance(self):
		# The custom field exists on every Journal Entry once patch v33 ran, so the
		# common case is present-but-empty, not absent.
		self.guard.assert_not_a_remittance_stage(_Doc("ACC-JV-2026-00005", stabler_remittance_id="  "))

	def test_the_refusal_names_the_way_out(self):
		"""A refusal that does not say what to press instead is a dead end.

		Refund is the reversal that moves the money AND the transfer's status; the
		operator who mis-keyed a registration needs to be sent there, not stopped.
		"""
		doc = _Doc(
			"ACC-JV-2026-00006",
			stabler_remittance_id="REM-2026-00009",
			stabler_remittance_stage="Register",
		)

		with self.assertRaises(_Thrown) as caught:
			self.guard.assert_not_a_remittance_stage(doc)

		self.assertIn("Refund", str(caught.exception))

	def test_the_explicit_flag_is_the_only_door(self):
		doc = _Doc(
			"ACC-JV-2026-00007",
			stabler_remittance_id="REM-2026-00010",
			stabler_remittance_stage="Payout",
		)
		doc.flags[self.guard.BYPASS_FLAG] = True

		self.guard.assert_not_a_remittance_stage(doc)

	def test_an_unrelated_flag_does_not_open_it(self):
		doc = _Doc(
			"ACC-JV-2026-00008",
			stabler_remittance_id="REM-2026-00011",
			stabler_remittance_stage="Payout",
		)
		doc.flags["ignore_permissions"] = True
		doc.flags["ignore_approval_gate"] = True

		with self.assertRaises(_Thrown):
			self.guard.assert_not_a_remittance_stage(doc)


if __name__ == "__main__":
	unittest.main()
