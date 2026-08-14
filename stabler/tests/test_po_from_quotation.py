"""Unit and contract tests for create_po_from_quotation (Phase B3).

Verifies that create_po_from_quotation:
- enforces company scope and reject foreign company
- validates that Supplier Quotation exists and is tagged to a CRM Deal lot
- returns existing draft PO when one already exists for the lot + supplier (idempotency)
- creates a new draft Purchase Order copying supplier, currency, items, and crm_deal link
- rejects cancelled quotations or quotations with no items
"""

from __future__ import annotations

import importlib
import types
import unittest
from pathlib import Path

from stabler.tests.module_sandbox import ModuleSandbox

_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


class _Doc(dict):
	def __getattr__(self, field):
		if field == "flags":
			return self.setdefault("_flags", types.SimpleNamespace())
		return self.get(field)

	def __setattr__(self, field, value):
		self[field] = value

	def as_dict(self):
		return dict(self)

	def append(self, field, row):
		self.setdefault(field, []).append(dict(row))
		return row

	def insert(self, **_kwargs):
		self["inserted"] = True
		self["name"] = self.get("name") or f"PO-{id(self)}"
		if hasattr(self, "_fake") and self._fake:
			self._fake.docs[("Purchase Order", self["name"])] = self
		return self

	def set_missing_values(self):
		pass

	def calculate_taxes_and_totals(self):
		pass


class _FakeDB:
	def __init__(self):
		self.docs = {
			("Company", "ACME"): _Doc(name="ACME", default_currency="USD"),
			("Company", "Other"): _Doc(name="Other", default_currency="EUR"),
			("Warehouse", "Stores - ACME"): _Doc(name="Stores - ACME", company="ACME", is_group=0),
			("Supplier Quotation", "SQ-VALID"): _Doc(
				name="SQ-VALID",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal="LOT-1",
				valid_till="2026-09-01",
				docstatus=0,
				items=[
					_Doc(
						item_code="RAIL-01",
						item_name="Steel Rail",
						qty=5.0,
						uom="Nos",
						rate=100.0,
						amount=500.0,
					)
				],
			),
			("Supplier Quotation", "SQ-NO-ITEMS"): _Doc(
				name="SQ-NO-ITEMS",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal="LOT-1",
				docstatus=0,
				items=[],
			),
			("Supplier Quotation", "SQ-NO-DEAL"): _Doc(
				name="SQ-NO-DEAL",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal=None,
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
			("Supplier Quotation", "SQ-CANCELLED"): _Doc(
				name="SQ-CANCELLED",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal="LOT-1",
				docstatus=2,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
			("Supplier Quotation", "SQ-OTHER-CO"): _Doc(
				name="SQ-OTHER-CO",
				company="Other",
				supplier="SUP-OTHER",
				currency="EUR",
				custom_crm_deal="LOT-OTHER",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
			("Purchase Order", "PO-EXISTING"): _Doc(
				name="PO-EXISTING",
				company="ACME",
				supplier="SUP-BETA",
				custom_crm_deal="LOT-EXISTING",
				docstatus=0,
			),
			("Supplier Quotation", "SQ-EXISTING-LOT"): _Doc(
				name="SQ-EXISTING-LOT",
				company="ACME",
				supplier="SUP-BETA",
				currency="USD",
				custom_crm_deal="LOT-EXISTING",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
		}
		self.created: list[_Doc] = []

	def exists(self, doctype, name):
		if doctype == "Company":
			return name in {"ACME", "Other"}
		return (doctype, name) in self.docs

	def get_value(self, doctype, name, fieldname):
		doc = self.docs.get((doctype, name))
		if not doc:
			return None
		return doc.get(fieldname)

	def has_column(self, doctype, column):
		return True


def _load_purchasing(db: _FakeDB):
	_SANDBOX.evict(
		"stabler.api.purchasing",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.approvals",
	)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.DoesNotExistError = KeyError
	frappe.ValidationError = ValueError
	frappe.session = types.SimpleNamespace(user="buyer@acme.example")
	frappe.flags = types.SimpleNamespace()
	frappe.db = db
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.get_roles = lambda _user=None: ["Purchase User"]
	frappe.has_permission = lambda doctype, ptype="read", doc=None: True
	frappe.throw = lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message))
	frappe.get_doc = lambda doctype, name: db.docs[(doctype, name)]
	frappe.new_doc = lambda doctype: _new_doc(db, doctype)
	frappe.get_list = lambda doctype, **kwargs: _get_list(db, doctype, **kwargs)
	frappe.get_all = lambda doctype, **kwargs: _get_list(db, doctype, **kwargs)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.cint = lambda value: int(value or 0)
	utils.getdate = lambda value: str(value)[:10]
	utils.today = lambda: "2026-08-14"
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_args, **_kwargs: None
	common._assert_can_write = lambda *_args, **_kwargs: None
	common._require_company = lambda company: company or "ACME"
	common._company_default_warehouse = lambda company: "Stores - ACME"
	common.check_concurrency = lambda *_args, **_kwargs: None

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: company

	settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	settings.module_map_for = lambda c: {"tender": True, "purchasing": True}
	settings.imports_supplier_groups_for = lambda c: []

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.stabler.doctype.stabler_settings.stabler_settings": settings,
		}
	)
	return importlib.import_module("stabler.api.purchasing")


def _new_doc(db: _FakeDB, doctype: str):
	doc = _Doc(doctype=doctype, _fake=db, docstatus=0)
	db.created.append(doc)
	return doc


def _get_list(db: _FakeDB, doctype: str, **kwargs):
	filters = kwargs.get("filters", {})
	res = []
	for (dt, _name), doc in db.docs.items():
		if dt != doctype:
			continue
		match = True
		for k, v in filters.items():
			if k == "docstatus" and isinstance(v, list) and v[0] == "<":
				if doc.get("docstatus", 0) >= v[1]:
					match = False
					break
			elif doc.get(k) != v:
				match = False
				break
		if match:
			res.append(doc)
	return res


class TestCreatePoFromQuotation(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.purchasing = _load_purchasing(self.db)

	def test_creates_draft_po_with_copied_lines_and_deal_link(self):
		res = self.purchasing.create_po_from_quotation("SQ-VALID", company="ACME")
		self.assertFalse(res["existing"])
		self.assertTrue(res["name"])

		po = self.db.docs[("Purchase Order", res["name"])]
		self.assertEqual(po["company"], "ACME")
		self.assertEqual(po["supplier"], "SUP-ALFA")
		self.assertEqual(po["currency"], "USD")
		self.assertEqual(po["custom_crm_deal"], "LOT-1")
		self.assertEqual(po["docstatus"], 0)
		self.assertEqual(len(po.get("items", [])), 1)
		self.assertEqual(po["items"][0]["item_code"], "RAIL-01")
		self.assertEqual(po["items"][0]["qty"], 5.0)
		self.assertEqual(po["items"][0]["rate"], 100.0)

	def test_returns_existing_po_if_one_already_exists_for_lot_and_supplier(self):
		res = self.purchasing.create_po_from_quotation("SQ-EXISTING-LOT", company="ACME")
		self.assertTrue(res["existing"])
		self.assertEqual(res["name"], "PO-EXISTING")

	def test_rejects_foreign_company(self):
		with self.assertRaises(PermissionError):
			self.purchasing.create_po_from_quotation("SQ-OTHER-CO", company="ACME")

	def test_rejects_cancelled_quotation(self):
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-CANCELLED", company="ACME")

	def test_rejects_quotation_without_crm_deal(self):
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-NO-DEAL", company="ACME")

	def test_rejects_quotation_with_no_lines(self):
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-NO-ITEMS", company="ACME")


if __name__ == "__main__":
	unittest.main()
