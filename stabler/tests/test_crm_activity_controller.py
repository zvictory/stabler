"""CRM Activity lifecycle invariants independent of the whitelisted API."""

from __future__ import annotations

import importlib
import sys
import types
import unittest


class _Document:
	def __init__(self, **values):
		self.__dict__.update(values)


def _load_controller(*, exists=True, permitted=True, reference_company="Mikas"):
	for name in (
		"stabler.stabler.doctype.crm_activity.crm_activity",
		"frappe",
		"frappe.model",
		"frappe.model.document",
	):
		sys.modules.pop(name, None)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.session = types.SimpleNamespace(user="rep@mikas.example")
	frappe.flags = types.SimpleNamespace()
	frappe.PermissionError = PermissionError
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.has_permission = lambda *_args, **_kwargs: permitted
	frappe.db = types.SimpleNamespace(
		exists=lambda *_args, **_kwargs: exists,
		get_value=lambda *_args, **_kwargs: reference_company,
	)
	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")
	document.Document = _Document
	sys.modules.update({"frappe": frappe, "frappe.model": model, "frappe.model.document": document})
	module = importlib.import_module("stabler.stabler.doctype.crm_activity.crm_activity")
	return module.CRMActivity


class TestCrmActivityController(unittest.TestCase):
	def test_direct_insert_rejects_disallowed_reference_doctype(self):
		activity = _load_controller()(
			reference_doctype="Sales Invoice",
			reference_name="SINV-1",
			company="Mikas",
		)
		with self.assertRaisesRegex(Exception, "valid CRM reference"):
			activity.validate()

	def test_direct_insert_rejects_missing_reference(self):
		activity = _load_controller(exists=False)(
			reference_doctype="CRM Deal",
			reference_name="MISSING",
			company="Mikas",
		)
		with self.assertRaisesRegex(Exception, "does not exist"):
			activity.validate()

	def test_direct_insert_requires_reference_permission(self):
		activity = _load_controller(permitted=False)(
			reference_doctype="CRM Deal",
			reference_name="DEAL-1",
			company="Mikas",
		)
		with self.assertRaises(PermissionError):
			activity.validate()

	def test_direct_insert_rejects_reference_company_mismatch(self):
		activity = _load_controller(reference_company="Other")(
			reference_doctype="CRM Deal",
			reference_name="DEAL-1",
			company="Mikas",
		)
		with self.assertRaisesRegex(Exception, "company"):
			activity.validate()


if __name__ == "__main__":
	unittest.main()
