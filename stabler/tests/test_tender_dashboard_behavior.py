"""Behavioural tender-dashboard tests with a minimal mocked Frappe runtime.

They exercise the public API functions instead of only inspecting source text:
submission must be immutable, sourcing must be assignment-scoped, and trusted
portal decisions must record the supplied server actor.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from datetime import date
from unittest.mock import patch


class _FakeDB:
	def __init__(self, intakes: dict[str, dict] | None = None):
		self.intakes = intakes or {}
		self.writes: list[tuple[str, str, str]] = []

	def exists(self, doctype, name):
		return doctype == "CRM Deal" and name in self.intakes

	def get_value(self, doctype, name, field):
		if doctype == "CRM Deal" and field == "company":
			return "Test Company"
		if doctype == "CRM Deal" and field == "creation":
			return "2026-07-10"
		if doctype == "CRM Deal" and field == "custom_tender_intake":
			return json.dumps(self.intakes.get(name, {}))
		if doctype == "Company" and field == "default_currency":
			return "UZS"
		return None

	def has_column(self, doctype, field):
		return doctype == "CRM Deal" and field == "custom_tender_intake"

	def set_value(self, doctype, name, field, value, **_kwargs):
		self.writes.append((doctype, name, value))
		self.intakes[name] = json.loads(value)


class _Row(dict):
	def __getattr__(self, key):
		return self[key]


def _load_tender(db: _FakeDB, roles: list[str], user: str = "source@example.com"):
	"""Import tender.py against only the Frappe surface the tested APIs need."""
	for name in (
		"stabler.api.tender",
		"frappe",
		"frappe.utils",
		"stabler.api.approvals",
		"stabler.api._common",
		"stabler.api._bid_package",
		"stabler.api.organization",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
	):
		sys.modules.pop(name, None)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.DoesNotExistError = LookupError
	frappe.session = types.SimpleNamespace(user=user)
	frappe.db = db
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if args == () else args[0]
	frappe.get_roles = lambda _user=None: roles
	frappe.has_permission = lambda *_args, **_kwargs: True
	frappe.get_list = lambda *_args, **_kwargs: []
	frappe.get_all = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("get_all must not fetch dashboard candidates"))
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.getdate = lambda value: date.fromisoformat(str(value)[:10])
	utils.today = lambda: "2026-07-22"
	utils.now = lambda: "2026-07-22 09:00:00"
	frappe.utils = utils
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = utils
	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda _company: None
	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda _company: None
	bid_package = types.ModuleType("stabler.api._bid_package")
	bid_package.assemble_bid_package = lambda *_args, **_kwargs: {}
	bid_package.build_bid_docx = lambda *_args, **_kwargs: b""
	organization = types.ModuleType("stabler.api.organization")
	organization._can_access_module = lambda *_args, **_kwargs: True
	settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	settings.module_map_for = lambda _company: {"tender": True}
	for name, module in (
		("stabler.api.approvals", approvals),
		("stabler.api._common", common),
		("stabler.api._bid_package", bid_package),
		("stabler.api.organization", organization),
		("stabler.stabler.doctype.stabler_settings.stabler_settings", settings),
	):
		sys.modules[name] = module
	return importlib.import_module("stabler.api.tender")


class TestTenderDashboardBehaviour(unittest.TestCase):
	def test_tender_role_without_finance_or_oversight_omits_finance(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Stabler Declarant"])

		payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertNotIn("finance", payload)
		self.assertFalse(payload["role_scope"]["can_view_finance"])

	def test_legacy_result_without_submission_is_unverified_not_participation(self):
		db = _FakeDB({"DEAL-1": {"assigned_to": "source@example.com", "result": "won"}})
		tender = _load_tender(db, ["Sales User"])

		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-1"}):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(payload["acquisition"]["unverified_history"], 1)
		for key in ("submitted", "won", "lost", "pending"):
			self.assertEqual(payload["acquisition"][key], 0)

	def test_first_submission_writes_server_timestamp_and_current_user(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Sales User"], user="submitter@example.com")

		payload = tender.mark_tender_submitted("DEAL-1", "REF-123")

		self.assertEqual(payload["submitted_at"], "2026-07-22 09:00:00")
		self.assertEqual(payload["submitted_by"], "submitter@example.com")
		self.assertEqual(payload["submission_reference"], "REF-123")
		self.assertEqual(db.intakes["DEAL-1"]["submitted_at"], "2026-07-22 09:00:00")
		self.assertEqual(db.intakes["DEAL-1"]["submitted_by"], "submitter@example.com")

	def test_submission_preserves_the_first_server_fact(self):
		db = _FakeDB({"DEAL-1": {"submitted_at": "2026-07-01 08:00:00", "submitted_by": "first@example.com", "submission_reference": "FIRST"}})
		tender = _load_tender(db, ["Sales User"])

		payload = tender.mark_tender_submitted("DEAL-1", "RETRY")

		self.assertEqual(payload["submitted_at"], "2026-07-01 08:00:00")
		self.assertEqual(payload["submitted_by"], "first@example.com")
		self.assertEqual(payload["submission_reference"], "FIRST")
		self.assertEqual(db.writes, [])

	def test_sourcing_dashboard_excludes_unassigned_deals(self):
		db = _FakeDB({
			"DEAL-MINE": {"assigned_to": "source@example.com", "go_no_go": "go"},
			"DEAL-OTHER": {"assigned_to": "other@example.com", "go_no_go": "go"},
		})
		tender = _load_tender(db, ["Sales User"])
		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE", "DEAL-OTHER"}):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(payload["acquisition"]["identified"], 1)
		self.assertEqual(payload["my_work"]["assigned"], 1)
		self.assertEqual(payload["role_scope"]["acquisition_scope"], "assigned")

	def test_trusted_portal_decision_records_webhook_actor(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Sales User"])

		payload = tender.set_tender_go_no_go_from_trusted_source("DEAL-1", "go", actor="uzex:telegram")

		self.assertEqual(payload["go_no_go"], "go")
		self.assertEqual(payload["go_no_go_by"], "uzex:telegram")
		self.assertEqual(payload["go_no_go_at"], "2026-07-22 09:00:00")

	def test_assigned_execution_uses_document_period_not_lifecycle_period(self):
		db = _FakeDB({"DEAL-MINE": {"assigned_to": "source@example.com", "result_at": "2026-06-20"}})
		tender = _load_tender(db, ["Sales User"])
		def has_column(doctype, field):
			return (doctype, field) in {
				("CRM Deal", "custom_tender_intake"),
				("Purchase Order", "custom_crm_deal"),
			}
		def get_list(doctype, **_kwargs):
			if doctype == "Purchase Order":
				return [_Row(name="PO-1", custom_crm_deal="DEAL-MINE", transaction_date="2026-07-05", schedule_date=None, per_received=0, status="To Receive", base_grand_total=100)]
			return []
		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE"}), patch.object(tender.frappe.db, "has_column", has_column), patch.object(tender.frappe, "get_list", get_list):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(payload["acquisition"]["identified"], 0)
		self.assertEqual(payload["execution"]["purchase_orders"], 1)

	def test_execution_excludes_closed_and_cancelled_sales_orders(self):
		db = _FakeDB({"DEAL-MINE": {"assigned_to": "source@example.com"}})
		tender = _load_tender(db, ["Sales User"])

		def has_column(doctype, field):
			return (doctype, field) in {
				("CRM Deal", "custom_tender_intake"),
				("Sales Order", "custom_crm_deal"),
			}

		def get_list(doctype, **_kwargs):
			if doctype == "Sales Order":
				return [
					_Row(name="SO-OPEN", custom_crm_deal="DEAL-MINE", transaction_date="2026-07-05", per_delivered=100, status="To Deliver and Bill", base_grand_total=100),
					_Row(name="SO-CLOSED", custom_crm_deal="DEAL-MINE", transaction_date="2026-07-06", per_delivered=100, status="Closed", base_grand_total=100),
					_Row(name="SO-CANCELLED", custom_crm_deal="DEAL-MINE", transaction_date="2026-07-07", per_delivered=0, status="Cancelled", base_grand_total=100),
				]
			return []

		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE"}), patch.object(tender.frappe.db, "has_column", has_column), patch.object(tender.frappe, "get_list", get_list):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(payload["execution"]["sales_orders"], 1)
		self.assertEqual(payload["execution"]["delivered"], 1)
		self.assertEqual(payload["execution"]["delivery_pending"], 0)

	def test_execution_targets_exclude_documents_without_read_permission(self):
		db = _FakeDB({"DEAL-MINE": {"assigned_to": "source@example.com"}})
		tender = _load_tender(db, ["Sales User"])
		so_rows = [
			_Row(name="SO-ALLOWED", customer="Customer", customer_name="Customer", transaction_date="2026-07-05", delivery_date="2026-07-20", currency="UZS", rounded_total=100, grand_total=100, base_grand_total=100, per_delivered=0, per_billed=0, status="To Deliver and Bill", custom_board_stage=None, custom_crm_deal="DEAL-MINE"),
			_Row(name="SO-DENIED", customer="Customer", customer_name="Customer", transaction_date="2026-07-05", delivery_date="2026-07-20", currency="UZS", rounded_total=200, grand_total=200, base_grand_total=200, per_delivered=0, per_billed=0, status="To Deliver and Bill", custom_board_stage=None, custom_crm_deal="DEAL-MINE"),
		]
		po_rows = [
			_Row(name="PO-ALLOWED", supplier="Supplier", supplier_name="Supplier", transaction_date="2026-07-05", schedule_date="2026-07-20", per_received=0, status="To Receive", base_grand_total=100, custom_crm_deal="DEAL-MINE"),
			_Row(name="PO-DENIED", supplier="Supplier", supplier_name="Supplier", transaction_date="2026-07-05", schedule_date="2026-07-20", per_received=0, status="To Receive", base_grand_total=200, custom_crm_deal="DEAL-MINE"),
		]

		def has_column(doctype, field):
			return (doctype, field) in {
				("CRM Deal", "custom_tender_intake"),
				("Sales Order", "custom_crm_deal"),
				("Purchase Order", "custom_crm_deal"),
			}

		def document_rows(doctype, **_kwargs):
			if doctype == "Sales Order":
				return so_rows
			if doctype == "Purchase Order":
				return po_rows
			return []

		def has_permission(_doctype, _ptype, doc=None):
			return doc not in {"SO-DENIED", "PO-DENIED"}

		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE"}), patch.object(tender, "_ensure_default_stages"), patch.object(tender, "_stages", return_value=[]), patch.object(tender, "_require_tender_view"), patch.object(tender.frappe.db, "has_column", has_column), patch.object(tender.frappe, "get_all", document_rows), patch.object(tender.frappe, "get_list", document_rows), patch.object(tender.frappe, "has_permission", has_permission):
			dashboard = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")
			sales_board = tender.so_board("Test Company", tender_only=1)
			logistics = tender.logist_board("Test Company")

		self.assertEqual(dashboard["execution"]["sales_orders"], 1)
		self.assertEqual(dashboard["execution"]["purchase_orders"], 1)
		self.assertEqual([card["name"] for card in sales_board["cards"]], ["SO-ALLOWED"])
		self.assertEqual([row["po"] for row in logistics["rows"]], ["PO-ALLOWED"])

	def test_sourcing_target_excludes_deals_without_read_permission(self):
		db = _FakeDB({
			"DEAL-ALLOWED": {"assigned_to": "source@example.com"},
			"DEAL-DENIED": {"assigned_to": "source@example.com"},
		})
		tender = _load_tender(db, ["Sales User"])

		def has_permission(doctype, _ptype, doc=None):
			return not (doctype == "CRM Deal" and doc == "DEAL-DENIED")

		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-ALLOWED", "DEAL-DENIED"}), patch.object(tender, "_require_tender_view"), patch.object(tender, "_deal_deadlines", return_value={"risk": "good", "milestones": []}), patch.object(tender, "_deal_landed", return_value=(0.0, 0)), patch.object(tender, "_deal_label", side_effect=lambda deal: deal), patch.object(tender.frappe, "has_permission", has_permission):
			payload = tender.sourcing_my_tenders("Test Company")

		self.assertEqual([row["deal"] for row in payload["rows"]], ["DEAL-ALLOWED"])

	def test_declarant_scope_is_execution_portfolio_not_acquisition_portfolio(self):
		db = _FakeDB({"DEAL-1": {"assigned_to": "other@example.com"}})
		tender = _load_tender(db, ["Stabler Declarant"])

		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-1"}):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(payload["acquisition"]["identified"], 0)
		self.assertEqual(payload["role_scope"]["acquisition_scope"], "none")
		self.assertEqual(payload["role_scope"]["execution_scope"], "portfolio")

	def test_dashboard_rejects_user_without_tender_window(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Accounts User"])

		with self.assertRaises(PermissionError):
			tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")


if __name__ == "__main__":
	unittest.main()
