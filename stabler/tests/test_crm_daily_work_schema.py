"""Contracts for the CRM daily-work schema and migration."""

from __future__ import annotations

import importlib
import json
import os
import types
import unittest
from unittest.mock import patch

from stabler.tests.module_sandbox import ModuleSandbox

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _install_frappe_package():
	"""Publish a fake ``frappe`` that is a *package*, not a bare module.

	``v74`` re-exports ``v27``, which does ``from frappe.custom.doctype.custom_field
	.custom_field import create_custom_fields`` at import time. A bare
	``ModuleType("frappe")`` has no ``__path__``, so that import dies with
	``'frappe' is not a package`` — the submodules have to exist too.
	"""
	frappe = types.ModuleType("frappe")
	frappe.__path__ = []
	modules = {"frappe": frappe}
	parent = frappe
	for name in ("frappe.custom", "frappe.custom.doctype", "frappe.custom.doctype.custom_field"):
		child = types.ModuleType(name)
		child.__path__ = []
		setattr(parent, name.rsplit(".", 1)[1], child)
		modules[name] = child
		parent = child
	leaf = types.ModuleType("frappe.custom.doctype.custom_field.custom_field")
	leaf.create_custom_fields = lambda *_args, **_kwargs: None
	parent.custom_field = leaf
	modules["frappe.custom.doctype.custom_field.custom_field"] = leaf
	_SANDBOX.install(modules)


class TestCrmDailyWorkSchema(unittest.TestCase):
	def test_tender_deal_field_repair_patch_is_registered_and_replays_v27(self):
		"""Sites where v27 ran before CRM existed must get a second schema pass."""
		repair = "stabler.patches.v74_repair_tender_deal_fields"
		with open(os.path.join(_ROOT, "patches.txt"), encoding="utf-8") as source:
			self.assertIn(repair, source.read().split())

		_SANDBOX.evict(repair, "stabler.patches.v27_tender_deal_fields")
		_install_frappe_package()
		module = importlib.import_module(repair)
		with patch.object(module, "create_tender_deal_fields") as create_fields:
			module.execute()
		create_fields.assert_called_once_with()

	def test_patch_is_registered_and_declares_all_deal_fields(self):
		with open(os.path.join(_ROOT, "patches.txt"), encoding="utf-8") as source:
			self.assertIn("stabler.patches.v60_crm_daily_work", source.read())
		with open(os.path.join(_ROOT, "patches", "v60_crm_daily_work.py"), encoding="utf-8") as source:
			patch = source.read()
		for fieldname in (
			"deal_type",
			"next_action_type",
			"next_action_at",
			"next_action_owner",
			"stage_entered_at",
			"won_at",
			"lost_at",
			"loss_reason",
			"forecast_category",
		):
			self.assertIn(f'"fieldname": "{fieldname}"', patch)

	def test_activity_and_stage_event_are_company_scoped_records(self):
		for doctype in ("crm_activity", "crm_stage_event"):
			path = os.path.join(_ROOT, "stabler", "doctype", doctype, f"{doctype}.json")
			with open(path, encoding="utf-8") as source:
				meta = json.load(source)
			fields = {field["fieldname"]: field for field in meta["fields"]}
			self.assertEqual(fields["company"]["options"], "Company")
			self.assertTrue(fields["company"]["reqd"])
			self.assertIn("reference_doctype", fields)
			self.assertIn("reference_name", fields)
			if doctype == "crm_stage_event":
				self.assertIn("loss_reason", fields)

	def test_framework_permissions_scope_both_audit_doctypes_by_company(self):
		with open(os.path.join(_ROOT, "hooks.py"), encoding="utf-8") as source:
			hooks = source.read()
		for doctype in ("CRM Activity", "CRM Stage Event"):
			self.assertGreaterEqual(hooks.count(f'"{doctype}"'), 2)

	def test_crm_hygiene_enforcement_setting_is_server_owned_and_defaults_off(self):
		path = os.path.join(_ROOT, "stabler", "doctype", "stabler_settings", "stabler_settings.json")
		with open(path, encoding="utf-8") as source:
			meta = json.load(source)
		fields = {field["fieldname"]: field for field in meta["fields"]}

		self.assertEqual(fields["enforce_crm_next_action"]["fieldtype"], "Check")
		self.assertEqual(fields["enforce_crm_next_action"]["default"], "0")

	def test_crm_deal_lifecycle_wires_server_hygiene_validation(self):
		with open(os.path.join(_ROOT, "hooks.py"), encoding="utf-8") as source:
			hooks = source.read()
		self.assertIn('"CRM Deal": {', hooks)
		self.assertIn('"stabler.api.crm.validate_crm_deal_hygiene"', hooks)


if __name__ == "__main__":
	unittest.main()
