"""Cancelling a remittance stage voucher: refused, and told what is really available.

Four layers, because each one alone passes on a broken guard:

* **Behaviour** — the handler refuses a register / payout / legacy voucher and
  lets an unrelated Journal Entry through untouched.
* **Registration** — `hooks.py` is read with `ast` and the handler must appear in
  `doc_events["Journal Entry"]["before_cancel"]`, *and* every path listed there
  must resolve to a function that exists on disk. A guard nobody registered is
  the exact state this bead found: the module could be perfect and the Money
  screen's Cancel button would still un-post a paid-out transfer. The behavioural
  tests cannot see that, because they call the handler directly.
* **Reachability** — the refusal makes a claim about the *product* ("nothing you
  can click reverses a transfer; escalate"), so that claim is measured against
  the tree rather than asserted in a docstring. See
  `RemittanceReversalReachabilityTest`; when it goes red the reversal story has
  changed and the message is now a lie.
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
import re
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.remittance_cancel_guard"
_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_APP, "api", "remittance_cancel_guard.py")
_HOOKS = os.path.join(_APP, "hooks.py")
_JS = os.path.join(_APP, "public", "js")
_API = {
	name: os.path.join(_APP, "api", f"{name}.py")
	for name in ("remittance", "remittance_commands", "remittance_accounting")
}

# Every `stabler.api.remittance*.<fn>` the SPA names. `call("...")` is the only
# way the SPA reaches the backend, so matching the dotted path finds them all.
_SPA_CALL = re.compile(r"stabler\.api\.(?:remittance[a-z_]*)\.[a-z_]+")

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


def _module_path(dotted: str) -> str:
	"""`stabler.api.x` -> the file on disk. Only this app's own modules resolve."""
	parts = dotted.split(".")
	return os.path.join(_APP, *parts[1:]) + ".py" if parts[0] == "stabler" else ""


def _functions(path: str) -> dict[str, ast.FunctionDef]:
	"""Top-level `def`s in a module, by name — ast, so no bench and no import."""
	with open(path, encoding="utf-8") as fh:
		tree = ast.parse(fh.read())
	return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _resolves(dotted: str) -> bool:
	"""Does `pkg.mod.fn` name a function that actually exists?"""
	module, _dot, func = dotted.rpartition(".")
	path = _module_path(module)
	return bool(path) and os.path.exists(path) and func in _functions(path)


def _whitelisted(path: str) -> set[str]:
	"""Functions carrying `@frappe.whitelist()` — the only ones the SPA can call."""
	names = set()
	for name, node in _functions(path).items():
		for decorator in node.decorator_list:
			target = decorator.func if isinstance(decorator, ast.Call) else decorator
			if isinstance(target, ast.Attribute) and target.attr == "whitelist":
				names.add(name)
	return names


def _spa_remittance_endpoints() -> set[str]:
	"""Every remittance endpoint the SPA names, read off `public/js`."""
	found: set[str] = set()
	for root, _dirs, files in os.walk(_JS):
		for name in files:
			if name.endswith((".vue", ".js")):
				with open(os.path.join(root, name), encoding="utf-8") as fh:
					found.update(_SPA_CALL.findall(fh.read()))
	return found


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

	def test_every_registered_path_resolves_to_a_real_function(self):
		"""hooks.py and this test agreeing on a *string* proves nothing about the guard.

		Both sides just spell a dotted path. If that path names no function,
		Frappe raises on import at cancel time and the voucher goes through
		unguarded — the precise failure this module exists to prevent. Measured
		2026-08-17: pointing hooks.py **and** the assertion above at
		`...remittance_cancel_guard.NO_SUCH_FUNCTION` left this whole class green.
		Resolving the path is what closes that.
		"""
		for path in self.events["before_cancel"]:
			self.assertTrue(_resolves(path), f"before_cancel names {path}, which does not exist")


class RemittanceReversalReachabilityTest(unittest.TestCase):
	"""What the refusal is *allowed* to promise, measured against the tree.

	The message tells the operator that nothing they can click reverses a
	transfer and sends them to an administrator instead. That is a claim about
	the product, not about this module, and the first version of it was false —
	it named "a Refund from the Remittance screen" that has never existed. A
	message test alone cannot catch that, because it can only compare the message
	to itself. So the four facts the message rests on are asserted here.

	**When one of these turns red, the reversal shipped — rewrite the message and
	its stage branch. Do not relax the assertion.**
	"""

	def test_the_spa_reaches_no_remittance_reversal(self):
		"""The load-bearing one: there is no button, so the message must not name one."""
		endpoints = _spa_remittance_endpoints()
		self.assertTrue(endpoints, "no remittance endpoint found at all — the regex broke")
		self.assertEqual(
			sorted(e for e in endpoints if "refund" in e or "reverse" in e),
			[],
		)

	def test_the_legacy_refund_is_whitelisted_but_unreachable_from_the_spa(self):
		"""Whitelisted is not the same as reachable, and the operator only has the SPA."""
		self.assertIn("refund_remittance", _whitelisted(_API["remittance"]))
		self.assertNotIn("stabler.api.remittance.refund_remittance", _spa_remittance_endpoints())

	def test_the_new_transfer_model_has_no_whitelisted_refund_at_all(self):
		"""`post_refund` exists, but nothing exposes it — only a bench test calls it."""
		for module in ("remittance_commands", "remittance_accounting"):
			exposed = {name for name in _whitelisted(_API[module]) if "refund" in name}
			self.assertEqual(sorted(exposed), [], f"{module} now exposes a refund")

	def test_a_paid_out_transfer_cannot_be_refunded_even_from_the_server(self):
		"""Why the Payout branch must not hint at a refund at all.

		`refund_remittance` opens with `_assert_registered`, which throws for a
		Paid Out transfer — so the one voucher an operator is most likely to try
		to cancel is the one no refund can touch.
		"""
		with open(_API["remittance"], encoding="utf-8") as fh:
			source = fh.read()
		functions = _functions(_API["remittance"])

		refund = functions["refund_remittance"]
		called = {
			node.func.id
			for node in ast.walk(refund)
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
		}
		self.assertIn("_assert_registered", called)

		gate = ast.get_source_segment(source, functions["_assert_registered"])
		self.assertIn("Paid Out", gate)
		self.assertIn("frappe.throw", gate)


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

	def _refusal(self, stage: str | None = None) -> str:
		fields = {"stabler_remittance_id": "REM-2026-00009"}
		if stage is not None:
			fields["stabler_remittance_stage"] = stage
		with self.assertRaises(_Thrown) as caught:
			self.guard.assert_not_a_remittance_stage(_Doc("ACC-JV-2026-00006", **fields))
		return str(caught.exception)

	# The shapes an instruction to press Refund takes. Bans the imperative, not
	# the word: the Payout refusal has to be able to say "cannot be refunded".
	_PRESS_A_REFUND = re.compile(r"(?i)\b(post|press|click|use|open|submit)\b[^.]{0,20}\brefund")

	def test_the_refusal_names_an_exit_that_exists(self):
		"""A refusal may only send the operator somewhere real.

		This message used to read "post a Refund from the Remittance screen".
		`RemittanceReversalReachabilityTest` measures that no such screen exists —
		the SPA calls five remittance endpoints and none of them refunds anything
		— so that sentence sent an operator with cash in the drawer and a posted
		three-leg entry to hunt for a button. That is worse than a bare refusal,
		because it reads as recourse. The only exit that exists today is a person,
		so the message must name the escalation and must not name a Refund to
		press. The predecessor of this test asserted `"Refund" in message`, which
		is exactly what the false version satisfied.
		"""
		message = self._refusal("Register")
		self.assertIn("administrator", message)
		self.assertNotRegex(message, self._PRESS_A_REFUND)
		self.assertNotRegex(message, r"(?i)remittance screen")

	def test_the_payout_refusal_does_not_offer_a_refund(self):
		"""Refund is refused for a paid-out transfer, so this branch cannot suggest it.

		`_assert_registered` throws "has already been paid out" before
		`refund_remittance` does anything, which makes Payout the stage where the
		old message was most wrong and most often shown.

		The `cannot be refunded` assertion is what pins the *branch*, not merely
		the wording. Measured 2026-08-17: replacing `if stage == PAYOUT_STAGE`
		with `if False` — the payout branch never firing, every paid-out operator
		getting the generic refusal — left the other three assertions green,
		because the generic message also escalates, also names no Refund, and
		still differs from itself at another stage. Only a sentence the payout
		branch alone carries can see that, and this is the sentence
		`RemittanceReversalReachabilityTest` independently proves true.
		"""
		message = self._refusal("Payout")
		self.assertNotRegex(message, self._PRESS_A_REFUND)
		self.assertIn("administrator", message)
		self.assertIn("cannot be refunded", message)
		self.assertNotEqual(message, self._refusal("Register"))

	def test_the_payout_stage_string_matches_what_the_writers_write(self):
		"""Get this constant wrong and the payout branch silently never fires.

		Two writers stamp `stabler_remittance_stage` and they do not stamp it the
		same way, so both are walked here. The legacy model writes the literal
		inline (`api/remittance.py:519`). The new model writes `_build_entry`'s
		`stage` argument (`api/remittance_accounting.py:220`), which `post_payout`
		feeds from the module constant `PAYOUT` — so reading the constant alone
		would still pass on the day `post_payout` stopped handing it over, which
		is the day this guard's payout branch would stop firing for the new model.
		"""
		with open(_API["remittance"], encoding="utf-8") as fh:
			self.assertIn(f'"stabler_remittance_stage": "{self.guard.PAYOUT_STAGE}"', fh.read())

		with open(_API["remittance_accounting"], encoding="utf-8") as fh:
			source = fh.read()
		accounting = ast.parse(source)
		payout = next(
			ast.literal_eval(node.value)
			for node in accounting.body
			if isinstance(node, ast.Assign)
			and any(isinstance(t, ast.Name) and t.id == "PAYOUT" for t in node.targets)
		)
		self.assertEqual(payout, self.guard.PAYOUT_STAGE)

		functions = {node.name: node for node in accounting.body if isinstance(node, ast.FunctionDef)}
		self.assertIn(
			'"stabler_remittance_stage": stage',
			ast.get_source_segment(source, functions["_build_entry"]),
		)
		self.assertIn(
			"_build_entry(transfer, PAYOUT,",
			ast.get_source_segment(source, functions["post_payout"]),
		)

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
