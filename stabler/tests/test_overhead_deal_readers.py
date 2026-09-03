"""ADR-609 — every CRM Deal reader keeps the GENEL GİDER bucket out of its answer.

WHY this file exists. `exclude_overhead_deals` says it is "shared by every CRM
Deal reader", and that sentence is the whole safety of the design: the bucket is
a ledger row wearing a CRM Deal, with no owner, no close date and no stage it
will ever leave. Any list that counts it reports a deal nobody can work — one
extra on the board, a permanently ageing row in stage aging, a phantom on a
rep's workload, an automation alert for a deal that cannot be actioned.

The claim used to be pinned by `assertIn("exclude_overhead_deals(filters)", …)`
against `crm.py`. That is a declaration-satisfiable assertion: it went green
while three of the five readers had never called the helper, because one caller
somewhere in the file satisfied the string. Measured on the test site,
`crm_metrics` answered `deal_count` 553 while `list_deals` answered 552 for the
same company on the same screen.

So each reader is DRIVEN here, against a fixture bucket that must not come back.
`get_manager_cockpit_metrics` is covered the same way in `test_crm_analytics`
and is not repeated.

    PYTHONPATH=$PWD python -m unittest stabler.tests.test_overhead_deal_readers -v

DOM-less and bench-free: the readers run against the `test_sourcing_api` double.
"""

from __future__ import annotations

import sys
import types
import unittest

from stabler.tests.test_sourcing_api import _SANDBOX, _Doc, _FakeFrappe, _load_api


def tearDownModule():
	"""`_load_api` evicts the real `frappe` process-wide; borrowing it means
	handing it back. Without this the fake outlives the suite and `bench
	run-tests` dies in its own `_cleanup_after_tests`."""
	_SANDBOX.restore()


COMPANY = "ACME"


class _Readers(unittest.TestCase):
	"""One tender company, one workable deal, one GENEL GİDER bucket."""

	fake = None

	@classmethod
	def setUpClass(cls):
		cls.fake = _FakeFrappe()
		_load_api(cls.fake)
		# `stabler.api.crm` reaches the real `organization` → `www.stabler` →
		# `frappe.sessions`, which the fake `frappe` cannot answer. Same stub as
		# `test_crm_analytics`, and the reason this suite runs in `make check`.
		organization = types.ModuleType("stabler.api.organization")
		organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
		organization._can_access_module = lambda *_args, **_kwargs: True
		organization._user_allowed_companies = lambda _user: [COMPANY]
		_SANDBOX.install({"stabler.api.organization": organization})
		# `crm_metrics` imports this one inside the function; the shared loader
		# only carries the names the sourcing tests need at import time.
		sys.modules["frappe.utils"].get_first_day = lambda _value: "2026-08-01"
		# Imported HERE, after the stubs are in place: `_load_api` evicted these
		# so they rebuild against the fake, and `crm` binds
		# `_user_allowed_companies` by name at import time.
		import stabler.api.crm
		import stabler.api.crm_automation

		sys.modules["stabler.api.crm"]._user_allowed_companies = lambda _user: [COMPANY]

	def setUp(self):
		self.fake.docs.clear()
		self.fake.created.clear()
		frappe = sys.modules["frappe"]
		frappe.session.user = "manager@acme.com"
		frappe.get_roles = lambda user=None: ["System Manager", "Sales Manager"]
		for name in ("stabler.api.crm", "stabler.api.crm_automation"):
			module = sys.modules.get(name)
			if module is not None:
				module.frappe.get_roles = frappe.get_roles

		self.fake.docs[("CRM Deal", "DEAL-WORKABLE")] = _Doc(
			name="DEAL-WORKABLE",
			doctype="CRM Deal",
			company=COMPANY,
			organization="Alfa Corp",
			deal_type="Standard",
			status="Open",
			stage="priced",
			deal_owner="rep1@acme.com",
			owner="rep1@acme.com",
			expected_monthly_volume=100.0,
			# Old enough to trip the stale-deal rule, and a deadline already past.
			last_activity_date="2026-07-01",
			deadline="2026-07-15",
			docstatus=0,
		)
		# The bucket, given exactly the two fields that would make the automation
		# engine act on it. It is inert on the live site today only because it
		# happens to carry neither — a reader that relies on that is one CRM
		# import away from paging somebody about GENEL GİDER.
		self.fake.docs[("CRM Deal", "DEAL-OVERHEAD")] = _Doc(
			name="DEAL-OVERHEAD",
			doctype="CRM Deal",
			company=COMPANY,
			organization="GENEL GIDER",
			deal_type="Overhead",
			status="Open",
			stage="qualification",
			deal_owner="Administrator",
			owner="Administrator",
			expected_monthly_volume=0.0,
			last_activity_date="2026-07-01",
			deadline="2026-07-15",
			docstatus=0,
		)

	def test_the_board_list_does_not_offer_the_bucket_as_a_deal(self):
		from stabler.api import crm

		result = crm.list_deals(company=COMPANY)

		names = [row["name"] for row in result["deals"]]
		self.assertEqual(names, ["DEAL-WORKABLE"])
		self.assertEqual(result["total"], 1, "the board's own count included the bucket")

	def test_the_pipeline_metrics_do_not_count_the_bucket(self):
		"""`deal_count` and `activation_rate` are the board's headline figures.

		The bucket is never won, so every extra one drags the activation rate
		down by a deal that was never winnable.
		"""
		from stabler.api import crm

		metrics = crm.crm_metrics(company=COMPANY)

		self.assertEqual(metrics["deal_count"], 1, "the bucket was counted as a deal")

	def test_the_automation_engine_does_not_raise_an_alert_about_the_bucket(self):
		"""A bucket with a passed deadline generates an SLA alert about a deal
		nobody can act on, addressed to whoever happens to own it."""
		from stabler.api import crm_automation

		result = crm_automation.run_crm_automation_rules(company=COMPANY, dry_run=True)

		flagged = {action["deal"] for action in result["actions"]}
		self.assertIn("DEAL-WORKABLE", flagged, "the fixture no longer trips any rule")
		self.assertNotIn("DEAL-OVERHEAD", flagged, "the engine raised an alert about the bucket")


if __name__ == "__main__":
	unittest.main()
