"""Behavior and contract tests for tender_quotations API (G3).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_supplier_quotations_api -v
"""

from __future__ import annotations

import ast
import importlib
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

# This module builds a fake `frappe` and imports `stabler.api.purchasing`
# against it. `sys.modules` is process-wide, so leaving the fake behind broke
# whatever ran next in the same process — including frappe's own
# `_cleanup_after_tests`, which is why the module printed a test failure and
# then an `AttributeError: module 'frappe' has no attribute 'cache'`.
# `module_sandbox` exists for exactly this; the module simply predated it.
_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


class _FakeFrappe:
	def __init__(self):
		self.columns = {"custom_crm_deal", "custom_landed_charges"}
		self.quotations = [
			{
				"name": "SQ-A",
				"supplier": "SUP-A",
				"supplier_name": "Supplier A",
				"currency": "USD",
				"grand_total": 1000.0,
				"base_grand_total": 1000.0,
				"custom_landed_charges": '[{"charge_type":"Freight","amount":500.0}]',
				"valid_till": "2026-12-31",
				"status": "Submitted",
				"transaction_date": "2026-08-01",
				"total_qty": 10.0,
			},
			{
				"name": "SQ-B",
				"supplier": "SUP-B",
				"supplier_name": "Supplier B",
				"currency": "USD",
				"grand_total": 1200.0,
				"base_grand_total": 1200.0,
				"custom_landed_charges": '[{"charge_type":"Freight","amount":100.0}]',
				"valid_till": "2026-12-31",
				"status": "Submitted",
				"transaction_date": "2026-08-01",
				"total_qty": 10.0,
			},
		]

	def get_all(self, doctype, filters=None, fields=None, order_by=None, limit_page_length=None):
		if doctype == "Supplier Quotation":
			return [dict(q) for q in self.quotations]
		if doctype == "Supplier":
			return [{"name": "SUP-A", "country": "China"}, {"name": "SUP-B", "country": "Uzbekistan"}]
		return []


def _load_purchasing(fake: _FakeFrappe):
	_SANDBOX.evict(
		"stabler.api.purchasing",
		"frappe",
		"frappe.utils",
		"frappe.model.document",
	)

	frappe_model_doc = types.ModuleType("frappe.model.document")

	class Document:
		pass

	frappe_model_doc.Document = Document

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.ValidationError = ValueError
	frappe.session = types.SimpleNamespace(user="user@example.com")
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.has_permission = lambda doctype, ptype="read", doc=None: True
	frappe.get_all = fake.get_all
	frappe.get_cached_value = lambda dt, name, field: "USD"
	frappe.db = types.SimpleNamespace(
		has_column=lambda dt, col: col in fake.columns,
		exists=lambda dt, name=None: True,
		get_value=lambda dt, name, field=None: "ACME",
	)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v: float(v or 0)
	utils.cint = lambda v: int(v or 0)
	utils.getdate = lambda v: str(v) if v else None
	utils.today = lambda: "2026-08-02"

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._require_company = lambda c: None
	approvals._assert_company_scope = lambda c: c or "ACME"

	stabler_settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	stabler_settings.module_map_for = lambda c: {"tender": True}
	# `purchasing.py:23` imports this at module level, so a fake settings module
	# without it makes the import itself fail — and the traceback names
	# `purchasing`, not this file. Kept in step with `test_po_from_quotation.py`,
	# which fakes the same pair.
	stabler_settings.imports_supplier_groups_for = lambda c: []

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api.approvals": approvals,
			"stabler.stabler.doctype.stabler_settings.stabler_settings": stabler_settings,
			"frappe.model.document": frappe_model_doc,
		}
	)
	return importlib.import_module("stabler.api.purchasing")


class TestSupplierQuotationsApiSource(unittest.TestCase):
	def test_api_defines_list_supplier_quotations(self):
		filepath = os.path.join(os.path.dirname(__file__), "..", "api", "purchasing.py")
		with open(filepath, encoding="utf-8") as f:
			tree = ast.parse(f.read(), filename=filepath)

		funcs = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
		self.assertIn("list_supplier_quotations", funcs)

	def test_tender_quotations_ranking_and_completeness(self):
		fake = _FakeFrappe()
		api = _load_purchasing(fake)
		res = api.tender_quotations("LOT-100")

		self.assertTrue(res["estimate_complete"])
		self.assertEqual(res["cheapest_price_quote"], "SQ-A")
		self.assertEqual(res["cheapest_landed_quote"], "SQ-B")
		self.assertEqual(res["missing_estimates"], [])

		sq_a = next(r for r in res["rows"] if r["name"] == "SQ-A")
		sq_b = next(r for r in res["rows"] if r["name"] == "SQ-B")

		self.assertTrue(sq_a["is_cheapest_price"])
		self.assertFalse(sq_a["is_cheapest_landed"])

		self.assertFalse(sq_b["is_cheapest_price"])
		self.assertTrue(sq_b["is_cheapest_landed"])
		# Since estimate_complete is True, cheapest is SQ-B (cheapest landed)
		self.assertTrue(sq_b["cheapest"])


if __name__ == "__main__":
	unittest.main()
