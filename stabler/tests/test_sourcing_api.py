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
import re
import sys
import types
import unittest
from pathlib import Path
from typing import ClassVar

_ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = _ROOT / "api" / "sourcing.py"
PATCH = _ROOT / "patches" / "v68_rfq_tender_deal.py"
PATCHES = _ROOT / "patches.txt"


class _Doc(dict):
	def __getattr__(self, field):
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
		self.emails: list[dict] = []

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


def _load_api(fake: _FakeFrappe, *, tender_allowed=True, missing_columns=(), can_create=True):
	for name in (
		"stabler.api.sourcing",
		"stabler.api.tender",
		"stabler.api.tender_master",
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
	)
	frappe.parse_json = lambda value: value
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))

	def _has_permission(doctype, ptype="read", doc=None):
		if ptype == "create":
			fake.create_checks.append(doctype)
			return can_create
		return (doctype, getattr(doc, "name", doc)) not in fake.unreadable

	frappe.has_permission = _has_permission
	frappe.sendmail = lambda **kwargs: fake.emails.append(kwargs)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.today = lambda: "2026-08-02"

	tender = types.ModuleType("stabler.api.tender")
	tender._require_tender = lambda _company=None: (
		None if tender_allowed else (_ for _ in ()).throw(PermissionError("Not permitted"))
	)

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


if __name__ == "__main__":
	unittest.main()
