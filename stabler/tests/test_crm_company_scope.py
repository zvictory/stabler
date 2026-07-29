"""Behaviour contracts for company-scoped CRM APIs.

The fake runtime models company and record permissions independently.  The
tests exercise public CRM APIs, including aggregate values that must never be
computed from invoices the current user cannot read.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import date


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

	def db_set(self, field, value):
		self[field] = value


class _FakeDB:
	def __init__(self):
		self.docs = {
			("CRM Lead", "LEAD-MIKAS"): _Doc(name="LEAD-MIKAS", company="Mikas", first_name="Amina"),
			("CRM Lead", "LEAD-OTHER"): _Doc(name="LEAD-OTHER", company="Other", first_name="Other"),
			(
				"CRM Deal",
				"DEAL-MIKAS",
			): _Doc(
				name="DEAL-MIKAS",
				company="Mikas",
				organization="Mikas Shop",
				linked_customer="CUST-MIKAS",
			),
			("CRM Deal", "DEAL-OTHER"): _Doc(name="DEAL-OTHER", company="Other", organization="Other Shop"),
		}
		self.deleted: list[tuple[str, str]] = []
		self.created: list[_Doc] = []
		self.get_list_calls: list[tuple[str, dict]] = []

	def exists(self, doctype, name):
		if doctype == "Company":
			return name in {"Mikas", "Other"}
		if doctype == "Customer":
			return name == "CUST-MIKAS"
		return (doctype, name) in self.docs

	def get_value(self, doctype, name, field):
		doc = self.docs.get((doctype, name))
		return doc.get(field) if doc else None

	def sql(self, query, values=None, as_dict=False):
		if "tabSales Invoice" in query:
			if "SUM(outstanding_amount)" in query:
				return [("CUST-MIKAS", 100)]
			return [("CUST-MIKAS", 1, "2026-07-01", 100)]
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
	frappe.get_doc = lambda doctype, name: db.docs[(doctype, name)]
	frappe.new_doc = lambda doctype: _new_doc(db, doctype)
	frappe.get_all = lambda *_args, **_kwargs: []
	frappe.get_list = lambda doctype, **kwargs: _get_list(db, doctype, **kwargs)
	frappe.delete_doc = lambda doctype, name: db.deleted.append((doctype, name))
	frappe.clear_last_message = lambda: None

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.get_first_day = lambda _value: "2026-07-01"
	utils.getdate = lambda value: date.fromisoformat(str(value)[:10])
	utils.nowdate = lambda: "2026-07-29"
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


def _get_list(db: _FakeDB, doctype: str, **kwargs):
	db.get_list_calls.append((doctype, kwargs))
	fields = kwargs.get("fields", [])
	filters = kwargs.get("filters", {})
	if fields == ["count(name) as total"]:
		return [{"total": 1}]
	if doctype == "CRM Lead":
		return [db.docs[("CRM Lead", "LEAD-MIKAS")]] if filters.get("company") == "Mikas" else []
	if doctype == "CRM Deal":
		return [db.docs[("CRM Deal", "DEAL-MIKAS")]] if filters.get("company") == "Mikas" else []
	if doctype == "Customer":
		return [_Doc(name="CUST-MIKAS", creation="2026-07-01")]
	if doctype == "Sales Invoice":
		return []  # Current user has no invoice read permission.
	return []


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

	def test_public_crm_endpoints_reject_missing_selected_company(self):
		"""Removing a public company gate must fail instead of defaulting scope."""
		calls = (
			lambda: self.crm.list_leads(),
			lambda: self.crm.get_lead("LEAD-MIKAS"),
			lambda: self.crm.save_lead({"first_name": "Amina"}),
			lambda: self.crm.delete_lead("LEAD-MIKAS"),
			lambda: self.crm.list_deals(),
			lambda: self.crm.get_deal("DEAL-MIKAS"),
			lambda: self.crm.save_deal({"organization": "Mikas Shop"}),
			lambda: self.crm.delete_deal("DEAL-MIKAS"),
			lambda: self.crm.convert_deal_to_customer("DEAL-MIKAS"),
			lambda: self.crm.crm_meta(),
			lambda: self.crm.crm_metrics(),
			lambda: self.crm.crm_analytics(),
			lambda: self.crm.crm_report("2026-07-01", "2026-07-31"),
		)
		for call in calls:
			with self.assertRaisesRegex(ValueError, "Company is required"):
				call()

	def test_forbidden_selected_company_is_rejected(self):
		"""Removing allowed-company enforcement would expose the Other tenant."""
		with self.assertRaises(PermissionError):
			self.crm.list_deals("Other")

	def test_lists_only_return_selected_company_records_and_totals(self):
		"""Dropping a company filter or permission-aware count breaks this contract."""
		leads = self.crm.list_leads("Mikas")
		deals = self.crm.list_deals("Mikas")

		self.assertEqual([row["name"] for row in leads["leads"]], ["LEAD-MIKAS"])
		self.assertEqual(leads["total"], 1)
		self.assertEqual([row["name"] for row in deals["deals"]], ["DEAL-MIKAS"])
		self.assertEqual(deals["total"], 1)

	def test_invoice_permissions_hide_board_ar_and_report_sales(self):
		"""Switching invoice aggregates back to db.sql leaks the hidden 100 value."""
		board = self.crm.list_deals("Mikas")
		analytics = self.crm.crm_analytics("Mikas")
		report = self.crm.crm_report("2026-07-01", "2026-07-31", "Mikas")

		self.assertEqual(board["deals"][0]["ar_outstanding"], 0.0)
		self.assertEqual(analytics["lifetime_sales"], 0.0)
		self.assertEqual(report["summary"]["sales"], 0.0)
		self.assertGreaterEqual(sum(doctype == "Sales Invoice" for doctype, _ in self.db.get_list_calls), 3)

	def test_missing_invoice_doctype_read_returns_empty_aggregates(self):
		"""Propagating invoice read denial must not make CRM boards unusable."""
		original_get_list = self.crm.frappe.get_list
		self.crm.frappe.has_permission = lambda doctype, ptype, name=None: not (
			doctype == "Sales Invoice" and ptype == "read"
		)

		def get_list(doctype, **kwargs):
			if doctype == "Sales Invoice":
				raise PermissionError("Sales Invoice read denied")
			return original_get_list(doctype, **kwargs)

		self.crm.frappe.get_list = get_list
		board = self.crm.list_deals("Mikas")
		analytics = self.crm.crm_analytics("Mikas")
		report = self.crm.crm_report("2026-07-01", "2026-07-31", "Mikas")

		self.assertEqual(board["deals"][0]["ar_outstanding"], 0.0)
		self.assertEqual(analytics["lifetime_sales"], 0.0)
		self.assertEqual(report["summary"]["sales"], 0.0)

	def test_metrics_fetches_every_visible_deal(self):
		"""Removing the unbounded permission-aware fetch truncates the 25-deal KPI."""
		deals = [_Doc(status="Open", expected_monthly_volume=1, deal_value=0, needs_freezer=0, modified="2026-07-01")]
		deals *= 25

		def get_list(doctype, **kwargs):
			if doctype == "CRM Deal":
				return deals if kwargs.get("limit_page_length") == 0 else deals[:20]
			return []

		self.crm.frappe.get_list = get_list
		metrics = self.crm.crm_metrics("Mikas")

		self.assertEqual(metrics["deal_count"], 25)
		self.assertEqual(metrics["open_run_rate"], 25.0)

	def test_record_permissions_and_selected_company_protect_named_deal_endpoints(self):
		"""Removing record checks would allow get/save/delete/convert on DEAL-MIKAS."""
		self.crm.frappe.has_permission = lambda doctype, ptype, name=None: not (
			doctype == "CRM Deal" and name == "DEAL-MIKAS" and ptype in {"read", "write", "delete"}
		)
		for call in (
			lambda: self.crm.get_deal("DEAL-MIKAS", "Mikas"),
			lambda: self.crm.save_deal({"name": "DEAL-MIKAS", "organization": "Changed"}, "Mikas"),
			lambda: self.crm.delete_deal("DEAL-MIKAS", "Mikas"),
			lambda: self.crm.convert_deal_to_customer("DEAL-MIKAS", "Mikas"),
		):
			with self.assertRaises(PermissionError):
				call()

	def test_record_permissions_protect_named_lead_endpoints(self):
		"""Removing Lead permission checks would allow get/save/delete on LEAD-MIKAS."""
		self.crm.frappe.has_permission = lambda doctype, ptype, name=None: not (
			doctype == "CRM Lead" and name == "LEAD-MIKAS" and ptype in {"read", "write", "delete"}
		)
		for call in (
			lambda: self.crm.get_lead("LEAD-MIKAS", "Mikas"),
			lambda: self.crm.save_lead({"name": "LEAD-MIKAS", "first_name": "Changed"}, "Mikas"),
			lambda: self.crm.delete_lead("LEAD-MIKAS", "Mikas"),
		):
			with self.assertRaises(PermissionError):
				call()

	def test_stored_company_mismatch_denies_named_lead_and_deal_endpoints(self):
		"""Removing selected-company equality would operate on Other tenant records."""
		for call in (
			lambda: self.crm.get_lead("LEAD-OTHER", "Mikas"),
			lambda: self.crm.save_lead({"name": "LEAD-OTHER", "first_name": "Changed"}, "Mikas"),
			lambda: self.crm.delete_lead("LEAD-OTHER", "Mikas"),
			lambda: self.crm.get_deal("DEAL-OTHER", "Mikas"),
			lambda: self.crm.save_deal({"name": "DEAL-OTHER", "organization": "Changed"}, "Mikas"),
			lambda: self.crm.delete_deal("DEAL-OTHER", "Mikas"),
			lambda: self.crm.convert_deal_to_customer("DEAL-OTHER", "Mikas"),
		):
			with self.assertRaises(PermissionError):
				call()

	def test_update_keeps_server_owned_company_link_and_audit_fields(self):
		"""Allowing payload company/link/audit fields would overwrite stored state."""
		result = self.crm.save_deal(
			{
				"name": "DEAL-MIKAS",
				"organization": "Updated Mikas Shop",
				"company": "Other",
				"linked_customer": "CUST-OTHER",
				"owner": "attacker@example.com",
			},
			"Mikas",
		)

		self.assertEqual(result["organization"], "Updated Mikas Shop")
		self.assertEqual(result["company"], "Mikas")
		self.assertEqual(result["linked_customer"], "CUST-MIKAS")
		self.assertNotIn("owner", result)

	def test_lead_update_keeps_server_owned_company_and_audit_fields(self):
		"""Allowing Lead company or owner updates would overwrite stored state."""
		result = self.crm.save_lead(
			{
				"name": "LEAD-MIKAS",
				"first_name": "Updated Amina",
				"company": "Other",
				"owner": "attacker@example.com",
			},
			"Mikas",
		)

		self.assertEqual(result["first_name"], "Updated Amina")
		self.assertEqual(result["company"], "Mikas")
		self.assertNotIn("owner", result)


if __name__ == "__main__":
	unittest.main()
