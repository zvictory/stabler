"""Behaviour contracts for Tender Master company and record permissions."""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
import types
import unittest
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = _ROOT / "api" / "tender_master.py"
STATE_SOURCE = _ROOT / "api" / "_tender_master_state.py"
COMPOSABLE_SOURCE = _ROOT / "public" / "js" / "composables" / "tenderMaster.js"


class _Doc(dict):
	def __getattr__(self, field):
		return self.get(field)

	def __setattr__(self, field, value):
		self[field] = value

	def as_dict(self):
		return dict(self)

	def insert(self):
		self["inserted"] = True
		return self

	def save(self):
		self["saved"] = True
		return self


class _FakeFrappe:
	#: Rows this user may not read. Real `frappe.get_list` enforces role AND user
	#: permissions inside the query — that is precisely what separates it from
	#: `get_all` — so the double enforces them there too. Modelling the check
	#: anywhere else would make the fake reward an API that re-reads every row by
	#: hand and punish one that simply trusts `get_list`, i.e. it would grade the
	#: implementation on the fake's shortcut instead of on Frappe's behaviour.
	unreadable = {("CRM Deal", "LOT-DENIED")}

	def __init__(self):
		self.docs = {
			("Tender Master", "TND-2026-00001"): _Doc(
				name="TND-2026-00001", company="ACME", title="Network tender", currency="USD", status="New"
			),
			("CRM Deal", "LOT-ALLOWED"): _Doc(
				name="LOT-ALLOWED",
				company="ACME",
				custom_parent_tender="TND-2026-00001",
				status="Open",
				custom_estimated_value=125,
			),
			("CRM Deal", "LOT-DENIED"): _Doc(
				name="LOT-DENIED",
				company="ACME",
				custom_parent_tender="TND-2026-00001",
				status="Won",
				custom_estimated_value=500,
			),
		}
		self.created: list[_Doc] = []
		self.last_filters: dict | None = None
		self.last_list_kwargs: dict | None = None
		self.list_calls: list[str] = []

	def get_doc(self, doctype, name):
		return self.docs[(doctype, name)]

	def new_doc(self, doctype):
		doc = _Doc(doctype=doctype, name="TND-NEW")
		self.created.append(doc)
		return doc

	def get_all(self, doctype, **kwargs):
		"""Unfiltered read, like the real `get_all`: ignores permissions."""
		return self._query(doctype, kwargs, permitted=False)

	def get_list(self, doctype, **kwargs):
		"""Permission-filtered read, like the real `get_list`."""
		return self._query(doctype, kwargs, permitted=True)

	def _query(self, doctype, kwargs, permitted):
		filters = kwargs.get("filters", {})
		self.list_calls.append(doctype)
		# Only the record-scope (list-form) filters are the ones the scope tests
		# assert on; the derived-card passes below use dict filters.
		if doctype == "Tender Master":
			self.last_filters = filters
			self.last_list_kwargs = kwargs
		rows = [doc for (kind, _name), doc in self.docs.items() if kind == doctype]
		if permitted:
			rows = [row for row in rows if (doctype, row["name"]) not in self.unreadable]
		if isinstance(filters, dict):
			for field, value in filters.items():
				if not isinstance(value, list):
					rows = [row for row in rows if row.get(field) == value]
					continue
				operator, operand = value
				if operator == "is":
					rows = [row for row in rows if bool(row.get(field)) == (operand == "set")]
				elif operator == "in":
					rows = [row for row in rows if row.get(field) in operand]
				elif operator == "<":
					rows = [row for row in rows if int(row.get(field) or 0) < operand]
				else:
					raise AssertionError(f"unsupported dict filter operator: {operator}")
		else:
			for field, operator, value in filters:
				if operator == "=":
					rows = [row for row in rows if row.get(field) == value]
				elif operator == "in":
					rows = [row for row in rows if row.get(field) in value]
				elif operator == "not in":
					rows = [row for row in rows if row.get(field) not in value]
		if kwargs.get("fields") == ["count(name) as total"]:
			return [{"total": len(rows)}]
		return rows


def _load_api(fake: _FakeFrappe, *, tender_allowed=True, missing_columns=()):
	for name in (
		"stabler.api.tender_master",
		"stabler.api.tender",
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.organization",
	):
		sys.modules.pop(name, None)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.session = types.SimpleNamespace(user="sales@example.com")
	frappe.get_doc = fake.get_doc
	frappe.new_doc = fake.new_doc
	frappe.get_list = fake.get_list
	frappe.get_all = fake.get_all
	frappe.db = types.SimpleNamespace(
		has_column=lambda _doctype, column: column not in missing_columns
	)
	frappe.parse_json = lambda value: value
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	# Same source of truth as the `get_list` scoping above, so the explicit
	# single-document checks (the `deal=` filter) and the list scoping cannot
	# disagree about who may read what.
	frappe.has_permission = lambda doctype, ptype="read", doc=None: (
		(doctype, getattr(doc, "name", doc)) not in fake.unreadable
	)
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.now_datetime = lambda: "2026-07-01"
	utils.add_days = lambda value, days: f"{value}+{days}"
	# Honest date helpers, not stubs that always agree: the overdue-bid rule is
	# real arithmetic, so a wrong comparison must be able to fail the test.
	utils.today = lambda: "2026-07-01"
	utils.getdate = lambda value: date.fromisoformat(str(value)[:10])
	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: (
		company or (_ for _ in ()).throw(ValueError("Company is required."))
	)
	organization = types.ModuleType("stabler.api.organization")
	organization._ADMIN_ROLES = ("System Manager", "Stabler Admin")
	organization._user_allowed_companies = lambda _user: ["ACME"]
	tender = types.ModuleType("stabler.api.tender")
	tender._require_tender = lambda _company=None: (
		None if tender_allowed else (_ for _ in ()).throw(PermissionError("Not permitted"))
	)
	tender._dashboard_period = lambda _from_date=None, _to_date=None: ("2026-07-01", "2026-07-31")
	_default_intake = {
		"submitted_at": "2026-07-10",
		"submitted_by": "user",
		"result": "won",
		"result_at": "2026-07-11",
	}
	# LOT-A is the one deal-scoped test case that must NOT match the lifecycle
	# filters, so a per-deal override is needed instead of the shared constant.
	_intake_overrides = {"LOT-A": {"submitted_at": None, "submitted_by": None, "result": None, "result_at": None}}
	tender._read_intake = lambda deal: _intake_overrides.get(deal, _default_intake)
	tender._parse_intake = lambda raw: (
		raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
	)
	tender._tender_event_dates = lambda _intake, _creation: {
		"identified": "2026-07-01",
		"submitted": "2026-07-10",
		"won": "2026-07-11",
	}
	tender._in_dashboard_period = lambda value, _start, _end: bool(value)
	tender._has_submission_evidence = lambda intake: bool(
		intake.get("submitted_at") and intake.get("submitted_by")
	)
	tender._deal_deadlines = lambda _deal, _company, _intake: {"risk": "risk"}
	frappe.get_roles = lambda _user=None: ["Sales User"]
	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.organization": organization,
			"stabler.api.tender": tender,
		}
	)
	return importlib.import_module("stabler.api.tender_master")


class TestTenderMasterApi(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)
		self.cross_company_deal = _Doc(
			name="DEAL-OTHER", company="Other Co", custom_parent_tender="TND-2026-00001"
		)

	def test_get_tender_master_rejects_cross_company_name(self):
		"""Removing the selected-company check would expose a named foreign tender."""
		with self.assertRaises(PermissionError):
			self.api.get_tender_master("TND-2026-00001", company="Other Co")

	def test_public_endpoints_reject_when_tender_module_is_unavailable(self):
		"""Removing the Tender module gate would expose its APIs to unavailable tenants."""
		api = _load_api(self.fake, tender_allowed=False)
		calls = (
			lambda: api.list_tender_masters(company="ACME"),
			lambda: api.get_tender_master("TND-2026-00001", company="ACME"),
			lambda: api.save_tender_master({"title": "Network tender"}, company="ACME"),
		)
		for call in calls:
			with self.assertRaises(PermissionError):
				call()

	def test_get_tender_master_returns_only_permitted_child_lots(self):
		"""Removing per-lot permission filtering would disclose an unreadable CRM Deal."""
		result = self.api.get_tender_master("TND-2026-00001", company="ACME")
		self.assertEqual([row["name"] for row in result["lots"]], ["LOT-ALLOWED"])
		self.assertEqual(
			result["summary"],
			{"lot_count": 1, "open_lot_count": 1, "estimated_total": 125.0, "currency": "USD"},
		)

	def test_save_tender_master_uses_allowlisted_fields(self):
		"""Allowing arbitrary payload keys would let callers overwrite audit ownership."""
		result = self.api.save_tender_master(
			{"title": "Network tender", "company": "ACME", "owner": "Administrator"}, company="ACME"
		)
		self.assertNotIn("owner", result)
		self.assertEqual(result["company"], "ACME")

	def test_parent_tender_company_must_match_deal_company(self):
		"""Removing this validation would link a CRM Deal to another company's tender."""
		with self.assertRaises(ValueError):
			self.api.validate_deal_parent_tender(self.cross_company_deal)

	def test_list_filters_use_canonical_status_stage_risk_deadline_and_deal(self):
		"""Removing any filter would make dashboard drill-downs show a broader portfolio."""
		self.api.list_tender_masters(
			company="ACME",
			status="won",
			stage="submitted",
			risk="risk",
			deal="LOT-ALLOWED",
			from_date="2026-07-01",
			to_date="2026-07-31",
		)
		filters = self.fake.last_filters
		self.assertIn(["name", "in", ["TND-2026-00001"]], filters)
		self.assertIn(["name", "=", "TND-2026-00001"], filters)

	def test_list_deal_filter_rejects_unreadable_or_foreign_deals_before_resolving_parent(self):
		"""Checking a deal's parent before permission/company scope would leak Tender Master existence."""
		with self.assertRaises(PermissionError):
			self.api.list_tender_masters(company="ACME", deal="LOT-DENIED")
		self.fake.docs[("CRM Deal", "LOT-OTHER")] = self.cross_company_deal
		with self.assertRaises(PermissionError):
			self.api.list_tender_masters(company="ACME", deal="LOT-OTHER")

	def test_list_deal_filter_does_not_leak_sibling_lot_under_shared_parent(self):
		"""Skipping the deal-narrowing loop guard would let a sibling lot's lifecycle match leak the shared parent tender into a lot that does not itself qualify."""
		self.fake.docs[("CRM Deal", "LOT-A")] = _Doc(
			name="LOT-A",
			company="ACME",
			custom_parent_tender="TND-2026-00001",
			status="Open",
			custom_estimated_value=10,
		)
		self.fake.docs[("CRM Deal", "LOT-B")] = _Doc(
			name="LOT-B",
			company="ACME",
			custom_parent_tender="TND-2026-00001",
			status="Open",
			custom_estimated_value=20,
		)
		result = self.api.list_tender_masters(company="ACME", deal="LOT-A", stage="submitted")
		filters = self.fake.last_filters
		self.assertIn(["name", "in", ["__no_permitted_tender_master__"]], filters)
		self.assertEqual(result["records"], [])

	def test_list_deal_filter_checks_permission_before_scanning_deal_candidates(self):
		"""Scanning all qualifying CRM Deals before checking the requested deal's permission would run an unnecessary — and leaky — full-portfolio scan for a lot the caller cannot read."""
		with self.assertRaises(PermissionError):
			self.api.list_tender_masters(company="ACME", deal="LOT-DENIED", stage="submitted")
		self.assertIsNone(self.fake.last_filters)

	def test_list_filters_without_deal_preserve_all_qualifying_parents(self):
		"""Applying the deal-narrowing loop guard when no deal is selected would drop qualifying lots from the portfolio view."""
		self.fake.docs[("Tender Master", "TND-2026-00002")] = _Doc(
			name="TND-2026-00002", company="ACME", title="Second tender", currency="USD", status="New"
		)
		self.fake.docs[("CRM Deal", "LOT-C")] = _Doc(
			name="LOT-C",
			company="ACME",
			custom_parent_tender="TND-2026-00002",
			status="Open",
			custom_estimated_value=30,
		)
		self.api.list_tender_masters(company="ACME", stage="submitted")
		filters = self.fake.last_filters
		self.assertIn(["name", "in", ["TND-2026-00001", "TND-2026-00002"]], filters)


def _lot(name, parent, value, intake=None):
	return _Doc(
		name=name,
		company="ACME",
		custom_parent_tender=parent,
		status="Open",
		custom_estimated_value=value,
		custom_tender_intake=json.dumps(intake) if intake else None,
	)


class TestTenderMasterDerivedBoard(unittest.TestCase):
	"""The board lane and card counts are a projection of the child lots."""

	def setUp(self):
		self.fake = _FakeFrappe()
		self.api = _load_api(self.fake)

	def _seed_mixed_lots(self):
		"""One parent with every outcome represented, plus an unreadable lot."""
		# Terminal: carries a bid deadline that must NOT become the next deadline.
		self.fake.docs[("CRM Deal", "LOT-WON")] = _lot(
			"LOT-WON",
			"TND-2026-00001",
			20,
			{
				"result": "won",
				"submitted_at": "2026-05-02",
				"submitted_by": "user",
				"bid_deadline": "2026-05-01",
			},
		)
		self.fake.docs[("CRM Deal", "LOT-SUBMITTED")] = _lot(
			"LOT-SUBMITTED",
			"TND-2026-00001",
			30,
			{"submitted_at": "2026-06-20", "submitted_by": "user", "bid_deadline": "2026-08-15"},
		)
		# Deadline passed with no result and no no-go: overdue.
		self.fake.docs[("CRM Deal", "LOT-OVERDUE")] = _lot(
			"LOT-OVERDUE", "TND-2026-00001", 40, {"bid_deadline": "2026-06-01"}
		)
		# Five live supplier bids clear the policy threshold for LOT-SUBMITTED;
		# the cancelled sixth must not be counted.
		for index in range(5):
			self.fake.docs[("Supplier Quotation", f"SQ-{index}")] = _Doc(
				name=f"SQ-{index}", company="ACME", custom_crm_deal="LOT-SUBMITTED", docstatus=1
			)
		self.fake.docs[("Supplier Quotation", "SQ-CANCELLED")] = _Doc(
			name="SQ-CANCELLED", company="ACME", custom_crm_deal="LOT-SUBMITTED", docstatus=2
		)

	def _board_record(self, name, api=None):
		records = (api or self.api).list_tender_masters(company="ACME")["records"]
		return next(row for row in records if row["name"] == name)

	def test_card_counts_equal_the_lot_drilldown_the_same_user_can_open(self):
		"""A card must be reconcilable against the lots that user can actually read.

		This is the whole point of deriving the lane: if the card counted every
		lot in the database while the drill-down showed only the permitted ones,
		a restricted user would see "4 lots" and open a list of 3 — and would
		reasonably conclude the board is broken (or, worse, learn that a lot they
		may not read exists). Card and drill-down therefore come from one pass
		over the same permitted rows, and open + won + lost must equal the total.
		"""
		self._seed_mixed_lots()
		record = self._board_record("TND-2026-00001")
		detail = self.api.get_tender_master("TND-2026-00001", company="ACME")

		visible = [row["name"] for row in detail["lots"]]
		self.assertNotIn("LOT-DENIED", visible)
		self.assertEqual(record["lot_count"], len(visible))
		self.assertEqual(
			record["open_lot_count"] + record["won_lot_count"] + record["lost_lot_count"],
			record["lot_count"],
		)
		self.assertEqual(
			{key: record[key] for key in ("stage", *_CARD_KEYS)},
			{
				"stage": "Partial Result",
				"lot_count": 4,
				"open_lot_count": 3,
				"submitted_lot_count": 1,
				"won_lot_count": 1,
				"lost_lot_count": 0,
				# Nothing in this fixture is still collecting bids: LOT-SUBMITTED's
				# round is closed, and the rest have no supplier bid at all, so
				# they classify `seen`, not `sourcing`. The rule itself is pinned
				# in test_policy_gap_counts_only_lots_still_collecting_bids.
				"policy_gap_count": 0,
				"risk_count": 1,
				# LOT-DENIED's 500 is excluded, like it is from the drill-down.
				"lot_estimated_total": 215.0,
				# LOT-WON's earlier deadline is settled, so it is not "next".
				"earliest_deadline": "2026-06-01",
			},
		)
		# The detail view must not be able to disagree with the card.
		self.assertEqual(detail["tender"]["stage"], record["stage"])
		self.assertEqual(detail["summary"]["lot_count"], record["lot_count"])
		self.assertEqual(detail["summary"]["estimated_total"], record["lot_estimated_total"])

	def test_policy_gap_counts_only_lots_still_collecting_bids(self):
		""""Policy gap" must mean the same thing here as on the funnel screen.

		The threshold (five supplier bids) is only actionable while the bid round
		is open. Counting an already-submitted or decided lot would put "Policy
		gap: 3" on a card while `tender.tender_funnel` reports 0 for the same
		tenant and the same day — two screens contradicting each other about a
		procurement-policy breach, with nothing anyone can do about the ones on
		the card. So the population is `sourcing`, exactly as it is there.
		"""
		# One live bid: still sourcing, four short of the threshold — actionable.
		self.fake.docs[("CRM Deal", "LOT-SOURCING")] = _lot("LOT-SOURCING", "TND-2026-00001", 10)
		self.fake.docs[("Supplier Quotation", "SQ-SOURCING")] = _Doc(
			name="SQ-SOURCING", company="ACME", custom_crm_deal="LOT-SOURCING", docstatus=1
		)
		# Two bids and the bid already submitted: under-sourced, but the round is
		# closed. A gap nobody can close is not a gap.
		self.fake.docs[("CRM Deal", "LOT-THIN")] = _lot(
			"LOT-THIN",
			"TND-2026-00001",
			10,
			{"submitted_at": "2026-06-10", "submitted_by": "user"},
		)
		for index in range(2):
			self.fake.docs[("Supplier Quotation", f"SQ-THIN-{index}")] = _Doc(
				name=f"SQ-THIN-{index}", company="ACME", custom_crm_deal="LOT-THIN", docstatus=1
			)

		record = self._board_record("TND-2026-00001")
		self.assertEqual(record["lot_count"], 3)
		self.assertEqual(record["policy_gap_count"], 1)

	def test_board_page_costs_a_constant_number_of_queries(self):
		"""Deriving the lane must not cost one query per lot.

		The board renders a whole page of parents, each with several lots. A
		per-lot read is invisible on the four-lot fixture below and lethal on a
		real portfolio, so the query count is asserted, not assumed: one pass for
		the lots, one grouped pass for the supplier bids, whatever the lot count.
		"""
		self._seed_mixed_lots()
		self.fake.list_calls.clear()
		self.api.list_tender_masters(company="ACME")
		self.assertEqual(self.fake.list_calls.count("CRM Deal"), 1)
		self.assertEqual(self.fake.list_calls.count("Supplier Quotation"), 1)

	def test_manual_parent_status_never_decides_the_lane(self):
		"""The typed `status` is a note; the lots decide.

		Both directions are asserted, because either one alone is a lie the board
		would tell: a parent typed "Won" whose lots have not moved must not read
		Completed, and a parent still typed "New" whose every lot is decided must
		not sit in Preparation while the work is finished.
		"""
		self.fake.docs[("Tender Master", "TND-2026-00001")]["status"] = "Won"
		self.fake.docs[("Tender Master", "TND-2026-00002")] = _Doc(
			name="TND-2026-00002", company="ACME", title="Second tender", currency="USD", status="New"
		)
		self.fake.docs[("CRM Deal", "LOT-DECIDED")] = _lot(
			"LOT-DECIDED",
			"TND-2026-00002",
			10,
			{"result": "lost", "submitted_at": "2026-06-01", "submitted_by": "user"},
		)

		records = {row["name"]: row for row in self.api.list_tender_masters(company="ACME")["records"]}
		self.assertEqual(records["TND-2026-00001"]["status"], "Won")
		self.assertEqual(records["TND-2026-00001"]["stage"], "Preparation")
		self.assertEqual(records["TND-2026-00002"]["status"], "New")
		self.assertEqual(records["TND-2026-00002"]["stage"], "Completed")

	def test_missing_intake_column_degrades_instead_of_inventing_progress(self):
		"""On a site without the intake column the card must under-claim, not guess.

		Submissions, results and bid deadlines all live in the intake JSON. With
		that column absent the only observable fact left is that supplier bids
		exist, so the lane may say Active — but it must never report a submission,
		a win or an overdue bid it cannot see.
		"""
		self._seed_mixed_lots()
		api = _load_api(self.fake, missing_columns=("custom_tender_intake",))
		record = self._board_record("TND-2026-00001", api=api)
		self.assertEqual(record["lot_count"], 4)
		self.assertEqual(record["stage"], "Active")
		self.assertEqual(record["submitted_lot_count"], 0)
		self.assertEqual(record["won_lot_count"], 0)
		self.assertEqual(record["lost_lot_count"], 0)
		self.assertEqual(record["risk_count"], 0)
		self.assertIsNone(record["earliest_deadline"])


#: Card keys every board record must carry, checked as one dict so a silently
#: dropped count cannot pass.
_CARD_KEYS = (
	"lot_count",
	"open_lot_count",
	"submitted_lot_count",
	"won_lot_count",
	"lost_lot_count",
	"policy_gap_count",
	"risk_count",
	"lot_estimated_total",
	"earliest_deadline",
)

#: Reads that must never appear inside a loop body in the functions below. Each
#: is a per-record round trip; `has_column` is included because re-asking the
#: schema per lot is the same mistake wearing a cheaper hat, and `has_permission`
#: because handing it a docNAME makes Frappe load the whole document
#: (`permissions.py` resolves the string through `get_lazy_doc`) — a per-lot
#: permission "check" is a per-lot document read, and `get_list` already applied
#: that verdict in the query.
_PER_RECORD_READS = {
	"get_list",
	"get_all",
	"get_value",
	"get_doc",
	"sql",
	"has_column",
	"has_permission",
	"_read_intake",
	"_deal_deadlines",
}

#: The functions this task owns. `_qualifying_parent_names` is excluded: it
#: already does per-deal reads (pre-existing, and it only runs for the three
#: lifecycle drill-down filters), so a file-wide assertion would fail for a
#: reason this rule is not about.
_DERIVATION_FUNCTIONS = (
	"_supplier_bid_counts",
	"_tender_lot_cards",
	"list_tender_masters",
	"get_tender_master",
)


def _call_name(node: ast.AST) -> str:
	if isinstance(node, ast.Attribute):
		return node.attr
	if isinstance(node, ast.Name):
		return node.id
	return ""


def _per_record_reads_inside_loops(function: ast.FunctionDef) -> list[str]:
	"""Names of per-record reads that are evaluated once per iteration.

	A comprehension's FIRST iterable is evaluated once, so `[r for r in
	frappe.get_list(...)]` is fine; its element expression and conditions are
	not, and neither is anything in a `for`/`while` body.
	"""
	hits: list[str] = []
	for node in ast.walk(function):
		if isinstance(node, (ast.For, ast.While)):
			repeated = [*node.body, *node.orelse]
		elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
			repeated = [
				*([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]),
				*[test for gen in node.generators for test in gen.ifs],
				*[gen.iter for gen in node.generators[1:]],
			]
		else:
			continue
		for branch in repeated:
			for inner in ast.walk(branch):
				if isinstance(inner, ast.Call) and _call_name(inner.func) in _PER_RECORD_READS:
					hits.append(f"{function.name}:{_call_name(inner.func)}")
	return hits


class TestTenderMasterDerivationSource(unittest.TestCase):
	def test_derivation_never_reads_a_record_inside_a_loop(self):
		"""One query per lot is the failure mode this whole design exists to avoid.

		It cannot be caught by the behaviour tests' fixtures — four fake lots
		make N+1 look instant — and it cannot be caught in review either, because
		the offending line (`_read_intake(lot)` in the aggregation loop) is the
		obvious way to write it. So the source is checked directly.
		"""
		tree = ast.parse(API_SOURCE.read_text())
		functions = {
			node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
		}
		missing = [name for name in _DERIVATION_FUNCTIONS if name not in functions]
		self.assertEqual(missing, [], "renamed derivation function — this guard stopped checking")
		hits: list[str] = []
		for name in _DERIVATION_FUNCTIONS:
			hits.extend(_per_record_reads_inside_loops(functions[name]))
		self.assertEqual(hits, [])

	def test_aggregate_counts_are_not_pushed_into_a_field_list(self):
		"""`count(<column>) as n` in a SELECT string fails on the live Frappe
		version even though it reads fine locally, so the derived counts are
		summed in Python. The one pre-existing `count(name) as total` is the
		app-wide row-count idiom (see api/crm.py) and is left as it is.

		Only string literals inside a list are checked — a `fields=[...]` list is
		one, a docstring is not. Scanning the raw text instead would flag the
		docstring that warns against this very idiom, which is the opposite of
		what this guard is for.
		"""
		tree = ast.parse(API_SOURCE.read_text())
		aggregates: set[tuple[str, str]] = set()
		for node in ast.walk(tree):
			if not isinstance(node, ast.List):
				continue
			for element in node.elts:
				if isinstance(element, ast.Constant) and isinstance(element.value, str):
					aggregates.update(re.findall(r"count\((\w+)\) as (\w+)", element.value))
		self.assertEqual(aggregates, {("name", "total")})

	def test_spa_and_backend_board_lanes_cannot_drift(self):
		"""The SPA groups cards by the backend's derived lane string.

		They are two literal lists in two languages, so nothing but a test keeps
		them in step — and a rename on one side does not error, it silently drops
		a whole lane's tenders into the first column.
		"""

		def lanes(source: str) -> list[str]:
			match = re.search(r"LANES = \[(.*?)\]", source, re.S)
			self.assertIsNotNone(match, "LANES list not found")
			return re.findall(r'"([^"]+)"', match.group(1))

		python_lanes = lanes(STATE_SOURCE.read_text())
		self.assertEqual(
			python_lanes, ["Preparation", "Active", "Awaiting Result", "Partial Result", "Completed"]
		)
		self.assertEqual(lanes(COMPOSABLE_SOURCE.read_text()), python_lanes)


if __name__ == "__main__":
	unittest.main()
