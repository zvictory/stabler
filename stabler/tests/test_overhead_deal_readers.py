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

import json
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


class _OperationsDesk(unittest.TestCase):
	"""R17 — the tender desk means TENDERS, and the bucket is not one."""

	fake = None

	@classmethod
	def setUpClass(cls):
		cls.fake = _FakeFrappe()
		_load_api(cls.fake)
		organization = types.ModuleType("stabler.api.organization")
		organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
		organization._can_access_module = lambda *_args, **_kwargs: True
		organization._user_allowed_companies = lambda _user: [COMPANY]
		# `tender_desk` reaches its permission helpers through `stabler.api.tender`,
		# which the loader stubs as an empty module; the desk needs seven names off
		# it. Everything stubbed here is a GUARD — the rule under test is which
		# deals the desk reads, and a guard that let the wrong ones through would
		# be a different test.
		tender = sys.modules["stabler.api.tender"]
		tender._assert_company_scope = lambda *_args, **_kwargs: None
		tender._require_company = lambda company: company
		tender._require_tender = lambda *_args, **_kwargs: None
		tender._require_tender_view = lambda *_args, **_kwargs: None
		tender._tender_views = lambda _user: ["director"]
		tender._is_tender_oversight = lambda _user: True
		tender._parse_intake = lambda raw: json.loads(raw) if raw else {}
		approvals = types.ModuleType("stabler.api.approvals")
		approvals.is_approver = lambda *_args, **_kwargs: False
		approvals.list_pending = lambda *_args, **_kwargs: {
			"requests": [],
			"total": 0,
			"can_approve": False,
		}
		_SANDBOX.install({"stabler.api.organization": organization, "stabler.api.approvals": approvals})
		sys.modules["frappe.utils"].now = lambda: "2026-08-02 10:00:00"
		# Evicted, not merely imported: in the single-process registry pass another
		# module may already have bound these to the REAL frappe.
		_SANDBOX.evict("stabler.api.tender_desk", "stabler.api._desk_rules")
		import stabler.api.tender_desk

		cls.desk = sys.modules["stabler.api.tender_desk"]

	def setUp(self):
		self.fake.docs.clear()
		self.fake.created.clear()
		sys.modules["frappe"].session.user = "director@acme.com"
		self.fake.docs[("CRM Deal", "LOT-1")] = _Doc(
			name="LOT-1",
			doctype="CRM Deal",
			company=COMPANY,
			organization="Ministry of Roads",
			deal_type="Tender",
			owner="rep1@acme.com",
			docstatus=0,
		)
		# R19. A lot made through the tender screens. `save_deal_intake` never sets
		# `deal_type`, and v103 stamped every NULL to `Standard` for good, so this
		# is what a real tender lot looks like on the site: Standard, identified by
		# its intake. Measured on genesis-test.local — 484 deals carry
		# `custom_tender_intake` and NOT ONE of them is typed Tender.
		self.fake.docs[("CRM Deal", "LOT-INTAKE")] = _Doc(
			name="LOT-INTAKE",
			doctype="CRM Deal",
			company=COMPANY,
			organization="City Water Authority",
			deal_type="Standard",
			custom_tender_intake=json.dumps({"lot_no": "LOT-77", "assigned_to": "sourcing@acme.com"}),
			owner="rep1@acme.com",
			docstatus=0,
		)
		self.fake.docs[("CRM Deal", "DEAL-OVERHEAD")] = _Doc(
			name="DEAL-OVERHEAD",
			doctype="CRM Deal",
			company=COMPANY,
			organization="GENEL GIDER",
			deal_type="Overhead",
			owner="Administrator",
			docstatus=0,
		)

	def test_a_lot_identified_only_by_its_intake_is_still_on_the_desk(self):
		"""R19. The desk is narrowed by what is NOT a lot, never by `deal_type`.

		`_tender_deal_names` unions five criteria — a tagged SO/PO/quotation, an
		intake, a bid pricing plan, a parent tender, and only then
		`deal_type == "Tender"`. Narrowing this reader to the last of them drops
		every lot the tender screens made: measured on genesis-test.local,
		`team_load` fell from 553 to 1, and `deals_raw` feeds the whole desk —
		bid_due, delivery_due, orphan_lots, won_without_po, the plan, the
		decisions and the calendar all empty out with it, silently. A tender
		tenant loses its bid-deadline board and nothing says so.
		"""
		result = self.desk.operations_desk(company=COMPANY)

		self.assertIn(
			"sourcing@acme.com",
			[row["user"] for row in result["team_load"]],
			"a lot carrying an intake vanished from the desk",
		)

	def test_the_bucket_is_not_a_lot_on_anybodys_desk(self):
		"""The desk reads CRM Deal by company alone, so the bucket arrived as work.

		`assigned_to` falls back to `owner` and the result falls back to `status`,
		so the bucket lands in `team_load` as an open lot that will never close —
		against whoever happens to own the CRM Deal, usually Administrator.
		Measured on the test site: Administrator's `open_lots` went 553 -> 552 once
		the bucket was excluded. A workload board that counts a ledger row as work
		is a workload board nobody can act on.
		"""
		result = self.desk.operations_desk(company=COMPANY)

		self.assertEqual(
			[row["user"] for row in result["team_load"]],
			["rep1@acme.com", "sourcing@acme.com"],
			"the GENEL GİDER bucket was counted as somebody's open lot",
		)
		self.assertEqual([row["open_lots"] for row in result["team_load"]], [1, 1])


if __name__ == "__main__":
	unittest.main()
