"""Behaviour contracts for company-scoped CRM APIs.

These tests run the public CRM methods against a deliberately small Frappe
surface.  They protect tenant boundaries rather than implementation details:
the selected company is mandatory, list results stay in that company, invoice
AR cannot cross it, and client payloads cannot take ownership of server fields.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest


class _Doc(dict):
	def __init__(self, **values):
		super().__init__(values)
		object.__setattr__(self, "saved", False)

	def __getattr__(self, field):
		return self.get(field)

	def __setattr__(self, field, value):
		if field == "saved":
			object.__setattr__(self, field, value)
			return
		self[field] = value

	def update(self, values):
		super().update(values)

	def save(self):
		self.saved = True

	def as_dict(self):
		return dict(self)


class _FakeDB:
	def __init__(self):
		self.leads = [
			{"name": "LEAD-MIKAS", "company": "Mikas", "lead_name": "Mikas lead"},
			{"name": "LEAD-OTHER", "company": "Other", "lead_name": "Other lead"},
		]
		self.deals = [
			{"name": "DEAL-MIKAS", "company": "Mikas", "linked_customer": "CUST-MIKAS"},
			{"name": "DEAL-OTHER", "company": "Other", "linked_customer": "CUST-OTHER"},
		]
		self.ar_queries: list[tuple[str, dict]] = []
		self.created: list[_Doc] = []

	def exists(self, doctype, name):
		return doctype == "Company" and name in {"Mikas", "Other"}

	def sql(self, query, values=None, as_dict=False):
		if "tabSales Invoice" in query:
			self.ar_queries.append((query, values or {}))
			if values.get("company") != "Mikas":
				return [("CUST-OTHER", 900)]
			return [("CUST-MIKAS", 100)]
		return []


def _load_crm(db: _FakeDB):
	for name in (
		"stabler.api.crm",
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.organization",
	):
		sys.modules.pop(name, None)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.session = types.SimpleNamespace(user="rep@mikas.example")
	frappe.db = db
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.get_roles = lambda _user=None: ["Sales User"]
	frappe.has_permission = lambda *_args, **_kwargs: True
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.parse_json = lambda value: value
	frappe.get_doc = lambda _doctype, _name: _Doc(name=_name, company="Mikas")
	frappe.new_doc = lambda doctype: _new_doc(db, doctype)
	frappe.get_all = lambda *_args, **_kwargs: []
	frappe.clear_last_message = lambda: None

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_args, **_kwargs: None
	common._assert_can_write = lambda *_args, **_kwargs: None
	common._require_company = lambda company: _require_company(db, company)

	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
	organization._can_access_module = lambda *_args, **_kwargs: True
	organization._user_allowed_companies = lambda _user: ["Mikas"]

	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.organization": organization,
		}
	)
	return importlib.import_module("stabler.api.crm")


def _require_company(db: _FakeDB, company: str):
	if not company:
		raise ValueError("Company is required.")
	if not db.exists("Company", company):
		raise ValueError(f"Unknown company: {company}")
	return company


def _new_doc(db: _FakeDB, doctype: str):
	doc = _Doc(doctype=doctype)
	db.created.append(doc)
	return doc


class TestCrmCompanyScope(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.crm = _load_crm(self.db)

	def test_lists_reject_missing_selected_company(self):
		"""Removing the company gate must fail this test instead of widening a list."""
		with self.assertRaisesRegex(ValueError, "Company is required"):
			self.crm.list_leads()
		with self.assertRaisesRegex(ValueError, "Company is required"):
			self.crm.list_deals()

	def test_lists_only_return_the_selected_company_records(self):
		"""Dropping the company filter must expose the Other fixtures and fail here."""
		def get_list(doctype, filters, **_kwargs):
			rows = self.db.leads if doctype == "CRM Lead" else self.db.deals
			return [row for row in rows if row["company"] == filters["company"]]

		self.crm.frappe.get_list = get_list
		leads = self.crm.list_leads("Mikas")
		deals = self.crm.list_deals("Mikas")

		self.assertEqual([row["name"] for row in leads["leads"]], ["LEAD-MIKAS"])
		self.assertEqual([row["name"] for row in deals["deals"]], ["DEAL-MIKAS"])

	def test_deal_ar_query_is_limited_to_the_selected_company(self):
		"""Removing Sales Invoice.company from AR SQL must leak CUST-OTHER here."""
		self.crm.frappe.get_list = lambda *_args, **_kwargs: [self.db.deals[0]]

		result = self.crm.list_deals("Mikas")

		self.assertEqual(result["deals"][0]["ar_outstanding"], 100.0)
		self.assertEqual(self.db.ar_queries[0][1]["company"], "Mikas")

	def test_lead_mutation_requires_company_and_discards_server_owned_fields(self):
		"""Allowing payload company, owner, or links would make this test fail."""
		payload = {
			"first_name": "Amina",
			"company": "Other",
			"owner": "attacker@example.com",
			"linked_customer": "CUST-OTHER",
		}
		with self.assertRaisesRegex(ValueError, "Company is required"):
			self.crm.save_lead(payload)

		result = self.crm.save_lead(payload, "Mikas")

		self.assertEqual(result["company"], "Mikas")
		self.assertEqual(result["first_name"], "Amina")
		self.assertNotIn("owner", result)
		self.assertNotIn("linked_customer", result)

	def test_deal_mutation_sets_company_and_discards_client_link_fields(self):
		"""Accepting linked_customer or a payload company would bypass hand-off controls."""
		payload = {
			"organization": "Mikas Shop",
			"company": "Other",
			"linked_customer": "CUST-OTHER",
			"owner": "attacker@example.com",
		}

		result = self.crm.save_deal(payload, "Mikas")

		self.assertEqual(result["company"], "Mikas")
		self.assertEqual(result["organization"], "Mikas Shop")
		self.assertNotIn("linked_customer", result)
		self.assertNotIn("owner", result)


if __name__ == "__main__":
	unittest.main()
