"""Behavior and contract tests for supplier quotation history (Faz 2 · Task 4).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_supplier_quotation_history -v
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest


class _FakeFrappe:
	def __init__(self):
		self.sql_calls = []
		self.get_list_calls = []
		self.columns = {"custom_crm_deal"}
		self.doctypes = {"DocType", "Supplier Quotation", "Tender Sourcing Decision"}
		self.quotations = [
			{
				"name": "SQ-WON",
				"supplier": "SUP-A",
				"company": "ACME",
				"custom_crm_deal": "LOT-1",
				"grand_total": 5000.0,
				"base_grand_total": 5000.0,
				"currency": "USD",
				"status": "Submitted",
				"valid_till": "2026-12-31",
				"transaction_date": "2026-08-01",
				"docstatus": 1,
			},
			{
				"name": "SQ-LOST",
				"supplier": "SUP-A",
				"company": "ACME",
				"custom_crm_deal": "LOT-2",
				"grand_total": 8000.0,
				"base_grand_total": 8000.0,
				"currency": "USD",
				"status": "Submitted",
				"valid_till": "2026-12-31",
				"transaction_date": "2026-07-15",
				"docstatus": 1,
			},
			{
				"name": "SQ-OPEN",
				"supplier": "SUP-A",
				"company": "ACME",
				"custom_crm_deal": "LOT-3",
				"grand_total": 3000.0,
				"base_grand_total": 3000.0,
				"currency": "USD",
				"status": "Submitted",
				"valid_till": "2026-12-31",
				"transaction_date": "2026-08-02",
				"docstatus": 1,
			},
		]
		self.decisions = [
			{
				"deal": "LOT-1",
				"selected_quotation": "SQ-WON",
				"company": "ACME",
				"status": "Approved",
			},
			{
				"deal": "LOT-2",
				"selected_quotation": "SQ-OTHER",
				"company": "ACME",
				"status": "Approved",
			},
		]

	def get_list(self, doctype, filters=None, fields=None, **kwargs):
		self.get_list_calls.append({"doctype": doctype, "filters": filters, "fields": fields, **kwargs})
		if doctype == "Supplier Quotation":
			supplier = filters.get("supplier")
			company = filters.get("company")
			rows = [r for r in self.quotations if r["company"] == company and r["supplier"] == supplier]
			return [dict(r) for r in rows]
		elif doctype == "Tender Sourcing Decision":
			company = filters.get("company")
			deal_filter = filters.get("deal")
			deals = deal_filter[1] if isinstance(deal_filter, list) and deal_filter[0] == "in" else []
			rows = [r for r in self.decisions if r["company"] == company and r["deal"] in deals]
			return [dict(r) for r in rows]
		return []

	def sql(self, query, params, as_dict=True):
		self.sql_calls.append((query, params))
		company = params.get("company")
		supplier = params.get("supplier")
		rows = [r for r in self.quotations if r["company"] == company and r["supplier"] == supplier]
		return [dict(r) for r in rows]


def _load_purchasing(fake: _FakeFrappe):
	for name in (
		"stabler.api.purchasing",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
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
	frappe.session = types.SimpleNamespace(user="user@example.com")
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.has_permission = lambda doctype, ptype="read", doc=None: True
	frappe.get_list = fake.get_list
	frappe.db = types.SimpleNamespace(
		has_column=lambda dt, col: col in fake.columns,
		exists=lambda dt, name=None: dt in fake.doctypes,
		sql=fake.sql,
	)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v: float(v or 0)
	utils.cint = lambda v: int(v or 0)
	utils.getdate = lambda v: str(v) if v else None
	utils.today = lambda: "2026-08-02"

	approvals = types.ModuleType("stabler.api.approvals")

	def _assert_company_scope(company):
		if company != "ACME":
			raise PermissionError("Foreign company")
		return company

	approvals._assert_company_scope = _assert_company_scope

	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api.approvals": approvals,
		}
	)
	return importlib.import_module("stabler.api.purchasing")


class TestSupplierQuotationHistory(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_purchasing(self.fake)

	def test_permission_aware_batch_list_queries_contract(self):
		res = self.api.supplier_quotation_history("SUP-A", company="ACME")
		self.assertLessEqual(
			len(self.fake.get_list_calls),
			2,
			"Must execute at most TWO permission-aware batch list queries (no N+1)",
		)
		self.assertEqual(res["count"], 3)

	def test_derived_result_values(self):
		res = self.api.supplier_quotation_history("SUP-A", company="ACME")
		results = {r["name"]: r["result"] for r in res["rows"]}
		self.assertEqual(results.get("SQ-WON"), "won")
		self.assertEqual(results.get("SQ-LOST"), "lost")
		self.assertEqual(results.get("SQ-OPEN"), "open")

	def test_rejects_foreign_company(self):
		with self.assertRaises(PermissionError):
			self.api.supplier_quotation_history("SUP-A", company="OTHER")

	def test_requires_company(self):
		with self.assertRaises(ValueError):
			self.api.supplier_quotation_history("SUP-A", company="")


if __name__ == "__main__":
	unittest.main()
