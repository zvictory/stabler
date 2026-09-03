"""Unit & contract tests for Manager Cockpit Analytics API (stabler/api/crm_analytics.py).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_crm_analytics -v
"""

from __future__ import annotations

import sys
import types
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


class TestCrmAnalytics(unittest.TestCase):
	fake = None
	frappe = None

	@classmethod
	def setUpClass(cls):
		cls.fake = _FakeFrappe()
		_load_api(cls.fake)
		# `stabler.api.crm_analytics` reaches `stabler.api.crm`, which imports the
		# REAL `stabler.api.organization` -> `stabler.www.stabler` -> `frappe.sessions`,
		# and that is a package import the fake `frappe` cannot answer. Stubbing the
		# one module is what lets this suite run in `make check` instead of only
		# behind a live bench.
		organization = types.ModuleType("stabler.api.organization")
		organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
		organization._can_access_module = lambda *_args, **_kwargs: True
		organization._user_allowed_companies = lambda _user: ["ACME"]
		_SANDBOX.install({"stabler.api.organization": organization})
		cls.frappe = sys.modules["frappe"]

	def setUp(self):
		self.fake.docs.clear()
		self.fake.created.clear()
		self.frappe.session.user = "crm_manager@acme.com"

		from stabler.api import crm, organization

		# Mock user roles to include Sales Manager / System Manager
		def _manager_roles(user=None):
			return ["System Manager", "Sales Manager"]

		sys.modules["frappe"].get_roles = _manager_roles
		if "stabler.api.crm" in sys.modules:
			sys.modules["stabler.api.crm"].frappe.get_roles = _manager_roles
			sys.modules["stabler.api.crm"]._user_allowed_companies = lambda _user: ["ACME"]

		organization._user_allowed_companies = lambda _user: ["ACME"]
		crm._user_allowed_companies = lambda _user: ["ACME"]

		# Add CRM Deal fixtures
		self.fake.docs[("CRM Deal", "DEAL-COCKPIT-1")] = _Doc(
			name="DEAL-COCKPIT-1",
			doctype="CRM Deal",
			company="ACME",
			organization="Alfa Corp",
			stage="priced",
			deal_type="Standard",
			contract_value=100000.0,
			probability=75.0,
			owner="rep1@acme.com",
			docstatus=0,
		)
		self.fake.docs[("CRM Deal", "DEAL-COCKPIT-FOREIGN")] = _Doc(
			name="DEAL-COCKPIT-FOREIGN",
			doctype="CRM Deal",
			company="OTHER_CO",
			organization="Beta Corp",
			stage="commit",
			deal_type="Standard",
			contract_value=500000.0,
			probability=90.0,
			owner="rep2@other.com",
			docstatus=0,
		)

	def test_get_manager_cockpit_metrics_returns_drillable_kpis(self):
		from stabler.api import crm_analytics

		res = crm_analytics.get_manager_cockpit_metrics(company="ACME")

		self.assertEqual(res["company"], "ACME")
		self.assertEqual(res["deal_count"], 1)
		self.assertEqual(res["total_value"], 100000.0)
		self.assertIn("stage_counts", res)
		self.assertIn("stage_aging", res)
		self.assertIn("rep_workload", res)

	def test_the_overhead_bucket_is_not_a_deal_in_the_cockpit(self):
		"""R9 (ADR-609). GENEL GIDER is a ledger bucket wearing a CRM Deal.

		It has no owner, no close date and never leaves its stage, so counting it
		inflates `deal_count`, plants a permanently ageing row in `stage_aging`
		and puts a phantom deal on a rep's workload — every cockpit number a
		manager steers by moves. `_crm_list` already keeps it off every board;
		the cockpit listed CRM Deal itself and so counted it.
		"""
		self.fake.docs[("CRM Deal", "DEAL-OVERHEAD")] = _Doc(
			name="DEAL-OVERHEAD",
			doctype="CRM Deal",
			company="ACME",
			organization="GENEL GIDER",
			stage="qualification",
			deal_type="Overhead",
			contract_value=0.0,
			probability=0.0,
			owner="Administrator",
			docstatus=0,
		)

		from stabler.api import crm_analytics

		res = crm_analytics.get_manager_cockpit_metrics(company="ACME")

		self.assertEqual(res["deal_count"], 1)
		self.assertNotIn("qualification", res["stage_counts"])
		self.assertNotIn("Administrator", res["rep_workload"])

	def test_get_manager_cockpit_metrics_rejects_unauthorized_company(self):
		from stabler.api import crm, crm_analytics, organization

		# Non-admin Sales Manager restricted to ACME
		def _sales_roles(user=None):
			return ["Sales Manager"]

		sys.modules["frappe"].get_roles = _sales_roles
		if "stabler.api.crm" in sys.modules:
			sys.modules["stabler.api.crm"].frappe.get_roles = _sales_roles
			sys.modules["stabler.api.crm"]._user_allowed_companies = lambda _user: ["ACME"]

		organization._user_allowed_companies = lambda _user: ["ACME"]

		with self.assertRaises(PermissionError):
			crm_analytics.get_manager_cockpit_metrics(company="OTHER_CO")

	def test_non_manager_crm_user_rejected_from_cockpit_analytics(self):
		from stabler.api import crm_analytics

		# Demote user role to plain user (no manager role)
		def _guest_roles(user=None):
			return ["Guest"]

		sys.modules["frappe"].get_roles = _guest_roles
		if "stabler.api.crm" in sys.modules:
			sys.modules["stabler.api.crm"].frappe.get_roles = _guest_roles

		with self.assertRaises(PermissionError):
			crm_analytics.get_manager_cockpit_metrics(company="ACME")


if __name__ == "__main__":
	unittest.main()
