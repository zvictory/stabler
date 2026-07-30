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
				name="LOT-ALLOWED",
				company="ACME",
				custom_parent_tender="TND-2026-00001",
				status="Open",
				custom_estimated_value=125,
			),
			("CRM Deal", "LOT-DENIED"): _Doc(
				name="LOT-DENIED",
				company="ACME",
				custom_parent_tender="TND-2026-00001",
				status="Won",
				custom_estimated_value=500,
			),
		}
		self.created: list[_Doc] = []
		self.last_filters: dict | None = None
		self.last_list_kwargs: dict | None = None

	def get_doc(self, doctype, name):
		return self.docs[(doctype, name)]

	def new_doc(self, doctype):
		doc = _Doc(doctype=doctype, name="TND-NEW")
		self.created.append(doc)
		return doc

	def get_list(self, doctype, **kwargs):
		filters = kwargs.get("filters", {})
		self.last_filters = filters
		self.last_list_kwargs = kwargs
		rows = [doc for (kind, _name), doc in self.docs.items() if kind == doctype]
		if isinstance(filters, dict):
			for field, value in filters.items():
				if value == ["is", "set"]:
					rows = [row for row in rows if row.get(field)]
				else:
					rows = [row for row in rows if row.get(field) == value]
		else:
			for field, operator, value in filters:
				if operator == "=":
					rows = [row for row in rows if row.get(field) == value]
				elif operator == "in":
					rows = [row for row in rows if row.get(field) in value]
				elif operator == "not in":
					rows = [row for row in rows if row.get(field) not in value]
		if kwargs.get("fields") == ["count(name) as total"]:
			return [{"total": len(rows)}]
		return rows


def _load_api(fake: _FakeFrappe, *, tender_allowed=True):
	for name in (
		"stabler.api.tender_master",
		"stabler.api.tender",
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.organization",
	):
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
	frappe.has_permission = lambda doctype, ptype="read", doc=None: (
		not (doctype == "CRM Deal" and getattr(doc, "name", doc) == "LOT-DENIED")
	)
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.now_datetime = lambda: "2026-07-01"
	utils.add_days = lambda value, days: f"{value}+{days}"
	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: (
		company or (_ for _ in ()).throw(ValueError("Company is required."))
	)
	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
	organization._user_allowed_companies = lambda _user: ["ACME"]
	tender = types.ModuleType("stabler.api.tender")
	tender._require_tender = lambda _company=None: (
		None if tender_allowed else (_ for _ in ()).throw(PermissionError("Not permitted"))
	)
	tender._dashboard_period = lambda _from_date=None, _to_date=None: ("2026-07-01", "2026-07-31")
	_default_intake = {
		"submitted_at": "2026-07-10",
		"submitted_by": "user",
		"result": "won",
		"result_at": "2026-07-11",
	}
	# LOT-A is the one deal-scoped test case that must NOT match the lifecycle
	# filters, so a per-deal override is needed instead of the shared constant.
	_intake_overrides = {"LOT-A": {"submitted_at": None, "submitted_by": None, "result": None, "result_at": None}}
	tender._read_intake = lambda deal: _intake_overrides.get(deal, _default_intake)
	tender._tender_event_dates = lambda _intake, _creation: {
		"identified": "2026-07-01",
		"submitted": "2026-07-10",
		"won": "2026-07-11",
	}
	tender._in_dashboard_period = lambda value, _start, _end: bool(value)
	tender._has_submission_evidence = lambda intake: bool(
		intake.get("submitted_at") and intake.get("submitted_by")
	)
	tender._deal_deadlines = lambda _deal, _company, _intake: {"risk": "risk"}
	frappe.get_roles = lambda _user=None: ["Sales User"]
	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.organization": organization,
			"stabler.api.tender": tender,
		}
	)
	return importlib.import_module("stabler.api.tender_master")


class TestTenderMasterApi(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)
		self.cross_company_deal = _Doc(
			name="DEAL-OTHER", company="Other Co", custom_parent_tender="TND-2026-00001"
		)

	def test_get_tender_master_rejects_cross_company_name(self):
		"""Removing the selected-company check would expose a named foreign tender."""
		with self.assertRaises(PermissionError):
			self.api.get_tender_master("TND-2026-00001", company="Other Co")

	def test_public_endpoints_reject_when_tender_module_is_unavailable(self):
		"""Removing the Tender module gate would expose its APIs to unavailable tenants."""
		api = _load_api(self.fake, tender_allowed=False)
		calls = (
			lambda: api.list_tender_masters(company="ACME"),
			lambda: api.get_tender_master("TND-2026-00001", company="ACME"),
			lambda: api.save_tender_master({"title": "Network tender"}, company="ACME"),
		)
		for call in calls:
			with self.assertRaises(PermissionError):
				call()

	def test_get_tender_master_returns_only_permitted_child_lots(self):
		"""Removing per-lot permission filtering would disclose an unreadable CRM Deal."""
		result = self.api.get_tender_master("TND-2026-00001", company="ACME")
		self.assertEqual([row["name"] for row in result["lots"]], ["LOT-ALLOWED"])
		self.assertEqual(
			result["summary"],
			{"lot_count": 1, "open_lot_count": 1, "estimated_total": 125.0, "currency": "USD"},
		)

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

	def test_list_filters_use_canonical_status_stage_risk_deadline_and_deal(self):
		"""Removing any filter would make dashboard drill-downs show a broader portfolio."""
		self.api.list_tender_masters(
			company="ACME",
			status="won",
			stage="submitted",
			risk="risk",
			deal="LOT-ALLOWED",
			from_date="2026-07-01",
			to_date="2026-07-31",
		)
		filters = self.fake.last_filters
		self.assertIn(["name", "in", ["TND-2026-00001"]], filters)
		self.assertIn(["name", "=", "TND-2026-00001"], filters)

	def test_list_deal_filter_rejects_unreadable_or_foreign_deals_before_resolving_parent(self):
		"""Checking a deal's parent before permission/company scope would leak Tender Master existence."""
		with self.assertRaises(PermissionError):
			self.api.list_tender_masters(company="ACME", deal="LOT-DENIED")
		self.fake.docs[("CRM Deal", "LOT-OTHER")] = self.cross_company_deal
		with self.assertRaises(PermissionError):
			self.api.list_tender_masters(company="ACME", deal="LOT-OTHER")

	def test_list_deal_filter_does_not_leak_sibling_lot_under_shared_parent(self):
		"""Skipping the deal-narrowing loop guard would let a sibling lot's lifecycle match leak the shared parent tender into a lot that does not itself qualify."""
		self.fake.docs[("CRM Deal", "LOT-A")] = _Doc(
			name="LOT-A",
			company="ACME",
			custom_parent_tender="TND-2026-00001",
			status="Open",
			custom_estimated_value=10,
		)
		self.fake.docs[("CRM Deal", "LOT-B")] = _Doc(
			name="LOT-B",
			company="ACME",
			custom_parent_tender="TND-2026-00001",
			status="Open",
			custom_estimated_value=20,
		)
		result = self.api.list_tender_masters(company="ACME", deal="LOT-A", stage="submitted")
		filters = self.fake.last_filters
		self.assertIn(["name", "in", ["__no_permitted_tender_master__"]], filters)
		self.assertEqual(result["records"], [])

	def test_list_deal_filter_checks_permission_before_scanning_deal_candidates(self):
		"""Scanning all qualifying CRM Deals before checking the requested deal's permission would run an unnecessary — and leaky — full-portfolio scan for a lot the caller cannot read."""
		with self.assertRaises(PermissionError):
			self.api.list_tender_masters(company="ACME", deal="LOT-DENIED", stage="submitted")
		self.assertIsNone(self.fake.last_filters)

	def test_list_filters_without_deal_preserve_all_qualifying_parents(self):
		"""Applying the deal-narrowing loop guard when no deal is selected would drop qualifying lots from the portfolio view."""
		self.fake.docs[("Tender Master", "TND-2026-00002")] = _Doc(
			name="TND-2026-00002", company="ACME", title="Second tender", currency="USD", status="New"
		)
		self.fake.docs[("CRM Deal", "LOT-C")] = _Doc(
			name="LOT-C",
			company="ACME",
			custom_parent_tender="TND-2026-00002",
			status="Open",
			custom_estimated_value=30,
		)
		self.api.list_tender_masters(company="ACME", stage="submitted")
		filters = self.fake.last_filters
		self.assertIn(["name", "in", ["TND-2026-00001", "TND-2026-00002"]], filters)


if __name__ == "__main__":
	unittest.main()
