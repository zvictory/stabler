"""Contract tests for Tender Navigation & Context propagation.

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_navigation_context -v
"""

from __future__ import annotations

import sys
import unittest
from stabler.tests.test_sourcing_api import _FakeFrappe, _load_api


class TestTenderNavigationContextBackend(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)
		self.frappe = sys.modules["frappe"]

	def test_cross_company_query_injection_rejected(self):
		"""Company parameter in query is NOT trusted over session company scope."""
		with self.assertRaises(self.frappe.PermissionError):
			self.api._assert_company_scope("OTHER_COMPANY")

	def test_company_scope_is_mandatory(self):
		with self.assertRaises(self.frappe.ValidationError):
			self.api._assert_company_scope("")

	def test_tender_module_gate_remains_active(self):
		with self.assertRaises(self.frappe.PermissionError):
			api = _load_api(self.fake, tender_allowed=False)
			api.list_rfqs(deal="LOT-A", company="ACME")


if __name__ == "__main__":
	unittest.main()
