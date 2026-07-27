"""Structural guards for the port-transfer departure gate.

Frappe-free: the source is read as text. These assert the properties that make
the gate trustworthy — that it is enforced in the controller and not only in
the UI, that its scope stays narrow, and that the override cannot be used
without a role and a reason.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))

TRUCK = os.path.join(_ROOT, "stabler", "doctype", "import_truck", "import_truck.py")
API = os.path.join(_ROOT, "api", "imports.py")
MATH = os.path.join(_ROOT, "stabler", "imports_module", "departure_math.py")
PATCH = os.path.join(_ROOT, "patches", "v55_departure_gate.py")
PATCHES_TXT = os.path.join(_ROOT, "patches.txt")


def read(path):
	with open(path, encoding="utf-8") as fh:
		return fh.read()


class EnforcedInTheControllerTest(unittest.TestCase):
	"""A gate that only lives in the SPA is not a gate."""

	def setUp(self):
		self.src = read(TRUCK)

	def test_validate_calls_the_gate(self):
		self.assertIn("self._check_departure_gate(previous_status)", self.src)

	def test_gate_throws(self):
		self.assertIn("frappe.throw(_blocker_message(", self.src)

	def test_gate_uses_the_shared_pure_rule(self):
		# The controller must not re-implement the decision; if it did, the API
		# preview and the enforcement could diverge.
		self.assertIn("departure_math.may_depart(", self.src)
		self.assertIn("departure_math.gates_this_transition(", self.src)


class ScopeTest(unittest.TestCase):
	def test_only_the_pending_to_departed_transition_is_gated(self):
		self.assertIn('GATED_TRANSITION = ("PENDING", "DEPARTED_IRAN")', read(MATH))

	def test_gate_respects_the_imports_module_toggle(self):
		# Six other tenants carry this doctype; the rule is msa's business.
		self.assertIn("_imports_enabled(self.company)", read(TRUCK))


class OverrideTest(unittest.TestCase):
	def setUp(self):
		self.truck = read(TRUCK)
		self.math = read(MATH)

	def test_override_requires_a_role(self):
		self.assertIn("_assert_override_role()", self.truck)
		self.assertIn("Imports Manager", self.truck)

	def test_override_requires_a_reason(self):
		self.assertIn('str(override_reason or "").strip()', self.math)

	def test_override_is_recorded_on_the_document(self):
		self.assertIn("self.add_comment(", self.truck)

	def test_override_does_not_erase_the_blockers(self):
		# may_depart returns the blockers even when it allows via override, so
		# the audit trail records what was overridden.
		body = re.search(r"def may_depart\(.*?\n\n\n", self.math, re.S).group(0)
		self.assertIn('"blockers": blockers, "via_override": True', body)


class PreviewMatchesEnforcementTest(unittest.TestCase):
	def setUp(self):
		self.api = read(API)

	def test_preview_endpoint_exists_and_is_whitelisted(self):
		self.assertRegex(self.api, r"@frappe\.whitelist\(\)\ndef truck_departure_status\(")

	def test_preview_uses_the_same_pure_rule(self):
		self.assertIn("departure_math.may_depart(", self.api)

	def test_preview_is_company_scoped(self):
		m = re.search(r"def truck_departure_status\(.*?(?=\n@frappe|\Z)", self.api, re.S)
		self.assertIn("_assert_imports_access(company)", m.group(0))
		self.assertIn('_assert_can_read("Import Truck", truck)', m.group(0))

	def test_preview_never_writes(self):
		m = re.search(r"def truck_departure_status\(.*?(?=\n@frappe|\Z)", self.api, re.S)
		for token in (".save(", ".insert(", "db_set(", "db.set_value("):
			with self.subTest(token=token):
				self.assertNotIn(token, m.group(0))


class BackwardCompatibilityTest(unittest.TestCase):
	"""The flag is a custom field; a tenant that has not migrated must not be
	silently released."""

	def test_missing_column_treats_every_declaration_as_required(self):
		src = read(TRUCK)
		self.assertIn("_has_required_flag()", src)
		self.assertIn('d["required_for_departure"] = 1', src)


class PatchTest(unittest.TestCase):
	def setUp(self):
		self.src = read(PATCH)

	def test_registered_in_patches_txt(self):
		self.assertIn("stabler.patches.v55_departure_gate", read(PATCHES_TXT))

	def test_idempotent(self):
		self.assertIn('frappe.db.exists("Custom Field"', self.src)

	def test_required_flag_defaults_to_on(self):
		# Forgetting to tick a declaration must not open the gate.
		m = re.search(r'"fieldname": "required_for_departure".*?\}', self.src, re.S)
		self.assertIn('"default": "1"', m.group(0))

	def test_patch_does_not_read_the_new_columns(self):
		# patches.txt has no [post_model_sync] marker, so this runs before the
		# DDL sync — touching the new column would abort migrate.
		self.assertNotIn("has_column", self.src)
		self.assertNotIn('required_for_departure"]', self.src)


if __name__ == "__main__":
	unittest.main()
