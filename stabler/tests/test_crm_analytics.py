"""Unit & contract tests for Manager Cockpit Analytics API (stabler/api/crm_analytics.py).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_crm_analytics -v
"""

from __future__ import annotations

import sys
import unittest

from stabler.tests.test_sourcing_api import _Doc, _FakeFrappe, _load_api


class TestCrmAnalytics(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.sourcing_api = _load_api(self.fake)
		self.frappe = sys.modules["frappe"]

		# Add CRM Deal fixtures
		self.fake.docs[("CRM Deal", "DEAL-COCKPIT-1")] = _Doc(
			name="DEAL-COCKPIT-1",
			company="ACME",
			organization="Alfa Corp",
			stage="priced",
			contract_value=100000.0,
			probability=75.0,
			owner="rep1@acme.com",
			docstatus=0,
		)
		self.fake.docs[("CRM Deal", "DEAL-COCKPIT-2")] = _Doc(
			name="DEAL-COCKPIT-2",
			company="ACME",
			organization="Beta Corp",
			stage="won",
			contract_value=250000.0,
			probability=100.0,
			owner="rep2@acme.com",
			docstatus=0,
		)

	def test_get_manager_cockpit_metrics_returns_drillable_kpis(self):
		from stabler.api import crm_analytics

		res = crm_analytics.get_manager_cockpit_metrics(company="ACME")
		self.assertIn("weighted_forecast", res)
		self.assertIn("commit_total", res)
		self.assertIn("stage_aging", res)
		self.assertIn("rep_workload", res)
		self.assertGreaterEqual(res["deal_count"], 2)

	def test_get_manager_cockpit_metrics_rejects_unauthorized_company(self):
		from stabler.api import crm_analytics

		with self.assertRaises(self.frappe.PermissionError):
			crm_analytics.get_manager_cockpit_metrics(company="OTHER_CO")


if __name__ == "__main__":
	unittest.main()
