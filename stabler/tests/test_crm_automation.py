"""Unit & idempotency tests for Audited CRM Automation Rules (stabler/api/crm_automation.py).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_crm_automation -v
"""

from __future__ import annotations

import sys
import unittest

from stabler.tests.test_sourcing_api import _Doc, _FakeFrappe, _load_api


class TestCrmAutomation(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.sourcing_api = _load_api(self.fake)
		self.frappe = sys.modules["frappe"]

		# Add CRM Deal fixtures
		self.fake.docs[("CRM Deal", "DEAL-AUTO-1")] = _Doc(
			name="DEAL-AUTO-1",
			company="ACME",
			organization="Alfa Corp",
			stage="priced",
			deadline="2026-08-03",  # <= 48h from 2026-08-02
			last_activity_date="2026-07-30",
			custom_parent_tender="TND-AUTO",
			docstatus=0,
		)
		self.fake.docs[("CRM Deal", "DEAL-AUTO-FOREIGN")] = _Doc(
			name="DEAL-AUTO-FOREIGN",
			company="OTHER_CO",
			stage="go",
			docstatus=0,
		)

	def test_run_crm_automation_rules_executes_and_dedupes(self):
		from stabler.api import crm_automation

		# Run automation rules for ACME
		res1 = crm_automation.run_crm_automation_rules(company="ACME")
		self.assertIn("summary", res1)
		self.assertGreaterEqual(res1["executed_rules"], 1)

		# Second run with same company -> idempotent (no duplicate actions)
		res2 = crm_automation.run_crm_automation_rules(company="ACME")
		self.assertEqual(res2["executed_rules"], 0)

	def test_run_crm_automation_rules_rejects_unauthorized_company(self):
		from stabler.api import crm_automation

		with self.assertRaises(self.frappe.PermissionError):
			crm_automation.run_crm_automation_rules(company="OTHER_CO")


if __name__ == "__main__":
	unittest.main()
