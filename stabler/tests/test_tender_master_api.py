"""Behaviour contracts for Tender Master company and record permissions."""

from __future__ import annotations

import importlib
import sys
import types
import unittest


class _Doc(dict):
	def __getattr__(self, field):
		return self.get(field)

	def __setattr__(self, field, value):
		self[field] = value

	def as_dict(self):
		return dict(self)

	def insert(self):
		self["inserted"] = True
		return self

	def save(self):
		self["saved"] = True
		return self


class _FakeFrappe:
	def __init__(self):
		self.docs = {
			("Tender Master", "TND-2026-00001"): _Doc(
				name="TND-2026-00001", company="ACME", title="Network tender", currency="USD", status="New"
			),
			("CRM Deal", "LOT-ALLOWED"): _Doc(
				name="LOT-ALLOWED", company="ACME", custom_parent_tender="TND-2026-00001", status="Open", custom_estimated_value=125
			),
			("CRM Deal", "LOT-DENIED"): _Doc(
				name="LOT-DENIED", company="ACME", custom_parent_tender="TND-2026-00001", status="Won", custom_estimated_value=500
			),
		}
		self.created: list[_Doc] = []
		self.last_filters: dict | None = None

	def get_doc(self, doctype, name):
		return self.docs[(doctype, name)]

	def new_doc(self, doctype):
		doc = _Doc(doctype=doctype, name="TND-NEW")
		self.created.append(doc)
		return doc

	def get_list(self, doctype, **kwargs):
		filters = kwargs.get("filters", {})
		self.last_filters = filters
		rows = [doc for (kind, _name), doc in self.docs.items() if kind == doctype]
		rows = [row for row in rows if all(row.get(field) == value for field, value in filters.items())]
		if kwargs.get("fields") == ["count(name) as total"]:
			return [{"total": len(rows)}]
		return rows


def _load_api(fake: _FakeFrappe):
	for name in ("stabler.api.tender_master", "frappe", "frappe.utils", "stabler.api._common", "stabler.api.organization"):
		sys.modules.pop(name, None)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.session = types.SimpleNamespace(user="sales@example.com")
	frappe.get_doc = fake.get_doc
	frappe.new_doc = fake.new_doc
	frappe.get_list = fake.get_list
	frappe.parse_json = lambda value: value
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.has_permission = lambda doctype, ptype="read", doc=None: not (doctype == "CRM Deal" and doc == "LOT-DENIED")
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: company or (_ for _ in ()).throw(ValueError("Company is required."))
	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
	organization._user_allowed_companies = lambda _user: ["ACME"]
	frappe.get_roles = lambda _user=None: ["Sales User"]
	sys.modules.update(
		{"frappe": frappe, "frappe.utils": utils, "stabler.api._common": common, "stabler.api.organization": organization}
	)
	return importlib.import_module("stabler.api.tender_master")


class TestTenderMasterApi(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)
		self.cross_company_deal = _Doc(name="DEAL-OTHER", company="Other Co", custom_parent_tender="TND-2026-00001")

	def test_get_tender_master_rejects_cross_company_name(self):
		"""Removing the selected-company check would expose a named foreign tender."""
		with self.assertRaises(PermissionError):
			self.api.get_tender_master("TND-2026-00001", company="Other Co")

	def test_get_tender_master_returns_only_permitted_child_lots(self):
		"""Removing per-lot permission filtering would disclose an unreadable CRM Deal."""
		result = self.api.get_tender_master("TND-2026-00001", company="ACME")
		self.assertEqual([row["name"] for row in result["lots"]], ["LOT-ALLOWED"])
		self.assertEqual(result["summary"], {"lot_count": 1, "open_lot_count": 1, "estimated_total": 125.0, "currency": "USD"})

	def test_save_tender_master_uses_allowlisted_fields(self):
		"""Allowing arbitrary payload keys would let callers overwrite audit ownership."""
		result = self.api.save_tender_master(
			{"title": "Network tender", "company": "ACME", "owner": "Administrator"}, company="ACME"
		)
		self.assertNotIn("owner", result)
		self.assertEqual(result["company"], "ACME")

	def test_parent_tender_company_must_match_deal_company(self):
		"""Removing this validation would link a CRM Deal to another company's tender."""
		with self.assertRaises(ValueError):
			self.api.validate_deal_parent_tender(self.cross_company_deal)


if __name__ == "__main__":
	unittest.main()
