"""Structural guards for the per-site Frappe Desk switch.

Frappe-free: the sources are read as text. Two halves, deliberately NOT
symmetric:

  - the /app gate (middleware/desk_gate.py) opens for everyone when the flag
    is on;
  - the write guard (api/desk_write_guard.py) does the opposite — it gets
    *wider* when the flag is on. A tenant that opens the Desk gets the
    purchasing and manufacturing forms there and nothing else, because the
    Stabler-only documents are orchestrated in the API layer (the stock
    reservation chain in api/sales.py), which a Desk save would skip.

The switch is a per-site setting (`Stabler Settings.allow_desk_access`), never
a tenant-name branch: the app ships to 7 tenants from one codebase.
"""

from __future__ import annotations

import ast
import json
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

GATE = os.path.join(_ROOT, "middleware", "desk_gate.py")
WRITE_GUARD = os.path.join(_ROOT, "api", "desk_write_guard.py")
HOOKS = os.path.join(_ROOT, "hooks.py")
SETTINGS_PY = os.path.join(_ROOT, "stabler", "doctype", "stabler_settings", "stabler_settings.py")
SETTINGS_JSON = os.path.join(_ROOT, "stabler", "doctype", "stabler_settings", "stabler_settings.json")

GUARD_PATH = "stabler.api.desk_write_guard.assert_write_via_stabler"

# The forms a Desk-open tenant is meant to keep using in the Desk. Their Stabler
# rules are doc_events, so they hold on any write channel — locking them would
# defeat the whole point of opening the Desk.
DESK_WRITABLE = (
	"Purchase Order",
	"Purchase Invoice",
	"Purchase Receipt",
	"Work Order",
	"BOM",
	"Job Card",
	"Stock Entry",
)

# Locked doctypes that can be submitted, so they also need the post-submit and
# cancel channels closed.
SUBMITTABLE = {
	"Sales Order",
	"Sales Invoice",
	"Delivery Note",
	"Payment Entry",
	"Journal Entry",
	"Stock Reconciliation",
	"Bank Transaction",
}


def read(path):
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def guard_constant(name):
	"""Read a module-level tuple out of desk_write_guard.py without importing frappe."""
	tree = ast.parse(read(WRITE_GUARD))
	for node in tree.body:
		if isinstance(node, ast.Assign) and node.targets[0].id == name:
			return tuple(ast.literal_eval(node.value))
	raise AssertionError(f"{name} is gone from desk_write_guard.py")


def hooks_doc_events():
	"""doc_events from hooks.py, parsed as a literal — hooks.py imports frappe."""
	tree = ast.parse(read(HOOKS))
	for node in tree.body:
		if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "doc_events":
			return ast.literal_eval(node.value)
	raise AssertionError("doc_events is gone from hooks.py")


class SwitchIsReadFromOnePlaceTest(unittest.TestCase):
	"""Two readers, one definition — so the flag can't mean different things."""

	def test_helper_reads_the_setting(self):
		src = read(SETTINGS_PY)
		self.assertIn("def desk_access_enabled()", src)
		self.assertIn('get_single_value("Stabler Settings", "allow_desk_access")', src)

	def test_helper_stays_closed_when_the_field_is_missing(self):
		# gate_desk runs on every request, including mid-migrate before the
		# doctype is synced. A raised exception there would 500 the whole site.
		src = read(SETTINGS_PY)
		helper = src.split("def desk_access_enabled()", 1)[1].split("\ndef ", 1)[0]
		self.assertIn("except Exception:", helper)
		self.assertIn("return False", helper)

	def test_both_gates_import_that_helper(self):
		for path in (GATE, WRITE_GUARD):
			with self.subTest(path=os.path.basename(path)):
				self.assertIn(
					"from stabler.stabler.doctype.stabler_settings.stabler_settings import "
					"desk_access_enabled",
					read(path),
				)


class GateOpensOnlyOnFlaggedSitesTest(unittest.TestCase):
	def setUp(self):
		self.src = read(GATE)

	def test_admin_check_survives(self):
		# The flag widens the gate; it must not replace the admin allowlist,
		# which is what keeps /app reachable on every other tenant.
		self.assertIn('"System Manager" in roles or "Administrator" in roles', self.src)

	def test_flag_short_circuits_before_the_redirect(self):
		flag = self.src.index("if desk_access_enabled():")
		roles = self.src.index('"System Manager" in roles')
		bounce = self.src.index("abort(redirect(STABLER_HOME")
		self.assertLess(roles, flag, "the flag read must sit after the role check")
		self.assertLess(flag, bounce, "the flag must be checked before the 302")

	def test_flag_is_read_after_the_path_filter(self):
		# Keeps the query off every non-desk request that passes through
		# before_request.
		self.assertLess(self.src.index("if not _is_gated(path)"), self.src.index("desk_access_enabled()"))


class WriteLockIsScopedByDoctypeTest(unittest.TestCase):
	"""The flag must widen the write lock, never lift it."""

	def setUp(self):
		self.always = guard_constant("_STABLER_ONLY_ALWAYS")
		self.when_open = guard_constant("_STABLER_ONLY_WHEN_DESK_OPEN")
		self.src = read(WRITE_GUARD)

	def test_sales_documents_are_locked_on_every_site(self):
		# The reservation chain is orchestrated in api/sales.py, not in
		# doc_events — a Desk save passes validation and strands the reservation.
		# No per-site flag may unlock these.
		self.assertEqual(("Sales Order", "Sales Invoice"), self.always)

	def test_purchasing_and_manufacturing_stay_writable(self):
		# The reason the Desk was opened in the first place. If one of these ever
		# shows up in a lock list, the tenant loses the forms it asked for.
		for doctype in DESK_WRITABLE:
			with self.subTest(doctype=doctype):
				self.assertNotIn(doctype, self.always)
				self.assertNotIn(doctype, self.when_open)

	def test_the_two_lists_do_not_overlap(self):
		self.assertEqual(set(), set(self.always) & set(self.when_open))

	def test_flag_only_widens_the_lock(self):
		# Off-flag sites must keep exactly the old scope: the other six tenants
		# have bots writing Payment Entries over REST.
		body = self.src.split("def _locked_doctypes()", 1)[1].split("\ndef ", 1)[0]
		self.assertIn("if desk_access_enabled():", body)
		self.assertIn("return _STABLER_ONLY_ALWAYS + _STABLER_ONLY_WHEN_DESK_OPEN", body)
		self.assertIn("return _STABLER_ONLY_ALWAYS", body)

	def test_stabler_and_headless_exemptions_survive(self):
		self.assertIn("if _from_stabler_or_headless():", self.src)
		self.assertIn("if _is_admin():", self.src)

	def test_free_channels_are_cleared_before_the_settings_read(self):
		# assert_write_via_stabler runs on every write of every locked doctype.
		# The DB read must sit behind the two checks that need no query.
		body = self.src.split("def assert_write_via_stabler", 1)[1]
		self.assertLess(body.index("_from_stabler_or_headless()"), body.index("_locked_doctypes()"))
		self.assertLess(body.index("_is_admin()"), body.index("_locked_doctypes()"))

	def test_the_message_names_the_doctype(self):
		# One guard, nine doctypes — a hardcoded "Sales Orders and Sales
		# Invoices" message would lie on seven of them.
		body = self.src.split("def assert_write_via_stabler", 1)[1]
		self.assertIn("{0} can only be created or changed through the Stabler app.", body)
		self.assertIn("_(doc.doctype)", body)


class EveryLockedDoctypeIsWiredTest(unittest.TestCase):
	"""The constants and hooks.py must not drift apart.

	A doctype in a lock list but missing from doc_events is a lock that silently
	does nothing — the failure mode this test exists to make impossible.
	"""

	def setUp(self):
		self.locked = guard_constant("_STABLER_ONLY_ALWAYS") + guard_constant("_STABLER_ONLY_WHEN_DESK_OPEN")
		self.events = hooks_doc_events()

	def test_every_locked_doctype_guards_its_write_channels(self):
		for doctype in self.locked:
			with self.subTest(doctype=doctype):
				handlers = self.events.get(doctype)
				self.assertIsNotNone(handlers, f"{doctype} is locked but absent from doc_events")
				expected = ["before_validate", "on_trash"]
				if doctype in SUBMITTABLE:
					expected += ["before_update_after_submit", "before_cancel"]
				for event in expected:
					self.assertIn(GUARD_PATH, handlers.get(event, []), f"{doctype}.{event}")

	def test_the_guard_runs_first_on_validate(self):
		# Validation and the diag hook both write; letting them run before the
		# guard means a rejected save still had side effects.
		for doctype in self.locked:
			with self.subTest(doctype=doctype):
				self.assertEqual(GUARD_PATH, self.events[doctype]["before_validate"][0])

	def test_no_writable_doctype_is_guarded(self):
		for doctype in DESK_WRITABLE:
			with self.subTest(doctype=doctype):
				for handlers in [self.events.get(doctype, {})]:
					for event, paths in handlers.items():
						self.assertNotIn(GUARD_PATH, paths, f"{doctype}.{event}")


class FlagIsOptInTest(unittest.TestCase):
	"""Default off: the app ships to 7 tenants, only one asked for the Desk."""

	def test_field_exists_and_defaults_to_off(self):
		doc = json.loads(read(SETTINGS_JSON))
		field = next(f for f in doc["fields"] if f["fieldname"] == "allow_desk_access")
		self.assertEqual(field["fieldtype"], "Check")
		self.assertEqual(field["default"], "0")

	def test_field_is_in_field_order(self):
		doc = json.loads(read(SETTINGS_JSON))
		self.assertIn("allow_desk_access", doc["field_order"])

	def test_description_does_not_promise_a_lifted_write_lock(self):
		# It used to. Admins read this string to decide whether to flip the flag.
		doc = json.loads(read(SETTINGS_JSON))
		field = next(f for f in doc["fields"] if f["fieldname"] == "allow_desk_access")
		self.assertNotIn("lifted", field.get("description", ""))


class NoTenantBranchTest(unittest.TestCase):
	"""Mirrors the Makefile guard at the unit-test level."""

	TENANT = re.compile(
		r'(==|!=|===|!==)\s*["\'](anjan|msa|mikas|dts|horeca|laminor|smartbox)', re.IGNORECASE
	)

	def test_sources_are_free_of_tenant_names(self):
		for path in (GATE, WRITE_GUARD, SETTINGS_PY):
			with self.subTest(path=os.path.basename(path)):
				self.assertIsNone(self.TENANT.search(read(path)))


if __name__ == "__main__":
	unittest.main()
