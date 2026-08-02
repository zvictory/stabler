"""Contract and behavior tests for quotation landed cost endpoints (G2).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_quotation_landed_api -v
"""

from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from datetime import datetime


class _FakeDoc:
	def __init__(self, data):
		self.__dict__.update(data)

	def get(self, key, default=None):
		return getattr(self, key, default)


class _FakeFrappe:
	def __init__(self):
		self.db_set_values = []
		self.quotations = {
			"SQ-001": _FakeDoc(
				{
					"name": "SQ-001",
					"company": "ACME",
					"supplier": "SUP-1",
					"currency": "USD",
					"grand_total": 10000.0,
					"base_grand_total": 10000.0,
					"custom_landed_charges": '[{"charge_type":"Freight","amount":1200.0}]',
				}
			),
		}

	def get_doc(self, doctype, name):
		if doctype == "Supplier Quotation" and name in self.quotations:
			return self.quotations[name]
		raise ValueError(f"No {doctype} {name}")

	def set_value(self, doctype, name, fieldname, value):
		self.db_set_values.append((doctype, name, fieldname, value))
		if doctype == "Supplier Quotation" and name in self.quotations:
			setattr(self.quotations[name], fieldname, value)


def _load_sourcing(fake: _FakeFrappe):
	for name in (
		"stabler.api.sourcing",
		"stabler.api.tender",
		"stabler.api.tender_master",
		"stabler.api.purchasing",
		"frappe",
		"frappe.utils",
		"frappe.model.document",
	):
		sys.modules.pop(name, None)

	frappe_model_doc = types.ModuleType("frappe.model.document")

	class Document:
		pass

	frappe_model_doc.Document = Document
	sys.modules["frappe.model.document"] = frappe_model_doc

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.ValidationError = ValueError
	frappe.session = types.SimpleNamespace(user="buyer@example.com")
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.has_permission = lambda doctype, ptype="read", doc=None: True
	frappe.parse_json = lambda val: json.loads(val) if isinstance(val, str) else val
	frappe.get_doc = fake.get_doc
	frappe.db = types.SimpleNamespace(set_value=fake.set_value)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v: float(v or 0)
	utils.cint = lambda v: int(v or 0)
	utils.today = lambda: "2026-08-02"
	utils.now = lambda: "2026-08-02 12:00:00"
	utils.getdate = lambda v: str(v) if v else None
	utils.add_months = lambda date, months: date
	utils.now_datetime = lambda: datetime(2026, 8, 2, 12, 0, 0)

	approvals = types.ModuleType("stabler.api.approvals")

	def _assert_company_scope(company):
		if company != "ACME":
			raise PermissionError("Foreign company")
		return company

	approvals._assert_company_scope = _assert_company_scope
	approvals._deal_scope = lambda deal, company, ptype="read": ("DEAL", company)

	tender = types.ModuleType("stabler.api.tender")
	tender._require_tender = lambda company=None: None
	tender._require_tender_view = lambda view, company: None
	tender._dashboard_period = lambda days: ("2026-05-01", "2026-08-02")

	tender_master = types.ModuleType("stabler.api.tender_master")
	tender_master.require_selected_company = lambda company: company or "ACME"

	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api.approvals": approvals,
			"stabler.api.tender": tender,
			"stabler.api.tender_master": tender_master,
		}
	)
	return importlib.import_module("stabler.api.sourcing")


class TestQuotationLandedApi(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_sourcing(self.fake)

	def test_get_quotation_landed(self):
		res = self.api.get_quotation_landed("SQ-001", company="ACME")
		self.assertEqual(res["quotation"], "SQ-001")
		self.assertEqual(res["base_grand_total"], 10000.0)
		self.assertEqual(res["landed_charges_total"], 1200.0)
		self.assertEqual(res["base_landed_total"], 11200.0)
		self.assertTrue(res["has_landed_estimate"])

	def test_update_quotation_landed(self):
		new_charges = [
			{"charge_type": "Freight", "amount": 1500.0},
			{"charge_type": "Handling", "amount": 250.0},
		]
		res = self.api.update_quotation_landed("SQ-001", new_charges, company="ACME")
		self.assertEqual(res["landed_charges_total"], 1750.0)
		self.assertEqual(res["base_landed_total"], 11750.0)
		self.assertEqual(len(self.fake.db_set_values), 1)
		dt, name, field, val = self.fake.db_set_values[0]
		self.assertEqual(dt, "Supplier Quotation")
		self.assertEqual(name, "SQ-001")
		self.assertEqual(field, "custom_landed_charges")
		self.assertIn("1500", val)

	def test_foreign_company_rejected(self):
		with self.assertRaises(PermissionError):
			self.api.get_quotation_landed("SQ-001", company="FOREIGN")


if __name__ == "__main__":
	unittest.main()
