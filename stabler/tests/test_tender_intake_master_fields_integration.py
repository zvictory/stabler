"""Against a real bench: the tender master fields survive the actual
`save_deal_intake` → `deal_intake` round trip, not just `_clean_intake` called
in isolation.

`test_tender_intake_master_fields.py` already proves the whitelist logic
itself — `_clean_intake` has no DB dependency, so it stays frappe-free and
runs under `make test`. What that module cannot see is whether the real
endpoints round-trip the same values through an actual `frappe.db.set_value` /
`frappe.db.get_value` write and a real `custom_tender_intake` column: company
scope, module gating, and permission checks all run for real here, none of
them faked. This is the same gap `test_crm_deal_trash_integration.py`
documents for the delete path, and the same fix: a second module, deliberately
kept out of `.github/frappe-free-tests.txt` so it is collected by
`make test-bench` only.

Reproduces the shape of the production defect measured on mikas 2026-08-15
(`docs/uat/evidence/2026-08-15-tender-crud-uat/README.md`, `UAT-A3-EDIT-OPEN` /
`UAT-A3-EDIT-SAVE`): create a tender with a title, save an unrelated intake
edit, and confirm the title is still the one the user typed — not blank, and
never the organization name (that substitution happens client-side in
`TenderMasterDrawer.vue`, out of reach from here; `test_tender_master_drawer_source.py`
covers that half).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api import tender

_MASTER_FIELDS = {
	"title": "Real Tender Title — ЁЖ 2026",
	"tender_no": "TN-2026-00099",
	"source": "UZEX",
	"publication_date": "2026-08-01",
	"submission_deadline": "2026-08-20",
	"currency": "USD",
	"estimated_total": "15000.50",
}


class TestTenderIntakeMasterFieldsRoundTrip(FrappeTestCase):
	def setUp(self):
		# `has_column`/`table_exists` probes first -- a site without the crm app
		# must read as "not applicable", not as a failed migrate
		# (.claude/rules/20-backend-migrations.md).
		for doctype in ("CRM Deal", "CRM Organization", "CRM Deal Status"):
			if not frappe.db.table_exists(doctype):
				self.skipTest(f"site does not carry {doctype}")
		if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
			self.skipTest("site has not run the tender intake column patch")
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("a Company fixture is required")
		self.status = frappe.db.get_value("CRM Deal Status", {"type": "Open"}, "name")
		if not self.status:
			self.skipTest("an open CRM Deal Status fixture is required")
		self._enable_tender_module()
		self.organization = self._organization()
		self.deal = self._make_deal()

	def tearDown(self):
		"""Leave the site as found: module flag and the fixture deal."""
		self._restore_tender_module()
		if frappe.db.exists("CRM Deal", self.deal.name):
			frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)

	def _enable_tender_module(self):
		"""Tender is opt-in per company (.claude/rules/30-tenant-modules.md) —
		`_deal_scope` refuses even an Administrator when the company's own
		`enable_tender` flag is off, so the fixture must set it regardless of
		the test site's tenant.

		A child-table row lives only inside the parent `Document` instance
		that read it out of the DB — it carries `parentfield`/`parenttype`
		names, not a live back-reference. An earlier version of this method
		read the row through `get_company_module_row` (which owns its own
		internal `frappe.get_single(...)` call), mutated that row, then
		called `frappe.get_single("Stabler Settings")` *again* and saved
		that — a second, independent fetch the mutation never touched. The
		save persisted the site's unchanged state and the flip silently
		didn't happen (`enable_tender` stayed 0, the `Stabler Company
		Modules` default), which is what production caught: `save_deal_intake`
		re-reads `module_map_for` fresh a moment later and throws. Fetching
		once and saving that same instance is the fix.
		"""
		from stabler.stabler.doctype.stabler_settings.stabler_settings import _default_enable_row

		settings = frappe.get_single("Stabler Settings")
		row = next((r for r in settings.company_modules or [] if r.company == self.company), None)
		self._created_module_row = row is None
		if row is None:
			row = settings.append("company_modules", _default_enable_row(self.company))
		self._prior_enable_tender = row.get("enable_tender")
		row.enable_tender = 1
		settings.save(ignore_permissions=True)
		frappe.db.commit()

	def _restore_tender_module(self):
		"""Leave the site as found: drop a row this fixture created, or put
		back the flag's prior value on one that already existed."""
		settings = frappe.get_single("Stabler Settings")
		row = next((r for r in settings.company_modules or [] if r.company == self.company), None)
		if row is None:
			return
		if self._created_module_row:
			settings.remove(row)
		else:
			row.enable_tender = self._prior_enable_tender
		settings.save(ignore_permissions=True)
		frappe.db.commit()

	def _organization(self) -> str:
		title = "UAT Tender Intake Master Fields Fixture"
		existing = frappe.db.exists("CRM Organization", {"organization_name": title})
		if existing:
			return existing
		org = frappe.new_doc("CRM Organization")
		org.organization_name = title
		org.insert(ignore_permissions=True, ignore_mandatory=True)
		return org.name

	def _make_deal(self):
		"""Deliberately NOT `deal_type = "Tender"`.

		`save_deal_intake`/`deal_intake` (what this module tests) never read
		`deal_type` -- checked, it appears nowhere in `_deal_scope` or
		`_clean_intake`. But `hooks.py`'s `CRM Deal` `validate` list also
		carries `tender_master.validate_deal_parent_tender`, which throws for
		a NEW `deal_type="Tender"` deal with no `custom_parent_tender`, once
		the company's tender module is on (`api/tender_master.py:403-432`) --
		which this fixture now genuinely turns on. In real production that
		parent link is created transparently by `crm.save_deal`'s
		`_apply_tender_parent_link` (`api/crm.py:152`), which this fixture
		does not go through (it writes the CRM Deal directly, the same way
		`test_crm_deal_trash_integration.py` does). Reproducing that whole
		Tender Master auto-creation here would pull in a parallel, largely
		superseded subsystem (see `test_tender_flow_contract.py`'s "tek
		seviyeli mimaride lot kavramı yok") this module has nothing to do
		with -- so the simplest correct fixture is a plain CRM Deal.

		`status` / `deal_owner` / `next_action_at` are set because
		`crm.validate_crm_deal_hygiene` (the other `CRM Deal` validate hook)
		requires an owner and a dated next action on an open deal whenever
		the site-wide `Stabler Settings.enforce_crm_next_action` switch is
		on -- a global setting this fixture cannot see from here, so it
		satisfies the requirement unconditionally rather than gamble on it.
		"""
		deal = frappe.new_doc("CRM Deal")
		deal.company = self.company
		deal.organization = self.organization
		deal.status = self.status
		deal.deal_owner = frappe.session.user
		deal.next_action_at = frappe.utils.now_datetime()
		deal.insert(ignore_permissions=True, ignore_mandatory=True)
		return deal

	def test_master_fields_survive_save_deal_intake_then_deal_intake(self):
		"""The whole point: what `TenderMasterDrawer.vue` sends must be what it
		reads back, through the real whitelisted endpoints end to end."""
		tender.save_deal_intake(deal=self.deal.name, intake=dict(_MASTER_FIELDS, lot_no="LOT-1"))

		result = tender.deal_intake(deal=self.deal.name)

		intake = result["intake"]
		for key, value in _MASTER_FIELDS.items():
			with self.subTest(key=key):
				if key == "estimated_total":
					self.assertEqual(intake[key], 15000.5)
				else:
					self.assertEqual(intake[key], value)

	def test_title_survives_a_later_unrelated_intake_edit(self):
		"""The exact production sequence: create with a title, then an
		ordinary intake edit (a lot-level field, nothing to do with the
		title) must not erase it."""
		tender.save_deal_intake(deal=self.deal.name, intake=dict(_MASTER_FIELDS, lot_no="LOT-1"))

		tender.save_deal_intake(deal=self.deal.name, intake=dict(_MASTER_FIELDS, lot_no="LOT-1-updated"))

		result = tender.deal_intake(deal=self.deal.name)
		self.assertEqual(result["intake"]["title"], _MASTER_FIELDS["title"])
		self.assertEqual(result["intake"]["lot_no"], "LOT-1-updated")
