"""Contract-level receivable feature guards."""

from __future__ import annotations

import os
import unittest


_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _read(*parts: str) -> str:
	with open(os.path.join(_ROOT, *parts), encoding="utf-8") as source:
		return source.read()


class TestAgreementReceivablesContract(unittest.TestCase):
	def test_patch_registers_native_contract_links(self):
		patch = _read("patches", "v57_agreement_management_fields.py")
		registered = _read("patches.txt")
		self.assertIn("stabler.patches.v57_agreement_management_fields", registered)
		for doctype in ("Contract", "Quotation", "Sales Order", "Sales Invoice"):
			self.assertIn(f'"{doctype}"', patch)
		self.assertIn('"fieldname": "custom_agreement"', patch)
		self.assertIn('"fieldname": "custom_agreement_no"', patch)

	def test_report_is_company_and_agreement_gated(self):
		report = _read("api", "reports.py")
		for contract in (
			"def agreement_receivables(",
			"module_map_for(company).get(\"agreements\")",
			"si.custom_agreement",
			"SUM(si.outstanding_amount)",
			"Unlinked",
		):
			self.assertIn(contract, report)

	def test_report_never_emits_a_base_currency_amount(self):
		"""CLAUDE.md: amounts render in their ORIGINAL transaction currency only.

		Rows are grouped per `si.currency`, so a base-currency column would be the
		one place the report re-converts and displays a second amount. ReportTable
		suppresses mixed-currency totals with a `-` UNLESS the column declares a
		`currency_key` -- so a base column would also silently defeat that guard.
		The FX conversion may survive only as an ORDER BY sort key, never as an
		emitted field, so a 1M UZS row does not outrank a 100k USD one.
		"""
		report = _read("api", "reports.py")
		start = report.index("def agreement_receivables(")
		body = report[start : report.index("\n@frappe.whitelist()", start)]
		self.assertNotIn("base_balance", body)
		self.assertNotIn("base_currency\"", body)
		conversion = "SUM(si.outstanding_amount * si.conversion_rate)"
		if conversion in body:
			self.assertGreater(
				body.index(conversion),
				body.index("ORDER BY"),
				"conversion_rate may appear only in ORDER BY, not in the SELECT list",
			)

	def test_ui_route_is_company_module_gated(self):
		router = _read("public", "js", "router.js")
		page = _read("public", "js", "pages", "reports", "AgreementReceivables.vue")
		self.assertIn("report-agreement-receivables", router)
		self.assertIn("module: \"agreements\"", router)
		self.assertIn("agreement_receivables", page)

	def test_opening_preview_is_non_mutating_and_fixed_to_uzs_date(self):
		api = _read("api", "agreement_opening.py")
		self.assertIn("def preview_agreement_opening(", api)
		self.assertIn('OPENING_DATE = "2026-07-20"', api)
		self.assertIn('"financial_mutation": False', api)
		self.assertIn('currency.upper() != "UZS"', api)
		self.assertNotIn("frappe.new_doc", api)
		self.assertNotIn("doc.insert", api)

	def test_sales_order_agreement_is_validated_and_invoice_propagated(self):
		sales = _read("api", "sales.py")
		self.assertIn("def _validate_agreement(", sales)
		self.assertIn("def list_agreements(", sales)
		self.assertIn("doc.custom_agreement = agreement", sales)
		self.assertIn("doc.custom_agreement = getattr(so, \"custom_agreement\", None)", sales)

	def test_excel_normalizer_is_read_only_and_pins_dts_defaults(self):
		normalizer = _read("maintenance", "normalize_dts_agreement_xlsx.py")
		self.assertIn('"currency": "UZS"', normalizer)
		self.assertIn('"as_of_date": "2026-07-20"', normalizer)
		self.assertIn("load_workbook", normalizer)
		self.assertNotIn("frappe.new_doc", normalizer)


if __name__ == "__main__":
	unittest.main()
