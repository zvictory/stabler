"""Structural guards for the per-site Frappe Desk switch.

Frappe-free: the sources are read as text. The Desk gate and the Sales
Order / Sales Invoice desk-write lock are two halves of one policy, so they
must open and close together — a site that lets everyone into /app must also
let them save there, otherwise the Desk is a read-only trap.

The switch is a per-site setting (`Stabler Settings.allow_desk_access`), never
a tenant-name branch: the app ships to 7 tenants from one codebase.
"""

from __future__ import annotations

import json
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

GATE = os.path.join(_ROOT, "middleware", "desk_gate.py")
WRITE_GUARD = os.path.join(_ROOT, "api", "desk_write_guard.py")
SETTINGS_PY = os.path.join(_ROOT, "stabler", "doctype", "stabler_settings", "stabler_settings.py")
SETTINGS_JSON = os.path.join(_ROOT, "stabler", "doctype", "stabler_settings", "stabler_settings.json")


def read(path):
	with open(path, encoding="utf-8") as fh:
		return fh.read()


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


class WriteLockFollowsTheSameFlagTest(unittest.TestCase):
	def setUp(self):
		self.src = read(WRITE_GUARD)

	def test_flag_short_circuits_before_the_throw(self):
		flag = self.src.index("if desk_access_enabled():")
		throw = self.src.index("frappe.throw(")
		self.assertLess(flag, throw)

	def test_stabler_and_headless_exemptions_survive(self):
		self.assertIn("if _from_stabler_or_headless():", self.src)
		self.assertIn("if _is_admin():", self.src)


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
