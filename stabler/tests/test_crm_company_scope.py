"""Behaviour contracts for company-scoped CRM APIs.

The fake runtime models company and record permissions independently.  The
tests exercise public CRM APIs, including aggregate values that must never be
computed from invoices the current user cannot read.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import date, datetime


class _Doc(dict):
	def __init__(self, **values):
		super().__init__(values)
		object.__setattr__(self, "saved", False)

	def __getattr__(self, field):
		return self.get(field)

	def __setattr__(self, field, value):
		if field == "saved":
			object.__setattr__(self, field, value)
			return
		self[field] = value

	def update(self, values):
		super().update(values)

	def save(self, **_kwargs):
		self.saved = True

	def insert(self, ignore_permissions=False):
		self.saved = True
		return self

	def as_dict(self):
		return dict(self)

	def db_set(self, field, value):
		self[field] = value

	def reload(self):
		return self


class _FakeDB:
	def __init__(self):
		self.docs = {
			("CRM Lead", "LEAD-MIKAS"): _Doc(name="LEAD-MIKAS", company="Mikas", first_name="Amina"),
			("CRM Lead", "LEAD-OTHER"): _Doc(name="LEAD-OTHER", company="Other", first_name="Other"),
			(
				"CRM Deal",
				"DEAL-MIKAS",
			): _Doc(
				name="DEAL-MIKAS",
				company="Mikas",
				organization="Mikas Shop",
				linked_customer="CUST-MIKAS",
				status="Open",
				deal_owner="rep@mikas.example",
			),
			("CRM Deal", "DEAL-OTHER"): _Doc(name="DEAL-OTHER", company="Other", organization="Other Shop"),
		}
		self.deleted: list[tuple[str, str]] = []
		self.created: list[_Doc] = []
		self.get_list_calls: list[tuple[str, dict]] = []
		self.enforce_crm_next_action = False
		self.status_on_lock: str | None = None
		self.rename_calls: list[tuple[str, str, str]] = []
		self.require_locked_deal_reads = False

	def exists(self, doctype, name):
		if doctype == "CRM Organization" and isinstance(name, dict):
			organization_name = name.get("organization_name")
			return next(
				(
					doc.get("name") or doc.get("organization_name")
					for doc in self.created
					if doc.get("doctype") == doctype and doc.get("organization_name") == organization_name
				),
				None,
			)
		if doctype == "Company":
			return name in {"Mikas", "Other"}
		if doctype == "Customer":
			return name == "CUST-MIKAS"
		if doctype == "CRM Deal Status":
			return name in {"Open", "Qualified", "Won", "Lost"}
		return (doctype, name) in self.docs

	def get_value(self, doctype, name, field):
		if doctype == "CRM Deal Status" and field == "type":
			return {"Won": "Won", "Lost": "Lost"}.get(name, "Open")
		doc = self.docs.get((doctype, name))
		return doc.get(field) if doc else None

	def get_single_value(self, doctype, field):
		if doctype == "Stabler Settings" and field == "enforce_crm_next_action":
			return self.enforce_crm_next_action
		return None

	def sql(self, query, values=None, as_dict=False):
		if "tabCRM Deal" in query and "FOR UPDATE" in query:
			deal = self.docs[("CRM Deal", values[0])]
			if self.status_on_lock:
				deal["status"] = self.status_on_lock
			return [{"status": deal.get("status")}] if as_dict else [(deal.get("status"),)]
		if "tabSales Invoice" in query:
			if "SUM(outstanding_amount)" in query:
				return [("CUST-MIKAS", 100)]
			return [("CUST-MIKAS", 1, "2026-07-01", 100)]
		return []


def _load_crm(db: _FakeDB):
	for name in (
		"stabler.api.crm",
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.organization",
	):
		sys.modules.pop(name, None)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.session = types.SimpleNamespace(user="rep@mikas.example")
	frappe.flags = types.SimpleNamespace()
	frappe.db = db
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.get_roles = lambda _user=None: ["Sales User"]
	frappe.has_permission = lambda *_args, **_kwargs: True
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	frappe.parse_json = lambda value: value
	frappe.get_doc = lambda doctype, name, **kwargs: _get_doc(db, doctype, name, **kwargs)
	frappe.new_doc = lambda doctype: _new_doc(db, doctype)
	frappe.get_all = lambda *_args, **_kwargs: []
	frappe.get_list = lambda doctype, **kwargs: _get_list(db, doctype, **kwargs)
	frappe.delete_doc = lambda doctype, name: db.deleted.append((doctype, name))
	frappe.rename_doc = lambda doctype, old, new, **_kwargs: _rename_doc(db, doctype, old, new)
	frappe.clear_last_message = lambda: None

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.get_first_day = lambda _value: "2026-07-01"
	utils.getdate = lambda value: date.fromisoformat(str(value)[:10])
	utils.nowdate = lambda: "2026-07-29"
	utils.now_datetime = lambda: datetime(2026, 7, 29, 10, 30)
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_args, **_kwargs: None
	common._assert_can_write = lambda *_args, **_kwargs: None
	common._require_company = lambda company: _require_company(db, company)

	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
	organization._can_access_module = lambda *_args, **_kwargs: True
	organization._user_allowed_companies = lambda _user: ["Mikas"]

	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.organization": organization,
		}
	)
	return importlib.import_module("stabler.api.crm")


def _get_list(db: _FakeDB, doctype: str, **kwargs):
	db.get_list_calls.append((doctype, kwargs))
	filters = kwargs.get("filters", {})
	# No special case for `count(name) as total`: answering an aggregate field
	# list here is exactly what hid a v16-illegal SELECT behind a green suite.
	# The count query asks for plain names now and takes this same path.
	if doctype == "CRM Lead":
		return [db.docs[("CRM Lead", "LEAD-MIKAS")]] if filters.get("company") == "Mikas" else []
	if doctype == "CRM Deal":
		return [db.docs[("CRM Deal", "DEAL-MIKAS")]] if filters.get("company") == "Mikas" else []
	if doctype == "Customer":
		return [_Doc(name="CUST-MIKAS", creation="2026-07-01")]
	if doctype == "Sales Invoice":
		return []  # Current user has no invoice read permission.
	return []


def _require_company(db: _FakeDB, company: str):
	if not company:
		raise ValueError("Company is required.")
	if not db.exists("Company", company):
		raise ValueError(f"Unknown company: {company}")
	return company


def _new_doc(db: _FakeDB, doctype: str):
	doc = _Doc(doctype=doctype, name="DEAL-NEW" if doctype == "CRM Deal" else None)
	db.created.append(doc)
	if doctype == "CRM Deal":
		db.docs[(doctype, doc.name)] = doc
	return doc


def _get_doc(db: _FakeDB, doctype: str, name: str, *, for_update=False):
	if doctype == "CRM Deal" and db.require_locked_deal_reads and not for_update:
		raise AssertionError("CRM Deal transition read was not locked")
	doc = db.docs[(doctype, name)]
	if doctype == "CRM Deal" and for_update:
		if db.status_on_lock:
			doc["status"] = db.status_on_lock
		doc["_locked"] = True
	return doc


def _rename_doc(db: _FakeDB, doctype: str, old: str, new: str):
	db.rename_calls.append((doctype, old, new))
	for doc in db.docs.values():
		for field in ("status", "from_stage", "to_stage"):
			if doc.get(field) == old:
				doc[field] = new
	return new


class TestCrmCompanyScope(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.crm = _load_crm(self.db)

	def test_public_crm_endpoints_reject_missing_selected_company(self):
		"""Removing a public company gate must fail instead of defaulting scope."""
		calls = (
			lambda: self.crm.list_leads(),
			lambda: self.crm.get_lead("LEAD-MIKAS"),
			lambda: self.crm.save_lead({"first_name": "Amina"}),
			lambda: self.crm.delete_lead("LEAD-MIKAS"),
			lambda: self.crm.list_deals(),
			lambda: self.crm.get_deal("DEAL-MIKAS"),
			lambda: self.crm.save_deal({"organization": "Mikas Shop"}),
			lambda: self.crm.delete_deal("DEAL-MIKAS"),
			lambda: self.crm.convert_deal_to_customer("DEAL-MIKAS"),
			lambda: self.crm.crm_meta(),
			lambda: self.crm.crm_metrics(),
			lambda: self.crm.crm_analytics(),
			lambda: self.crm.crm_report("2026-07-01", "2026-07-31"),
			lambda: self.crm.create_crm_activity({"reference_name": "DEAL-MIKAS"}),
			lambda: self.crm.complete_crm_activity("ACT-1"),
			lambda: self.crm.list_crm_activities("CRM Deal", "DEAL-MIKAS"),
			lambda: self.crm.transition_deal("DEAL-MIKAS", "Qualified"),
		)
		for call in calls:
			with self.assertRaisesRegex(ValueError, "Company is required"):
				call()

	def test_forbidden_selected_company_is_rejected(self):
		"""Removing allowed-company enforcement would expose the Other tenant."""
		with self.assertRaises(PermissionError):
			self.crm.list_deals("Other")

	def test_lists_only_return_selected_company_records_and_totals(self):
		"""Dropping a company filter or permission-aware count breaks this contract."""
		leads = self.crm.list_leads("Mikas")
		deals = self.crm.list_deals("Mikas")

		self.assertEqual([row["name"] for row in leads["leads"]], ["LEAD-MIKAS"])
		self.assertEqual(leads["total"], 1)
		self.assertEqual([row["name"] for row in deals["deals"]], ["DEAL-MIKAS"])
		self.assertEqual(deals["total"], 1)

	def test_invoice_permissions_hide_board_ar_and_report_sales(self):
		"""Switching invoice aggregates back to db.sql leaks the hidden 100 value."""
		board = self.crm.list_deals("Mikas")
		analytics = self.crm.crm_analytics("Mikas")
		report = self.crm.crm_report("2026-07-01", "2026-07-31", "Mikas")

		self.assertEqual(board["deals"][0]["ar_outstanding"], 0.0)
		self.assertEqual(analytics["lifetime_sales"], 0.0)
		self.assertEqual(report["summary"]["sales"], 0.0)
		self.assertGreaterEqual(sum(doctype == "Sales Invoice" for doctype, _ in self.db.get_list_calls), 3)

	def test_missing_invoice_doctype_read_returns_empty_aggregates(self):
		"""Propagating invoice read denial must not make CRM boards unusable."""
		original_get_list = self.crm.frappe.get_list
		self.crm.frappe.has_permission = lambda doctype, ptype, name=None: (
			not (doctype == "Sales Invoice" and ptype == "read")
		)

		def get_list(doctype, **kwargs):
			if doctype == "Sales Invoice":
				raise PermissionError("Sales Invoice read denied")
			return original_get_list(doctype, **kwargs)

		self.crm.frappe.get_list = get_list
		board = self.crm.list_deals("Mikas")
		analytics = self.crm.crm_analytics("Mikas")
		report = self.crm.crm_report("2026-07-01", "2026-07-31", "Mikas")

		self.assertEqual(board["deals"][0]["ar_outstanding"], 0.0)
		self.assertEqual(analytics["lifetime_sales"], 0.0)
		self.assertEqual(report["summary"]["sales"], 0.0)

	def test_invoice_aggregates_are_folded_in_python_not_in_the_select(self):
		"""Frappe v16 rejects a SQL function inside a string SELECT, so the
		per-customer count/sum/min are folded here from plain columns.

		Two things must hold at once, and each hides the other's failure: the
		numbers have to be identical to what `count()/sum()/min()` produced (the
		board's AR and the acquisition KPIs are money and days, read by reps), and
		no field list may carry a function call — a `fields=["sum(x) as y"]`
		passes every fake DB and then 500s the live board (0682569, msa).
		"""
		invoices = [
			_Doc(
				customer="CUST-MIKAS",
				name="SI-1",
				posting_date=date(2026, 7, 5),
				base_grand_total=60,
				outstanding_amount=25,
			),
			_Doc(
				customer="CUST-MIKAS",
				name="SI-2",
				posting_date=date(2026, 7, 3),
				base_grand_total=40,
				outstanding_amount=0,
			),
		]
		original_get_list = self.crm.frappe.get_list

		def get_list(doctype, **kwargs):
			if doctype != "Sales Invoice":
				return original_get_list(doctype, **kwargs)
			self.db.get_list_calls.append((doctype, kwargs))
			rows = invoices
			if kwargs.get("filters", {}).get("outstanding_amount"):
				rows = [row for row in rows if row["outstanding_amount"] > 0]
			return [_Doc(**{field: row[field] for field in kwargs["fields"]}) for row in rows]

		self.crm.frappe.get_list = get_list
		board = self.crm.list_deals("Mikas")
		analytics = self.crm.crm_analytics("Mikas")

		self.assertEqual(board["deals"][0]["ar_outstanding"], 25.0)
		self.assertEqual(analytics["lifetime_sales"], 100.0)
		self.assertEqual(analytics["avg_orders_per_customer"], 2.0)
		self.assertEqual(analytics["reorder_rate"], 100.0)
		# Earliest posting_date (07-03), not the first row (07-05), against the
		# customer's 07-01 creation — a broken min() would report 4 days.
		self.assertEqual(analytics["avg_time_to_first_order_days"], 2.0)
		selects = [field for _doctype, kwargs in self.db.get_list_calls for field in kwargs.get("fields", [])]
		self.assertEqual([field for field in selects if "(" in field], [])

	def test_activity_creation_is_company_scoped_and_server_owned(self):
		"""Allowing client company/audit fields would corrupt the activity audit trail."""
		activity = self.crm.create_crm_activity(
			{
				"reference_doctype": "CRM Deal",
				"reference_name": "DEAL-MIKAS",
				"activity_type": "Call",
				"subject": "Confirm quantities",
				"due_at": "2026-07-30 09:00:00",
				"company": "Other",
				"created_by": "attacker@example.com",
			},
			"Mikas",
		)

		self.assertEqual(activity["company"], "Mikas")
		self.assertEqual(activity["created_by"], "rep@mikas.example")
		self.assertEqual(activity["reference_name"], "DEAL-MIKAS")

	def test_activity_completion_is_audited_and_reference_permission_aware(self):
		"""Completing an activity must stamp the current user through the controlled API."""
		self.db.docs[("CRM Activity", "ACT-1")] = _Doc(
			name="ACT-1",
			company="Mikas",
			reference_doctype="CRM Deal",
			reference_name="DEAL-MIKAS",
			status="Planned",
		)

		activity = self.crm.complete_crm_activity("ACT-1", "Mikas")

		self.assertEqual(activity["status"], "Completed")
		self.assertEqual(activity["completed_by"], "rep@mikas.example")
		self.assertEqual(activity["completed_at"], datetime(2026, 7, 29, 10, 30))

	def test_activity_timeline_filters_by_company_and_reference(self):
		"""Dropping any timeline scope key could leak another tenant or deal."""
		self.crm.list_crm_activities("CRM Deal", "DEAL-MIKAS", "Mikas")
		_, kwargs = self.db.get_list_calls[-1]

		self.assertEqual(
			kwargs["filters"],
			{
				"company": "Mikas",
				"reference_doctype": "CRM Deal",
				"reference_name": "DEAL-MIKAS",
			},
		)

	def test_transition_owns_stage_timestamps_and_history(self):
		"""Direct status-only saves must not replace transition history."""
		result = self.crm.transition_deal("DEAL-MIKAS", "Qualified", "Mikas")
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		events = [doc for doc in self.db.created if doc.get("doctype") == "CRM Stage Event"]

		self.assertEqual(result["status"], "Qualified")
		self.assertEqual(deal["stage_entered_at"], datetime(2026, 7, 29, 10, 30))
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["from_stage"], "Open")
		self.assertEqual(events[0]["to_stage"], "Qualified")
		self.assertEqual(events[0]["company"], "Mikas")

	def test_server_setting_enforces_open_deal_hygiene_on_transition(self):
		"""A caller must not be able to opt out after the server enables enforcement."""
		self.db.enforce_crm_next_action = True
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["deal_owner"] = ""

		with self.assertRaisesRegex(Exception, "owner"):
			self.crm.transition_deal("DEAL-MIKAS", "Qualified", "Mikas")

	def test_server_enforcement_defaults_off_for_existing_deals(self):
		"""Migration-safe defaults must not instantly break incomplete legacy deals."""
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["deal_owner"] = ""
		deal["next_action_at"] = None

		result = self.crm.transition_deal("DEAL-MIKAS", "Qualified", "Mikas")

		self.assertEqual(result["status"], "Qualified")

	def test_serialized_zero_setting_remains_disabled(self):
		"""A database value of '0' must not accidentally end the migration grace."""
		self.db.enforce_crm_next_action = "0"
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["deal_owner"] = ""
		deal["next_action_at"] = None

		result = self.crm.transition_deal("DEAL-MIKAS", "Qualified", "Mikas")

		self.assertEqual(result["status"], "Qualified")

	def test_client_cannot_disable_server_hygiene_enforcement(self):
		"""Restoring a caller flag would make the invariant optional again."""
		self.db.enforce_crm_next_action = True
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["deal_owner"] = ""

		with self.assertRaises(TypeError):
			self.crm.transition_deal("DEAL-MIKAS", "Qualified", "Mikas", enforce_next_action=0)

	def test_server_setting_enforces_hygiene_on_generic_open_deal_update(self):
		"""Generic edits must not clear owner or next action after grace ends."""
		self.db.enforce_crm_next_action = True
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["next_action_at"] = "2026-07-30 09:00:00"

		with self.assertRaisesRegex(Exception, "owner"):
			self.crm.save_deal({"name": "DEAL-MIKAS", "deal_owner": ""}, "Mikas")

	def test_server_setting_enforces_hygiene_on_new_open_deals(self):
		"""New open deals cannot bypass the enabled invariant."""
		self.db.enforce_crm_next_action = True

		with self.assertRaisesRegex(Exception, "owner"):
			self.crm.save_deal({"organization": "New Shop"}, "Mikas")

	def test_new_deal_creates_missing_crm_organization_from_spa_text_input(self):
		"""A first-time organization name entered in the SPA must be usable immediately."""
		result = self.crm.save_deal({"organization": "UAT Mikas Rail Buyer"}, "Mikas")
		organizations = [doc for doc in self.db.created if doc.get("doctype") == "CRM Organization"]

		self.assertEqual(result["organization"], "UAT Mikas Rail Buyer")
		self.assertEqual(
			[doc.get("organization_name") for doc in organizations],
			["UAT Mikas Rail Buyer"],
		)

	def test_document_hook_enforces_hygiene_outside_whitelisted_api(self):
		"""Direct Frappe writes must not bypass the server-owned invariant."""
		self.db.enforce_crm_next_action = True
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["deal_owner"] = ""

		with self.assertRaisesRegex(Exception, "owner"):
			self.crm.validate_crm_deal_hygiene(deal)

	def test_save_deal_routes_kanban_status_through_transition_history(self):
		"""Kanban's existing save_deal payload must not silently discard status."""
		result = self.crm.save_deal({"name": "DEAL-MIKAS", "status": "Qualified"}, "Mikas")
		events = [doc for doc in self.db.created if doc.get("doctype") == "CRM Stage Event"]

		self.assertEqual(result["status"], "Qualified")
		self.assertEqual(
			[(event["from_stage"], event["to_stage"]) for event in events], [("Open", "Qualified")]
		)

	def test_terminal_kanban_move_is_not_blocked_by_old_open_stage_hygiene(self):
		"""The compatibility path must validate the target outcome, not pre-transition state."""
		self.db.enforce_crm_next_action = True
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["deal_owner"] = ""
		deal["next_action_at"] = None
		original_save = _Doc.save
		_Doc.save = lambda doc, **_kwargs: self.crm.validate_crm_deal_hygiene(doc)
		try:
			result = self.crm.save_deal(
				{"name": "DEAL-MIKAS", "status": "Won", "organization": "Won Shop"},
				"Mikas",
			)
		finally:
			_Doc.save = original_save

		self.assertEqual(result["status"], "Won")
		self.assertEqual(result["organization"], "Won Shop")

	def test_new_terminal_deal_uses_target_outcome_and_records_initial_history(self):
		"""Creating a terminal deal must not be validated as an incomplete open deal."""
		self.db.enforce_crm_next_action = True
		original_save = _Doc.save
		_Doc.save = lambda doc, **_kwargs: self.crm.validate_crm_deal_hygiene(doc)
		try:
			result = self.crm.save_deal(
				{"organization": "Already Won", "status": "Won", "loss_reason": "Must be ignored"},
				"Mikas",
			)
		finally:
			_Doc.save = original_save
		events = [doc for doc in self.db.created if doc.get("doctype") == "CRM Stage Event"]

		self.assertEqual(result["status"], "Won")
		self.assertEqual([(event["from_stage"], event["to_stage"]) for event in events], [("", "Won")])
		self.assertEqual(events[0]["loss_reason"], "")

	def test_kanban_won_transition_preserves_customer_handoff(self):
		"""Routing status through transition history must retain the existing Won side effect."""
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["linked_customer"] = None
		self.crm.convert_deal_to_customer = lambda _name, _company: deal.update(
			{"linked_customer": "CUST-NEW"}
		)

		result = self.crm.save_deal({"name": "DEAL-MIKAS", "status": "Won"}, "Mikas")

		self.assertEqual(result["linked_customer"], "CUST-NEW")

	def test_same_target_won_save_retries_handoff_without_duplicate_event(self):
		"""Editing an already-Won deal must retry handoff without inventing a transition."""
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["status"] = "Won"
		deal["linked_customer"] = None
		self.crm.convert_deal_to_customer = lambda _name, _company: deal.update(
			{"linked_customer": "CUST-RETRIED"}
		)

		result = self.crm.save_deal(
			{
				"name": "DEAL-MIKAS",
				"status": "Won",
				"organization": "Updated Won Shop",
			},
			"Mikas",
		)
		events = [doc for doc in self.db.created if doc.get("doctype") == "CRM Stage Event"]

		self.assertEqual(result["linked_customer"], "CUST-RETRIED")
		self.assertEqual(result["organization"], "Updated Won Shop")
		self.assertEqual(events, [])

	def test_transition_uses_status_observed_after_row_lock(self):
		"""A concurrent stage change must become the next event's from-stage."""
		self.db.status_on_lock = "Qualified"

		self.crm.transition_deal("DEAL-MIKAS", "Won", "Mikas")
		events = [doc for doc in self.db.created if doc.get("doctype") == "CRM Stage Event"]

		self.assertEqual(events[0]["from_stage"], "Qualified")

	def test_compatibility_transition_uses_one_locked_document_and_keeps_updates(self):
		"""A concurrent same-stage move must save accompanying edits on the locked row."""
		self.db.require_locked_deal_reads = True
		self.db.status_on_lock = "Qualified"
		self.db.created.append(
			_Doc(
				doctype="CRM Organization",
				name="Current Locked Shop",
				organization_name="Current Locked Shop",
			)
		)
		self.crm.frappe.has_permission = lambda _doctype, _ptype, doc=None, **_kwargs: (
			isinstance(doc, _Doc) and bool(doc.get("_locked"))
		)

		result = self.crm.save_deal(
			{
				"name": "DEAL-MIKAS",
				"status": "Qualified",
				"organization": "Current Locked Shop",
			},
			"Mikas",
		)

		self.assertEqual(result["status"], "Qualified")
		self.assertEqual(result["organization"], "Current Locked Shop")
		self.assertTrue(self.db.docs[("CRM Deal", "DEAL-MIKAS")].saved)

	def test_terminal_fields_describe_only_the_current_outcome(self):
		"""Lost→Won→Open must not retain stale loss or terminal timestamps."""
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		self.crm.transition_deal("DEAL-MIKAS", "Lost", "Mikas", loss_reason="Price")
		self.assertIsNotNone(deal["lost_at"])
		self.assertEqual(deal["loss_reason"], "Price")
		self.assertIsNone(deal.get("won_at"))

		self.crm.transition_deal("DEAL-MIKAS", "Won", "Mikas")
		self.assertIsNotNone(deal["won_at"])
		self.assertIsNone(deal["lost_at"])
		self.assertIsNone(deal["loss_reason"])

		self.crm.transition_deal("DEAL-MIKAS", "Open", "Mikas")
		self.assertIsNone(deal["won_at"])
		self.assertIsNone(deal["lost_at"])
		self.assertIsNone(deal["loss_reason"])
		lost_event = next(
			event
			for event in self.db.created
			if event.get("doctype") == "CRM Stage Event" and event.get("to_stage") == "Lost"
		)
		self.assertEqual(lost_event["loss_reason"], "Price")

	def test_generic_deal_save_cannot_mutate_loss_reason(self):
		"""Loss explanations belong to Lost transitions and their history."""
		deal = self.db.docs[("CRM Deal", "DEAL-MIKAS")]
		deal["loss_reason"] = "Original"

		result = self.crm.save_deal({"name": "DEAL-MIKAS", "loss_reason": "Rewritten"}, "Mikas")

		self.assertEqual(result["loss_reason"], "Original")

	def test_status_rename_repoints_deals_and_immutable_history(self):
		"""Renaming a pipeline stage must not leave dangling history links."""
		self.crm.frappe.get_roles = lambda _user=None: ["Sales Manager"]
		event = _Doc(
			name="EVENT-1",
			company="Mikas",
			from_stage="Open",
			to_stage="Qualified",
		)
		self.db.docs[("CRM Stage Event", "EVENT-1")] = event

		self.crm.rename_deal_status(
			"Open",
			"New",
		)

		self.assertEqual(self.db.docs[("CRM Deal", "DEAL-MIKAS")]["status"], "New")
		self.assertEqual(event["from_stage"], "New")

	def test_transition_rejects_an_unknown_stage(self):
		"""Accepting arbitrary labels would detach deals from the configured pipeline."""
		with self.assertRaisesRegex(Exception, "valid deal status"):
			self.crm.transition_deal("DEAL-MIKAS", "Invented", "Mikas")

	def test_metrics_fetches_every_visible_deal(self):
		"""Removing the unbounded permission-aware fetch truncates the 25-deal KPI."""
		deals = [
			_Doc(
				status="Open", expected_monthly_volume=1, deal_value=0, needs_freezer=0, modified="2026-07-01"
			)
		]
		deals *= 25

		def get_list(doctype, **kwargs):
			if doctype == "CRM Deal":
				return deals if kwargs.get("limit_page_length") == 0 else deals[:20]
			return []

		self.crm.frappe.get_list = get_list
		metrics = self.crm.crm_metrics("Mikas")

		self.assertEqual(metrics["deal_count"], 25)
		self.assertEqual(metrics["open_run_rate"], 25.0)

	def test_record_permissions_and_selected_company_protect_named_deal_endpoints(self):
		"""Removing record checks would allow get/save/delete/convert on DEAL-MIKAS."""
		self.crm.frappe.has_permission = lambda doctype, ptype, name=None: (
			not (doctype == "CRM Deal" and name == "DEAL-MIKAS" and ptype in {"read", "write", "delete"})
		)
		for call in (
			lambda: self.crm.get_deal("DEAL-MIKAS", "Mikas"),
			lambda: self.crm.save_deal({"name": "DEAL-MIKAS", "organization": "Changed"}, "Mikas"),
			lambda: self.crm.delete_deal("DEAL-MIKAS", "Mikas"),
			lambda: self.crm.convert_deal_to_customer("DEAL-MIKAS", "Mikas"),
		):
			with self.assertRaises(PermissionError):
				call()

	def test_record_permissions_protect_named_lead_endpoints(self):
		"""Removing Lead permission checks would allow get/save/delete on LEAD-MIKAS."""
		self.crm.frappe.has_permission = lambda doctype, ptype, name=None: (
			not (doctype == "CRM Lead" and name == "LEAD-MIKAS" and ptype in {"read", "write", "delete"})
		)
		for call in (
			lambda: self.crm.get_lead("LEAD-MIKAS", "Mikas"),
			lambda: self.crm.save_lead({"name": "LEAD-MIKAS", "first_name": "Changed"}, "Mikas"),
			lambda: self.crm.delete_lead("LEAD-MIKAS", "Mikas"),
		):
			with self.assertRaises(PermissionError):
				call()

	def test_stored_company_mismatch_denies_named_lead_and_deal_endpoints(self):
		"""Removing selected-company equality would operate on Other tenant records."""
		for call in (
			lambda: self.crm.get_lead("LEAD-OTHER", "Mikas"),
			lambda: self.crm.save_lead({"name": "LEAD-OTHER", "first_name": "Changed"}, "Mikas"),
			lambda: self.crm.delete_lead("LEAD-OTHER", "Mikas"),
			lambda: self.crm.get_deal("DEAL-OTHER", "Mikas"),
			lambda: self.crm.save_deal({"name": "DEAL-OTHER", "organization": "Changed"}, "Mikas"),
			lambda: self.crm.delete_deal("DEAL-OTHER", "Mikas"),
			lambda: self.crm.convert_deal_to_customer("DEAL-OTHER", "Mikas"),
		):
			with self.assertRaises(PermissionError):
				call()

	def test_update_keeps_server_owned_company_link_and_audit_fields(self):
		"""Allowing payload company/link/audit fields would overwrite stored state."""
		result = self.crm.save_deal(
			{
				"name": "DEAL-MIKAS",
				"organization": "Updated Mikas Shop",
				"company": "Other",
				"linked_customer": "CUST-OTHER",
				"owner": "attacker@example.com",
			},
			"Mikas",
		)

		self.assertEqual(result["organization"], "Updated Mikas Shop")
		self.assertEqual(result["company"], "Mikas")
		self.assertEqual(result["linked_customer"], "CUST-MIKAS")
		self.assertNotIn("owner", result)

	def test_lead_update_keeps_server_owned_company_and_audit_fields(self):
		"""Allowing Lead company or owner updates would overwrite stored state."""
		result = self.crm.save_lead(
			{
				"name": "LEAD-MIKAS",
				"first_name": "Updated Amina",
				"company": "Other",
				"owner": "attacker@example.com",
			},
			"Mikas",
		)

		self.assertEqual(result["first_name"], "Updated Amina")
		self.assertEqual(result["company"], "Mikas")
		self.assertNotIn("owner", result)


if __name__ == "__main__":
	unittest.main()
