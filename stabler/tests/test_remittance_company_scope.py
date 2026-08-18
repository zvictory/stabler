"""Company isolation for Remittance Transfer and Remittance Event.

Until the operating roles landed, both doctypes carried a single System-Manager
permission row, and admins are exempt from company isolation by design — so
their absence from the two record-level maps in ``hooks.py`` cost nothing. The
roles branch grants ``read`` to Remittance Viewer, Auditor, Cashier and Finance
Manager, which makes remittance the first money data in the app reachable by a
non-admin. A Viewer whose Allowed Companies list is Company A could then read
Company B's transfers — sender and receiver names, amounts, corridors, the
three Journal Entry links — off ``/api/resource``. Cross-company **within a
site**: the tenants have separate databases, so the site boundary is untouched.

Three layers, because each one alone passes on a broken scope:

* **Shape** — which idiom is correct is decided by the doctype JSONs, so the
  JSONs are read rather than trusted. Both doctypes carry a ``company`` field,
  so both use the same direct condition. The event carried none until v92 and
  was scoped through its parent transfer by a subquery; that shape is what this
  bullet used to describe, and the tests below are what turned red when the
  column landed. Take the column away again and they turn red the other way.
* **Wiring** — ``hooks.py`` is parsed with ``ast``; both doctypes must appear in
  both maps and **every** path in either map must resolve to a function that
  exists on disk. A condition nobody registered scopes nothing, and the
  behavioural tests cannot see that because they call the functions directly.
  The event's ``has_permission`` is asserted *not* to be
  ``company_has_permission``: that helper reads ``doc.company``, which is always
  None on an event, so it takes its blank-is-allowed branch and returns True for
  every row — wiring that looks right and scopes nothing.
* **Behaviour** — the emitted WHERE fragments are run against an in-memory
  SQLite database holding two companies' rows, and the surviving row set is
  asserted. This catches an always-true fragment, which a string-shape
  assertion does not.

**What this file cannot prove.** It is bench-free by design (registered in
``.github/frappe-free-tests.txt``, so it gates a push). SQLite is not MariaDB
and nothing here runs Frappe's query builder, so it proves the fragment's own
logic — not that Frappe splices it into a real ``/api/resource`` query, nor
that a live Viewer is actually filtered. That belongs on a bench; see
``stabler/tests/test_remittance_company_scope_bench.py``.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \\
        stabler.tests.test_remittance_company_scope -v
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import sqlite3
import types
import unittest
from types import SimpleNamespace

from stabler.tests.module_sandbox import ModuleSandbox

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOOKS = os.path.join(_PKG, "hooks.py")
_TRANSFER_JSON = os.path.join(_PKG, "stabler", "doctype", "remittance_transfer", "remittance_transfer.json")
_EVENT_JSON = os.path.join(_PKG, "stabler", "doctype", "remittance_event", "remittance_event.json")

_SANDBOX = ModuleSandbox()

ADMIN_ROLES = ("System Manager", "Stabler Admin")


# --- hooks.py / doctype JSON readers (no frappe, no import of the app) ------


def _hook_map(name: str) -> dict:
	"""``permission_query_conditions`` / ``has_permission`` as literal dicts."""
	with open(_HOOKS, encoding="utf-8") as fh:
		tree = ast.parse(fh.read())
	for node in tree.body:
		if isinstance(node, ast.Assign) and any(
			isinstance(target, ast.Name) and target.id == name for target in node.targets
		):
			return ast.literal_eval(node.value)
	raise AssertionError(f"hooks.py has no {name} assignment")


def _module_functions(dotted_module: str) -> set[str]:
	"""Top-level function names defined in an app module, read off disk."""
	assert dotted_module.startswith("stabler."), dotted_module
	path = os.path.join(_PKG, *dotted_module.split(".")[1:]) + ".py"
	if not os.path.exists(path):
		raise AssertionError(f"no module on disk for {dotted_module} (looked at {path})")
	with open(path, encoding="utf-8") as fh:
		tree = ast.parse(fh.read())
	return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _fields(doctype_json: str) -> dict[str, dict]:
	with open(doctype_json, encoding="utf-8") as fh:
		return {f["fieldname"]: f for f in json.load(fh)["fields"]}


def _roles_with_read(doctype_json: str) -> set[str]:
	with open(doctype_json, encoding="utf-8") as fh:
		return {p["role"] for p in json.load(fh).get("permissions", []) if p.get("read")}


# --- frappe fakes ----------------------------------------------------------

_ROLES: list[str] = []
_ALLOWED: list[str] = []
_VALUES: dict[tuple[str, str, str], object] = {}


def _escape(value):
	"""Mirror frappe.db.escape: quote and backslash-escape, MySQL style."""
	return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _get_value(doctype, name, field=None, **_kwargs):
	return _VALUES.get((doctype, name, field))


def _install_fakes() -> None:
	frappe_mod = types.ModuleType("frappe")
	frappe_mod._ = lambda s: s
	frappe_mod.PermissionError = PermissionError
	frappe_mod.throw = lambda msg, exc=None: (_ for _ in ()).throw(RuntimeError(msg))
	frappe_mod.whitelist = lambda *a, **k: lambda fn: fn
	frappe_mod.get_roles = lambda user=None: list(_ROLES)
	frappe_mod.session = SimpleNamespace(user="viewer@example.com")
	frappe_mod.logger = lambda name=None: SimpleNamespace(info=lambda *a, **k: None)
	frappe_mod.get_meta = lambda dt: SimpleNamespace(get_valid_columns=list)
	frappe_mod.get_doc = lambda *a, **k: None
	frappe_mod.db = SimpleNamespace(
		escape=_escape,
		get_value=_get_value,
		get_single_value=lambda *a, **k: "",
		exists=lambda *a, **k: False,
		sql=lambda *a, **k: [],
		sql_list=lambda *a, **k: [],
		get_all=lambda *a, **k: [],
	)
	frappe_mod.get_all = lambda *a, **k: []

	utils = types.ModuleType("frappe.utils")
	utils.get_datetime = lambda v: v
	frappe_mod.utils = utils

	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ADMIN_ROLES
	organization._user_allowed_companies = lambda user: list(_ALLOWED)

	_SANDBOX.evict("frappe", "frappe.utils", "stabler.api.organization", "stabler.api.permissions")
	_SANDBOX.install(
		{
			"frappe": frappe_mod,
			"frappe.utils": utils,
			"stabler.api.organization": organization,
		}
	)


def setUpModule():
	"""Install fakes only when the tests actually run — the bench runner imports
	every test module up front just to categorise it, and tearDownModule never
	runs in that process."""
	global permissions
	_install_fakes()
	permissions = importlib.import_module("stabler.api.permissions")


def tearDownModule():
	_SANDBOX.restore()


def _restrict_to(*companies: str) -> None:
	"""Make the session user a non-admin with an explicit Allowed Companies list."""
	_ROLES[:] = ["Remittance Viewer"]
	_ALLOWED[:] = list(companies)


class RemittanceDoctypeShapeTest(unittest.TestCase):
	"""What the JSONs say is what decides which scoping idiom is correct."""

	def test_the_transfer_carries_its_own_company_field(self):
		company = _fields(_TRANSFER_JSON).get("company")
		self.assertIsNotNone(company, "Remittance Transfer lost its company field")
		self.assertEqual(company["fieldtype"], "Link")
		self.assertEqual(company["options"], "Company")

	def test_the_event_carries_its_own_company_and_still_links_its_transfer(self):
		fields = _fields(_EVENT_JSON)
		company = fields.get("company")
		self.assertIsNotNone(
			company,
			"Remittance Event lost its company column — without it the scope has to be "
			"read through the parent transfer again, which is the subquery v92 deleted.",
		)
		self.assertEqual(company["fieldtype"], "Link")
		self.assertEqual(company["options"], "Company")
		self.assertTrue(
			company.get("reqd"),
			"an event with a blank company is invisible to nobody: the shared condition "
			"lets a NULL company through by design, so an unrequired column would let an "
			"event that failed to copy its parent's company be read by every viewer",
		)
		# The link stays required even though the scope no longer travels through
		# it: an event is a fact *about a transfer*, and an orphan one is not a
		# smaller audit trail, it is a corrupt one.
		transfer = fields.get("transfer")
		self.assertIsNotNone(transfer, "Remittance Event lost its transfer link")
		self.assertEqual(transfer["options"], "Remittance Transfer")
		self.assertTrue(
			transfer.get("reqd"),
			"the transfer link is the event's only route to a company; unrequired, "
			"an orphan event would be unscopeable",
		)

	def test_both_doctypes_are_readable_by_a_non_admin_role(self):
		# The premise of the whole file. If remittance ever goes back to
		# admin-only, the scoping is still correct but no longer load-bearing —
		# and this test is where that shows.
		for label, path in (("Remittance Transfer", _TRANSFER_JSON), ("Remittance Event", _EVENT_JSON)):
			with self.subTest(doctype=label):
				readers = _roles_with_read(path)
				self.assertTrue(
					readers - set(ADMIN_ROLES),
					f"{label} is admin-only again — company scoping is no longer load-bearing",
				)


class RemittanceScopeWiringTest(unittest.TestCase):
	"""A condition nobody registered scopes nothing."""

	def setUp(self):
		self.query_map = _hook_map("permission_query_conditions")
		self.perm_map = _hook_map("has_permission")

	def test_both_remittance_doctypes_are_registered_for_query_conditions(self):
		self.assertEqual(
			self.query_map.get("Remittance Transfer"),
			"stabler.api.permissions.remittance_transfer_query",
		)
		self.assertEqual(
			self.query_map.get("Remittance Event"),
			"stabler.api.permissions.remittance_event_query",
		)

	def test_both_remittance_doctypes_are_registered_for_has_permission(self):
		self.assertEqual(
			self.perm_map.get("Remittance Transfer"),
			"stabler.api.permissions.company_has_permission",
		)
		self.assertIn("Remittance Event", self.perm_map)

	def test_the_event_now_reuses_the_shared_company_helper(self):
		# The reason it could not, before v92: company_has_permission reads
		# doc.company, which was always None on an event, so it took its
		# blank-is-allowed branch and returned True for every row — registered,
		# green, and scoping nothing. The column is what makes the shared helper
		# correct here, so this assertion and the shape test above are one fact
		# split across two files.
		self.assertEqual(
			self.perm_map.get("Remittance Event"),
			"stabler.api.permissions.company_has_permission",
		)

	def test_every_registered_path_resolves_to_a_real_function(self):
		# Not remittance-specific on purpose: a typo in any entry silently
		# disables that doctype's isolation, and Frappe logs it rather than
		# raising. Both maps, every entry.
		for map_name, hook_map in (
			("permission_query_conditions", self.query_map),
			("has_permission", self.perm_map),
		):
			for doctype, path in hook_map.items():
				with self.subTest(hook=map_name, doctype=doctype):
					module, _, func = path.rpartition(".")
					self.assertIn(
						func,
						_module_functions(module),
						f"{map_name}[{doctype!r}] points at {path}, which does not exist",
					)


class RemittanceQueryConditionTest(unittest.TestCase):
	"""The fragments are run, not just read."""

	def setUp(self):
		_ROLES.clear()
		_ALLOWED.clear()
		_VALUES.clear()
		self.conn = sqlite3.connect(":memory:")
		self.conn.execute("CREATE TABLE `tabRemittance Transfer` (name TEXT, company TEXT)")
		self.conn.execute("CREATE TABLE `tabRemittance Event` (name TEXT, transfer TEXT, company TEXT)")
		self.conn.executemany(
			"INSERT INTO `tabRemittance Transfer` VALUES (?, ?)",
			[("REM-A", "A Co"), ("REM-B", "B Co"), ("REM-NULL", None)],
		)
		self.conn.executemany(
			"INSERT INTO `tabRemittance Event` VALUES (?, ?, ?)",
			[("EVT-A", "REM-A", "A Co"), ("EVT-B", "REM-B", "B Co"), ("EVT-NULL", "REM-NULL", None)],
		)

	def tearDown(self):
		self.conn.close()

	def _select(self, doctype: str, condition: str) -> set[str]:
		where = f"WHERE {condition}" if condition else ""
		sql = f"SELECT `tab{doctype}`.name FROM `tab{doctype}` {where}"
		return {row[0] for row in self.conn.execute(sql).fetchall()}

	# --- safe-by-default: only a restricted non-admin is ever filtered ------

	def test_a_user_with_no_allowed_companies_is_unrestricted(self):
		_ROLES[:] = ["Remittance Viewer"]
		_ALLOWED[:] = []
		self.assertEqual(permissions.remittance_transfer_query("viewer@example.com"), "")
		self.assertEqual(permissions.remittance_event_query("viewer@example.com"), "")

	def test_an_admin_with_an_allowed_list_is_still_unrestricted(self):
		for admin_role in ADMIN_ROLES:
			with self.subTest(role=admin_role):
				_ROLES[:] = [admin_role]
				_ALLOWED[:] = ["A Co"]
				self.assertEqual(permissions.remittance_transfer_query("admin@example.com"), "")
				self.assertEqual(permissions.remittance_event_query("admin@example.com"), "")

	def test_the_administrator_account_is_unrestricted(self):
		_restrict_to("A Co")
		self.assertEqual(permissions.remittance_transfer_query("Administrator"), "")
		self.assertEqual(permissions.remittance_event_query("Administrator"), "")

	# --- the actual isolation ----------------------------------------------

	def test_the_transfer_condition_hides_the_other_company(self):
		_restrict_to("A Co")
		condition = permissions.remittance_transfer_query("viewer@example.com")
		self.assertTrue(condition, "a restricted viewer got no condition at all")
		visible = self._select("Remittance Transfer", condition)
		self.assertEqual(visible, {"REM-A", "REM-NULL"})
		self.assertNotIn("REM-B", visible)

	def test_the_event_condition_hides_the_other_company(self):
		_restrict_to("A Co")
		condition = permissions.remittance_event_query("viewer@example.com")
		self.assertTrue(condition, "a restricted viewer got no condition at all")
		visible = self._select("Remittance Event", condition)
		self.assertEqual(visible, {"EVT-A", "EVT-NULL"})
		self.assertNotIn(
			"EVT-B",
			visible,
			"the event trail leaks the other company's transfers: event rows carry "
			"actor, branch and event_type for a transfer the reader cannot see",
		)

	def test_the_event_condition_reads_its_own_column_not_the_parent_table(self):
		# The whole point of v92. A subquery per list query is the cost this
		# replaced, but correctness is the real reason: the parent join let an
		# event whose transfer link was blank through unconditionally, and the
		# fragment had to spell that out in two extra clauses.
		_restrict_to("A Co")
		condition = permissions.remittance_event_query("viewer@example.com")
		self.assertIn("`tabRemittance Event`.company", condition)
		self.assertNotIn(
			"`tabRemittance Transfer`",
			condition,
			"the event condition still joins its parent — the column it now carries is unused",
		)
		self.assertNotIn("select", condition.lower(), "the subquery is back")

	def test_a_multi_company_list_shows_exactly_those_companies(self):
		self.conn.execute("INSERT INTO `tabRemittance Transfer` VALUES ('REM-C', 'C Co')")
		self.conn.execute("INSERT INTO `tabRemittance Event` VALUES ('EVT-C', 'REM-C', 'C Co')")
		_restrict_to("A Co", "B Co")
		self.assertEqual(
			self._select("Remittance Transfer", permissions.remittance_transfer_query("v@e.com")),
			{"REM-A", "REM-B", "REM-NULL"},
		)
		self.assertEqual(
			self._select("Remittance Event", permissions.remittance_event_query("v@e.com")),
			{"EVT-A", "EVT-B", "EVT-NULL"},
		)

	def test_a_company_name_with_a_quote_is_escaped_not_interpolated(self):
		# Both fragments, because they build their value list separately: the
		# parent-join condition has its own `frappe.db.escape` call, and an
		# escaping regression there is invisible to the transfer assertions.
		_restrict_to("O'Brien Ltd")
		for label, condition in (
			("Remittance Transfer", permissions.remittance_transfer_query("viewer@example.com")),
			("Remittance Event", permissions.remittance_event_query("viewer@example.com")),
		):
			with self.subTest(doctype=label):
				self.assertNotIn(
					"'O'Brien Ltd'",
					condition,
					f"{label}: the company name reached the SQL unescaped",
				)
				# SQLite escapes a quote by doubling it, MySQL by backslashing it;
				# both dialects agree the value must never reach the SQL raw, which
				# is what is asserted here. Row sets are checked in the tests above.
				self.assertIn("\\'", condition)


class RemittanceEventHasPermissionTest(unittest.TestCase):
	"""Single-document access — the path a direct GET takes.

	Before v92 this exercised a bespoke ``remittance_event_has_permission`` that
	resolved the parent transfer to find a company. The column removed the reason
	for it, and the function with it. What is asserted here is therefore not new
	logic but the claim that the *shared* helper is now sufficient for an event —
	which is only true because the event carries the column, and is exactly the
	claim that was false before.
	"""

	def setUp(self):
		_ROLES.clear()
		_ALLOWED.clear()
		_VALUES.clear()

	def test_the_other_company_event_is_denied(self):
		_restrict_to("A Co")
		self.assertIs(
			permissions.company_has_permission(
				SimpleNamespace(company="B Co", transfer="REM-B"), "read", "viewer@example.com"
			),
			False,
		)

	def test_the_own_company_event_is_allowed(self):
		_restrict_to("A Co")
		self.assertIs(
			permissions.company_has_permission(
				SimpleNamespace(company="A Co", transfer="REM-A"), "read", "viewer@example.com"
			),
			True,
		)

	def test_an_unrestricted_user_is_allowed(self):
		_ROLES[:] = ["Remittance Viewer"]
		_ALLOWED[:] = []
		self.assertIs(
			permissions.company_has_permission(
				SimpleNamespace(company="B Co", transfer="REM-B"), "read", "viewer@example.com"
			),
			True,
		)

	def test_the_bespoke_event_helper_is_gone(self):
		# Not tidiness. Left on disk it would still be importable, still look like
		# the right thing to register, and still be one `hooks.py` line away from
		# scoping the event through a subquery nobody needs. The wiring test above
		# proves what IS registered; this proves the alternative cannot be.
		for dead in ("remittance_event_has_permission", "_parent_company_condition"):
			with self.subTest(name=dead):
				self.assertFalse(
					hasattr(permissions, dead),
					f"{dead} survived v92 — the parent-join scoping path is still reachable",
				)

	def test_the_transfer_still_uses_the_shared_company_helper(self):
		_restrict_to("A Co")
		self.assertIs(
			permissions.company_has_permission(SimpleNamespace(company="B Co"), "read", "viewer@example.com"),
			False,
		)
		self.assertIs(
			permissions.company_has_permission(SimpleNamespace(company="A Co"), "read", "viewer@example.com"),
			True,
		)


class ListingEndpointsKeepTheConditionOnTest(unittest.TestCase):
	"""A scoped condition is only worth what the caller lets it run.

	``frappe.get_all`` sets ``ignore_permissions`` (``frappe/__init__.py``: "will
	**not** check for permissions"), which switches
	``permission_query_conditions`` off wholesale — the fragment tested above is
	then never spliced in, and the DocPerm read is never asked for either. Every
	other layer in this file can be perfectly correct while one caller reading
	``Remittance Transfer`` with ``get_all`` hands a whole tenant's transfers to a
	user who holds no remittance role at all.

	``remittance_queries`` pins this for itself. This pins the *other* module that
	lists the same doctype for a screen: ``remittance_commands.payout_queue``,
	which shipped on ``get_all`` and returned sender, receiver, principal,
	commission, tendered and the full corridor for every payable transfer in any
	company the caller named.

	Source-level on purpose. The commands module needs a bench to import, so a
	behavioural version of this would live in the bench set and would not gate a
	push — and this defect is exactly the kind that ships between bench runs.
	"""

	#: Modules that list Remittance Transfer on behalf of a screen. Both must go
	#: through the permission-checking path.
	_LISTING_MODULES = ("remittance_queries.py", "remittance_commands.py")

	def test_no_listing_endpoint_calls_get_all(self):
		for module in self._LISTING_MODULES:
			path = os.path.join(_PKG, "api", module)
			with self.subTest(module=module):
				with open(path, encoding="utf-8") as fh:
					src = fh.read()
				# Matched as a CALL. Both modules name `get_all` in prose to explain
				# why it is banned, and a scan that tripped over its own rationale
				# would be deleted the first time somebody documented the rule.
				# assertFalse over assertNotIn: a failing assertNotIn prints the whole
				# 1000-line module as the "container" and buries its own message.
				self.assertFalse(
					"get_all(" in src,
					f"{module} lists Remittance Transfer with get_all, which turns "
					"permissions.remittance_transfer_query off for that read",
				)


if __name__ == "__main__":
	unittest.main()
