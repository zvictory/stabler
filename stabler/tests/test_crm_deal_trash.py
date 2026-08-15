"""A deal must not be made undeletable by its own stage history.

`CRM Stage Event` is written on every lane move (`api/tender.py:move_deal_stage`)
and every status change (`api/crm.py:_insert_stage_event`), and it links the deal
twice — `deal` (reqd Link) and `reference_name` (Dynamic Link). Stabler registers
no `ignore_links_on_delete`, so `frappe.delete_doc("CRM Deal", …)` without `force`
hits `LinkExistsError` for any deal that was ever moved. Proven on production
mikas 2026-08-15: `docs/uat/evidence/2026-08-15-tender-crud-uat/` (`UAT-B3-DELETE`).

`clear_deal_stage_events` drops that history in `on_trash`, which
`frappe/model/delete_doc.py` runs at line 165 — before the link checks at 172-173.

What these tests defend, and why the obvious cheaper versions would not:

  1. The hook registration. The handler is dead code unless `hooks.py` names it,
     and nothing else in the suite would notice its removal.
  2. The delete is scoped to the one deal. A missing filter would silently wipe
     the whole tenant's audit log the first time anyone deletes anything.
  3. The handler must not go through `frappe.delete_doc`. `CRM Stage Event` is an
     immutable audit log whose controller throws in `on_trash`
     (crm_stage_event.py:72), so a "cleaner" rewrite to `delete_doc` would make
     every deal deletion fail — the exact bug this fixes, reintroduced.
  4. `delete_deal` must stay force-free. Passing `force=1` would also pass this
     module's other assertions while destroying the protection that still refuses
     to delete a deal referenced by a Tender Sourcing Decision, quotation, RFQ or
     order. That refusal is the deliberate semantic, not an accident.

`CRM Stage Event` was only half the blockade. `CRM Activity` links the deal too —
Dynamic Link only, so it is `check_if_doc_is_dynamically_linked` (delete_doc.py:173)
that raises, one line after the static check that the fix above cleared. The
static check firing first is why the production traceback named `CRM Stage Event`
and nothing else. `clear_deal_automation_activities` closes that half, and the
tests below defend the one thing that makes it safe: the filter deletes only the
rows a scheduler wrote, never the ones a rep did.
"""

from __future__ import annotations

import importlib
import inspect
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()

TRASH_HANDLER = "stabler.api.crm.clear_deal_stage_events"
ACTIVITY_HANDLER = "stabler.api.crm.clear_deal_automation_activities"


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _FakeDB:
	"""Records the writes the handler attempts, and nothing else."""

	def __init__(self, columns=True):
		self.deleted_rows = []
		self._columns = columns

	def delete(self, doctype, filters=None):
		self.deleted_rows.append((doctype, filters))

	def has_column(self, _doctype, _column):
		return self._columns


def _load_crm(db: _FakeDB):
	_SANDBOX.evict(
		"stabler.api.crm",
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.organization",
	)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.session = types.SimpleNamespace(user="rep@mikas.example")
	frappe.flags = types.SimpleNamespace()
	frappe.db = db
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	# Deliberately explosive: the handler reaching for the document API instead of
	# a raw row delete is the regression this module exists to catch.
	frappe.delete_doc = lambda *_args, **_kwargs: (_ for _ in ()).throw(
		AssertionError("clear_deal_stage_events must not call frappe.delete_doc")
	)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.now_datetime = lambda: None
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_args, **_kwargs: None
	common._assert_can_write = lambda *_args, **_kwargs: None
	common._require_company = lambda company: company

	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
	organization._can_access_module = lambda *_args, **_kwargs: True
	organization._user_allowed_companies = lambda _user: ["Mikas"]

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.organization": organization,
		}
	)
	return importlib.import_module("stabler.api.crm")


class TestTheHandlerIsRegistered(unittest.TestCase):
	def test_on_trash_names_the_handler(self):
		"""Unregistered, the handler is dead code and delete stays broken."""
		import stabler.hooks as hooks

		self.assertIn(TRASH_HANDLER, hooks.doc_events["CRM Deal"]["on_trash"])

	def test_on_trash_names_the_activity_handler_too(self):
		"""Stage events were only half the blockade; the other half is dynamic."""
		import stabler.hooks as hooks

		self.assertIn(ACTIVITY_HANDLER, hooks.doc_events["CRM Deal"]["on_trash"])

	def test_registration_does_not_displace_the_existing_validate_chain(self):
		import stabler.hooks as hooks

		validate = hooks.doc_events["CRM Deal"]["validate"]
		self.assertIn("stabler.api.crm.validate_crm_deal_hygiene", validate)
		self.assertIn("stabler.api.tender_master.validate_deal_parent_tender", validate)


class TestTheHandlerClearsOnlyThatDealsHistory(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.crm = _load_crm(self.db)

	def test_it_drops_the_stage_events_of_the_deal_being_trashed(self):
		doc = types.SimpleNamespace(name="CRM-DEAL-2026-00042")

		self.crm.clear_deal_stage_events(doc, "on_trash")

		self.assertEqual(
			self.db.deleted_rows,
			[("CRM Stage Event", {"deal": "CRM-DEAL-2026-00042"})],
		)

	def test_the_filter_names_the_deal_so_other_deals_keep_their_audit_trail(self):
		"""An unfiltered delete would wipe the tenant's whole stage log."""
		self.crm.clear_deal_stage_events(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)

		_doctype, filters = self.db.deleted_rows[0]
		self.assertTrue(filters, "the delete must be filtered")
		self.assertEqual(filters.get("deal"), "CRM-DEAL-2026-00042")

	def test_it_touches_nothing_but_crm_stage_event(self):
		self.crm.clear_deal_stage_events(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)

		self.assertEqual({doctype for doctype, _filters in self.db.deleted_rows}, {"CRM Stage Event"})

	def test_it_does_not_route_through_the_document_api(self):
		"""`CRM Stage Event` throws in its own `on_trash` (crm_stage_event.py:72)."""
		# `frappe.delete_doc` is wired to raise; a rewrite to it fails here.
		self.crm.clear_deal_stage_events(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)


class TestTheHandlerClearsAutomationActivitiesOnly(unittest.TestCase):
	"""`CRM Activity` holds two kinds of row and only one of them may be cascaded.

	`scheduled_daily_crm_automation` (hooks.py:97 → crm_automation.py:73) writes a
	row per matching rule per day, so a deal accumulates blockers it never asked
	for and every deal eventually becomes undeletable. But `create_crm_activity`
	(crm.py:650) is a whitelisted endpoint — a rep's own follow-up task lives in
	the same table, and cascading it would destroy authored work on delete.

	The two are separable because only the automation writer sets
	`custom_rule_name` (crm_automation.py:86). A rep cannot forge that marker:
	`create_crm_activity` runs the payload through `_mutable_payload`, which
	admits only `_ACTIVITY_MUTABLE_FIELDS` — no `custom_*` field is in it. The
	last test here pins that, because the day someone adds one, this handler
	starts deleting user-authored rows and nothing else would notice.
	"""

	def setUp(self):
		self.db = _FakeDB()
		self.crm = _load_crm(self.db)

	def test_it_drops_the_automation_activities_of_the_deal_being_trashed(self):
		doc = types.SimpleNamespace(name="CRM-DEAL-2026-00042")

		self.crm.clear_deal_automation_activities(doc, "on_trash")

		self.assertEqual(
			self.db.deleted_rows,
			[
				(
					"CRM Activity",
					{
						"reference_doctype": "CRM Deal",
						"reference_name": "CRM-DEAL-2026-00042",
						"custom_rule_name": ("is", "set"),
					},
				)
			],
		)

	def test_the_filter_keys_on_the_pair_the_dynamic_check_reads(self):
		"""`CRM Activity` has no static Link to the deal — only the pair.

		`check_if_doc_is_dynamically_linked` matches `reference_doctype` against
		the doctype and `reference_name` against the name (delete_doc.py,
		`get_dynamic_linked_docs`). A delete keyed on anything else leaves rows
		the check will still see, and the deal stays undeletable.
		"""
		self.crm.clear_deal_automation_activities(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)

		_doctype, filters = self.db.deleted_rows[0]
		self.assertEqual(filters.get("reference_doctype"), "CRM Deal")
		self.assertEqual(filters.get("reference_name"), "CRM-DEAL-2026-00042")

	def test_it_never_deletes_an_activity_a_person_wrote(self):
		"""The whole point of the handler being narrow. Losing this is data loss."""
		self.crm.clear_deal_automation_activities(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)

		_doctype, filters = self.db.deleted_rows[0]
		self.assertEqual(
			filters.get("custom_rule_name"),
			("is", "set"),
			"the automation marker must be part of the filter, or a rep's own "
			"follow-up task is deleted along with the deal",
		)

	def test_it_touches_nothing_but_crm_activity(self):
		self.crm.clear_deal_automation_activities(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)

		self.assertEqual({doctype for doctype, _filters in self.db.deleted_rows}, {"CRM Activity"})

	def test_it_does_not_route_through_the_document_api(self):
		"""`CRM Activity` throws in its own `on_trash` (crm_activity.py:37)."""
		# `frappe.delete_doc` is wired to raise; a rewrite to it fails here.
		self.crm.clear_deal_automation_activities(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)

	def test_it_deletes_nothing_before_the_v72_patch_has_run(self):
		"""A site mid-migrate has no `custom_rule_name` column.

		Filtering on a missing column is a SQL error inside `on_trash`, which
		would break *every* deal deletion on that site — a worse outage than the
		bug being fixed. Skipping is also the safe direction for the data: the
		deal refuses to delete instead of taking rows the handler cannot classify.
		"""
		db = _FakeDB(columns=False)
		crm = _load_crm(db)

		crm.clear_deal_automation_activities(types.SimpleNamespace(name="CRM-DEAL-2026-00042"), None)

		self.assertEqual(db.deleted_rows, [])

	def test_the_automation_marker_is_not_writable_through_the_public_endpoint(self):
		"""The separation rests on this: a rep cannot forge an automation row.

		If a `custom_*` field ever joins the mutable set, a user-authored activity
		becomes indistinguishable from a scheduler-written one and this handler
		silently deletes it.
		"""
		forgeable = [field for field in self.crm._ACTIVITY_MUTABLE_FIELDS if field.startswith("custom_")]

		self.assertEqual(
			forgeable,
			[],
			"a custom_* field in _ACTIVITY_MUTABLE_FIELDS lets a user forge the "
			"automation marker that clear_deal_automation_activities deletes on",
		)


class TestDeleteDealStillRefusesLinkedBusinessDocuments(unittest.TestCase):
	def setUp(self):
		self.crm = _load_crm(_FakeDB())

	def test_delete_deal_does_not_force(self):
		"""Force would delete deals that a sourcing decision or order still needs."""
		source = inspect.getsource(self.crm.delete_deal)

		self.assertIn('frappe.delete_doc("CRM Deal", name)', source)
		self.assertNotIn("force", source)


if __name__ == "__main__":
	unittest.main()
