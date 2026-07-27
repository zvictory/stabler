"""Contract guards for CRM Deal company scoping.

Frappe CRM v2 does not ship a ``CRM Deal.company`` field, while Stabler's
tender APIs require it for tenant-safe company filters. The patch must add the
field idempotently and may only infer existing deal ownership on a single-
company site.
"""

from __future__ import annotations

import os
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_PATCH = os.path.join(_ROOT, "patches", "v56_crm_deal_company_scope.py")
_PATCHES_TXT = os.path.join(_ROOT, "patches.txt")


def _read(path: str) -> str:
	if not os.path.exists(path):
		return ""
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestCrmDealCompanyScopePatch(unittest.TestCase):
	def setUp(self):
		self.patch = _read(_PATCH)

	def test_patch_is_registered(self):
		self.assertTrue(os.path.exists(_PATCH), "CRM Deal company-scope patch is missing")
		self.assertIn("stabler.patches.v56_crm_deal_company_scope", _read(_PATCHES_TXT))

	def test_patch_adds_an_idempotent_company_link(self):
		for contract in (
			'frappe.db.has_column("CRM Deal", "company")',
			'"fieldname": "company"',
			'"fieldtype": "Link"',
			'"options": "Company"',
			'"default": ":Company"',
		):
			self.assertIn(contract, self.patch)

	def test_backfill_only_infers_scope_for_a_single_company(self):
		for contract in (
			'filters={"is_group": 0}',
			"if len(companies) != 1:",
			"COALESCE(company, '') = ''",
			"(companies[0],)",
		):
			self.assertIn(contract, self.patch)


if __name__ == "__main__":
	unittest.main()
