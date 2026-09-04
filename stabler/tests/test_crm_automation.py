"""Unit & contract tests for Real Audited CRM Automation Rules (stabler/api/crm_automation.py).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_crm_automation -v
"""

from __future__ import annotations

import sys
import unittest

from stabler.tests.test_sourcing_api import _SANDBOX, _Doc, _FakeFrappe, _load_api


def tearDownModule():
	"""``_load_api`` evicts the real ``frappe`` from ``sys.modules`` process-wide.

	unittest runs ``tearDownModule`` per module, so the owning module's teardown
	does NOT run for a borrower — importing ``_load_api`` borrows the sandbox and
	inherits the duty to hand it back. Without this the fake ``frappe`` outlives
	the suite, and ``bench run-tests`` dies in its own ``_cleanup_after_tests``
	calling ``frappe.clear_cache()``: tests print OK, the runner still exits 1.
	"""
	_SANDBOX.restore()


class TestCrmAutomation(unittest.TestCase):
	fake = None
	frappe = None

	@classmethod
	def setUpClass(cls):
		cls.fake = _FakeFrappe()
		_load_api(cls.fake)
		cls.frappe = sys.modules["frappe"]

	def setUp(self):
		self.fake.docs.clear()
		self.fake.created.clear()
		self.frappe.session.user = "crm_manager@acme.com"

		from stabler.api import crm, organization

		# Mock user roles to include Sales Manager / System Manager
		def _roles_fn(user=None):
			return ["System Manager", "Sales Manager"]

		sys.modules["frappe"].get_roles = _roles_fn
		if "stabler.api.crm" in sys.modules:
			sys.modules["stabler.api.crm"].frappe.get_roles = _roles_fn
			sys.modules["stabler.api.crm"]._user_allowed_companies = lambda _user: ["ACME"]

		organization._user_allowed_companies = lambda _user: ["ACME"]
		crm._user_allowed_companies = lambda _user: ["ACME"]

		# Add CRM Deal fixtures with dynamic date attributes
		self.fake.docs[("CRM Deal", "DEAL-AUTO-1")] = _Doc(
			name="DEAL-AUTO-1",
			doctype="CRM Deal",
			company="ACME",
			organization="Alfa Corp",
			stage="priced",
			deadline="2026-08-03",  # <= 2 days from today (2026-08-02)
			last_activity_date="2026-07-28",  # 5 days ago (> 3 days stale)
			custom_parent_tender="TND-AUTO",
			# `deal_type` is what every live row carries after v103 backfilled NULL to
			# Standard; the readers filter `deal_type != "Overhead"` and the double drops
			# NULL rows on `!=` exactly as MariaDB does, so a fixture without a type is
			# a row that cannot exist on a migrated site — and vanishes from every list.
			deal_type="Standard",
			docstatus=0,
		)
		self.fake.docs[("CRM Deal", "DEAL-AUTO-FOREIGN")] = _Doc(
			name="DEAL-AUTO-FOREIGN",
			doctype="CRM Deal",
			company="OTHER_CO",
			stage="go",
			deadline="2026-08-03",
			deal_type="Standard",
			docstatus=0,
		)

	def test_run_crm_automation_rules_creates_real_activities_and_dedupes_in_db(self):
		from stabler.api import crm_automation

		# Run automation rules for ACME (dry_run=False)
		res1 = crm_automation.run_crm_automation_rules(company="ACME", dry_run=False)
		self.assertIn("summary", res1)
		self.assertGreaterEqual(res1["executed_rules"], 1)

		# Verify persistent audit CRM Activity was created in DB
		activities = [
			doc
			for (kind, name), doc in self.fake.docs.items()
			if kind == "CRM Activity" and doc.get("company") == "ACME"
		]
		self.assertGreaterEqual(len(activities), 1)
		self.assertIn("custom_idempotency_key", activities[0])

		# Second run with same company -> idempotent via DB record lookup
		res2 = crm_automation.run_crm_automation_rules(company="ACME", dry_run=False)
		self.assertEqual(res2["executed_rules"], 0)

	def test_non_duplicate_insert_failure_fails_loud_and_does_not_increment_executed_count(self):
		from stabler.api import crm_automation

		original_new_doc = sys.modules["frappe"].new_doc

		def _broken_new_doc(doctype):
			doc = original_new_doc(doctype)

			def _broken_insert():
				raise self.frappe.ValidationError("Database Locked Error")

			object.__setattr__(doc, "insert", _broken_insert)
			return doc

		sys.modules["frappe"].new_doc = _broken_new_doc

		try:
			with self.assertRaises(self.frappe.ValidationError):
				crm_automation.run_crm_automation_rules(company="ACME", dry_run=False)
		finally:
			sys.modules["frappe"].new_doc = original_new_doc

	def test_preview_crm_automation_rules_does_not_mutate_db(self):
		from stabler.api import crm_automation

		initial_count = len(self.fake.docs)
		preview = crm_automation.preview_crm_automation_rules(company="ACME")

		self.assertIn("actions", preview)
		self.assertGreaterEqual(len(preview["actions"]), 1)
		# Assert no new documents created during preview
		self.assertEqual(len(self.fake.docs), initial_count)

	def test_failed_action_retry_status_transition(self):
		from stabler.api import crm_automation

		# Add a pre-existing Failed activity in DB
		failed_key = "crm_sla:ACME:DEAL-AUTO-1:2026-08-03"
		failed_doc = _Doc(
			name="ACT-FAILED-1",
			doctype="CRM Activity",
			company="ACME",
			reference_doctype="CRM Deal",
			reference_name="DEAL-AUTO-1",
			custom_idempotency_key=failed_key,
			custom_execution_status="Failed",
			custom_attempts=1,
			custom_last_error="Temporary Network Error",
		)
		self.fake.docs[("CRM Activity", "ACT-FAILED-1")] = failed_doc

		res = crm_automation.run_crm_automation_rules(company="ACME", dry_run=False)
		self.assertGreaterEqual(res["executed_rules"], 1)

		# Check status was updated to Retried with attempts = 2
		self.assertEqual(failed_doc.get("custom_execution_status"), "Retried")
		self.assertEqual(failed_doc.get("custom_attempts"), 2)

	def test_scheduler_daily_crm_automation_runs_fault_tolerant(self):
		from stabler.api import crm_automation

		# Mock get_all for Company
		self.fake.get_all_rows = [{"name": "ACME"}, {"name": "OTHER_CO"}]

		# System administrator context during daily scheduler run
		self.frappe.session.user = "Administrator"

		crm_automation.scheduled_daily_crm_automation()

	def test_run_crm_automation_rules_rejects_unauthorized_role(self):
		from stabler.api import crm, crm_automation, organization

		# Demote user role to plain user (no manager role)
		def _guest_roles(user=None):
			return ["Guest"]

		sys.modules["frappe"].get_roles = _guest_roles
		if "stabler.api.crm" in sys.modules:
			sys.modules["stabler.api.crm"].frappe.get_roles = _guest_roles

		with self.assertRaises(PermissionError):
			crm_automation.run_crm_automation_rules(company="ACME")

	def test_run_crm_automation_rules_rejects_unauthorized_company(self):
		from stabler.api import crm, crm_automation, organization

		# Non-admin sales manager restricted to ACME
		def _sales_roles(user=None):
			return ["Sales Manager"]

		sys.modules["frappe"].get_roles = _sales_roles
		if "stabler.api.crm" in sys.modules:
			sys.modules["stabler.api.crm"].frappe.get_roles = _sales_roles
			sys.modules["stabler.api.crm"]._user_allowed_companies = lambda _user: ["ACME"]

		organization._user_allowed_companies = lambda _user: ["ACME"]

		with self.assertRaises(PermissionError):
			crm_automation.run_crm_automation_rules(company="OTHER_CO")

	def test_cross_company_automation_isolation(self):
		from stabler.api import crm_automation

		res = crm_automation.run_crm_automation_rules(company="ACME", dry_run=False)
		actions_deals = [a["deal"] for a in res["actions"]]

		self.assertIn("DEAL-AUTO-1", actions_deals)
		self.assertNotIn("DEAL-AUTO-FOREIGN", actions_deals)


if __name__ == "__main__":
	unittest.main()
