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
from typing import ClassVar

from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.remittance_cancel_guard"
_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_APP, "api", "remittance_cancel_guard.py")
_HOOKS = os.path.join(_APP, "hooks.py")
_JS = os.path.join(_APP, "public", "js")
_API = {
	name: os.path.join(_APP, "api", f"{name}.py") for name in ("remittance_commands", "remittance_accounting")
}

#: The JE-only engine, retired 2026-08-20. Named here so the test below can prove
#: it is gone rather than merely stop mentioning it.
_RETIRED_API = os.path.join(_APP, "api", "remittance.py")

# Every `stabler.api.remittance*.<fn>` the SPA names, written out in full.
_SPA_CALL = re.compile(r"stabler\.api\.(?:remittance[a-z_]*)\.[a-z_]+")

# ...and the same endpoint assembled at runtime. `api/remittance.js:16` binds the
# module path once (`const CMD = "stabler.api.remittance_commands"`) and every
# call site interpolates it (`` call(`${CMD}.request_refund`) ``), so the dotted
# path never appears contiguously in the file.
#
# **This indirection is why this class went stale-green.** The scanner used to be
# `_SPA_CALL` alone, on the stated assumption that `call("...")` is the only way
# the SPA reaches the backend. `RemittanceRefund.vue` shipped the full refund
# chain, the guard's message kept saying no screen reverses a transfer, and the
# two tests written expressly to go red that day could not see the call. A
# scanner that resolves one alias is not a general JS parser — it is the one
# indirection this tree actually uses, and `test_the_scanner_resolves_a_call_
# target_built_from_a_constant` below fails if it stops resolving it.
_JS_MODULE_CONST = re.compile(
	r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*["'](stabler\.api\.remittance[a-z_]*)["']"""
)

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


class _Row(dict):
	"""`frappe._dict` in miniature — `get_value(..., as_dict=True)` returns one."""

	__getattr__ = dict.get


class _FakeDB:
	"""Just enough of `frappe.db` for the single row the guard reads.

	`transfers` is the entire database as far as this module is concerned: an id
	present in it is a `Remittance Transfer`, an id absent from it is a legacy
	JE-only remittance with no master row. `has_table` is settable separately
	because "this site predates the doctype" and "this site has the table but not
	this row" are different states, and the guard has to survive both — the first
	one raises in real Frappe rather than returning falsy.
	"""

	def __init__(self):
		self.transfers: dict[str, dict] = {}
		self.has_table = True

	def table_exists(self, doctype: str) -> bool:
		return self.has_table

	def get_value(self, doctype: str, name: str, fields, as_dict: bool = False):
		if not self.has_table:
			raise AssertionError("get_value ran on a site whose table does not exist")
		row = self.transfers.get(name)
		return _Row(row) if row else None


def _load():
	_SANDBOX.evict(_MODULE, "frappe")

	frappe = types.ModuleType("frappe")

	def _throw(message, exc=None):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.ValidationError = _Thrown
	frappe.db = _FakeDB()

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


def _endpoints_in(source: str) -> set[str]:
	"""Both spellings of a call target, from one file's text."""
	found = set(_SPA_CALL.findall(source))
	for alias, module in _JS_MODULE_CONST.findall(source):
		interpolated = re.compile(r"\$\{" + re.escape(alias) + r"\}\.([a-z_]+)")
		found.update(f"{module}.{fn}" for fn in interpolated.findall(source))
	return found


def _spa_remittance_endpoints() -> set[str]:
	"""Every remittance endpoint the SPA names, read off `public/js`."""
	found: set[str] = set()
	for root, _dirs, files in os.walk(_JS):
		for name in files:
			if name.endswith((".vue", ".js")):
				with open(os.path.join(root, name), encoding="utf-8") as fh:
					found.update(_endpoints_in(fh.read()))
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

	The message tells the operator what to do instead of cancelling. That is a claim
	about the product, not about this module, and a message test cannot check it —
	it can only compare the message to itself. So the facts each branch rests on are
	asserted here, against the source.

	**This class has now been wrong in both directions.** The first message named "a
	Refund from the Remittance screen" that did not exist. The correction said no
	screen reverses a transfer — and stayed in the tree after `RemittanceRefund.vue`
	shipped one, because `api/remittance.js` builds its call targets from a constant
	and the scanner only saw contiguous literals (see `_JS_MODULE_CONST`). Both
	failures send the operator to the wrong place; naming no recourse when one exists
	is not the safe direction, it is the same defect facing the other way.

	**When one of these turns red the product moved — rewrite the message and its
	stage branch. Do not relax the assertion.**
	"""

	def test_the_scanner_resolves_a_call_target_built_from_a_constant(self):
		"""The canary, and the reason this class could assert the opposite of the truth.

		Every tree-reading test below sees the SPA through `_endpoints_in`. A scanner
		that stops resolving the alias makes all of them agree that the SPA reaches
		nothing — silently, and in the direction that looks like good news. This one
		asserts the mechanism on a source it owns, so it cannot be fooled by what the
		tree happens to contain on any given day.
		"""
		source = (
			'const CMD = "stabler.api.remittance_commands";\n'
			"export const requestRefund = (name) => call(`${CMD}.request_refund`, { name });\n"
			'export const detail = (name) => call("stabler.api.remittance_queries.detail", { name });\n'
		)
		self.assertEqual(
			_endpoints_in(source),
			{
				"stabler.api.remittance_commands.request_refund",
				"stabler.api.remittance_queries.detail",
			},
		)

	def test_the_spa_reaches_the_refund_chain(self):
		"""The load-bearing one: there IS a button now, so the message must name it.

		`RemittanceRefund.vue` works the three-signature refund from three desks and
		reaches all four commands through `api/remittance.js:182-192`. While that is
		true, the Register branch of the refusal must send the operator to that screen
		and must not escalate to an administrator as though nothing they can click
		reverses a transfer.
		"""
		endpoints = _spa_remittance_endpoints()
		self.assertTrue(endpoints, "no remittance endpoint found at all — the regex broke")
		self.assertEqual(
			sorted(e for e in endpoints if "refund" in e or "reverse" in e),
			[
				"stabler.api.remittance_commands.approve_refund",
				"stabler.api.remittance_commands.complete_refund",
				"stabler.api.remittance_commands.reject_refund",
				"stabler.api.remittance_commands.request_refund",
			],
		)

	def test_the_retired_engine_is_gone_and_nothing_still_calls_it(self):
		"""This used to assert that the legacy refund was whitelisted and unreachable.

		Its subject was deleted on 2026-08-20, and "the test that watched it went
		away too" is how a resurrected module gets in without anyone noticing. So
		it now measures the deletion instead: no file, and no screen naming an
		endpoint in it. The second half is the one that earns its keep — a Vue file
		left holding `stabler.api.remittance.list_remittances` compiles fine and
		fails at the user.
		"""
		self.assertFalse(os.path.exists(_RETIRED_API), "the JE-only engine is back")
		self.assertEqual(
			sorted(e for e in _spa_remittance_endpoints() if e.startswith("stabler.api.remittance.")),
			[],
		)

	def test_every_whitelisted_refund_command_is_one_the_screen_calls(self):
		"""Exposed and reached must be the same set, or one of the two is lying.

		This used to assert the opposite — that none of them had a screen — and it was
		the second of the two tests that stayed green through slice 4. Asserting the
		equality in both directions is what makes it load-bearing: a command that is
		whitelisted and unreached is an open endpoint nobody audits, and one that is
		reached and unwhitelisted is a screen that throws on click.
		"""
		exposed = sorted(name for name in _whitelisted(_API["remittance_commands"]) if "refund" in name)
		self.assertEqual(exposed, ["approve_refund", "complete_refund", "reject_refund", "request_refund"])
		reached = _spa_remittance_endpoints()
		for name in exposed:
			self.assertIn(f"stabler.api.remittance_commands.{name}", reached)
		# The accounting half stays unexposed: posting is not a command, and a
		# whitelisted `post_refund` would be a refund with no approval in front of it.
		self.assertEqual(
			sorted(name for name in _whitelisted(_API["remittance_accounting"]) if "refund" in name), []
		)

	def _gate_source(self, module: str, entry: str, gate: str) -> str:
		"""The body of `gate`, having proved `entry` is what calls it."""
		with open(_API[module], encoding="utf-8") as fh:
			source = fh.read()
		functions = _functions(_API[module])
		called = {
			node.func.id
			for node in ast.walk(functions[entry])
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
		}
		self.assertIn(gate, called, f"{entry} no longer calls {gate}")
		return ast.get_source_segment(source, functions[gate])

	def test_a_paid_out_transfer_cannot_be_refunded_even_from_the_server(self):
		"""Why the Payout branch must not hint at a refund at all — in both engines.

		The one voucher an operator is most likely to try to cancel is the payout, and
		it is the one no refund can touch: both engines gate on the transfer still
		being Registered before anything moves.

		This walked both engines' gates for four days. It first read only the
		legacy `refund_remittance`, which meant the branch's claim rested on a
		function the test never opened — the refund the SPA actually reaches is
		V1's `request_refund`. The legacy half was added to the walk on 2026-08-20
		and deleted with its engine hours later; had the V1 half not been added
		first, retiring the engine would have left this branch asserting nothing.
		"""
		gate = self._gate_source("remittance_commands", "request_refund", "_assert_refundable")
		self.assertIn("Registered", gate)
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

	def _refusal(self, stage: str | None = None, transfer: dict | None = None) -> str:
		"""The message thrown for one voucher, with the transfer row it points at.

		`transfer=None` is the legacy case on purpose: a JE-only remittance has no
		master row, and it is the default because it is also what every V1 voucher
		looks like once its transfer has moved past `Registered`.
		"""
		if transfer is not None:
			self.guard.frappe.db.transfers["REM-2026-00009"] = transfer
		fields = {"stabler_remittance_id": "REM-2026-00009"}
		if stage is not None:
			fields["stabler_remittance_stage"] = stage
		with self.assertRaises(_Thrown) as caught:
			self.guard.assert_not_a_remittance_stage(_Doc("ACC-JV-2026-00006", **fields))
		return str(caught.exception)

	# A transfer the Refund screen can actually act on — `_assert_refundable`'s two
	# preconditions, spelled out so a drift in either is visible in the test that
	# depends on it rather than hidden behind a helper.
	_REFUNDABLE: ClassVar[dict] = {"operational_status": "Registered", "accounting_status": "Posted"}

	# The shapes an instruction to press Refund takes. Bans the imperative, not the
	# word: the Payout refusal has to be able to say "cannot be refunded".
	_PRESS_A_REFUND = re.compile(r"(?i)\b(post|press|click|use|open|submit)\b[^.]{0,20}\brefund")

	def test_a_register_entry_whose_transfer_can_still_be_refunded_names_the_refund(self):
		"""The branch this whole change exists for.

		`RemittanceRefund.vue` shipped and the message kept escalating to a person
		anyway, for months, because the test that should have caught it could not see
		a call target built from a constant. An operator holding a still-Registered
		transfer has a button; a refusal that hides it is a refusal that costs someone
		a phone call for nothing.
		"""
		message = self._refusal("Register", transfer=self._REFUNDABLE)
		self.assertRegex(message, self._PRESS_A_REFUND)
		self.assertNotIn("administrator", message)

	def test_the_same_entry_escalates_once_the_transfer_has_been_paid_out(self):
		"""Same voucher, same stage — the recourse is a property of the transfer.

		This is why the branch cannot key on the stage. The Register voucher outlives
		the payout, so an operator can reach for it long after `_assert_refundable`
		stopped saying yes, and pointing them at a screen that will refuse is the
		first draft's bug wearing different words.
		"""
		message = self._refusal(
			"Register",
			transfer={"operational_status": "Paid Out", "accounting_status": "Posted"},
		)
		self.assertNotRegex(message, self._PRESS_A_REFUND)
		self.assertIn("administrator", message)

	def test_an_unposted_transfer_escalates_even_while_it_is_registered(self):
		"""Both preconditions are load-bearing, so both are measured.

		`_assert_refundable` throws "there is no posted obligation to reverse" when
		the accounting half has not landed. Reading only `operational_status` would
		leave this case naming a screen that refuses.
		"""
		message = self._refusal(
			"Register",
			transfer={"operational_status": "Registered", "accounting_status": "Pending"},
		)
		self.assertNotRegex(message, self._PRESS_A_REFUND)
		self.assertIn("administrator", message)

	def test_a_legacy_remittance_escalates_because_no_screen_can_reach_it(self):
		"""The JE-only model has no master row, so no screen can reverse it.

		This is the case the original message was written for, and it is still true —
		which is exactly why the message could stay wrong for everyone else without
		looking wrong to anyone reading it.
		"""
		message = self._refusal("Register")
		self.assertIn("administrator", message)
		self.assertNotRegex(message, self._PRESS_A_REFUND)
		self.assertNotRegex(message, r"(?i)remittance screen")

	def test_a_site_without_the_transfer_doctype_still_gets_a_message(self):
		"""A `before_cancel` hook that raises replaces a refusal with a traceback.

		`frappe.db` raises `TableMissingError` instead of returning falsy when the
		doctype's table is absent, and a site carrying legacy remittance vouchers
		from before `Remittance Transfer` shipped is exactly that site. Without the
		probe, this change would break every remittance voucher cancel there — a
		worse outage than the wrong message it fixes. The fake raises on `get_value`
		so the probe is what is measured, not the fake's tolerance.
		"""
		self.guard.frappe.db.has_table = False
		message = self._refusal("Register")
		self.assertIn("administrator", message)

	def test_the_payout_refusal_does_not_offer_a_refund(self):
		"""Refund is refused for a paid-out transfer, so this branch cannot suggest it.

		Both engines gate on the transfer still being Registered before a refund
		moves anything, which makes Payout the stage where the old message was most
		wrong and most often shown.

		The `cannot be refunded` assertion is what pins the *branch*, not merely the
		wording. Measured 2026-08-17: replacing `if stage == PAYOUT_STAGE` with `if
		False` — the payout branch never firing, every paid-out operator getting the
		generic refusal — left the other assertions green, because the generic
		message also escalates, also names no Refund, and still differs from itself
		at another stage. Only a sentence the payout branch alone carries can see
		that, and it is the sentence `RemittanceReversalReachabilityTest` proves true.

		The transfer row is deliberately the refundable one: the payout branch is
		checked first and must win regardless of what the row says, or a stale row
		could talk an operator into a refund the cash has already outrun.
		"""
		message = self._refusal("Payout", transfer=self._REFUNDABLE)
		self.assertNotRegex(message, self._PRESS_A_REFUND)
		self.assertIn("administrator", message)
		self.assertIn("cannot be refunded", message)
		self.assertNotEqual(message, self._refusal("Register"))

	def test_the_payout_stage_string_matches_what_the_writers_write(self):
		"""Get this constant wrong and the payout branch silently never fires.

		One writer stamps `stabler_remittance_stage` now — `_build_entry`'s `stage`
		argument (`api/remittance_accounting.py:220`), which `post_payout` feeds
		from the module constant `PAYOUT`. The whole path is walked rather than the
		constant alone, because reading `PAYOUT` would still pass on the day
		`post_payout` stopped handing it over, which is the day this guard's payout
		branch would stop firing.

		The retired JE-only engine stamped the same literal inline, and its walk was
		dropped with it. Its VOUCHERS are not gone — a Journal Entry it stamped is
		still on disk and still lands in this branch — but no code writes that
		literal any more, so there is nothing left to hold in step.
		"""
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
