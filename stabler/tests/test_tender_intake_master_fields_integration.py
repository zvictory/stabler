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

Since 2026-08-25 this module also carries the ADR-202/203/205 contract, for
the same reason. `test_tender_intake_contract.py` proves those rules on
`_clean_intake` in isolation, but three of them are only observable through
the endpoint. The refusal of an out-of-contract key IS a `frappe.throw`, and
`frappe.throw` needs `frappe.local`, which a site-free process never binds --
so nothing under `make test` can assert that a bad payload is refused, nor
the half that actually matters: that a refused payload wrote nothing. The
deadline chain is the same. The bid milestone is built inside
`_deal_deadlines`, which queries Sales Order and Purchase Order before it
can return, so defect #4 closes against a real database or not at all.
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


class _IntakeBenchFixture:
	"""setUp/tearDown and the helpers both test classes below need.

	A plain mixin, deliberately NOT a `FrappeTestCase` subclass, so unittest
	does not collect it as a test class of its own. Copying the fixture into a
	second module was the alternative, and this repository has already measured
	what that costs: four copies of the rsync exclude list, all of them
	disagreeing by the time anyone read them.
	"""

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


class TestTenderIntakeMasterFieldsRoundTrip(_IntakeBenchFixture, FrappeTestCase):
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


# --------------------------------------------------------------------------- #
# ADR-202 / 203 / 205 — the contract, as the endpoint actually enforces it
# --------------------------------------------------------------------------- #
_PO_BOARD_INTAKE = {
	"lot_no": "LOT-9",
	"buyer": "Uzbekgidroenergo",
	"volume": "120",
	"unit": "m3",
	"delivery_deadline": "2026-11-01",
	"notes": "call the buyer before the site visit",
}

# What a browser that predates 2026-08-28 still sends. The PO board panel no
# longer has a checklist editor, but a tab opened before the deploy holds the
# old bundle — and the empty list is the dangerous half, because honouring it
# would delete the rows together with their uploads and waivers.
_STALE_PO_BOARD_INTAKE = dict(_PO_BOARD_INTAKE, documents=[])

_CHECKLIST = [
	{"key": "gtd", "label": "ГТД", "required": 1, "role": "customs"},
	{"key": "contract", "label": "Shartnoma", "required": 1},
]

_DRAWER_INTAKE = {
	"title": "Real Tender Title — ЁЖ 2026",
	"tender_no": "TN-2026-00099",
	"source": "UZEX",
	"publication_date": "2026-08-01",
	"currency": "USD",
	"estimated_total": "15000.50",
	# Section E — pre-win evaluation, moved off the PO board by ADR-206.
	"guarantee_amount": "1500000",
	"guarantee_return": "2026-12-01",
	"cert_required": 1,
	"penalty_pct_per_day": "0.5",
	"go_no_go": "go",
	"purchase_method": "tender",
	"items": [
		{"item_code": "RAIL-01", "item_name": "Rail 01", "qty": 2, "uom": "Nos", "rate": 10, "amount": 20}
	],
	"tender_files": [{"file_name": "lot.pdf", "file_url": "/files/lot.pdf", "file_size": 2048}],
}


class TestTheEndpointRefusesWhatItCannotStore(_IntakeBenchFixture, FrappeTestCase):
	"""ADR-202/2. Only reachable here: the refusal is a `frappe.throw`, and
	`frappe.throw` is unraisable without `frappe.local`."""

	def test_an_out_of_contract_key_is_refused_and_named(self):
		"""Naming the key is the whole value. `title` sat outside the whitelist
		for months and cost a production incident precisely because nothing
		said so — the save reported success and the field came back wrong."""
		with self.assertRaises(frappe.ValidationError) as caught:
			tender.save_deal_intake(deal=self.deal.name, intake={"lot_no": "LOT-1", "budget": 5})
		self.assertIn("budget", str(caught.exception))

	def test_a_refused_payload_writes_nothing(self):
		"""The half that matters, and the half no unit test can see: refusing
		must be refusing, not "throw after a partial write". If the throw landed
		downstream of `frappe.db.set_value` the user would get an error *and* a
		mutated record — strictly worse than the silent drop it replaced."""
		tender.save_deal_intake(deal=self.deal.name, intake={"lot_no": "LOT-KEEP"})
		with self.assertRaises(frappe.ValidationError):
			tender.save_deal_intake(deal=self.deal.name, intake={"lot_no": "LOT-GONE", "budget": 5})
		self.assertEqual(tender.deal_intake(deal=self.deal.name)["intake"]["lot_no"], "LOT-KEEP")

	def test_the_retired_deadline_key_is_still_accepted(self):
		"""ADR-203's transition clause, end to end. One deploy swaps the API and
		the bundle together, but a tab opened before it still holds the old
		bundle — rejecting `submission_deadline` would turn that tab's every Save
		into an error until the user happened to reload."""
		result = tender.save_deal_intake(deal=self.deal.name, intake={"submission_deadline": "2026-09-01"})
		self.assertEqual(result["intake"]["submission_deadline"], "2026-09-01")


class TestAPartialSaveKeepsTheOtherScreensWork(_IntakeBenchFixture, FrappeTestCase):
	"""ADR-202/3 and ADR-205, through the real `custom_tender_intake` column.

	Two screens write this one blob and neither sends all of it. The unit tests
	prove `_clean_intake` merges correctly; only this module proves the merged
	result is what the column ends up holding and what the next read returns."""

	def test_a_drawer_shaped_save_keeps_the_po_board_fields(self):
		"""The production defect in one sequence: sourcing fills the lot in the
		PO board panel, someone opens the kanban drawer and presses Save, and
		everything sourcing entered is gone."""
		tender.save_deal_intake(deal=self.deal.name, intake=dict(_PO_BOARD_INTAKE))

		tender.save_deal_intake(deal=self.deal.name, intake=dict(_DRAWER_INTAKE))

		intake = tender.deal_intake(deal=self.deal.name)["intake"]
		self.assertEqual(intake["lot_no"], "LOT-9")
		self.assertEqual(intake["buyer"], "Uzbekgidroenergo")
		self.assertEqual(intake["unit"], "m3")
		self.assertEqual(intake["delivery_deadline"], "2026-11-01")
		self.assertEqual(intake["notes"], "call the buyer before the site visit")
		# and the drawer's own fields did land
		self.assertEqual(intake["title"], _DRAWER_INTAKE["title"])

	def test_a_po_board_save_keeps_the_drawer_s_decision(self):
		"""The same defect the other way round, and it is new: until ADR-206 the
		decision was entered on the PO board, so a PO board save could not lose
		it. Now the drawer owns it and this panel sits on a board a user leaves
		open for hours — the sequence that has to survive is: director records
		Go in the drawer at 11:00, sourcing saves a lot number here at 11:05."""
		tender.save_deal_intake(deal=self.deal.name, intake=dict(_DRAWER_INTAKE))

		tender.save_deal_intake(deal=self.deal.name, intake=dict(_PO_BOARD_INTAKE))

		intake = tender.deal_intake(deal=self.deal.name)["intake"]
		self.assertEqual(intake["go_no_go"], "go")
		self.assertEqual(intake["guarantee_amount"], 1500000.0)
		self.assertEqual(intake["guarantee_return"], "2026-12-01")
		self.assertEqual(intake["cert_required"], 1)
		self.assertEqual(intake["penalty_pct_per_day"], 0.5)
		self.assertEqual(intake["purchase_method"], "tender")
		# and the PO board's own field did land
		self.assertEqual(intake["lot_no"], "LOT-9")

	def test_no_intake_save_can_touch_the_document_checklist(self):
		"""ADR-205 / defect #2, closed on both sides.

		The requirement rows carry the uploaded files and the waiver
		justifications, so losing the rows loses those with them. The checklist
		is seeded the way it is now actually created — through the document
		centre's writer, against this real database — and then survives two
		saves that used to be able to empty it: a drawer-shaped one that never
		mentions the key, and a stale PO-board tab that sends an empty list.

		The second is the one that only works here. `_clean_intake` alone can
		be asked what it returns; only the endpoint can prove the stored column
		still holds the rows afterwards."""
		from stabler.api import tender_documents

		tender_documents.set_tender_document_requirements(
			deal=self.deal.name, requirements=_CHECKLIST, company=self.company
		)

		tender.save_deal_intake(deal=self.deal.name, intake=dict(_DRAWER_INTAKE))
		docs = tender.deal_intake(deal=self.deal.name)["intake"]["documents"]
		self.assertEqual([d["key"] for d in docs], ["gtd", "contract"])

		tender.save_deal_intake(deal=self.deal.name, intake=dict(_STALE_PO_BOARD_INTAKE))
		docs = tender.deal_intake(deal=self.deal.name)["intake"]["documents"]
		self.assertEqual([d["key"] for d in docs], ["gtd", "contract"], "bayat sekme listeyi sildi")

	def test_an_unrelated_save_does_not_reissue_the_go_no_go_stamp(self):
		"""Preserving a decision must preserve when it was made. Re-stamping on
		every save would make the audit trail claim the director decided at the
		moment an unrelated user edited an item line."""
		first = tender.save_deal_intake(deal=self.deal.name, intake=dict(_DRAWER_INTAKE))
		stamped_at = first["intake"]["go_no_go_at"]
		self.assertTrue(stamped_at)

		tender.save_deal_intake(deal=self.deal.name, intake=dict(_PO_BOARD_INTAKE))

		intake = tender.deal_intake(deal=self.deal.name)["intake"]
		self.assertEqual(intake["go_no_go_at"], stamped_at)
		self.assertEqual(intake["go_no_go_by"], first["intake"]["go_no_go_by"])


class TestTheBidDeadlineReachesTheTimeline(_IntakeBenchFixture, FrappeTestCase):
	"""ADR-203 / defect #4. `_deal_deadlines` queries Sales Order and Purchase
	Order before it can build a single milestone, so the chain from the saved
	key to the chip the user sees is only observable against a database."""

	def _bid_milestone(self, payload: dict) -> dict:
		result = tender.save_deal_intake(deal=self.deal.name, intake=payload)
		milestones = result["deadlines"]["milestones"]
		return next(m for m in milestones if m["key"] == "bid")

	def test_the_bid_milestone_shows_the_key_the_drawer_now_writes(self):
		"""Before the rename the drawer wrote `submission_deadline` and this
		milestone read `bid_deadline`, so a tender entered through the drawer
		read "not set" and never raised an SLA warning, however close its
		deadline was."""
		due = frappe.utils.add_days(frappe.utils.today(), 30)
		milestone = self._bid_milestone({"bid_deadline": due})
		self.assertEqual(milestone["date"], str(due))
		self.assertEqual(milestone["days_left"], 30)
		self.assertEqual(milestone["status"], "good")

	def test_a_record_written_before_the_rename_still_shows_its_deadline(self):
		"""Every tender saved by the previous bundle carries only the old key.
		Without the read tolerance, shipping the rename would blank their bid
		chips — a regression introduced by the fix for the same defect."""
		due = frappe.utils.add_days(frappe.utils.today(), 3)
		milestone = self._bid_milestone({"submission_deadline": due})
		self.assertEqual(milestone["date"], str(due))
		self.assertEqual(milestone["status"], "warn")

	def test_a_tender_with_neither_key_reads_as_not_set(self):
		""" "Not set" and "overdue" must stay distinguishable: a falsy deadline
		that fell through to the epoch would paint every such tender red."""
		milestone = self._bid_milestone({"lot_no": "LOT-1"})
		self.assertIsNone(milestone["date"])
		self.assertEqual(milestone["status"], "none")


class TestTheUploadedPackIsStored(_IntakeBenchFixture, FrappeTestCase):
	def test_tender_files_survive_the_endpoint_round_trip(self):
		"""ADR-202/1. The drawer uploads the tender pack and reads it back from
		`tender_files` — a key neither whitelist carried, so the read-back was
		always empty and the upload looked like it had never happened."""
		tender.save_deal_intake(deal=self.deal.name, intake=dict(_DRAWER_INTAKE))

		files = tender.deal_intake(deal=self.deal.name)["intake"]["tender_files"]
		self.assertEqual([f["file_url"] for f in files], ["/files/lot.pdf"])
		self.assertEqual(files[0]["file_name"], "lot.pdf")

	def test_a_later_po_board_save_does_not_detach_the_pack(self):
		"""The PO board panel never sends this key; under the old rebuild rule
		that alone was enough to drop the whole pack."""
		tender.save_deal_intake(deal=self.deal.name, intake=dict(_DRAWER_INTAKE))

		tender.save_deal_intake(deal=self.deal.name, intake=dict(_PO_BOARD_INTAKE))

		files = tender.deal_intake(deal=self.deal.name)["intake"]["tender_files"]
		self.assertEqual(len(files), 1)
