"""Against a real bench: a deal's own stage history must not outlive the deal.

The frappe-free module (`test_crm_deal_trash.py`) can only prove the handler
issues the right row delete. It cannot prove the thing that actually broke:
whether Frappe's link integrity still refuses the deletion. That needs real
doctypes, real rows and the real `check_if_doc_is_linked` — hence this module,
which is deliberately kept out of `.github/frappe-free-tests.txt` so it is
collected by `make test-bench` only.

The order the fix depends on, from `frappe/model/delete_doc.py`:

    165:  doc.run_method("on_trash")
    172:  check_if_doc_is_linked(doc)            # only when `force` is falsy
    173:  check_if_doc_is_dynamically_linked(doc)

Every test here first proves the link IS detected without the handler. Without
that step a green result would mean nothing — the same green appears when the
fixture silently failed to create a stage event. Same discipline as
`test_lcv_integration.py:305-340`.
"""

import frappe
from frappe.exceptions import LinkExistsError
from frappe.model.delete_doc import check_if_doc_is_linked
from frappe.tests.utils import FrappeTestCase

from stabler.api._funnel import STAGES

TRASH_HANDLER = "stabler.api.crm.clear_deal_stage_events"
TENDER_STAGE = "go"


class TestCRMDealTrash(FrappeTestCase):
	def setUp(self):
		# `has_column`/`get_all` raise TableMissingError instead of returning empty
		# on a site without the crm app — probe the table first
		# (.claude/rules/20-backend-migrations.md).
		for doctype in ("CRM Deal", "CRM Stage Event", "CRM Organization", "CRM Deal Status"):
			if not frappe.db.table_exists(doctype):
				self.skipTest(f"site does not carry {doctype}")
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("a Company fixture is required")
		self.status = frappe.db.get_value("CRM Deal Status", {"type": "Open"}, "name")
		if not self.status:
			self.skipTest("an open CRM Deal Status fixture is required")
		self.organization = self._organization()
		self.trash = []
		self.deal = self._make_deal()

	def tearDown(self):
		"""Leave the site as found — a leaked deal poisons the next run's fixtures."""
		for name in self.trash:
			if frappe.db.exists("CRM Deal", name):
				frappe.db.delete("CRM Stage Event", {"deal": name})
				frappe.delete_doc("CRM Deal", name, force=True, ignore_permissions=True)

	def _organization(self) -> str:
		title = "UAT Trash Fixture"
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
		deal.status = self.status
		deal.insert(ignore_permissions=True, ignore_mandatory=True)
		self.trash.append(deal.name)
		return deal

	def _add_stage_event(self, deal_name: str) -> str:
		"""Write one lane-move event, exactly as `api/tender.py:2802` does.

		`axis` must be `tender_stage` and the destination must be a member of
		`_funnel.STAGES` — the controller validates both (crm_stage_event.py:47-58).
		"""
		self.assertIn(TENDER_STAGE, STAGES)
		event = frappe.new_doc("CRM Stage Event")
		event.update(
			{
				"company": self.company,
				"reference_doctype": "CRM Deal",
				"reference_name": deal_name,
				"deal": deal_name,
				"axis": "tender_stage",
				"to_tender_stage": TENDER_STAGE,
				"changed_at": frappe.utils.now_datetime(),
				"changed_by": frappe.session.user,
			}
		)
		event.insert(ignore_permissions=True)
		return event.name

	def _stage_event_count(self, deal_name: str) -> int:
		return frappe.db.count("CRM Stage Event", {"deal": deal_name})

	def test_the_handler_is_registered_under_on_trash(self):
		"""Unregistered, the handler is dead code and the delete stays broken."""
		registered = frappe.get_hooks("doc_events").get("CRM Deal", {}).get("on_trash", [])
		self.assertIn(TRASH_HANDLER, registered)

	def test_stage_history_blocks_the_delete_until_the_handler_runs(self):
		self._add_stage_event(self.deal.name)

		# Prove the link IS detected first, otherwise this test is a false green.
		with self.assertRaises(LinkExistsError):
			check_if_doc_is_linked(self.deal)

		frappe.get_attr(TRASH_HANDLER)(self.deal, "on_trash")

		check_if_doc_is_linked(self.deal)

	def test_a_deal_that_changed_lane_can_actually_be_deleted(self):
		"""The end-to-end claim: this is the delete that failed on production mikas."""
		name = self.deal.name
		self._add_stage_event(name)
		self.assertEqual(self._stage_event_count(name), 1)

		frappe.delete_doc("CRM Deal", name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("CRM Deal", name))
		self.assertEqual(self._stage_event_count(name), 0)

	def test_deleting_one_deal_leaves_another_deals_history_intact(self):
		"""An unfiltered delete would take the whole tenant's audit log with it."""
		other = self._make_deal()
		self._add_stage_event(other.name)
		self._add_stage_event(self.deal.name)

		frappe.delete_doc("CRM Deal", self.deal.name, ignore_permissions=True)

		self.assertEqual(self._stage_event_count(other.name), 1)

	def test_a_linked_business_document_still_refuses_the_delete(self):
		"""Zafar's semantic: clear your own history, keep refusing real work.

		`Tender Sourcing Decision` is inserted with its own controller bypassed —
		its award policy ("5 quotations / 2 countries") is a separate invariant
		with its own tests, and satisfying it here would mean building supplier
		quotations that this test never reads. What is under test is a real row
		holding a real Link to the deal; link integrity reads no other field.
		"""
		if not frappe.db.table_exists("Tender Sourcing Decision"):
			self.skipTest("site does not carry Tender Sourcing Decision")
		self._add_stage_event(self.deal.name)
		decision = frappe.new_doc("Tender Sourcing Decision")
		decision.company = self.company
		decision.deal = self.deal.name
		decision.flags.ignore_validate = True
		decision.insert(ignore_permissions=True, ignore_mandatory=True)

		frappe.get_attr(TRASH_HANDLER)(self.deal, "on_trash")

		# History gone, but the business document must still block the delete.
		self.assertEqual(self._stage_event_count(self.deal.name), 0)
		with self.assertRaises(LinkExistsError):
			check_if_doc_is_linked(self.deal)

		frappe.delete_doc("Tender Sourcing Decision", decision.name, force=True, ignore_permissions=True)
