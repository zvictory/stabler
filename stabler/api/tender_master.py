"""Company-safe Tender Master APIs and CRM Deal lot validation."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from stabler.api import _funnel, _tender_master_state
from stabler.api._common import _require_company
from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies
from stabler.api.tender import (
	_dashboard_period,
	_deal_deadlines,
	_has_submission_evidence,
	_in_dashboard_period,
	_parse_intake,
	_read_intake,
	_require_tender,
	_tender_event_dates,
)

_TENDER_FIELDS = (
	"naming_series",
	"company",
	"title",
	"tender_number",
	"buyer_name",
	"source",
	"publication_date",
	"submission_deadline",
	"currency",
	"estimated_total",
	"status",
	"owner_user",
)


#: Procurement policy: a lot needs at least this many supplier bids before its
#: pricing is defensible. Same threshold `tender.tender_funnel` reports on.
_MIN_SUPPLIER_BIDS = 5

#: The gap is only a gap while the lot is still being sourced — the same
#: population `tender.tender_funnel` counts (see the `stage == "sourcing"` test
#: there). Counting terminal lots too would let a finished tender advertise
#: "Policy gap: 3" on the board while the funnel reports 0 for the same tenant,
#: and nobody can act on a bid round that already closed.
_POLICY_GAP_STAGES = ("sourcing",)

#: Lot columns the drill-down renders. The intake / pricing columns are read for
#: the derivation but deliberately NOT returned — the SPA has no use for raw
#: intake JSON, and shipping it would put a whole bid history in every payload.
_LOT_LIST_FIELDS = ("name", "status", "custom_estimated_value", "currency", "modified")

#: Derived card counts. Every one counts lots the caller may actually READ, so a
#: card can always be reconciled against the drill-down the same user can open.
_CARD_COUNTS = (
	"lot_count",
	"open_lot_count",
	"submitted_lot_count",
	"won_lot_count",
	"lost_lot_count",
	"policy_gap_count",
	"risk_count",
)


def _empty_card() -> dict:
	"""A parent with no readable lots: lane Preparation, every count zero.

	Zeroes, not `None` — a tender with no lots yet HAS no lots, and the board
	should say 0 rather than hide the field and make the card look broken.
	"""
	card = {field: 0 for field in _CARD_COUNTS}
	card["lot_estimated_total"] = 0.0
	card["earliest_deadline"] = None
	card["stage"] = _tender_master_state.derive([])
	return card


def _bid_at_risk(intake: dict, today_d) -> bool:
	"""A lot is at risk when its bid deadline passed with no decision recorded.

	Mirrors `tender._milestone` (not done AND days left < 0) and
	`tender._deal_deadlines`'s definition of done for the bid milestone: a
	recorded result, or an explicit no-go. Only the intake's own dates are used
	— `_deal_deadlines` costs two queries plus a permission scan PER deal, and
	the board renders a whole page of parents at once. Contract/PO/delivery
	milestones are therefore left out rather than guessed at: an invented risk
	count is worse than a narrower one.
	"""
	deadline = intake.get("bid_deadline")
	if not deadline or intake.get("result") or intake.get("go_no_go") == "no_go":
		return False
	try:
		return getdate(deadline) < today_d
	except (TypeError, ValueError):
		return False


def _supplier_bid_counts(company: str, lot_names: list[str]) -> dict[str, int]:
	"""Supplier bids per lot in ONE grouped pass — never one query per lot.

	Counting happens in Python on purpose: pushing the aggregate into the field
	list (`fields=["count(name) as n"]`) passes review and then fails at runtime
	on the live Frappe version. Same shape as `tender.tender_funnel`'s
	`sq_counts`.
	"""
	counts: dict[str, int] = {}
	if not lot_names or not frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		return counts
	rows = frappe.get_all(
		"Supplier Quotation",
		filters={"company": company, "custom_crm_deal": ["in", lot_names], "docstatus": ["<", 2]},
		fields=["custom_crm_deal"],
		limit_page_length=0,
	)
	for row in rows:
		deal = row["custom_crm_deal"]
		counts[deal] = counts.get(deal, 0) + 1
	return counts


def _tender_lot_cards(company: str, parent_names: list[str]) -> tuple[dict[str, dict], dict[str, list]]:
	"""Derive every parent's board lane and lot breakdown from its child lots.

	Returns ``(cards, lots_by_parent)``. Both are built from the SAME permitted
	lot rows, so a card's numbers and the drill-down the same user can open can
	never disagree — including for a user who may read only some of the lots.
	The lane comes from `_tender_master_state.derive`, never from the parent's
	hand-typed `status`: that field drifts the moment one lot moves.

	NO QUERY MAY RUN PER LOT here — the board asks for a page of parents at
	once. So: one `get_list` for the lots, one grouped pass for the supplier-bid
	counts, and the intake JSON read as a COLUMN instead of via
	`tender._read_intake` (which is a `get_value` per deal). When a column is
	missing the derivation degrades toward Preparation instead of inventing
	progress, exactly like `_funnel.classify` does with unknown facts.
	"""
	cards = {name: _empty_card() for name in parent_names}
	lots_by_parent: dict[str, list] = {name: [] for name in parent_names}
	if not parent_names:
		return cards, lots_by_parent

	has_intake = frappe.db.has_column("CRM Deal", "custom_tender_intake")
	has_pricing = frappe.db.has_column("CRM Deal", "custom_bid_pricing")
	fields = [*_LOT_LIST_FIELDS, "custom_parent_tender"]
	if has_intake:
		fields.append("custom_tender_intake")
	if has_pricing:
		fields.append("custom_bid_pricing")
	rows = frappe.get_list(
		"CRM Deal",
		filters={"company": company, "custom_parent_tender": ["in", parent_names]},
		fields=fields,
		order_by="modified desc",
		limit_page_length=0,
	)
	# `get_list` (not `get_all`) already applied this user's role AND user
	# permissions in the query above, and CRM Deal registers neither a
	# `has_permission` hook nor a `permission_query_conditions` entry in hooks.py
	# — so re-checking each row would only repeat that verdict, and passing a
	# docNAME to `frappe.has_permission` makes it load the whole document
	# (permissions.py resolves the string via `get_lazy_doc`). That is one doc
	# load per lot: a 50-parent page with 8 lots each = 400 loads, exactly the
	# per-lot cost this function's contract forbids.
	sq_counts = _supplier_bid_counts(company, [row["name"] for row in rows])
	today_d = getdate(today())

	lot_stages: dict[str, list[str]] = {name: [] for name in parent_names}
	for row in rows:
		parent = row["custom_parent_tender"]
		card = cards.get(parent)
		if card is None:
			continue
		intake = _parse_intake(row.get("custom_tender_intake")) if has_intake else {}
		sq_count = sq_counts.get(row["name"], 0)
		stage = _funnel.classify(
			{
				"go_no_go": intake.get("go_no_go"),
				"result": intake.get("result"),
				"submitted": _has_submission_evidence(intake),
				"has_pricing": bool(has_pricing and row.get("custom_bid_pricing")),
				"sq_count": sq_count,
			}
		)
		lot_stages[parent].append(stage)
		lots_by_parent[parent].append({field: row.get(field) for field in _LOT_LIST_FIELDS})
		card["lot_count"] += 1
		if stage == "won":
			card["won_lot_count"] += 1
		elif stage == "lost":
			card["lost_lot_count"] += 1
		else:
			card["open_lot_count"] += 1
		if stage == "submitted":
			card["submitted_lot_count"] += 1
		card["lot_estimated_total"] += flt(row.get("custom_estimated_value"))
		if stage in _POLICY_GAP_STAGES and sq_count < _MIN_SUPPLIER_BIDS:
			card["policy_gap_count"] += 1
		if _bid_at_risk(intake, today_d):
			card["risk_count"] += 1
		deadline = intake.get("bid_deadline")
		if deadline and stage not in ("won", "lost"):
			current = card["earliest_deadline"]
			if not current or str(deadline) < str(current):
				card["earliest_deadline"] = str(deadline)

	for parent, card in cards.items():
		card["stage"] = _tender_master_state.derive(lot_stages[parent])
	return cards, lots_by_parent


def _list_filters(company, status=None, stage=None, risk=None, deal=None, from_date=None, to_date=None):
	filters = [["company", "=", company]]
	deal_doc = None
	if deal:
		deal_doc = frappe.get_doc("CRM Deal", deal)
		if not frappe.has_permission("CRM Deal", "read", doc=deal_doc) or deal_doc.company != company:
			frappe.throw(_("Not permitted."), frappe.PermissionError)
	parent_names = _qualifying_parent_names(company, status, stage, risk, from_date, to_date, deal)
	if parent_names is not None:
		filters.append(["name", "in", sorted(parent_names) or ["__no_permitted_tender_master__"]])
	if deal_doc:
		filters.append(["name", "=", deal_doc.custom_parent_tender])
	return filters


def _qualifying_parent_names(company, status=None, stage=None, risk=None, from_date=None, to_date=None, deal=None):
	if not any((stage in {"identified", "submitted"}, str(status).casefold() == "won", risk == "risk")):
		return None
	start, end = _dashboard_period(from_date, to_date)
	rows = frappe.get_list(
		"CRM Deal",
		filters={"company": company, "custom_parent_tender": ["is", "set"]},
		fields=["name", "custom_parent_tender", "creation"],
		limit_page_length=0,
	)
	parents = set()
	for row in rows:
		if deal and row.name != deal:
			continue
		if not frappe.has_permission("CRM Deal", "read", doc=row.name):
			continue
		intake = _read_intake(row.name)
		events = _tender_event_dates(intake, row.creation)
		matches = (
			(stage == "identified" and _in_dashboard_period(events["identified"], start, end))
			or (
				stage == "submitted"
				and _has_submission_evidence(intake)
				and _in_dashboard_period(events["submitted"], start, end)
			)
			or (
				str(status).casefold() == "won"
				and _has_submission_evidence(intake)
				and _in_dashboard_period(events["won"], start, end)
			)
			or (risk == "risk" and _deal_deadlines(row.name, company, intake)["risk"] == "risk")
		)
		if matches:
			parents.add(row.custom_parent_tender)
	return parents


def require_selected_company(company: str | None) -> str:
	"""Require an explicit, permitted company instead of inferring a default."""
	selected_company = _require_company(company)
	if any(role in frappe.get_roles(frappe.session.user) for role in _ADMIN_ROLES):
		return selected_company
	allowed_companies = _user_allowed_companies(frappe.session.user)
	if allowed_companies and selected_company not in allowed_companies:
		frappe.throw(_("Not permitted for company {0}").format(selected_company), frappe.PermissionError)
	return selected_company


def _assert_company_scope(company: str | None) -> str:
	"""Canonical company-scope wrapper for public Tender Master endpoints."""
	return require_selected_company(company)


def _master_scope(name: str, company: str | None, ptype: str = "read"):
	selected_company = require_selected_company(company)
	master = frappe.get_doc("Tender Master", name)
	if master.company != selected_company:
		frappe.throw(_("Tender does not belong to the selected company."), frappe.PermissionError)
	if not frappe.has_permission("Tender Master", ptype=ptype, doc=master):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return master, selected_company


def _list_options(start: int, limit: int) -> tuple[int, int]:
	return max(int(start or 0), 0), min(max(int(limit or 50), 1), 500)


@frappe.whitelist()
def list_tender_masters(
	company=None,
	status=None,
	stage=None,
	risk=None,
	deal=None,
	from_date=None,
	to_date=None,
	search=None,
	start=0,
	limit=50,
):
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	if not frappe.has_permission("Tender Master", "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	filters = _list_filters(selected_company, status, stage, risk, deal, from_date, to_date)
	page_start, page_limit = _list_options(start, limit)
	kwargs = {
		"filters": filters,
		"fields": [*list(_TENDER_FIELDS), "name", "modified"],
		"order_by": "modified desc",
		"start": page_start,
		"limit_page_length": page_limit,
	}
	if search:
		kwargs["or_filters"] = [
			[field, "like", f"%{search}%"] for field in ("title", "tender_number", "buyer_name")
		]
	records = frappe.get_list("Tender Master", **kwargs)
	count_kwargs = {"filters": filters, "fields": ["count(name) as total"], "limit_page_length": 1}
	if search:
		count_kwargs["or_filters"] = kwargs["or_filters"]
	count_rows = frappe.get_list("Tender Master", **count_kwargs)
	total = int((count_rows[0].get("total") if count_rows else 0) or 0)
	# One derivation pass for the whole page — the board's lane is a projection
	# of the child lots, so it is computed here, not read from `status`.
	cards, _lots_by_parent = _tender_lot_cards(selected_company, [row["name"] for row in records])
	records = [{**row, **cards[row["name"]]} for row in records]
	return {"records": records, "total": total}


@frappe.whitelist()
def get_tender_master(name, company=None):
	_require_tender(company)
	_assert_company_scope(company)
	master, selected_company = _master_scope(name, company)
	# Same helper the board uses, so the detail view can never show a different
	# lane (or different counts) than the card the user clicked.
	cards, lots_by_parent = _tender_lot_cards(selected_company, [name])
	card = cards[name]
	permitted_lots = lots_by_parent[name]
	tender = master.as_dict()
	tender.update(card)
	summary = {
		"lot_count": card["lot_count"],
		"open_lot_count": card["open_lot_count"],
		"estimated_total": card["lot_estimated_total"],
		"currency": master.currency,
	}
	return {"tender": tender, "lots": permitted_lots, "summary": summary}


@frappe.whitelist()
def save_tender_master(data, company=None):
	_require_tender(company)
	selected_company = _assert_company_scope(company)
	payload = frappe.parse_json(data)
	name = payload.get("name")
	if name:
		doc, _ = _master_scope(name, selected_company, "write")
	else:
		if not frappe.has_permission("Tender Master", "create"):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		doc = frappe.new_doc("Tender Master")
	updates = {field: payload[field] for field in _TENDER_FIELDS if field in payload and field != "company"}
	doc.update(updates)
	doc.company = selected_company
	if name:
		doc.save()
	else:
		doc.insert()
	return doc.as_dict()


def validate_deal_parent_tender(doc, method=None):
	"""Keep CRM Deal lots and their Tender Master in the same company."""
	if not doc.custom_parent_tender:
		return
	master = frappe.get_doc("Tender Master", doc.custom_parent_tender)
	if master.company != doc.company:
		frappe.throw(_("Parent Tender must belong to the same company as the CRM Deal."), ValueError)

