"""Behaviour contracts for the tender sourcing RFQ endpoints (Faz 2 · Task 1).

Frappe-free: the module under test is imported against a double that models the
two things the real framework actually does differently — `get_all` ignores
permissions while `get_list` enforces them, and `has_permission` answers per
document. Every guard this file asserts is one an attacker (or an honest bug)
would otherwise walk straight through.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_sourcing_api -v
"""

from __future__ import annotations

import importlib
import json
import re
import types
import unittest
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from stabler.tests.module_sandbox import ModuleSandbox

_ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = _ROOT / "api" / "sourcing.py"
PATCH = _ROOT / "patches" / "v68_rfq_tender_deal.py"
PATCHES = _ROOT / "patches.txt"

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Doc(dict):
	def __getattr__(self, field):
		# Every real frappe Document carries `flags`; a double that answers None
		# turns "the controller was told this is the approval path" into an
		# AttributeError instead of a failed assertion.
		if field == "flags":
			return self.setdefault("_flags", types.SimpleNamespace())
		return self.get(field)

	def __setattr__(self, field, value):
		self[field] = value

	def as_dict(self):
		return dict(self)

	def append(self, field, row):
		"""Frappe's child-table append. Modelled because the RFQ carries two of
		them and a supplier list that never lands is the whole bug class here."""
		self.setdefault(field, []).append(dict(row))
		return row

	def set(self, field, value):
		"""Frappe's `set`. Editing a quotation must REPLACE its lines, not add a
		second copy beside them — the bug this models is a silently doubled
		quotation total, which is exactly the number the award is decided on."""
		self[field] = value
		return value

	def insert(self, **_kwargs):
		self["inserted"] = True
		self["name"] = self.get("name") or f"{self.get('doctype', 'DOC')[:3].upper()}-{id(self)}"
		if hasattr(self, "_fake") and self._fake:
			self._fake.docs[(self.get("doctype", "Communication"), self["name"])] = self
		return self

	def save(self):
		self["saved"] = True
		return self

	def submit(self):
		self["docstatus"] = 1
		return self


class _FakeFrappe:
	#: Rows this user may not read. `get_list` filters them out and
	#: `has_permission` denies them — the same source of truth for both, so a
	#: list guard and a single-document guard cannot disagree.
	unreadable: ClassVar[set[tuple[str, str]]] = {
		("CRM Deal", "LOT-DENIED"),
		("Supplier", "SUP-DENIED"),
	}

	def __init__(self):
		self.docs = {
			("Company", "ACME"): _Doc(name="ACME", abbr="ACME", company_name="ACME Corp"),
			# Warehouse resolution reads this table, NOT a Company field:
			# ERPNext's Company doctype has no `default_warehouse`, so modelling
			# one here would test a fiction.
			("Warehouse", "Stores - ACME"): _Doc(name="Stores - ACME", company="ACME", is_group=0),
			("Item", "RAIL-01"): _Doc(name="RAIL-01", is_stock_item=1, stock_uom="Nos"),
			("Item", "SERVICE-01"): _Doc(name="SERVICE-01", is_stock_item=0, stock_uom="Nos"),
			("CRM Deal", "LOT-A"): _Doc(
				name="LOT-A",
				company="ACME",
				deal_type="Tender",
				organization="Alfa Rail Lot",
				custom_tender_intake=json.dumps(
					{
						"items": [
							{
								"item_code": "RAIL-01",
								"item_name": "Rail 01",
								"qty": 10,
								"uom": "Nos",
								"rate": 2.5,
								"amount": 25.0,
							}
						]
					}
				),
			),
			("CRM Deal", "LOT-DENIED"): _Doc(name="LOT-DENIED", company="ACME", deal_type="Tender"),
			("CRM Deal", "LOT-OTHER"): _Doc(name="LOT-OTHER", company="Other Co", deal_type="Tender"),
			("Supplier", "SUP-A"): _Doc(name="SUP-A", supplier_name="Alfa"),
			("Supplier", "SUP-B"): _Doc(name="SUP-B", supplier_name="Beta"),
			("Supplier", "SUP-DENIED"): _Doc(name="SUP-DENIED", supplier_name="Gizli"),
			("Supplier Quotation", "SQ-DRAFT"): _Doc(
				name="SQ-DRAFT",
				company="ACME",
				supplier="SUP-A",
				currency="USD",
				custom_crm_deal="LOT-A",
				custom_rfq="RFQ-1",
				docstatus=0,
				items=[{"item_code": "RAIL-01", "qty": 5.0, "rate": 100.0}],
			),
			("Supplier Quotation", "SQ-PAST-DRAFT"): _Doc(
				name="SQ-PAST-DRAFT",
				company="ACME",
				supplier="SUP-A",
				currency="USD",
				custom_crm_deal="LOT-A",
				custom_rfq="RFQ-1",
				transaction_date="2026-07-01",
				docstatus=0,
				items=[{"item_code": "RAIL-01", "qty": 5.0, "rate": 100.0}],
			),
			("Supplier Quotation", "SQ-SUBMITTED"): _Doc(
				name="SQ-SUBMITTED",
				company="ACME",
				supplier="SUP-A",
				currency="USD",
				custom_crm_deal="LOT-A",
				custom_rfq="RFQ-1",
				docstatus=1,
			),
			("Supplier Quotation", "SQ-OTHER-COMPANY"): _Doc(
				name="SQ-OTHER-COMPANY",
				company="Other Co",
				supplier="SUP-A",
				currency="USD",
				custom_crm_deal="LOT-OTHER",
				docstatus=0,
			),
			("Supplier Quotation", "SQ-UNTAGGED"): _Doc(
				name="SQ-UNTAGGED",
				company="ACME",
				supplier="SUP-A",
				currency="USD",
				custom_crm_deal=None,
				docstatus=0,
			),
			("Supplier Quotation", "SQ-OTHER-LOT"): _Doc(
				name="SQ-OTHER-LOT",
				company="ACME",
				supplier="SUP-B",
				currency="USD",
				custom_crm_deal="LOT-B",
				docstatus=0,
			),
			("CRM Deal", "LOT-B"): _Doc(name="LOT-B", company="ACME", deal_type="Tender"),
			("CRM Deal", "LOT-C"): _Doc(name="LOT-C", company="ACME", deal_type="Tender"),
			("Tender Sourcing Decision", "TSD-DRAFT"): _Doc(
				name="TSD-DRAFT",
				company="ACME",
				deal="LOT-C",
				status="Draft",
				selected_quotation="SQ-DRAFT",
				selection_reason="Fits the deadline.",
			),
			("Tender Sourcing Decision", "TSD-APPROVED"): _Doc(
				name="TSD-APPROVED",
				company="ACME",
				deal="LOT-B",
				status="Approved",
				selected_quotation="SQ-OTHER-LOT",
				approved_by="dir@example.com",
			),
			("Tender Sourcing Decision", "TSD-OTHER-COMPANY"): _Doc(
				name="TSD-OTHER-COMPANY",
				company="Other Co",
				deal="LOT-OTHER",
				status="Draft",
			),
			("Request for Quotation", "RFQ-1"): _Doc(
				name="RFQ-1",
				company="ACME",
				custom_crm_deal="LOT-A",
				status="Draft",
				docstatus=0,
				transaction_date="2026-07-01",
				schedule_date="2026-07-05",
				suppliers=[
					{"supplier": "SUP-A", "supplier_name": "Alfa", "contact": "", "email_id": ""},
					{"supplier": "SUP-B", "supplier_name": "Beta", "contact": "", "email_id": ""},
				],
				items=[
					{
						"item_code": "RAIL-01",
						"item_name": "Rail 01",
						"qty": 10.0,
						"uom": "Nos",
						"warehouse": "Stores - ACME",
						"schedule_date": "2026-07-05",
						"description": "",
					}
				],
			),
			# Child rows counted by the list page: two suppliers were asked on
			# RFQ-1, none anywhere else. The counts query reads this table, not
			# the parent — modelling them only on the parent would test a fiction.
			("Request for Quotation Supplier", "RFQ1-SUP-A"): _Doc(
				parent="RFQ-1", parenttype="Request for Quotation", supplier="SUP-A"
			),
			("Request for Quotation Supplier", "RFQ1-SUP-B"): _Doc(
				parent="RFQ-1", parenttype="Request for Quotation", supplier="SUP-B"
			),
			("Request for Quotation", "RFQ-OTHER-COMPANY"): _Doc(
				name="RFQ-OTHER-COMPANY",
				company="Other Co",
				custom_crm_deal="LOT-OTHER",
				status="Draft",
				docstatus=0,
				transaction_date="2026-07-04",
			),
			("Request for Quotation", "RFQ-CANCELLED"): _Doc(
				name="RFQ-CANCELLED",
				company="ACME",
				custom_crm_deal="LOT-A",
				status="Cancelled",
				docstatus=2,
				transaction_date="2026-07-02",
			),
			("Request for Quotation", "RFQ-OTHER-LOT"): _Doc(
				name="RFQ-OTHER-LOT",
				company="ACME",
				custom_crm_deal="LOT-DENIED",
				status="Draft",
				docstatus=0,
				transaction_date="2026-07-03",
			),
		}
		self.created: list[_Doc] = []
		self.list_calls: list[str] = []
		self.last_filters: dict | None = None
		#: Every doctype a create-permission was demanded for.
		self.create_checks: list[str] = []
		#: Every doctype a submit-permission was demanded for.
		self.submit_checks: list[str] = []
		self.emails: list[dict] = []
		#: What `purchasing.tender_quotations` answers. Two bids from two
		#: countries — deliberately BELOW the five-quotation policy, so the
		#: exception rule is exercised by the default fixture rather than by a
		#: special case nobody remembers to write.
		self.quotation_rows = [
			{
				"name": "SQ-DRAFT",
				"supplier": "SUP-A",
				"supplier_name": "Alfa",
				"country": "Uzbekistan",
				"currency": "USD",
				"grand_total": 100.0,
				"base_total": 1200.0,
				"cheapest": True,
			},
			{
				"name": "SQ-SUBMITTED",
				"supplier": "SUP-B",
				"supplier_name": "Beta",
				"country": "China",
				"currency": "USD",
				"grand_total": 130.0,
				"base_total": 1560.0,
				"cheapest": False,
			},
		]

	def comparison(self, deal):
		# LOT-B teklifsiz: "award yok" hâli uydurma bir bayrakla değil, gerçekten
		# boş bir karşılaştırmayla sınansın.
		rows = [] if deal == "LOT-B" else list(self.quotation_rows)
		countries = {r["country"] for r in rows if r["country"]}
		return {
			"rows": rows,
			"base_currency": "UZS",
			"count": len(rows),
			"countries": len(countries),
			"has_min_5": len(rows) >= 5,
			"has_2_countries": len(countries) >= 2,
		}

	def get_doc(self, doctype, name):
		try:
			return self.docs[(doctype, name)]
		except KeyError:
			raise Exception(f"{doctype} {name} not found") from None

	def new_doc(self, doctype):
		doc = _Doc(doctype=doctype, _fake=self)
		self.created.append(doc)
		return doc

	def get_all(self, doctype, **kwargs):
		"""Unfiltered read, like the real `get_all`: ignores permissions."""
		return self._query(doctype, kwargs, permitted=False)

	def get_list(self, doctype, **kwargs):
		"""Permission-filtered read, like the real `get_list`."""
		return self._query(doctype, kwargs, permitted=True)

	def _query(self, doctype, kwargs, permitted):
		self.list_calls.append(doctype)
		filters = kwargs.get("filters", {})
		if doctype == "Request for Quotation":
			self.last_filters = filters
		rows = [doc for (kind, _name), doc in self.docs.items() if kind == doctype]
		if permitted:
			rows = [row for row in rows if (doctype, row["name"]) not in self.unreadable]
		for field, value in (filters or {}).items():
			if not isinstance(value, list):
				rows = [row for row in rows if row.get(field) == value]
				continue
			operator, operand = value
			if operator == "in":
				rows = [row for row in rows if row.get(field) in operand]
			elif operator == "<":
				rows = [row for row in rows if int(row.get(field) or 0) < operand]
			elif operator == "=":
				rows = [row for row in rows if row.get(field) == operand]
			elif operator == "like":
				needle = str(operand).strip("%")
				rows = [row for row in rows if needle.lower() in str(row.get(field) or "").lower()]
			else:
				raise AssertionError(f"unsupported filter operator: {operator}")
		return [dict(row) for row in rows]


def _load_api(
	fake: _FakeFrappe,
	*,
	tender_allowed=True,
	missing_columns=(),
	can_create=True,
	can_submit=True,
	views=("sourcing", "director"),
):
	_SANDBOX.evict(
		"stabler.api.sourcing",
		"stabler.api._common",
		"stabler.api.tender",
		"stabler.api.tender_master",
		"stabler.api.purchasing",
		"stabler.api.crm",
		"stabler.api.crm_email",
		"stabler.api.crm_automation",
		"stabler.api.crm_analytics",
		"stabler.api.organization",
		"frappe",
		"frappe.utils",
	)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.ValidationError = ValueError
	frappe.session = types.SimpleNamespace(user="sourcing@example.com")
	frappe.get_doc = fake.get_doc
	frappe.new_doc = fake.new_doc
	frappe.get_list = fake.get_list
	frappe.get_all = fake.get_all

	def _fake_get_value(doctype, name, field=None):
		if isinstance(name, dict):
			for (d_kind, _), doc in fake.docs.items():
				if d_kind == doctype and all(doc.get(k) == v for k, v in name.items()):
					return doc.get(field) if field else doc
			return None
		doc = fake.docs.get((doctype, name))
		if isinstance(doc, dict):
			return doc.get(field) if field else doc
		return None

	def _fake_set_value(doctype, name, field, value=None):
		if isinstance(field, dict):
			for k, v in field.items():
				_fake_set_value(doctype, name, k, v)
			return
		doc = fake.docs.get((doctype, name))
		if doc is not None:
			doc[field] = value

	def _fake_exists(doctype, name=None):
		# Warehouses are the one doctype whose *absence* is load-bearing: the
		# resolver provisions "Stores - <abbr>" when none exists, so a blanket
		# True would make that branch untestable and silently green.
		if doctype != "Warehouse":
			return True
		if isinstance(name, dict):
			return any(
				kind == "Warehouse" and all(doc.get(k) == v for k, v in name.items())
				for (kind, _), doc in fake.docs.items()
			)
		return ("Warehouse", name) in fake.docs

	frappe.db = types.SimpleNamespace(
		has_column=lambda _doctype, column: column not in missing_columns,
		exists=_fake_exists,
		get_value=_fake_get_value,
		set_value=_fake_set_value,
	)
	frappe.get_cached_value = frappe.db.get_value
	frappe.parse_json = lambda value: value
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.get_roles = lambda user=None: ["System Manager"]

	def _has_permission(doctype, ptype="read", doc=None):
		if ptype == "create":
			fake.create_checks.append(doctype)
			return can_create
		if ptype == "submit":
			# Submit is its own right in Frappe, not implied by write. A buyer who
			# may draft a quotation is not automatically allowed to freeze one into
			# the record the award is decided from.
			fake.submit_checks.append(doctype)
			return can_submit and (doctype, getattr(doc, "name", doc)) not in fake.unreadable
		return (doctype, getattr(doc, "name", doc)) not in fake.unreadable

	frappe.has_permission = _has_permission
	frappe.sendmail = lambda **kwargs: fake.emails.append(kwargs)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.cint = lambda value, default=0: int(value or default)
	utils.today = lambda: "2026-08-02"
	utils.nowdate = lambda: "2026-08-02"
	utils.getdate = lambda val=None: (
		datetime.strptime(str(val)[:10], "%Y-%m-%d").date() if val else datetime(2026, 8, 2).date()
	)
	utils.date_diff = lambda d1, d2: (utils.getdate(d1) - utils.getdate(d2)).days

	utils.now_datetime = lambda: datetime(2026, 8, 2, 10, 0, 0)

	tender = types.ModuleType("stabler.api.tender")
	tender._require_tender = lambda _company=None: (
		None if tender_allowed else (_ for _ in ()).throw(PermissionError("Not permitted"))
	)
	# Two separate windows on purpose: sourcing writes the award, a director
	# approves it. A test double that treats them as one role could not fail the
	# separation-of-duties rule, which is the only reason the split exists.
	tender._require_tender_view = lambda view, company: (
		None if view in views else (_ for _ in ()).throw(PermissionError("Not permitted"))
	)

	purchasing = types.ModuleType("stabler.api.purchasing")
	purchasing.tender_quotations = lambda deal: fake.comparison(deal)

	tender_master = types.ModuleType("stabler.api.tender_master")

	def _require_selected_company(company):
		if not company:
			raise ValueError("Company is required.")
		if company != "ACME":
			raise PermissionError(f"Not permitted for company {company}")
		return company

	tender_master.require_selected_company = _require_selected_company

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api.tender": tender,
			"stabler.api.tender_master": tender_master,
			"stabler.api.purchasing": purchasing,
		}
	)
	return importlib.import_module("stabler.api.sourcing")


class TestRfqGates(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_endpoints_reject_when_the_tender_module_is_unavailable(self):
		"""Both endpoints must ask the module gate BEFORE touching a record.

		Six of the seven tenants carry CRM Deal for ordinary sales. Without this
		gate, `create_rfq` would let any of them write purchase documents through
		a tender endpoint they never enabled.
		"""
		api = _load_api(self.fake, tender_allowed=False)
		for call in (
			lambda: api.list_rfqs("LOT-A", company="ACME"),
			lambda: api.create_rfq("LOT-A", ["SUP-A"], [{"item_code": "IT", "qty": 1}], company="ACME"),
		):
			with self.subTest(call=call), self.assertRaises(PermissionError):
				call()

	def test_endpoints_reject_a_deal_from_another_company(self):
		"""Tenant isolation: the deal name alone must not select the scope."""
		for call in (
			lambda: self.api.list_rfqs("LOT-OTHER", company="ACME"),
			lambda: self.api.create_rfq(
				"LOT-OTHER", ["SUP-A"], [{"item_code": "IT", "qty": 1}], company="ACME"
			),
		):
			with self.subTest(call=call), self.assertRaises(PermissionError):
				call()

	def test_endpoints_reject_a_company_the_user_may_not_select(self):
		with self.assertRaises(PermissionError):
			self.api.list_rfqs("LOT-A", company="Other Co")

	def test_endpoints_reject_a_deal_the_user_may_not_read(self):
		"""Record permission, not just company. `LOT-DENIED` is in ACME."""
		with self.assertRaises(PermissionError):
			self.api.list_rfqs("LOT-DENIED", company="ACME")

	def test_company_is_required_and_never_inferred(self):
		with self.assertRaises(ValueError):
			self.api.list_rfqs("LOT-A")


class TestListRfqs(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_returns_only_the_rfqs_of_that_lot(self):
		result = self.api.list_rfqs("LOT-A", company="ACME")
		self.assertEqual([row["name"] for row in result["rows"]], ["RFQ-1"])
		self.assertEqual(result["count"], 1)

	def test_cancelled_rfqs_are_excluded(self):
		"""A cancelled RFQ is not an open request — counting it would inflate the
		"we asked N suppliers" story the policy badge tells."""
		self.api.list_rfqs("LOT-A", company="ACME")
		self.assertEqual(self.fake.last_filters.get("docstatus"), ["<", 2])

	def test_reads_through_the_permission_filtered_query(self):
		"""`get_all` would leak RFQs of lots this user may not see."""
		self.api.list_rfqs("LOT-A", company="ACME")
		self.assertIn("Request for Quotation", self.fake.list_calls)
		api_source = API_SOURCE.read_text()
		self.assertNotIn('frappe.get_all(\n\t\t"Request for Quotation"', api_source)

	def test_returns_empty_before_the_patch_has_run(self):
		"""Pre-migrate the column does not exist. Reading it would 500 the page;
		mirroring `tender_quotations`, an unmigrated site reports "no RFQs"."""
		api = _load_api(self.fake, missing_columns=("custom_crm_deal",))
		self.assertEqual(api.list_rfqs("LOT-A", company="ACME"), {"rows": [], "count": 0})


class TestCreateRfq(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def _create(self, **overrides):
		payload = {
			"deal": "LOT-A",
			"suppliers": ["SUP-A", "SUP-B"],
			"items": [{"item_code": "RAIL-01", "qty": 10}],
			"schedule_date": "2026-08-20",
			"company": "ACME",
		}
		payload.update(overrides)
		return self.api.create_rfq(**payload)

	def test_the_rfq_carries_the_lot_and_the_selected_company(self):
		"""Without the tag the request is invisible to every sourcing screen —
		the exact gap this task closes."""
		self._create()
		doc = self.fake.created[-1]
		self.assertEqual(doc["doctype"], "Request for Quotation")
		self.assertEqual(doc["custom_crm_deal"], "LOT-A")
		self.assertEqual(doc["company"], "ACME")
		self.assertTrue(doc.get("inserted"))

	def test_suppliers_and_items_land_as_child_rows(self):
		self._create()
		doc = self.fake.created[-1]
		self.assertEqual([row["supplier"] for row in doc["suppliers"]], ["SUP-A", "SUP-B"])
		self.assertEqual(doc["items"][0]["item_code"], "RAIL-01")
		self.assertEqual(doc["items"][0]["qty"], 10.0)

	def test_stock_item_rfq_resolves_company_default_warehouse(self):
		self._create(items=[{"item_code": "RAIL-01", "qty": 5}])
		doc = self.fake.created[-1]
		self.assertIsNone(doc.get("set_warehouse"))
		self.assertEqual(doc["items"][0].get("warehouse"), "Stores - ACME")

	def test_explicit_warehouse_overrides_company_default(self):
		self._create(items=[{"item_code": "RAIL-01", "qty": 5}], warehouse="Stores - ACME")
		doc = self.fake.created[-1]
		self.assertEqual(doc["items"][0].get("warehouse"), "Stores - ACME")

	def test_company_without_any_warehouse_gets_one_provisioned(self):
		# A brand-new tenant has no Warehouse rows yet. Blocking the first RFQ
		# on "go configure a warehouse" strands the user on a screen that
		# cannot tell them where to go, so the resolver provisions Stores
		# instead. Losing that means day-one onboarding dead-ends.
		del self.fake.docs[("Warehouse", "Stores - ACME")]
		self._create(items=[{"item_code": "RAIL-01", "qty": 5}])
		provisioned = [d for d in self.fake.created if d.get("doctype") == "Warehouse"]
		self.assertEqual(len(provisioned), 1)
		self.assertEqual(provisioned[0].get("company"), "ACME")
		self.assertEqual(provisioned[0].get("warehouse_name"), "Stores")
		self.assertEqual(self.fake.created[-1]["items"][0].get("warehouse"), provisioned[0]["name"])

	def test_service_only_rfq_saves_without_a_configured_warehouse(self):
		# A service line stores nothing, so warehouse configuration must never
		# be what stands between the user and sending the request.
		del self.fake.docs[("Warehouse", "Stores - ACME")]
		res = self._create(items=[{"item_code": "SERVICE-01", "qty": 1}])
		self.assertTrue(res.get("name"))

	def test_rfq_item_uom_and_stock_uom_populated_from_item(self):
		self._create(items=[{"item_code": "RAIL-01", "qty": 5}])
		item_row = self.fake.created[-1]["items"][0]
		self.assertEqual(item_row.get("stock_uom"), "Nos")
		self.assertEqual(item_row.get("uom"), "Nos")

	def test_rfq_item_conversion_factor_is_one_when_uom_matches_stock_uom(self):
		self._create(items=[{"item_code": "RAIL-01", "qty": 5}])
		item_row = self.fake.created[-1]["items"][0]
		self.assertEqual(item_row.get("conversion_factor"), 1.0)

	def test_rfq_item_empty_schedule_date_uses_header_or_today(self):
		self._create(items=[{"item_code": "RAIL-01", "qty": 5}], schedule_date="2026-08-20")
		item_row = self.fake.created[-1]["items"][0]
		self.assertEqual(item_row.get("schedule_date"), "2026-08-20")

		self._create(items=[{"item_code": "RAIL-01", "qty": 5}], schedule_date=None)
		item_row_today = self.fake.created[-1]["items"][0]
		self.assertTrue(item_row_today.get("schedule_date"))

	def test_rfq_item_explicit_schedule_date_is_preserved(self):
		self._create(
			items=[{"item_code": "RAIL-01", "qty": 5, "schedule_date": "2026-09-01"}],
			schedule_date="2026-08-20",
		)
		item_row = self.fake.created[-1]["items"][0]
		self.assertEqual(item_row.get("schedule_date"), "2026-09-01")

	def test_the_rfq_stays_a_draft_and_sends_no_email(self):
		"""This slice creates the request; contacting the supplier stays a human
		act (plan: "NO email sending in this slice")."""
		self._create()
		doc = self.fake.created[-1]
		self.assertNotEqual(doc.get("docstatus"), 1)
		self.assertEqual(self.fake.emails, [])

	def test_a_supplier_the_user_may_not_read_is_refused(self):
		"""Permission-filtered supplier read, not a bare existence check."""
		with self.assertRaises(PermissionError):
			self._create(suppliers=["SUP-A", "SUP-DENIED"])
		self.assertEqual(self.fake.created, [])

	def test_an_unknown_supplier_is_refused(self):
		with self.assertRaises(PermissionError):
			self._create(suppliers=["SUP-A", "SUP-GHOST"])

	def test_at_least_one_supplier_and_one_item_are_required(self):
		"""An RFQ with no supplier asks nobody; with no item it asks for nothing.
		Both would still satisfy a naive "an RFQ exists" policy count."""
		with self.assertRaises(ValueError):
			self._create(suppliers=[])
		with self.assertRaises(ValueError):
			self._create(items=[])

	def test_a_non_positive_quantity_is_refused(self):
		with self.assertRaises(ValueError):
			self._create(items=[{"item_code": "RAIL-01", "qty": 0}])

	def test_an_item_without_a_code_is_refused(self):
		with self.assertRaises(ValueError):
			self._create(items=[{"item_code": "", "qty": 5}])

	def test_create_permission_on_the_rfq_doctype_is_demanded(self):
		self.api = _load_api(self.fake, can_create=False)
		with self.assertRaises(self.api.frappe.PermissionError):
			self._create()


class TestRfqDefaultsEndpoint(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_get_deal_rfq_defaults_returns_company_scoped_defaults(self):
		res = self.api.get_deal_rfq_defaults("LOT-A", company="ACME")
		self.assertIn("items", res)
		self.assertIn("suppliers", res)
		self.assertEqual(res["deal"], "LOT-A")
		self.assertEqual(res["company"], "ACME")

	def test_defaults_come_from_the_tender_intake_not_from_a_dead_field(self):
		"""The whole point of this slice: a lot that reached sourcing was
		already specified line by line at intake, and the RFQ form must open
		with exactly those lines. The old body read child tables CRM Deal never
		had, so the answer was always empty."""
		res = self.api.get_deal_rfq_defaults("LOT-A", company="ACME")
		self.assertEqual(len(res["items"]), 1)
		line = res["items"][0]
		self.assertEqual(line["item_code"], "RAIL-01")
		self.assertEqual(line["item_name"], "Rail 01")
		self.assertEqual(line["qty"], 10.0)
		self.assertEqual(line["uom"], "Nos")
		self.assertEqual(line["rate"], 2.5)
		self.assertEqual(res["deal_label"], "Alfa Rail Lot")

	def test_suppliers_are_never_prefilled(self):
		"""The policy wants >=5 quotations from >=2 countries — a deliberate
		choice per request, not whatever a table happens to contain."""
		res = self.api.get_deal_rfq_defaults("LOT-A", company="ACME")
		self.assertEqual(res["suppliers"], [])

	def test_a_lot_without_intake_lines_defaults_to_no_lines(self):
		res = self.api.get_deal_rfq_defaults("LOT-B", company="ACME")
		self.assertEqual(res["items"], [])

	def test_get_deal_rfq_defaults_rejects_unauthorized_deal(self):
		with self.assertRaises(self.api.frappe.PermissionError):
			self.api.get_deal_rfq_defaults("LOT-DENIED", company="ACME")

	def test_get_deal_rfq_defaults_rejects_foreign_company_deal(self):
		with self.assertRaises(self.api.frappe.PermissionError):
			self.api.get_deal_rfq_defaults("LOT-OTHER", company="ACME")

	def test_creating_before_the_patch_has_run_fails_loudly(self):
		"""Reading tolerates an unmigrated site; WRITING must not — an untagged
		RFQ is worse than no RFQ, because nothing will ever find it again."""
		api = _load_api(self.fake, missing_columns=("custom_crm_deal",))
		with self.assertRaises(Exception) as ctx:
			api.create_rfq("LOT-A", ["SUP-A"], [{"item_code": "RAIL-01", "qty": 1}], company="ACME")
		self.assertIn("migrate", str(ctx.exception).lower())
		self.assertEqual(self.fake.created, [])


class TestListAllRfqs(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_lists_only_this_company_open_rfqs(self):
		"""The list page answers 'whom did we ask' company-wide; a foreign
		company's RFQ or a cancelled one must not be in it."""
		res = self.api.list_all_rfqs(company="ACME")
		names = [row["name"] for row in res["rows"]]
		self.assertIn("RFQ-1", names)
		self.assertIn("RFQ-OTHER-LOT", names)
		self.assertNotIn("RFQ-OTHER-COMPANY", names)
		self.assertNotIn("RFQ-CANCELLED", names)

	def test_rows_carry_the_two_policy_numbers(self):
		"""Supplier count from the RFQ's own child table; quotation count from
		the lot's answers. These are the numbers the >=5/>=2 policy is argued
		with, so they may not be guessed client-side."""
		res = self.api.list_all_rfqs(company="ACME")
		by_name = {row["name"]: row for row in res["rows"]}
		self.assertEqual(by_name["RFQ-1"]["supplier_count"], 2)
		self.assertEqual(by_name["RFQ-1"]["quotation_count"], 3)  # 2 drafts + 1 submitted on LOT-A
		self.assertEqual(by_name["RFQ-1"]["deal_label"], "Alfa Rail Lot")

	def test_deal_filter_narrows_to_one_lot(self):
		res = self.api.list_all_rfqs(company="ACME", deal="LOT-A")
		self.assertEqual([row["name"] for row in res["rows"]], ["RFQ-1"])

	def test_search_matches_the_document_name(self):
		res = self.api.list_all_rfqs(company="ACME", search="RFQ-1")
		self.assertEqual([row["name"] for row in res["rows"]], ["RFQ-1"])

	def test_reads_through_the_permission_filtered_query(self):
		self.api.list_all_rfqs(company="ACME")
		self.assertIn("Request for Quotation", self.fake.list_calls)

	def test_rejects_when_the_tender_module_is_unavailable(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.list_all_rfqs(company="ACME")

	def test_rejects_a_company_the_user_may_not_select(self):
		with self.assertRaises(PermissionError):
			self.api.list_all_rfqs(company="Other Co")

	def test_returns_empty_before_the_patch_has_run(self):
		api = _load_api(self.fake, missing_columns=("custom_crm_deal",))
		self.assertEqual(api.list_all_rfqs(company="ACME"), {"rows": [], "count": 0})


class TestGetRfq(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_answers_whom_we_asked_and_who_answered(self):
		"""SUP-A has quotations on this lot, SUP-B does not: the per-supplier
		response status is exactly what the ERPNext Desk 'Received' row state
		encodes, and what the award audit later relies on."""
		res = self.api.get_rfq("RFQ-1", company="ACME")
		by_supplier = {row["supplier"]: row for row in res["suppliers"]}
		self.assertTrue(by_supplier["SUP-A"]["responded"])
		self.assertEqual(by_supplier["SUP-A"]["quotations"], ["SQ-DRAFT", "SQ-PAST-DRAFT", "SQ-SUBMITTED"])
		self.assertFalse(by_supplier["SUP-B"]["responded"])

	def test_lines_carry_the_intake_target_rate_as_a_reference(self):
		"""The RFQ doctype has no rate; the intake estimate is joined back by
		item code so the officer sees the tender's expectation next to the ask."""
		res = self.api.get_rfq("RFQ-1", company="ACME")
		self.assertEqual(len(res["items"]), 1)
		self.assertEqual(res["items"][0]["item_code"], "RAIL-01")
		self.assertEqual(res["items"][0]["target_rate"], 2.5)

	def test_rejects_an_rfq_of_another_company(self):
		with self.assertRaises(PermissionError):
			self.api.get_rfq("RFQ-OTHER-COMPANY", company="ACME")

	def test_rejects_when_the_tender_module_is_unavailable(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.get_rfq("RFQ-1", company="ACME")


class TestRfqPrint(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_print_payload_extends_the_detail_with_the_company_letterhead(self):
		res = self.api.rfq_print("RFQ-1", company="ACME")
		self.assertEqual(res["name"], "RFQ-1")
		self.assertEqual(res["company_name"], "ACME Corp")
		self.assertEqual(res["company_abbr"], "ACME")
		self.assertEqual(len(res["items"]), 1)

	def test_rejects_an_rfq_of_another_company(self):
		with self.assertRaises(PermissionError):
			self.api.rfq_print("RFQ-OTHER-COMPANY", company="ACME")


class TestMarkRfqSent(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_records_a_communication_on_the_rfq(self):
		"""Stabler does not email anything; the human act of handing the RF
		Q over is still a business fact. It is logged on the same record type
		the CRM email trail uses, referenced to this RFQ."""
		res = self.api.mark_rfq_sent("RFQ-1", company="ACME", channel="whatsapp")
		comm = next(d for d in self.fake.created if d.get("doctype") == "Communication")
		self.assertEqual(comm["reference_doctype"], "Request for Quotation")
		self.assertEqual(comm["reference_name"], "RFQ-1")
		self.assertEqual(comm["company"], "ACME")
		self.assertEqual(comm["sent_or_received"], "Sent")
		self.assertEqual(res["channel"], "whatsapp")

	def test_an_unknown_channel_is_rejected_before_anything_is_written(self):
		with self.assertRaises(ValueError):
			self.api.mark_rfq_sent("RFQ-1", company="ACME", channel="pigeon")
		self.assertFalse(any(d.get("doctype") == "Communication" for d in self.fake.created))

	def test_requires_the_communication_create_right(self):
		api = _load_api(self.fake, can_create=False)
		with self.assertRaises(PermissionError):
			api.mark_rfq_sent("RFQ-1", company="ACME", channel="email")
		self.assertFalse(any(d.get("doctype") == "Communication" for d in self.fake.created))

	def test_rejects_an_rfq_of_another_company(self):
		with self.assertRaises(PermissionError):
			self.api.mark_rfq_sent("RFQ-OTHER-COMPANY", company="ACME", channel="email")


class TestRfqPatch(unittest.TestCase):
	def test_the_patch_is_registered_and_idempotent(self):
		source = PATCH.read_text()
		self.assertIn('"custom_crm_deal"', source)
		self.assertIn('"options": "CRM Deal"', source)
		self.assertIn('"Request for Quotation"', source)
		# Double-run safety. `patches.txt` has no `[post_model_sync]` marker, so a
		# patch runs on every migrate until it is re-registered; without the guard
		# the second run raises DuplicateEntryError and aborts the whole migrate.
		self.assertIn('frappe.db.exists("Custom Field"', source)
		self.assertIn("stabler.patches.v68_rfq_tender_deal", PATCHES.read_text().split())

	def test_the_patch_returns_early_when_the_doctype_is_absent(self):
		"""Four of the seven sites do not carry the tender/purchase stack. A patch
		that assumes ERPNext's RFQ doctype exists aborts migrate there."""
		source = PATCH.read_text()
		self.assertRegex(source, r'if not frappe\.db\.exists\(\s*"DocType",\s*"Request for Quotation"')

	def test_the_patch_number_is_not_already_taken(self):
		"""v62 was free when the plan was written and is not any more. A reused
		number silently never runs — `patches.txt` dedupes on the module path."""
		registered = [line.strip() for line in PATCHES.read_text().splitlines() if line.strip()]
		numbers = [m.group(1) for line in registered if (m := re.search(r"\.(v\d+)_", line))]
		self.assertEqual(len(numbers), len(set(numbers)), "patches.txt carries a duplicate version")


class TestSaveSupplierQuotation(unittest.TestCase):
	"""Entering the answer, in the SPA, without a trip to the Desk.

	Until now a Supplier Quotation had to be created somewhere else and tagged to
	the lot by hand — and "somewhere else" meant the Frappe Desk, which this
	project forbids linking to. The gap was not cosmetic: an untagged quotation is
	invisible to the 5-quotations / 2-countries policy count, so the badge that
	says a lot is ready to price could be green on an empty quote set.
	"""

	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def _save(self, **overrides):
		payload = {
			"deal": "LOT-A",
			"supplier": "SUP-A",
			"currency": "USD",
			"items": [{"item_code": "RAIL-01", "qty": 10, "rate": 12.5}],
			"valid_till": "2026-09-01",
			"company": "ACME",
		}
		payload.update(overrides)
		return self.api.save_supplier_quotation(**payload)

	def test_the_quotation_is_tagged_to_the_lot_and_the_selected_company(self):
		self._save()
		doc = self.fake.created[-1]
		self.assertEqual(doc["doctype"], "Supplier Quotation")
		self.assertEqual(doc["custom_crm_deal"], "LOT-A")
		self.assertEqual(doc["company"], "ACME")
		self.assertEqual(doc["supplier"], "SUP-A")
		self.assertEqual(doc["currency"], "USD")
		self.assertEqual(doc["valid_till"], "2026-09-01")
		self.assertTrue(doc.get("inserted"))

	def test_saving_never_submits(self):
		"""Draft and submitted are different facts for the policy count, so the
		two must stay two calls. A save that submitted would make "5 quotations
		collected" unfalsifiable — every draft would count as a firm offer."""
		self._save()
		self.assertNotEqual(self.fake.created[-1].get("docstatus"), 1)

	def test_lines_carry_item_qty_and_rate(self):
		self._save()
		line = self.fake.created[-1]["items"][0]
		self.assertEqual(line["item_code"], "RAIL-01")
		self.assertEqual(line["qty"], 10.0)
		self.assertEqual(line["rate"], 12.5)

	def test_a_zero_rate_is_allowed_but_a_negative_one_is_not(self):
		"""Zero is a real quote — an included line, a sample, freight the vendor
		absorbs. Negative is data entry damage that would drag the comparison
		total below every honest bid and win the award."""
		self._save(items=[{"item_code": "RAIL-01", "qty": 1, "rate": 0}])
		self.assertEqual(self.fake.created[-1]["items"][0]["rate"], 0.0)
		with self.assertRaises(ValueError):
			self._save(items=[{"item_code": "RAIL-01", "qty": 1, "rate": -1}])

	def test_quantity_item_and_line_count_are_validated(self):
		with self.assertRaises(ValueError):
			self._save(items=[{"item_code": "RAIL-01", "qty": 0, "rate": 5}])
		with self.assertRaises(ValueError):
			self._save(items=[{"item_code": "", "qty": 1, "rate": 5}])
		with self.assertRaises(ValueError):
			self._save(items=[])

	def test_a_supplier_the_user_may_not_read_is_refused(self):
		before = len(self.fake.created)
		with self.assertRaises(PermissionError):
			self._save(supplier="SUP-DENIED")
		self.assertEqual(len(self.fake.created), before)

	def test_a_currency_is_required(self):
		"""The comparison is done in company currency via `base_grand_total`; a
		quotation with no currency of its own has no honest conversion."""
		with self.assertRaises(ValueError):
			self._save(currency="")

	def test_gates_are_enforced(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.save_supplier_quotation(
				deal="LOT-A",
				supplier="SUP-A",
				currency="USD",
				items=[{"item_code": "RAIL-01", "qty": 1, "rate": 1}],
				company="ACME",
			)
		with self.assertRaises(PermissionError):
			self._save(deal="LOT-OTHER")
		with self.assertRaises(PermissionError):
			self._save(company="Other Co")
		with self.assertRaises(PermissionError):
			self._save(deal="LOT-DENIED")

	def test_create_permission_on_the_quotation_doctype_is_demanded(self):
		self._save()
		self.assertIn("Supplier Quotation", self.fake.create_checks)
		api = _load_api(self.fake, can_create=False)
		with self.assertRaises(PermissionError):
			api.save_supplier_quotation(
				deal="LOT-A",
				supplier="SUP-A",
				currency="USD",
				items=[{"item_code": "RAIL-01", "qty": 1, "rate": 1}],
				company="ACME",
			)

	def test_saved_quotation_has_warehouse_from_company_default(self):
		res = self._save(items=[{"item_code": "RAIL-01", "qty": 1, "rate": 10}])
		doc = next(d for d in self.fake.created if d.get("name") == res["name"])
		self.assertIsNone(doc.get("set_warehouse"))
		self.assertEqual(doc["items"][0].get("warehouse"), "Stores - ACME")

	def test_quotation_for_company_without_any_warehouse_gets_one_provisioned(self):
		# Same day-one guarantee as the RFQ side: a supplier's price must be
		# recordable before anyone has set up a warehouse.
		del self.fake.docs[("Warehouse", "Stores - ACME")]
		res = self._save(items=[{"item_code": "RAIL-01", "qty": 1, "rate": 10}])
		provisioned = [d for d in self.fake.created if d.get("doctype") == "Warehouse"]
		self.assertEqual(len(provisioned), 1)
		self.assertEqual(provisioned[0].get("company"), "ACME")
		doc = next(d for d in self.fake.created if d.get("name") == res["name"])
		self.assertEqual(doc["items"][0].get("warehouse"), provisioned[0]["name"])

	def test_explicit_warehouse_overrides_company_default(self):
		res = self._save(
			items=[{"item_code": "RAIL-01", "qty": 1, "rate": 10}],
			warehouse="Stores - ACME",
		)
		doc = next(d for d in self.fake.created if d.get("name") == res["name"])
		self.assertEqual(doc["items"][0].get("warehouse"), "Stores - ACME")

	def test_valid_till_before_transaction_date_throws_our_error(self):
		with self.assertRaises(ValueError) as ctx:
			self._save(valid_till="2026-01-01")
		self.assertIn("cannot be before transaction date", str(ctx.exception))

	def test_valid_till_equal_or_after_transaction_date_is_valid(self):
		res = self._save(valid_till="2026-08-02")
		self.assertTrue(res.get("name"))
		res2 = self._save(valid_till="2026-09-01")
		self.assertTrue(res2.get("name"))

	def test_empty_valid_till_is_valid(self):
		res = self._save(valid_till=None)
		self.assertTrue(res.get("name"))

	def test_edit_quotation_compares_against_document_transaction_date_not_today(self):
		# SQ-PAST-DRAFT has transaction_date 2026-07-01. Setting valid_till to 2026-07-15
		# (before today 2026-08-02 but after transaction_date) must succeed.
		res = self.api.save_supplier_quotation(
			name="SQ-PAST-DRAFT",
			deal="LOT-A",
			supplier="SUP-A",
			currency="USD",
			valid_till="2026-07-15",
			company="ACME",
			items=[{"item_code": "RAIL-01", "qty": 1, "rate": 10}],
		)
		self.assertEqual(res["name"], "SQ-PAST-DRAFT")

	def test_saving_before_the_patch_has_run_fails_loudly(self):
		api = _load_api(self.fake, missing_columns=("custom_crm_deal",))
		with self.assertRaises(Exception) as ctx:
			api.save_supplier_quotation(
				deal="LOT-A",
				supplier="SUP-A",
				currency="USD",
				items=[{"item_code": "RAIL-01", "qty": 1, "rate": 1}],
				company="ACME",
			)
		self.assertIn("migrate", str(ctx.exception).lower())


class TestEditSupplierQuotation(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def _edit(self, name, **overrides):
		payload = {
			"deal": "LOT-A",
			"supplier": "SUP-A",
			"currency": "EUR",
			"items": [{"item_code": "RAIL-02", "qty": 3, "rate": 7.0}],
			"company": "ACME",
			"name": name,
		}
		payload.update(overrides)
		return self.api.save_supplier_quotation(**payload)

	def test_editing_replaces_the_lines_instead_of_appending(self):
		"""Appending would double the total the award is decided on."""
		self._edit("SQ-DRAFT")
		doc = self.fake.docs[("Supplier Quotation", "SQ-DRAFT")]
		self.assertEqual([line["item_code"] for line in doc["items"]], ["RAIL-02"])
		self.assertTrue(doc.get("saved"))
		self.assertNotIn("inserted", doc)

	def test_a_submitted_quotation_cannot_be_edited(self):
		"""Submitted is the record the comparison already used. Rewriting it in
		place would change a decided number with no trace."""
		with self.assertRaises(Exception) as ctx:
			self._edit("SQ-SUBMITTED")
		self.assertNotIsInstance(ctx.exception, PermissionError)

	def test_a_quotation_of_another_lot_cannot_be_reassigned(self):
		"""Passing someone else's SQ name with your own deal would move a rival
		bid onto your lot."""
		with self.assertRaises(Exception):
			self._edit("SQ-OTHER-LOT")

	def test_a_quotation_of_another_company_is_refused(self):
		with self.assertRaises(PermissionError):
			self._edit("SQ-OTHER-COMPANY", deal="LOT-A")


class TestSubmitSupplierQuotation(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_a_draft_is_submitted(self):
		result = self.api.submit_supplier_quotation("SQ-DRAFT", company="ACME")
		self.assertEqual(self.fake.docs[("Supplier Quotation", "SQ-DRAFT")]["docstatus"], 1)
		self.assertEqual(result["docstatus"], 1)

	def test_submit_permission_is_its_own_right(self):
		self.api.submit_supplier_quotation("SQ-DRAFT", company="ACME")
		self.assertIn("Supplier Quotation", self.fake.submit_checks)
		fake = _FakeFrappe()
		api = _load_api(fake, can_submit=False)
		with self.assertRaises(PermissionError):
			api.submit_supplier_quotation("SQ-DRAFT", company="ACME")
		self.assertEqual(fake.docs[("Supplier Quotation", "SQ-DRAFT")]["docstatus"], 0)

	def test_an_already_submitted_quotation_is_refused(self):
		with self.assertRaises(Exception):
			self.api.submit_supplier_quotation("SQ-SUBMITTED", company="ACME")

	def test_a_quotation_with_no_lot_is_not_a_tender_quotation(self):
		"""The endpoint is module-gated; letting it submit an untagged SQ would
		make it a general-purpose purchase submit button for tender roles."""
		with self.assertRaises(Exception):
			self.api.submit_supplier_quotation("SQ-UNTAGGED", company="ACME")

	def test_gates_are_enforced(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.submit_supplier_quotation("SQ-DRAFT", company="ACME")
		with self.assertRaises(PermissionError):
			self.api.submit_supplier_quotation("SQ-OTHER-COMPANY", company="ACME")
		with self.assertRaises(PermissionError):
			self.api.submit_supplier_quotation("SQ-DRAFT", company="Other Co")


class TestSavingTheAward(unittest.TestCase):
	"""Sourcing writes the award; the numbers behind it are taken server-side.

	A payload that carries its own comparison is a payload that can carry a
	flattering one, and the snapshot is the whole point of the record: it is what
	the decision was made against, not what the totals happen to be today.
	"""

	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def _save(self, **overrides):
		payload = {
			"deal": "LOT-A",
			"selected_quotation": "SQ-SUBMITTED",
			"selection_reason": "Delivery window fits the tender deadline.",
			"policy_exception": 1,
			"exception_reason": "Only two suppliers hold the certificate.",
			"company": "ACME",
		}
		payload.update(overrides)
		return self.api.save_sourcing_decision(**payload)

	def test_cheapest_and_selected_are_recorded_as_two_facts(self):
		"""The interesting award is the one where they differ; a record that only
		keeps the choice cannot show that it was a choice."""
		result = self._save()
		doc = self.fake.created[-1]
		self.assertEqual(doc["selected_quotation"], "SQ-SUBMITTED")
		self.assertEqual(doc["cheapest_quotation"], "SQ-DRAFT")
		self.assertEqual(result["cheapest_quotation"], "SQ-DRAFT")

	def test_the_snapshot_is_computed_here_not_posted(self):
		self._save()
		snapshot = json.loads(self.fake.created[-1]["comparison_snapshot"])
		self.assertEqual(snapshot["base_currency"], "UZS")
		self.assertEqual([r["quotation"] for r in snapshot["rows"]], ["SQ-DRAFT", "SQ-SUBMITTED"])
		self.assertEqual(snapshot["taken_at"], "2026-08-02 10:00:00")

	def test_the_policy_counts_travel_with_the_decision(self):
		"""The controller enforces the exception rule from these two numbers, so
		they have to be on the document, not only in the endpoint that wrote it."""
		self._save()
		doc = self.fake.created[-1]
		self.assertEqual(doc["quotation_count"], 2)
		self.assertEqual(doc["country_count"], 2)

	def test_a_quotation_from_another_lot_cannot_be_awarded(self):
		with self.assertRaises(ValueError):
			self._save(selected_quotation="SQ-OTHER-LOT")
		self.assertEqual(self.fake.created, [])

	def test_a_reason_is_required(self):
		"""An award with no reason is a click, not a decision."""
		with self.assertRaises(ValueError):
			self._save(selection_reason="   ")

	def test_a_lot_gets_one_open_award_at_a_time(self):
		"""Two drafts are two answers to "who won", and nothing in the record
		says which one the buyer acted on. LOT-A already carries TSD-DRAFT."""
		fake = _FakeFrappe()
		api = _load_api(fake)
		with self.assertRaises(ValueError):
			api.save_sourcing_decision(
				deal="LOT-C",
				selected_quotation="SQ-SUBMITTED",
				selection_reason="Second opinion.",
				policy_exception=1,
				exception_reason="…",
				company="ACME",
			)

	def test_only_the_sourcing_window_may_write_one(self):
		"""Separation of duties: the same person must not both pick and approve."""
		api = _load_api(self.fake, views=("director",))
		with self.assertRaises(PermissionError):
			api.save_sourcing_decision(
				deal="LOT-A",
				selected_quotation="SQ-SUBMITTED",
				selection_reason="x",
				policy_exception=1,
				exception_reason="y",
				company="ACME",
			)

	def test_the_usual_three_gates_still_apply(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.save_sourcing_decision(
				deal="LOT-A", selected_quotation="SQ-SUBMITTED", selection_reason="x", company="ACME"
			)
		with self.assertRaises(PermissionError):
			self._save(deal="LOT-OTHER")
		with self.assertRaises(PermissionError):
			self._save(company="Other Co")


class TestApprovingTheAward(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_the_stamp_is_written_by_the_server(self):
		result = self.api.approve_sourcing_decision("TSD-DRAFT", company="ACME")
		doc = self.fake.docs[("Tender Sourcing Decision", "TSD-DRAFT")]
		self.assertEqual(doc["status"], "Approved")
		self.assertEqual(doc["approved_by"], "sourcing@example.com")
		self.assertEqual(doc["approved_at"], "2026-08-02 10:00:00")
		self.assertEqual(result["status"], "Approved")

	def test_the_controller_is_told_this_is_the_approval_path(self):
		"""Without the flag the controller refuses the transition — which is what
		stops an ordinary save from approving a decision."""
		self.api.approve_sourcing_decision("TSD-DRAFT", company="ACME")
		doc = self.fake.docs[("Tender Sourcing Decision", "TSD-DRAFT")]
		self.assertTrue(doc.flags.stabler_approving)

	def test_only_a_director_may_approve(self):
		api = _load_api(self.fake, views=("sourcing",))
		with self.assertRaises(PermissionError):
			api.approve_sourcing_decision("TSD-DRAFT", company="ACME")

	def test_an_approved_decision_cannot_be_approved_again(self):
		with self.assertRaises(ValueError):
			self.api.approve_sourcing_decision("TSD-APPROVED", company="ACME")

	def test_a_decision_from_another_company_is_refused(self):
		with self.assertRaises(PermissionError):
			self.api.approve_sourcing_decision("TSD-OTHER-COMPANY", company="ACME")

	def test_the_module_gate_still_applies(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.approve_sourcing_decision("TSD-DRAFT", company="ACME")


class TestReadingTheAward(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_the_open_decision_comes_back_with_its_comparison(self):
		"""One call, because the screen shows them together and two calls can
		disagree about what "now" was."""
		result = self.api.get_sourcing_decision("LOT-C", company="ACME")
		self.assertEqual(result["decision"]["name"], "TSD-DRAFT")
		self.assertEqual(result["comparison"]["count"], 2)

	def test_a_lot_without_an_award_reads_as_none_not_an_error(self):
		result = self.api.get_sourcing_decision("LOT-B", company="ACME")
		self.assertIsNone(result["decision"])

	def test_reading_is_gated_like_everything_else(self):
		with self.assertRaises(PermissionError):
			self.api.get_sourcing_decision("LOT-DENIED", company="ACME")


class TestGetSupplierQuotation(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_returns_quotation_details_with_lines(self):
		res = self.api.get_supplier_quotation("SQ-DRAFT", company="ACME")
		self.assertEqual(res["name"], "SQ-DRAFT")
		self.assertEqual(res["deal"], "LOT-A")
		self.assertEqual(res["supplier"], "SUP-A")
		self.assertEqual(res["supplier_name"], "Alfa")
		self.assertIn("transaction_date", res)
		self.assertEqual(len(res["items"]), 1)
		self.assertEqual(res["items"][0]["item_code"], "RAIL-01")

	def test_rejects_quotation_of_another_company(self):
		with self.assertRaises(PermissionError):
			self.api.get_supplier_quotation("SQ-OTHER-COMPANY", company="ACME")

	def test_gates_are_enforced(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.get_supplier_quotation("SQ-DRAFT", company="ACME")


class TestUnassignedQuotationsAndLinking(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_list_unassigned_returns_only_untagged_for_selected_company(self):
		res = self.api.list_unassigned_quotations(company="ACME")
		names = [r["name"] for r in res]
		self.assertIn("SQ-UNTAGGED", names)
		self.assertNotIn("SQ-DRAFT", names)
		self.assertNotIn("SQ-OTHER-COMPANY", names)

	def test_list_unassigned_never_returns_other_company(self):
		api = _load_api(self.fake)
		res = api.list_unassigned_quotations(company="ACME")
		for r in res:
			self.assertNotEqual(r.get("company"), "Other Co")

	def test_attach_quotation_sets_deal_and_supports_submitted(self):
		res = self.api.attach_quotation_to_deal("SQ-UNTAGGED", "LOT-A", company="ACME")
		self.assertEqual(res["quotation"], "SQ-UNTAGGED")
		self.assertEqual(res["deal"], "LOT-A")
		doc = self.fake.docs[("Supplier Quotation", "SQ-UNTAGGED")]
		self.assertEqual(doc.get("custom_crm_deal"), "LOT-A")

	def test_detach_quotation_clears_deal(self):
		res = self.api.detach_quotation_from_deal("SQ-DRAFT", company="ACME")
		self.assertTrue(res["detached"])
		doc = self.fake.docs[("Supplier Quotation", "SQ-DRAFT")]
		self.assertFalse(doc.get("custom_crm_deal"))

	def test_detach_refused_if_part_of_approved_sourcing_decision(self):
		with self.assertRaises(ValueError) as ctx:
			self.api.detach_quotation_from_deal("SQ-OTHER-LOT", company="ACME")
		self.assertIn("approved sourcing decision", str(ctx.exception))


class TestGetQuotationDefaults(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_defaults_from_explicit_rfq(self):
		res = self.api.get_quotation_defaults("LOT-A", rfq="RFQ-1", company="ACME")
		self.assertEqual(len(res["items"]), 1)
		self.assertEqual(res["items"][0]["item_code"], "RAIL-01")
		self.assertEqual(res["items"][0]["qty"], 10.0)
		self.assertEqual(res["items"][0]["uom"], "Nos")
		self.assertNotIn("rate", res["items"][0])

	def test_defaults_from_latest_rfq_when_rfq_not_specified(self):
		res = self.api.get_quotation_defaults("LOT-A", company="ACME")
		self.assertEqual(len(res["items"]), 1)
		self.assertEqual(res["items"][0]["item_code"], "RAIL-01")

	def test_defaults_empty_when_no_rfqs_exist(self):
		res = self.api.get_quotation_defaults("LOT-C", company="ACME")
		self.assertEqual(res, {"items": []})

	def test_defaults_rejects_foreign_rfq(self):
		with self.assertRaises(PermissionError):
			self.api.get_quotation_defaults("LOT-A", rfq="RFQ-OTHER-COMPANY", company="ACME")


class TestSqRfqLink(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def test_save_supplier_quotation_sets_custom_rfq(self):
		self.api.save_supplier_quotation(
			deal="LOT-A",
			supplier="SUP-A",
			currency="USD",
			rfq="RFQ-1",
			items=[{"item_code": "RAIL-01", "qty": 1.0, "rate": 50.0}],
			company="ACME",
		)
		doc = self.fake.created[-1]
		self.assertEqual(doc.get("custom_rfq"), "RFQ-1")

	def test_save_supplier_quotation_rejects_foreign_rfq(self):
		with self.assertRaises(Exception):
			self.api.save_supplier_quotation(
				deal="LOT-A",
				supplier="SUP-A",
				currency="USD",
				rfq="RFQ-OTHER-COMPANY",
				items=[{"item_code": "RAIL-01", "qty": 1.0, "rate": 50.0}],
				company="ACME",
			)


if __name__ == "__main__":
	unittest.main()
