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
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from typing import ClassVar

_ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = _ROOT / "api" / "sourcing.py"
PATCH = _ROOT / "patches" / "v68_rfq_tender_deal.py"
PATCHES = _ROOT / "patches.txt"


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

	def insert(self):
		self["inserted"] = True
		self["name"] = self.get("name") or "RFQ-NEW"
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
			("CRM Deal", "LOT-A"): _Doc(name="LOT-A", company="ACME", deal_type="Tender"),
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
				docstatus=0,
				items=[{"item_code": "RAIL-01", "qty": 5.0, "rate": 100.0}],
			),
			("Supplier Quotation", "SQ-SUBMITTED"): _Doc(
				name="SQ-SUBMITTED",
				company="ACME",
				supplier="SUP-A",
				currency="USD",
				custom_crm_deal="LOT-A",
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
		doc = _Doc(doctype=doctype)
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
	for name in (
		"stabler.api.sourcing",
		"stabler.api.tender",
		"stabler.api.tender_master",
		"stabler.api.purchasing",
		"frappe",
		"frappe.utils",
	):
		sys.modules.pop(name, None)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.ValidationError = ValueError
	frappe.session = types.SimpleNamespace(user="sourcing@example.com")
	frappe.get_doc = fake.get_doc
	frappe.new_doc = fake.new_doc
	frappe.get_list = fake.get_list
	frappe.get_all = fake.get_all
	frappe.db = types.SimpleNamespace(
		has_column=lambda _doctype, column: column not in missing_columns,
		exists=lambda doctype, name=None: True,
		get_value=lambda doctype, name, field: (
			fake.docs.get((doctype, name), {}).get(field)
			if isinstance(fake.docs.get((doctype, name)), dict)
			else None
		),
	)
	frappe.parse_json = lambda value: value
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))

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
	utils.today = lambda: "2026-08-02"

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

	sys.modules.update(
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
		"""Deal write permission is not RFQ create permission."""
		self._create()
		self.assertIn("Request for Quotation", self.fake.create_checks)
		api = _load_api(self.fake, can_create=False)
		with self.assertRaises(PermissionError):
			api.create_rfq("LOT-A", ["SUP-A"], [{"item_code": "RAIL-01", "qty": 1}], company="ACME")

	def test_creating_before_the_patch_has_run_fails_loudly(self):
		"""Reading tolerates an unmigrated site; WRITING must not — an untagged
		RFQ is worse than no RFQ, because nothing will ever find it again."""
		api = _load_api(self.fake, missing_columns=("custom_crm_deal",))
		with self.assertRaises(Exception) as ctx:
			api.create_rfq("LOT-A", ["SUP-A"], [{"item_code": "RAIL-01", "qty": 1}], company="ACME")
		self.assertIn("migrate", str(ctx.exception).lower())
		self.assertEqual(self.fake.created, [])


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
		self.assertEqual(len(res["items"]), 1)
		self.assertEqual(res["items"][0]["item_code"], "RAIL-01")

	def test_rejects_quotation_of_another_company(self):
		with self.assertRaises(PermissionError):
			self.api.get_supplier_quotation("SQ-OTHER-COMPANY", company="ACME")

	def test_gates_are_enforced(self):
		api = _load_api(self.fake, tender_allowed=False)
		with self.assertRaises(PermissionError):
			api.get_supplier_quotation("SQ-DRAFT", company="ACME")


if __name__ == "__main__":
	unittest.main()
