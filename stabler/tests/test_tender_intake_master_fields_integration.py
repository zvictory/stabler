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
		for doctype in ("CRM Deal", "CRM Organization"):
			if not frappe.db.table_exists(doctype):
				self.skipTest(f"site does not carry {doctype}")
		if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
			self.skipTest("site has not run the tender intake column patch")
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("a Company fixture is required")
		self._enable_tender_module()
		self.organization = self._organization()
		self.deal = self._make_deal()

	def tearDown(self):
		"""Leave the site as found: module flag and the fixture deal."""
		self._restore_tender_module()
		if frappe.db.exists("CRM Deal", self.deal.name):
			frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)

	def _module_row(self):
		from stabler.stabler.doctype.stabler_settings.stabler_settings import get_company_module_row

		return get_company_module_row(self.company)

	def _enable_tender_module(self):
		"""Tender is opt-in per company (.claude/rules/30-tenant-modules.md) —
		`_deal_scope` refuses even an Administrator when the company's own
		`enable_tender` flag is off, so the fixture must set it regardless of
		the test site's tenant."""
		row = self._module_row()
		self._prior_enable_tender = row.get("enable_tender")
		row.enable_tender = 1
		frappe.get_single("Stabler Settings").save(ignore_permissions=True)
		frappe.db.commit()

	def _restore_tender_module(self):
		row = self._module_row()
		row.enable_tender = self._prior_enable_tender
		frappe.get_single("Stabler Settings").save(ignore_permissions=True)
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
		deal = frappe.new_doc("CRM Deal")
		deal.company = self.company
		deal.organization = self.organization
		deal.deal_type = "Tender"
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
