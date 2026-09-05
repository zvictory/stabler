"""Behavioural tender-dashboard tests with a minimal mocked Frappe runtime.

They exercise the public API functions instead of only inspecting source text:
submission must be immutable, sourcing must be assignment-scoped, and trusted
portal decisions must record the supplied server actor.
"""

from __future__ import annotations

import importlib
import json
import types
import unittest
from datetime import date
from unittest.mock import patch

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _FakeDB:
	def __init__(
		self,
		intakes: dict[str, dict] | None = None,
		*,
		creations: dict[str, str] | None = None,
		locked_intakes: dict[str, dict] | None = None,
		users: dict[str, str] | None = None,
	):
		self.intakes = intakes or {}
		self.creations = creations or {}
		self.locked_intakes = locked_intakes or {}
		self.users = users or {}
		self.writes: list[tuple[str, str, str]] = []
		self.lock_reads: list[tuple[str, object]] = []

	def exists(self, doctype, name):
		return (doctype == "CRM Deal" and name in self.intakes) or (doctype == "User" and name in self.users)

	def get_value(self, doctype, name, field):
		if doctype == "CRM Deal" and field == "company":
			return "Test Company"
		if doctype == "CRM Deal" and field == "creation":
			return self.creations.get(name, "2026-07-10")
		if doctype == "CRM Deal" and field == "custom_tender_intake":
			return json.dumps(self.intakes.get(name, {}))
		if doctype == "Company" and field == "default_currency":
			return "UZS"
		if doctype == "User" and field == "full_name":
			return self.users.get(name)
		return None

	def has_column(self, doctype, field):
		return doctype == "CRM Deal" and field == "custom_tender_intake"

	def set_value(self, doctype, name, field, value, **_kwargs):
		self.writes.append((doctype, name, value))
		self.intakes[name] = json.loads(value)

	def sql(self, query, values=None, **_kwargs):
		self.lock_reads.append((query, values))
		deal = values[0] if isinstance(values, (list, tuple)) else values
		intake = self.locked_intakes.get(deal, self.intakes.get(deal, {}))
		return [{"custom_tender_intake": json.dumps(intake)}]


class _Row(dict):
	def __getattr__(self, key):
		return self[key]


def _load_tender(db: _FakeDB, roles: list[str], user: str = "source@example.com"):
	"""Import tender.py against only the Frappe surface the tested APIs need."""
	_SANDBOX.evict(
		"stabler.api.tender",
		"stabler.api.purchasing",
		"frappe",
		"frappe.utils",
		"stabler.api.approvals",
		"stabler.api._common",
		"stabler.api._bid_package",
		"stabler.api.organization",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
	)
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
	frappe.get_all = lambda *_args, **_kwargs: (_ for _ in ()).throw(
		AssertionError("get_all must not fetch dashboard candidates")
	)
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.getdate = lambda value: date.fromisoformat(str(value)[:10])
	utils.add_months = lambda value, months: date(
		value.year + (value.month - 1 + months) // 12,
		(value.month - 1 + months) % 12 + 1,
		min(value.day, 28),
	)
	utils.cint = lambda value=0: int(float(value or 0))
	utils.today = lambda: "2026-07-22"
	utils.now = lambda: "2026-07-22 09:00:00"
	frappe.utils = utils
	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})
	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda _company: None
	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda _company: None
	bid_package = types.ModuleType("stabler.api._bid_package")
	bid_package.assemble_bid_package = lambda *_args, **_kwargs: {}
	bid_package.build_bid_docx = lambda *_args, **_kwargs: b""
	organization = types.ModuleType("stabler.api.organization")
	organization._can_access_module = lambda *_args, **_kwargs: True
	purchasing = types.ModuleType("stabler.api.purchasing")
	purchasing.tender_quotations = lambda _deal: {"rows": []}
	settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	settings.module_map_for = lambda _company: {"tender": True}
	_SANDBOX.install(
		{
			"stabler.api.approvals": approvals,
			"stabler.api._common": common,
			"stabler.api._bid_package": bid_package,
			"stabler.api.organization": organization,
			"stabler.api.purchasing": purchasing,
			"stabler.stabler.doctype.stabler_settings.stabler_settings": settings,
		}
	)
	return importlib.import_module("stabler.api.tender")


class TestTenderDashboardBehaviour(unittest.TestCase):
	def test_crm_board_cards_carry_parent_tender_for_master_drilldown_filter(self):
		"""The parent drill-down must not filter every correctly linked lot away."""
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Sales Manager"])
		original_get_value = db.get_value
		db.get_value = lambda doctype, name, field: (
			"TND-1"
			if doctype == "CRM Deal" and field == "custom_parent_tender"
			else original_get_value(doctype, name, field)
		)
		tender.frappe.get_cached_value = lambda *_args, **_kwargs: "UZS"

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-1"}),
			patch.object(tender, "_read_intake", return_value={}),
			patch.object(tender, "_deal_deadlines", return_value={"deadline": None, "risk": "good"}),
			patch.object(tender, "_deal_label", return_value="UAT lot"),
		):
			result = tender.crm_board("Test Company")

		self.assertEqual(result["cards"][0]["custom_parent_tender"], "TND-1")

	def test_workspace_omits_finance_for_non_finance_role(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Stabler Declarant"])

		with (
			patch.object(tender, "deal_intake", return_value={}),
			patch.object(
				tender,
				"_purchase_document_chain",
				return_value={"orders": [], "receipts": [], "invoices": []},
			),
			patch.object(
				tender, "_sales_document_chain", return_value={"orders": [], "deliveries": [], "invoices": []}
			),
		):
			result = tender.tender_workspace("DEAL-1")

		self.assertNotIn("finance", result)
		self.assertIn("purchase_execution", result)
		self.assertIn("sales_execution", result)

	def test_workspace_traces_invoices_through_order_item_links(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Accounts User"])

		def get_list(doctype, **_kwargs):
			rows = {
				"Purchase Order": [
					_Row(name="PO-1", transaction_date="2026-07-01", status="To Receive", grand_total=100)
				],
				"Purchase Receipt": [],
				"Purchase Invoice": [
					_Row(
						name="PINV-1",
						posting_date="2026-07-03",
						status="Unpaid",
						grand_total=100,
						outstanding_amount=100,
					)
				],
				"Purchase Invoice Item": [_Row(parent="PINV-1", purchase_order="PO-1")],
				"Sales Order": [
					_Row(
						name="SO-1",
						transaction_date="2026-07-01",
						status="To Deliver and Bill",
						grand_total=160,
					)
				],
				"Delivery Note": [],
				"Sales Invoice": [
					_Row(
						name="SINV-1",
						posting_date="2026-07-04",
						status="Unpaid",
						grand_total=160,
						outstanding_amount=160,
					)
				],
				"Sales Invoice Item": [_Row(parent="SINV-1", sales_order="SO-1")],
			}
			return rows.get(doctype, [])

		def has_column(doctype, field):
			return (doctype, field) in {
				("CRM Deal", "custom_tender_intake"),
				("Purchase Order", "custom_crm_deal"),
				("Sales Order", "custom_crm_deal"),
			}

		with (
			patch.object(tender.frappe.db, "has_column", has_column),
			patch.object(tender.frappe, "get_list", get_list),
			patch.object(tender, "deal_intake", return_value={}),
			patch.object(tender, "_bid_inputs", return_value=({}, {})),
			patch.object(tender, "_compute_bid_pnl", return_value={"profit": 0}),
		):
			result = tender.tender_workspace("DEAL-1")

		self.assertEqual(result["purchase_execution"]["invoices"][0]["purchase_order"], "PO-1")
		self.assertEqual(result["sales_execution"]["invoices"][0]["sales_order"], "SO-1")

	def test_workspace_finance_outstanding_survives_frappe_dropping_the_column_it_never_had(self):
		"""Neither invoice DocType has a `base_outstanding_amount` column, and
		`frappe.get_list` does not fail when asked for one: the unknown field is dropped
		from the SELECT, `flt(None)` read every invoice as fully paid, and the PO control
		board's Finance tab showed "Outstanding: 0" against two Unpaid invoices (measured
		2026-09-05 on CRM-DEAL-2026-00015: ap_total 214 800 000, ap_outstanding 0,
		ap_paid 214 800 000).  The fake below answers like Frappe does — only the
		requested fields the row actually has."""
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Accounts User"])
		invoice = {
			"posting_date": "2026-07-03",
			"status": "Unpaid",
			"currency": "UZS",
			"conversion_rate": 1,
			"party_account_currency": "UZS",
		}
		rows = {
			"Purchase Order": [
				_Row(name="PO-1", transaction_date="2026-07-01", status="To Receive", grand_total=100)
			],
			"Purchase Invoice": [
				_Row(name="PINV-1", grand_total=100, base_grand_total=100, outstanding_amount=100, **invoice)
			],
			"Purchase Invoice Item": [_Row(parent="PINV-1", purchase_order="PO-1")],
			"Sales Order": [
				_Row(
					name="SO-1", transaction_date="2026-07-01", status="To Deliver and Bill", grand_total=160
				)
			],
			"Sales Invoice": [
				_Row(name="SINV-1", grand_total=160, base_grand_total=160, outstanding_amount=160, **invoice)
			],
			"Sales Invoice Item": [_Row(parent="SINV-1", sales_order="SO-1")],
		}

		def get_list(doctype, fields=None, **_kwargs):
			wanted = set(fields or [])
			return [
				_Row({key: value for key, value in row.items() if key in wanted})
				for row in rows.get(doctype, [])
			]

		def has_column(doctype, field):
			return (doctype, field) in {
				("CRM Deal", "custom_tender_intake"),
				("Purchase Order", "custom_crm_deal"),
				("Sales Order", "custom_crm_deal"),
			}

		with (
			patch.object(tender.frappe.db, "has_column", has_column),
			patch.object(tender.frappe, "get_list", get_list),
			patch.object(tender, "deal_intake", return_value={"currency": "UZS"}),
			patch.object(tender, "_bid_inputs", return_value=({}, {})),
			patch.object(tender, "_compute_bid_pnl", return_value={"profit": 0}),
		):
			finance = tender.tender_workspace("DEAL-1")["finance"]

		self.assertEqual((finance["ap_outstanding"], finance["ap_paid"]), (100, 0))
		self.assertEqual((finance["ar_outstanding"], finance["ar_paid"]), (160, 0))

	def test_document_row_states_outstanding_in_company_currency_the_way_erpnext_keeps_it(self):
		"""`outstanding_amount` is denominated in `party_account_currency` (the field's own
		DocType option): the invoice currency when the payable/receivable account is held
		in it, otherwise the company currency already — `calculate_outstanding_amount`,
		erpnext/controllers/taxes_and_totals.py.  Only the first case converts, at the
		invoice's own booking rate, so an unpaid invoice's outstanding equals its
		`base_grand_total` and `ap_paid` comes out as 0 rather than the whole total."""
		tender = _load_tender(_FakeDB(), ["Accounts User"])
		usd_invoice = {
			"name": "PINV-USD",
			"posting_date": "2026-07-03",
			"currency": "USD",
			"grand_total": 100,
			"base_grand_total": 1_300_000,
			"conversion_rate": 13_000,
		}

		def base_outstanding(**row) -> float:
			normalized = tender._document_row(
				_Row(**usd_invoice, **row), "posting_date", "purchase_order", "PO-1"
			)
			return normalized["base_outstanding_amount"]

		self.assertEqual(base_outstanding(outstanding_amount=20, party_account_currency="USD"), 260_000)
		self.assertEqual(base_outstanding(outstanding_amount=260_000, party_account_currency="UZS"), 260_000)

	def test_workspace_finance_deduplicates_multi_order_invoices_in_base_currency(self):
		db = _FakeDB()
		tender = _load_tender(db, ["Accounts User"])

		finance = tender._tender_finance_chain(
			{
				"invoices": [
					{
						"name": "PINV-USD",
						"grand_total": 100,
						"outstanding_amount": 20,
						"base_grand_total": 1_300_000,
						"base_outstanding_amount": 260_000,
						"purchase_order": "PO-1",
					},
					{
						"name": "PINV-USD",
						"grand_total": 100,
						"outstanding_amount": 20,
						"base_grand_total": 1_300_000,
						"base_outstanding_amount": 260_000,
						"purchase_order": "PO-2",
					},
					{
						"name": "PINV-EUR",
						"grand_total": 200,
						"outstanding_amount": 0,
						"base_grand_total": 2_800_000,
						"base_outstanding_amount": 0,
						"purchase_order": "PO-3",
					},
				],
			},
			{
				"invoices": [
					{
						"name": "SINV-USD",
						"grand_total": 500,
						"outstanding_amount": 50,
						"base_grand_total": 6_500_000,
						"base_outstanding_amount": 650_000,
						"sales_order": "SO-1",
					},
					{
						"name": "SINV-USD",
						"grand_total": 500,
						"outstanding_amount": 50,
						"base_grand_total": 6_500_000,
						"base_outstanding_amount": 650_000,
						"sales_order": "SO-2",
					},
				],
			},
			currency="UZS",
		)

		self.assertEqual(finance["currency"], "UZS")
		self.assertEqual(finance["ap_total"], 4_100_000)
		self.assertEqual(finance["ap_outstanding"], 260_000)
		self.assertEqual(finance["ar_total"], 6_500_000)
		self.assertEqual(finance["ar_outstanding"], 650_000)
		self.assertEqual(finance["actual_margin"], 2_400_000)

	def test_workspace_finance_exposes_planned_margin_from_bid_pricing(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Accounts User"])

		with (
			patch.object(tender, "deal_intake", return_value={"currency": "UZS"}),
			patch.object(
				tender,
				"_purchase_document_chain",
				return_value={"orders": [], "receipts": [], "invoices": []},
			),
			patch.object(
				tender, "_sales_document_chain", return_value={"orders": [], "deliveries": [], "invoices": []}
			),
			patch.object(tender, "_bid_inputs", return_value=({}, {})),
			patch.object(tender, "_compute_bid_pnl", return_value={"profit": 425_000}),
		):
			result = tender.tender_workspace("DEAL-1")

		self.assertEqual(result["finance"]["planned_margin"], 425_000)
		self.assertEqual(result["finance"]["currency"], "UZS")

	def test_portfolio_progress_is_value_weighted(self):
		db = _FakeDB()
		tender = _load_tender(db, ["Sales Manager"])
		pos = [
			_Row(base_grand_total=100, per_received=100, per_billed=100),
			_Row(base_grand_total=300, per_received=0, per_billed=0),
		]

		result = tender._weighted_progress(pos, "per_received")

		self.assertEqual(result, 25.0)

	def test_monthly_trend_uses_verified_server_dates(self):
		db = _FakeDB()
		tender = _load_tender(db, ["Sales Manager"])
		events = [
			{"submitted_at": "2026-05-08", "result": "won", "result_at": "2026-05-12", "value": 165},
			{"submitted_at": "2026-06-10", "result": "won", "result_at": "2026-06-14", "value": 213.6},
		]

		self.assertEqual(
			tender._monthly_trend(events, tender.getdate("2026-05-01"), tender.getdate("2026-06-30")),
			[
				{"month": "2026-05", "submitted": 1, "won": 1, "won_value": 165.0},
				{"month": "2026-06", "submitted": 1, "won": 1, "won_value": 213.6},
			],
		)

	def test_dashboard_can_request_three_month_trend_without_widening_kpis(self):
		db = _FakeDB(
			{
				"DEAL-MAY": {
					"assigned_to": "source@example.com",
					"submitted_at": "2026-05-08",
					"submitted_by": "source@example.com",
				},
				"DEAL-JULY": {
					"assigned_to": "source@example.com",
					"submitted_at": "2026-07-08",
					"submitted_by": "source@example.com",
				},
			},
		)
		tender = _load_tender(db, ["Sales User"])

		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-MAY", "DEAL-JULY"}):
			payload = tender.tender_dashboard(
				"Test Company",
				"2026-07-01",
				"2026-07-31",
				"2026-05-01",
				"2026-07-31",
			)

		self.assertEqual(payload["period"], {"from_date": "2026-07-01", "to_date": "2026-07-31"})
		self.assertEqual(payload["trend_period"], {"from_date": "2026-05-01", "to_date": "2026-07-31"})
		self.assertEqual([row["month"] for row in payload["trend"]], ["2026-05", "2026-06", "2026-07"])
		self.assertEqual(payload["acquisition"]["submitted"], 1)

	def test_missing_crm_doctype_returns_no_tender_candidates(self):
		db = _FakeDB()
		tender = _load_tender(db, ["Sales Manager"])
		original_has_column = db.has_column

		def has_column(doctype, field):
			if doctype == "CRM Deal":
				raise RuntimeError("CRM Deal metadata is unavailable")
			return original_has_column(doctype, field)

		with patch.object(db, "has_column", side_effect=has_column):
			self.assertEqual(tender._tender_deal_names("Test Company"), set())

	def test_tender_role_without_finance_or_oversight_omits_finance(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Stabler Declarant"])

		payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertNotIn("finance", payload)
		self.assertFalse(payload["role_scope"]["can_view_finance"])

	def test_legacy_result_without_submission_is_unverified_not_participation(self):
		db = _FakeDB(
			{"DEAL-1": {"assigned_to": "source@example.com", "result": "won", "result_at": "2026-07-10"}}
		)
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
		db = _FakeDB(
			{
				"DEAL-1": {
					"submitted_at": "2026-07-01 08:00:00",
					"submitted_by": "first@example.com",
					"submission_reference": "FIRST",
				}
			}
		)
		tender = _load_tender(db, ["Sales User"])

		payload = tender.mark_tender_submitted("DEAL-1", "RETRY")

		self.assertEqual(payload["submitted_at"], "2026-07-01 08:00:00")
		self.assertEqual(payload["submitted_by"], "first@example.com")
		self.assertEqual(payload["submission_reference"], "FIRST")
		self.assertEqual(db.writes, [])

	def test_submission_locks_and_rereads_before_claiming_first_audit_fact(self):
		db = _FakeDB(
			{"DEAL-1": {}},
			locked_intakes={
				"DEAL-1": {
					"submitted_at": "2026-07-22 08:59:59",
					"submitted_by": "concurrent@example.com",
					"submission_reference": "CONCURRENT-FIRST",
				},
			},
		)
		tender = _load_tender(db, ["Sales User"], user="second@example.com")

		payload = tender.mark_tender_submitted("DEAL-1", "SECOND")

		self.assertEqual(payload["submitted_by"], "concurrent@example.com")
		self.assertEqual(payload["submission_reference"], "CONCURRENT-FIRST")
		self.assertEqual(db.writes, [])
		self.assertEqual(len(db.lock_reads), 1)
		self.assertIn("FOR UPDATE", db.lock_reads[0][0].upper())

	def test_intake_save_cannot_spoof_or_clear_server_managed_assignment(self):
		db = _FakeDB(
			{
				"DEAL-1": {
					"assigned_to": "owner@example.com",
					"assigned_to_name": "Original Owner",
					"assigned_at": "2026-07-01 08:00:00",
					"assigned_by": "director@example.com",
					"notes": "before",
				},
			}
		)
		tender = _load_tender(db, ["Sales User"])

		payload = tender.save_deal_intake(
			"DEAL-1",
			{
				"assigned_to": "attacker@example.com",
				"assigned_to_name": "Spoofed Owner",
				"assigned_at": "2099-01-01 00:00:00",
				"assigned_by": "attacker@example.com",
				"ready_at": "2099-01-01 00:00:00",
				"ready_by": "attacker@example.com",
				"notes": "after",
			},
		)

		self.assertEqual(payload["intake"]["assigned_to"], "owner@example.com")
		self.assertEqual(payload["intake"]["assigned_to_name"], "Original Owner")
		self.assertEqual(payload["intake"]["assigned_at"], "2026-07-01 08:00:00")
		self.assertEqual(payload["intake"]["assigned_by"], "director@example.com")
		self.assertEqual(payload["intake"]["ready_at"], "")
		self.assertEqual(payload["intake"]["ready_by"], "")
		self.assertEqual(payload["intake"]["notes"], "after")

	def test_concurrent_intake_save_preserves_a_submission_that_won_the_row_lock(self):
		db = _FakeDB(
			{"DEAL-1": {"notes": "stale"}},
			locked_intakes={
				"DEAL-1": {
					"notes": "current",
					"submitted_at": "2026-07-22 08:59:59",
					"submitted_by": "first@example.com",
					"submission_reference": "FIRST",
				},
			},
		)
		tender = _load_tender(db, ["Sales User"])

		payload = tender.save_deal_intake("DEAL-1", {"notes": "edited"})

		self.assertEqual(payload["intake"]["submitted_by"], "first@example.com")
		self.assertEqual(payload["intake"]["submission_reference"], "FIRST")
		self.assertIn("FOR UPDATE", db.lock_reads[0][0].upper())

	def test_director_assignment_is_the_only_path_that_changes_assignment(self):
		db = _FakeDB({"DEAL-1": {"assigned_to": "old@example.com", "assigned_to_name": "Old"}})
		tender = _load_tender(db, ["Stabler Tender Director"])

		payload = tender.assign_tender("DEAL-1", "")

		self.assertEqual(payload["assigned_to"], "")
		self.assertEqual(db.intakes["DEAL-1"]["assigned_to"], "")
		self.assertEqual(db.intakes["DEAL-1"]["assigned_to_name"], "")
		self.assertEqual(db.intakes["DEAL-1"]["assigned_at"], "")
		self.assertEqual(db.intakes["DEAL-1"]["assigned_by"], "")

	def test_assignment_transition_uses_server_time_and_current_director(self):
		db = _FakeDB(
			{
				"DEAL-OLD": {
					"assigned_to": "previous@example.com",
					"assigned_to_name": "Previous Manager",
					"assigned_at": "2026-05-01 08:00:00",
					"assigned_by": "previous-director@example.com",
				},
			},
			creations={"DEAL-OLD": "2026-01-10"},
			users={"source@example.com": "Source Manager"},
		)
		tender = _load_tender(db, ["Stabler Tender Director"], user="director@example.com")

		assigned = tender.assign_tender("DEAL-OLD", "source@example.com")

		self.assertEqual(assigned["assigned_at"], "2026-07-22 09:00:00")
		self.assertEqual(assigned["assigned_by"], "director@example.com")
		self.assertEqual(db.intakes["DEAL-OLD"]["assigned_at"], "2026-07-22 09:00:00")

		tender = _load_tender(db, ["Sales User"], user="source@example.com")
		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-OLD"}):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")
		self.assertEqual(payload["acquisition"]["identified"], 0)
		self.assertEqual(payload["my_work"]["assigned"], 1)
		evidence = tender._tender_filter_evidence(db.intakes["DEAL-OLD"], "2026-01-10", "good")
		self.assertEqual(evidence["event_dates"]["assigned"], "2026-07-22 09:00:00")

	def test_sourcing_dashboard_excludes_unassigned_deals(self):
		db = _FakeDB(
			{
				"DEAL-MINE": {
					"assigned_to": "source@example.com",
					"assigned_at": "2026-07-03 09:00:00",
					"assigned_by": "director@example.com",
					"go_no_go": "go",
				},
				"DEAL-OTHER": {"assigned_to": "other@example.com", "go_no_go": "go"},
			}
		)
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
		db = _FakeDB(
			{"DEAL-MINE": {"assigned_to": "source@example.com", "result_at": "2026-06-20"}},
			creations={"DEAL-MINE": "2026-06-01"},
		)
		tender = _load_tender(db, ["Sales User"])

		def has_column(doctype, field):
			return (doctype, field) in {
				("CRM Deal", "custom_tender_intake"),
				("Purchase Order", "custom_crm_deal"),
			}

		def get_list(doctype, **_kwargs):
			if doctype == "Purchase Order":
				return [
					_Row(
						name="PO-1",
						custom_crm_deal="DEAL-MINE",
						transaction_date="2026-07-05",
						schedule_date=None,
						per_received=0,
						status="To Receive",
						base_grand_total=100,
					)
				]
			return []

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE"}),
			patch.object(tender.frappe.db, "has_column", has_column),
			patch.object(tender.frappe, "get_list", get_list),
		):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(payload["acquisition"]["identified"], 0)
		self.assertEqual(payload["execution"]["purchase_orders"], 1)

	def test_execution_invoices_are_tender_linked_period_scoped_and_exclusive(self):
		db = _FakeDB({"DEAL-MINE": {"assigned_to": "source@example.com"}})
		tender = _load_tender(db, ["Sales User"])

		def has_column(doctype, field):
			return (doctype, field) in {
				("CRM Deal", "custom_tender_intake"),
				("Purchase Order", "custom_crm_deal"),
				("Sales Order", "custom_crm_deal"),
			}

		def get_list(doctype, **_kwargs):
			rows = {
				"Purchase Order": [
					_Row(
						name="PO-MINE",
						custom_crm_deal="DEAL-MINE",
						transaction_date="2026-06-05",
						schedule_date=None,
						per_received=0,
						status="To Receive",
						base_grand_total=100,
					)
				],
				"Sales Order": [
					_Row(
						name="SO-MINE",
						custom_crm_deal="DEAL-MINE",
						transaction_date="2026-06-05",
						delivery_date=None,
						per_delivered=0,
						status="To Deliver and Bill",
						base_grand_total=100,
					)
				],
				"Purchase Invoice": [
					_Row(name="PINV-DRAFT", posting_date="2026-07-02", docstatus=0, status="Draft"),
					_Row(name="PINV-UNPAID", posting_date="2026-07-03", docstatus=1, status="Unpaid"),
					_Row(name="PINV-SUBMITTED", posting_date="2026-07-04", docstatus=1, status="Paid"),
					_Row(name="PINV-OUTSIDE", posting_date="2026-06-30", docstatus=1, status="Unpaid"),
					_Row(name="PINV-OTHER", posting_date="2026-07-04", docstatus=1, status="Unpaid"),
				],
				"Purchase Invoice Item": [
					_Row(parent="PINV-DRAFT", purchase_order="PO-MINE"),
					_Row(parent="PINV-UNPAID", purchase_order="PO-MINE"),
					_Row(parent="PINV-SUBMITTED", purchase_order="PO-MINE"),
					_Row(parent="PINV-OUTSIDE", purchase_order="PO-MINE"),
					_Row(parent="PINV-OTHER", purchase_order="PO-OTHER"),
				],
				"Sales Invoice": [
					_Row(name="SINV-UNPAID", posting_date="2026-07-05", docstatus=1, status="Partly Paid")
				],
				"Sales Invoice Item": [_Row(parent="SINV-UNPAID", sales_order="SO-MINE")],
			}
			result = rows.get(doctype, [])
			filters = _kwargs.get("filters", {})
			if doctype == "Purchase Invoice Item":
				return [row for row in result if row.purchase_order in filters["purchase_order"][1]]
			if doctype == "Sales Invoice Item":
				return [row for row in result if row.sales_order in filters["sales_order"][1]]
			return result

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE"}),
			patch.object(tender.frappe.db, "has_column", has_column),
			patch.object(tender.frappe, "get_list", get_list),
		):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(
			payload["execution"]["invoice_status"],
			{
				"purchase_invoices": {"draft": 1, "submitted": 1, "unpaid": 1},
				"sales_invoices": {"draft": 0, "submitted": 0, "unpaid": 1},
			},
		)

	def test_acquisition_counts_each_transition_in_its_own_period(self):
		db = _FakeDB(
			{
				"DEAL-MULTI": {
					"assigned_to": "source@example.com",
					"go_no_go": "go",
					"go_no_go_at": "2026-06-04 10:00:00",
					"ready_at": "2026-06-04 10:00:00",
					"ready_by": "source@example.com",
					"submitted_at": "2026-07-08 11:00:00",
					"submitted_by": "source@example.com",
					"result": "won",
					"result_at": "2026-08-12 12:00:00",
				},
			},
			creations={"DEAL-MULTI": "2026-05-02 09:00:00"},
		)
		tender = _load_tender(db, ["Sales User"])

		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-MULTI"}):
			may = tender.tender_dashboard("Test Company", "2026-05-01", "2026-05-31")["acquisition"]
			june = tender.tender_dashboard("Test Company", "2026-06-01", "2026-06-30")["acquisition"]
			july = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")["acquisition"]
			august = tender.tender_dashboard("Test Company", "2026-08-01", "2026-08-31")["acquisition"]

		self.assertEqual(may["identified"], 1)
		self.assertEqual(sum(may[key] for key in ("go", "ready", "submitted", "won")), 0)
		self.assertEqual((june["go"], june["ready"]), (1, 1))
		self.assertEqual((june["identified"], june["submitted"], june["won"]), (0, 0, 0))
		self.assertEqual(july["submitted"], 1)
		self.assertEqual((july["identified"], july["go"], july["won"]), (0, 0, 0))
		self.assertEqual(august["won"], 1)
		self.assertEqual((august["identified"], august["go"], august["submitted"]), (0, 0, 0))

	def test_ready_transition_occurs_when_required_documents_complete(self):
		# An attachment is a server fact: it arrives through the document
		# center, which writes it into the stored intake. The editor may not
		# submit one — a browser that could would be able to declare itself
		# ready. So the fixture is the deal as it stands right after that
		# upload: the file is there, the transition audit is not yet.
		db = _FakeDB(
			{
				"DEAL-READY": {
					"go_no_go": "go",
					"go_no_go_at": "2026-06-04 10:00:00",
					"go_no_go_by": "source@example.com",
					"assigned_to": "source@example.com",
					"documents": [
						{
							"label": "Bid security",
							"required": 1,
							"date": "2026-07-22",
							"files": [{"file_name": "bid_security.pdf"}],
						}
					],
				},
			}
		)
		tender = _load_tender(db, ["Sales User"])

		completed = tender.save_deal_intake(
			"DEAL-READY",
			{
				"go_no_go": "go",
				"documents": [{"label": "Bid security", "required": 1, "date": "2026-07-22"}],
			},
		)

		self.assertEqual(completed["intake"]["go_no_go_at"], "2026-06-04 10:00:00")
		self.assertEqual(completed["intake"]["ready_at"], "2026-07-22 09:00:00")
		self.assertEqual(completed["intake"]["ready_by"], "source@example.com")
		with patch.object(tender, "_tender_deal_names", return_value={"DEAL-READY"}):
			june = tender.tender_dashboard("Test Company", "2026-06-01", "2026-06-30")["acquisition"]
			july = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")["acquisition"]
		self.assertEqual((june["go"], june["ready"]), (1, 0))
		self.assertEqual((july["go"], july["ready"]), (0, 1))

	def test_ready_regression_clears_audit_and_recompletion_records_a_new_transition(self):
		# A lot regresses when the document center detaches the file, not when
		# the editor stops listing it — the editor cannot take a file away any
		# more than it can add one. Every writer of that fact goes through
		# apply_ready_audit, so the rule is exercised where it lives.
		#
		# Both halves matter and only together: a stale ready_at would keep an
		# incomplete lot counted as ready, and a re-completion that reused the
		# old timestamp would file the second transition under the first one's
		# month.
		from stabler.api._tender_documents import apply_ready_audit

		intake = {
			"go_no_go": "go",
			"go_no_go_at": "2026-06-04 10:00:00",
			"ready_at": "2026-07-01 08:00:00",
			"ready_by": "first@example.com",
		}

		apply_ready_audit(
			intake,
			[{"label": "Bid security", "required": True, "done": False}],
			"second@example.com",
			"2026-07-22 09:00:00",
		)
		self.assertEqual((intake["ready_at"], intake["ready_by"]), ("", ""))

		apply_ready_audit(
			intake,
			[{"label": "Bid security", "required": True, "done": True}],
			"second@example.com",
			"2026-07-22 09:00:00",
		)
		self.assertEqual(intake["ready_at"], "2026-07-22 09:00:00")
		self.assertEqual(intake["ready_by"], "second@example.com")

	def test_ready_filter_requires_complete_server_audit_evidence(self):
		db = _FakeDB({"DEAL-READY": {}})
		tender = _load_tender(db, ["Sales User"])
		intake = {
			"go_no_go": "go",
			"ready_at": "2099-01-01 00:00:00",
			"ready_by": "",
			"documents": [{"label": "Bid security", "required": 1, "done": 1}],
		}

		evidence = tender._tender_filter_evidence(intake, "2026-01-10", "good")

		self.assertFalse(evidence["lifecycle"]["ready"])
		self.assertEqual(evidence["event_dates"]["ready"], "")

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
					_Row(
						name="SO-OPEN",
						custom_crm_deal="DEAL-MINE",
						transaction_date="2026-07-05",
						per_delivered=100,
						status="To Deliver and Bill",
						base_grand_total=100,
					),
					_Row(
						name="SO-CLOSED",
						custom_crm_deal="DEAL-MINE",
						transaction_date="2026-07-06",
						per_delivered=100,
						status="Closed",
						base_grand_total=100,
					),
					_Row(
						name="SO-CANCELLED",
						custom_crm_deal="DEAL-MINE",
						transaction_date="2026-07-07",
						per_delivered=0,
						status="Cancelled",
						base_grand_total=100,
					),
				]
			return []

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE"}),
			patch.object(tender.frappe.db, "has_column", has_column),
			patch.object(tender.frappe, "get_list", get_list),
		):
			payload = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")

		self.assertEqual(payload["execution"]["sales_orders"], 1)
		self.assertEqual(payload["execution"]["delivered"], 1)
		self.assertEqual(payload["execution"]["delivery_pending"], 0)

	def test_execution_targets_exclude_documents_without_read_permission(self):
		db = _FakeDB({"DEAL-MINE": {"assigned_to": "source@example.com"}})
		tender = _load_tender(db, ["Sales User"])
		so_rows = [
			_Row(
				name="SO-ALLOWED",
				customer="Customer",
				customer_name="Customer",
				transaction_date="2026-07-05",
				delivery_date="2026-07-20",
				currency="UZS",
				rounded_total=100,
				grand_total=100,
				base_grand_total=100,
				per_delivered=0,
				per_billed=0,
				status="To Deliver and Bill",
				custom_board_stage=None,
				custom_crm_deal="DEAL-MINE",
			),
			_Row(
				name="SO-DENIED",
				customer="Customer",
				customer_name="Customer",
				transaction_date="2026-07-05",
				delivery_date="2026-07-20",
				currency="UZS",
				rounded_total=200,
				grand_total=200,
				base_grand_total=200,
				per_delivered=0,
				per_billed=0,
				status="To Deliver and Bill",
				custom_board_stage=None,
				custom_crm_deal="DEAL-MINE",
			),
		]
		po_rows = [
			_Row(
				name="PO-ALLOWED",
				supplier="Supplier",
				supplier_name="Supplier",
				transaction_date="2026-07-05",
				schedule_date="2026-07-20",
				per_received=0,
				status="To Receive",
				base_grand_total=100,
				custom_crm_deal="DEAL-MINE",
			),
			_Row(
				name="PO-DENIED",
				supplier="Supplier",
				supplier_name="Supplier",
				transaction_date="2026-07-05",
				schedule_date="2026-07-20",
				per_received=0,
				status="To Receive",
				base_grand_total=200,
				custom_crm_deal="DEAL-MINE",
			),
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

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-MINE"}),
			patch.object(tender, "_ensure_default_stages"),
			patch.object(tender, "_stages", return_value=[]),
			patch.object(tender, "_require_tender_view"),
			patch.object(tender.frappe.db, "has_column", has_column),
			patch.object(tender.frappe, "get_all", document_rows),
			patch.object(tender.frappe, "get_list", document_rows),
			patch.object(tender.frappe, "has_permission", has_permission),
		):
			dashboard = tender.tender_dashboard("Test Company", "2026-07-01", "2026-07-31")
			sales_board = tender.so_board("Test Company", tender_only=1)
			logistics = tender.logist_board("Test Company")

		self.assertEqual(dashboard["execution"]["sales_orders"], 1)
		self.assertEqual(dashboard["execution"]["purchase_orders"], 1)
		self.assertEqual([card["name"] for card in sales_board["cards"]], ["SO-ALLOWED"])
		self.assertEqual([row["po"] for row in logistics["rows"]], ["PO-ALLOWED"])

	def test_sourcing_target_excludes_deals_without_read_permission(self):
		db = _FakeDB(
			{
				"DEAL-ALLOWED": {"assigned_to": "source@example.com"},
				"DEAL-DENIED": {"assigned_to": "source@example.com"},
			}
		)
		tender = _load_tender(db, ["Sales User"])

		def has_permission(doctype, _ptype, doc=None):
			return not (doctype == "CRM Deal" and doc == "DEAL-DENIED")

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-ALLOWED", "DEAL-DENIED"}),
			patch.object(tender, "_require_tender_view"),
			patch.object(tender, "_deal_deadlines", return_value={"risk": "good", "milestones": []}),
			patch.object(tender, "_deal_landed", return_value=(0.0, 0)),
			patch.object(tender, "_deal_label", side_effect=lambda deal: deal),
			patch.object(tender.frappe, "has_permission", has_permission),
		):
			payload = tender.sourcing_my_tenders("Test Company")

		self.assertEqual([row["deal"] for row in payload["rows"]], ["DEAL-ALLOWED"])

	def test_director_board_never_reads_or_returns_denied_deals(self):
		db = _FakeDB({"DEAL-ALLOWED": {}, "DEAL-DENIED": {"result": "won"}})
		tender = _load_tender(db, ["Stabler Tender Director"])

		def has_permission(doctype, _ptype, doc=None):
			return not (doctype == "CRM Deal" and doc == "DEAL-DENIED")

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-ALLOWED", "DEAL-DENIED"}),
			patch.object(tender, "_deal_deadlines", return_value={"risk": "good", "milestones": []}),
			patch.object(
				tender,
				"_bid_inputs",
				return_value=({}, {"so_revenue": 0, "po_landed": 0, "po_count": 0, "so_count": 0}),
			),
			patch.object(
				tender,
				"_compute_bid_pnl",
				return_value={"bid_price": 0, "ostatok": 0, "margin_on_revenue_pct": 0},
			),
			patch.object(tender, "_deal_label", side_effect=lambda deal: deal),
			patch.object(tender.frappe, "has_permission", has_permission),
		):
			payload = tender.tender_director_board("Test Company")

		self.assertEqual([row["deal"] for row in payload["rows"]], ["DEAL-ALLOWED"])

	def test_director_board_uses_deal_name_as_the_stable_final_sort_key(self):
		db = _FakeDB({"DEAL-B": {}, "DEAL-A": {}})
		tender = _load_tender(db, ["Stabler Tender Director"])

		with (
			patch.object(tender, "_tender_deal_names", return_value=("DEAL-B", "DEAL-A")),
			patch.object(tender, "_deal_deadlines", return_value={"risk": "good", "milestones": []}),
			patch.object(
				tender,
				"_bid_inputs",
				return_value=({}, {"so_revenue": 0, "po_landed": 0, "po_count": 0, "so_count": 0}),
			),
			patch.object(
				tender,
				"_compute_bid_pnl",
				return_value={"bid_price": 0, "ostatok": 0, "margin_on_revenue_pct": 0},
			),
			patch.object(tender, "_deal_label", side_effect=lambda deal: deal),
		):
			payload = tender.tender_director_board("Test Company")

		self.assertEqual([row["deal"] for row in payload["rows"]], ["DEAL-A", "DEAL-B"])

	def test_director_payload_can_omit_rows_without_changing_kpis(self):
		db = _FakeDB({"DEAL-1": {}})
		tender = _load_tender(db, ["Stabler Tender Director"])

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-1"}),
			patch.object(tender, "_deal_deadlines", return_value={"risk": "good", "milestones": []}),
			patch.object(
				tender,
				"_bid_inputs",
				return_value=({}, {"so_revenue": 0, "po_landed": 0, "po_count": 0, "so_count": 0}),
			),
			patch.object(
				tender,
				"_compute_bid_pnl",
				return_value={"bid_price": 0, "ostatok": 0, "margin_on_revenue_pct": 0},
			),
			patch.object(tender, "_deal_label", return_value="Deal 1"),
		):
			payload_with_rows = tender._tender_director_payload("Test Company", include_rows=True)
			payload_without_rows = tender._tender_director_payload("Test Company", include_rows=False)

		self.assertEqual(payload_without_rows["kpi"], payload_with_rows["kpi"])
		self.assertEqual(payload_without_rows["currency"], payload_with_rows["currency"])
		self.assertNotIn("rows", payload_without_rows)

	def test_dashboard_exposes_executive_kpis_only_to_director_view(self):
		db = _FakeDB()
		tender = _load_tender(db, ["Stabler Tender Director"])

		with patch.object(
			tender,
			"_tender_director_payload",
			return_value={
				"currency": "UZS",
				"kpi": {"count": 35, "total_value": 3041273130},
			},
		) as director_payload:
			payload = tender._dashboard_executive_payload("Test Company", {"director"})

		self.assertEqual(payload["executive_kpi"]["count"], 35)
		self.assertEqual(payload["executive_currency"], "UZS")
		director_payload.assert_called_once_with("Test Company", include_rows=False)

	def test_dashboard_hides_executive_kpis_without_director_view(self):
		db = _FakeDB()
		tender = _load_tender(db, ["Sales User"])

		with patch.object(tender, "_tender_director_payload") as director_payload:
			payload = tender._dashboard_executive_payload("Test Company", {"sourcing"})

		self.assertIsNone(payload["executive_kpi"])
		self.assertEqual(payload["executive_currency"], "")
		director_payload.assert_not_called()

	def test_operational_boards_redact_denied_deal_data_but_keep_permitted_po(self):
		db = _FakeDB({"DEAL-DENIED": {"delivery_deadline": "2026-07-01"}})
		tender = _load_tender(db, ["Stabler Declarant", "Stabler Logist"])
		po = _Row(
			name="PO-1",
			supplier="SUP-1",
			supplier_name="Permitted Supplier",
			transaction_date="2026-07-05",
			schedule_date="2026-07-25",
			per_received=0,
			custom_crm_deal="DEAL-DENIED",
			status="To Receive",
		)

		def has_permission(doctype, _ptype, doc=None):
			return not (doctype == "CRM Deal" and doc == "DEAL-DENIED")

		with (
			patch.object(tender, "_po_rows_for_views", return_value=([po], False)),
			patch.object(tender.frappe, "has_permission", has_permission),
		):
			declarant = tender.declarant_queue("Test Company")
			logistics = tender.logist_board("Test Company")

		self.assertEqual([row["po"] for row in declarant["rows"]], ["PO-1"])
		self.assertEqual([row["po"] for row in logistics["rows"]], ["PO-1"])
		self.assertEqual(declarant["rows"][0]["deal_label"], "")
		self.assertEqual(logistics["rows"][0]["deal_label"], "")
		self.assertIsNone(logistics["rows"][0]["delivery"])

	def test_director_legacy_result_is_unverified_not_a_verified_win(self):
		db = _FakeDB(
			{
				"DEAL-LEGACY": {"result": "won", "result_at": "2026-06-01"},
				"DEAL-VERIFIED": {
					"result": "lost",
					"result_at": "2026-07-01",
					"submitted_at": "2026-06-20",
					"submitted_by": "source@example.com",
				},
			}
		)
		tender = _load_tender(db, ["Stabler Tender Director"])

		with (
			patch.object(tender, "_tender_deal_names", return_value={"DEAL-LEGACY", "DEAL-VERIFIED"}),
			patch.object(tender, "_deal_deadlines", return_value={"risk": "good", "milestones": []}),
			patch.object(
				tender,
				"_bid_inputs",
				return_value=({}, {"so_revenue": 0, "po_landed": 0, "po_count": 0, "so_count": 0}),
			),
			patch.object(
				tender,
				"_compute_bid_pnl",
				return_value={"bid_price": 0, "ostatok": 0, "margin_on_revenue_pct": 0},
			),
			patch.object(tender, "_deal_label", side_effect=lambda deal: deal),
		):
			payload = tender.tender_director_board("Test Company")

		self.assertEqual(payload["kpi"]["won"], 0)
		self.assertEqual(payload["kpi"]["lost"], 1)
		self.assertEqual(payload["kpi"]["unverified_history"], 1)
		self.assertEqual(payload["kpi"]["win_rate"], 0)
		legacy = next(row for row in payload["rows"] if row["deal"] == "DEAL-LEGACY")
		self.assertEqual(legacy["result"], "")
		self.assertEqual(legacy["status"], "unverified_history")

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


class TestDeadlineSummaryMatchesItsOwnRiskChip(unittest.TestCase):
	"""Bir CRM kartı iki şey gösteriyor: tarih rozeti ve risk çipi. TenderCrm.vue
	İKİSİNİ birden `v-if="c.deadline"` ile kapıyor. `_deal_deadlines` 2026-08-01'e
	kadar hiç `deadline` anahtarı DÖNDÜRMÜYORDU; crm_board'un
	`deadline_info.get("deadline")` çağrısı her seferinde None veriyor, böylece
	panodaki her kart hem tarihini hem de risk rengini sessizce kaybediyordu —
	hata yok, boş liste yok, yalnız eksik bilgi. Buradaki testler o anahtarın
	varlığını ve ondan daha önemlisi ANLAMINI çiviliyor: rozetteki tarih, çipi
	kırmızıya boyayan kilometre taşının ta kendisi olmalı."""

	def _deadlines(self, intake: dict) -> dict:
		tender = _load_tender(_FakeDB({"DEAL-1": intake}), ["Stabler Tender Manager"])
		# has_column yalnız CRM Deal/custom_tender_intake için True: Sales/Purchase
		# Order kolonları yok sayılır, kilometre taşları sadece intake'ten doğar.
		return tender._deal_deadlines("DEAL-1", "Test Company", intake)

	def test_the_badge_date_is_the_milestone_that_set_the_risk(self):
		# Bugün 2026-07-22 (stub). Teklif iki gün geçmiş, teslim 41 gün uzakta.
		res = self._deadlines({"bid_deadline": "2026-07-20", "delivery_deadline": "2026-09-01"})

		self.assertIn("deadline", res, "crm_board bu anahtarı okuyor; yokluğu kartı boşaltır")
		self.assertEqual(res["risk"], "risk")
		self.assertEqual(
			res["deadline"],
			"2026-07-20",
			"kırmızı çipin yanında rahat bir gelecek tarih göstermek, kartı yalancı yapar",
		)

	def test_a_finished_milestone_never_becomes_the_badge(self):
		# Teklif verilmiş (result var → bid_done), teslim hâlâ açık. Rozet, biten
		# işi değil kalan işi göstermeli — yoksa kapanmış bir tarih paneli meşgul eder.
		res = self._deadlines(
			{"bid_deadline": "2026-07-20", "result": "won", "delivery_deadline": "2026-09-01"}
		)

		self.assertEqual(res["deadline"], "2026-09-01")
		self.assertEqual(res["risk"], "good")

	def test_no_dates_yields_no_badge_instead_of_an_exception(self):
		# Yeni açılmış bir anlaşmada hiçbir tarih yok. Boş liste üzerinde min()
		# ValueError atsaydı, tek tarihsiz anlaşma tüm panoyu 500'e düşürürdü.
		res = self._deadlines({})

		self.assertIsNone(res["deadline"])
		self.assertEqual(res["risk"], "good")

	def test_the_badge_and_the_chip_are_read_from_one_list(self):
		# Aynı doğruyu iki kez hesaplamak, iki farklı cevabın kapısını açar.
		# `deadline`, `risk`'i üreten milestones listesinden seçilmiş olmalı.
		res = self._deadlines({"bid_deadline": "2026-07-25", "delivery_deadline": "2026-07-24"})

		dates = {m["date"] for m in res["milestones"] if m["date"]}
		self.assertIn(res["deadline"], dates)
		self.assertEqual(res["deadline"], "2026-07-24", "en yakın açık kilometre taşı")


if __name__ == "__main__":
	unittest.main()
