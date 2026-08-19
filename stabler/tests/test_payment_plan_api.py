"""The payment-plan API's two hard edges: who may see whose plan, and what a client may write.

The calendar's whole premise is that a user records their own intentions freely
and only an authorised reader sees everyone's. That premise is enforced in
exactly one place — the endpoint — and it fails in two directions:

1. **Widening.** If the owner filter can be influenced by a request parameter,
   any Payment Plan User reads the director's forecast. So the visibility filter
   is a pure function here, tested with roles injected, rather than an ``if``
   buried in a query builder.

2. **Derived fields arriving from the client.** ``direction`` and ``base_amount``
   are what every total sums, and ``read_only`` in a DocType JSON is a form hint,
   not a write guard — ``doc.direction = payload["direction"]`` sails straight
   past it. So the payload is whitelisted, not filtered, and the whitelist is
   asserted against the derived set so adding a derived field to the schema
   without excluding it here fails loudly.

Plus the two invariants that hold for every Stabler endpoint and one that is
specific to this module:

- every ``@frappe.whitelist()`` entry point passes the module gate, because a
  whitelisted method is reachable by any logged-in user on any tenant;
- the cross-user totals endpoint requires the manager role, not merely the module;
- nothing here posts a Payment Entry (Zafar, 2026-08-19).

Bench-free: ``make check`` does not run the bench set, so a test needing a bench
would not gate a push.
"""

from __future__ import annotations

import ast
import types
import unittest
from pathlib import Path

from stabler.tests.module_sandbox import ModuleSandbox

_ROOT = Path(__file__).resolve().parent.parent
API = _ROOT / "api" / "payment_plan.py"
ORGANIZATION = _ROOT / "api" / "organization.py"

MODULE_KEY = "payment_calendar"
MANAGER_ROLE = "Payment Plan Manager"
USER_ROLE = "Payment Plan User"

# Computed on validate, or set by the endpoint from the session. A client that
# could send any of these could write a number the ledger never agreed to.
DERIVED_FIELDS = {"direction", "base_amount", "party_name", "owner_user", "company", "naming_series"}

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


def _load_api(*, user="planner@example.com", roles=()):
	_SANDBOX.evict(
		"stabler.api.payment_plan",
		"stabler.api._common",
		"stabler.api.organization",
		"frappe",
		"frappe.utils",
	)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value

	def _throw(message, exc=None, *args, **kwargs):
		raise (exc or ValueError)(str(message))

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: lambda fn: fn
	frappe.session = types.SimpleNamespace(user=user)
	frappe.get_roles = lambda _user=None: list(roles)
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.db = types.SimpleNamespace(
		exists=lambda *a, **k: True,
		get_value=lambda *a, **k: None,
	)
	frappe.get_all = lambda *a, **k: []

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value, precision=None: 0.0 if value in (None, "") else float(value)
	utils.getdate = lambda value=None: value
	utils.cint = lambda value: int(value or 0)
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: company
	common._assert_can_read = lambda *a, **k: None
	common._assert_can_write = lambda *a, **k: None

	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
	organization._can_access_module = lambda _user, _key: True
	organization._user_allowed_companies = lambda _user: []

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.organization": organization,
		}
	)

	import importlib

	return importlib.import_module("stabler.api.payment_plan"), frappe


class PaymentPlanModuleRegistrationTest(unittest.TestCase):
	def test_the_module_key_is_registered_against_the_company_flag(self):
		"""``_can_access_module`` resolves nothing for an unregistered key, so an
		unregistered module is silently admin-only — the module would look gated
		while being unreachable for every role that is supposed to have it."""
		source = ORGANIZATION.read_text(encoding="utf-8")
		self.assertIn(f'"{MODULE_KEY}": "enable_payment_calendar"', source)

	def test_both_roles_grant_the_module(self):
		"""A key absent from ``_MODULE_ROLES`` is admin-only by design
		(least-privilege default). Both plan roles must appear, or the two roles
		v95 creates cannot open the page they exist for."""
		source = ORGANIZATION.read_text(encoding="utf-8")
		tree = ast.parse(source)
		roles = None
		for node in ast.walk(tree):
			if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "_MODULE_ROLES":
				roles = ast.literal_eval(node.value)
			elif isinstance(node, ast.Assign) and any(
				getattr(t, "id", None) == "_MODULE_ROLES" for t in node.targets
			):
				roles = ast.literal_eval(node.value)
		self.assertIsNotNone(roles, "organization.py defines no _MODULE_ROLES")
		self.assertIn(MODULE_KEY, roles)
		self.assertEqual(set(roles[MODULE_KEY]), {USER_ROLE, MANAGER_ROLE})

	def test_the_flag_is_toggleable_from_the_admin_screen(self):
		"""Two flags shipped read-only once already — reachable in the module map
		but absent from ``set_company_modules``, so only a patch could set them
		(see the Turkish comment at organization.py's writer). A module nobody
		can switch on is a module nobody uses."""
		source = ORGANIZATION.read_text(encoding="utf-8")
		self.assertIn('"enable_payment_calendar": payment_calendar', source)


class PaymentPlanVisibilityTest(unittest.TestCase):
	def test_a_plain_user_sees_only_their_own_rows(self):
		module, _ = _load_api(user="planner@example.com", roles=(USER_ROLE,))
		self.assertEqual(
			module.visibility_filter("planner@example.com", (USER_ROLE,), owner_user="boss@example.com"),
			{"owner_user": "planner@example.com"},
		)

	def test_a_request_parameter_cannot_widen_a_plain_user(self):
		"""The whole confidentiality model is this one line. A user who can name
		someone else's plan in a filter reads the director's forecast."""
		module, _ = _load_api(user="planner@example.com", roles=(USER_ROLE,))
		for requested in (None, "", "boss@example.com", "%"):
			self.assertEqual(
				module.visibility_filter("planner@example.com", (USER_ROLE,), owner_user=requested)[
					"owner_user"
				],
				"planner@example.com",
			)

	def test_a_manager_sees_everyone_by_default(self):
		module, _ = _load_api(user="boss@example.com", roles=(MANAGER_ROLE,))
		self.assertEqual(module.visibility_filter("boss@example.com", (MANAGER_ROLE,), owner_user=None), {})

	def test_a_manager_may_narrow_to_one_planner(self):
		"""Reading one person's plan is the point of the role; the totals view
		drills into a name."""
		module, _ = _load_api(user="boss@example.com", roles=(MANAGER_ROLE,))
		self.assertEqual(
			module.visibility_filter("boss@example.com", (MANAGER_ROLE,), owner_user="planner@example.com"),
			{"owner_user": "planner@example.com"},
		)

	def test_an_admin_reads_across_without_the_module_role(self):
		"""Every other Stabler module lets System Manager / Stabler Admin
		through; a payment calendar that locked out the admin would need a role
		grant just to support it."""
		module, _ = _load_api(user="admin@example.com", roles=("System Manager",))
		self.assertEqual(
			module.visibility_filter("admin@example.com", ("System Manager",), owner_user=None), {}
		)


class PaymentPlanPayloadTest(unittest.TestCase):
	def test_a_client_cannot_write_a_derived_field(self):
		"""``read_only`` in a DocType JSON is a form hint. Copying a payload
		wholesale onto the doc writes ``base_amount`` straight into the number a
		director reads as a total."""
		module, _ = _load_api(roles=(USER_ROLE,))
		cleaned = module.clean_payload(
			{
				"kind": "Expense",
				"amount": 500,
				"direction": "In",
				"base_amount": 999_999_999,
				"owner_user": "boss@example.com",
				"company": "Other Co",
			}
		)
		for field in DERIVED_FIELDS:
			self.assertNotIn(field, cleaned)
		self.assertEqual(cleaned["kind"], "Expense")

	def test_the_writable_set_and_the_derived_set_do_not_overlap(self):
		"""Adding a derived field to the schema and forgetting it here is the
		regression this asserts: the two sets are checked against each other, not
		against a hand-copied list."""
		module, _ = _load_api(roles=(USER_ROLE,))
		self.assertEqual(set(module.WRITABLE_FIELDS) & DERIVED_FIELDS, set())

	def test_an_unknown_key_is_dropped_not_passed_through(self):
		"""A whitelist, not a blocklist — otherwise every field added to the
		doctype later becomes client-writable the moment it exists."""
		module, _ = _load_api(roles=(USER_ROLE,))
		self.assertNotIn("docstatus", module.clean_payload({"kind": "Expense", "docstatus": 1}))


class PaymentPlanEndpointGuardTest(unittest.TestCase):
	"""Source-level guards. ``@frappe.whitelist()`` gates method access only —
	any logged-in user on any tenant can call the method, so the gate has to be
	inside the body."""

	def _whitelisted(self):
		tree = ast.parse(API.read_text(encoding="utf-8"))
		out = []
		for node in tree.body:
			if not isinstance(node, ast.FunctionDef):
				continue
			for dec in node.decorator_list:
				target = dec.func if isinstance(dec, ast.Call) else dec
				if getattr(target, "attr", None) == "whitelist":
					out.append(node)
		return out

	def _calls(self, node) -> set[str]:
		names = set()
		for sub in ast.walk(node):
			if isinstance(sub, ast.Call):
				fn = sub.func
				names.add(getattr(fn, "id", None) or getattr(fn, "attr", None) or "")
		return names

	def test_there_are_endpoints_to_guard(self):
		self.assertTrue(self._whitelisted(), "payment_plan.py exposes no endpoints")

	def test_every_endpoint_passes_the_module_gate(self):
		for node in self._whitelisted():
			self.assertIn(
				"_require_payment_calendar",
				self._calls(node),
				f"{node.name} does not gate on the payment_calendar module",
			)

	def test_every_endpoint_resolves_a_company(self):
		"""An endpoint that infers the company from user defaults reads another
		tenant's plan on a multi-company site."""
		for node in self._whitelisted():
			self.assertIn(
				"_require_plan_company",
				self._calls(node),
				f"{node.name} does not scope to an explicit company",
			)

	def test_the_cross_user_totals_endpoint_requires_the_manager_role(self):
		"""The module gate is not enough: a Payment Plan User holds the module
		and must still not read the aggregate."""
		names = {n.name: n for n in self._whitelisted()}
		self.assertIn("payment_plan_totals", names)
		self.assertIn("_require_plan_manager", self._calls(names["payment_plan_totals"]))

	def test_the_api_never_posts_a_payment_entry(self):
		"""Zafar, 2026-08-19: "otomatik payment entry olmasin". Asserted as an
		absence, in the layer that would be tempted to do it."""
		self.assertNotIn("Payment Entry", API.read_text(encoding="utf-8"))


if __name__ == "__main__":
	unittest.main()
