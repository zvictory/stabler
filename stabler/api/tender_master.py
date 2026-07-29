"""Company-safe Tender Master APIs and CRM Deal lot validation."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from stabler.api._common import _require_company
from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies
from stabler.api.tender import (
	_dashboard_period,
	_deal_deadlines,
	_has_submission_evidence,
	_in_dashboard_period,
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


def _list_filters(company, status=None, stage=None, risk=None, deal=None, from_date=None, to_date=None):
	filters = [["company", "=", company]]
	parent_names = _qualifying_parent_names(company, status, stage, risk, from_date, to_date)
	if parent_names is not None:
		filters.append(["name", "in", sorted(parent_names) or ["__no_permitted_tender_master__"]])
	if deal:
		deal_doc = frappe.get_doc("CRM Deal", deal)
		if not frappe.has_permission("CRM Deal", "read", doc=deal_doc):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		if deal_doc.company != company:
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		filters.append(["name", "=", deal_doc.custom_parent_tender])
	return filters


def _qualifying_parent_names(company, status=None, stage=None, risk=None, from_date=None, to_date=None):
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
	return {"records": records, "total": total}


@frappe.whitelist()
def get_tender_master(name, company=None):
	_require_tender(company)
	_assert_company_scope(company)
	master, selected_company = _master_scope(name, company)
	lots = frappe.get_list(
		"CRM Deal",
		filters={"company": selected_company, "custom_parent_tender": name},
		fields=["name", "status", "custom_estimated_value", "currency", "modified"],
		order_by="modified desc",
		limit_page_length=0,
	)
	permitted_lots = [lot for lot in lots if frappe.has_permission("CRM Deal", "read", lot["name"])]
	summary = {
		"lot_count": len(permitted_lots),
		"open_lot_count": sum(
			1 for lot in permitted_lots if lot["status"] not in {"Won", "Lost", "Cancelled"}
		),
		"estimated_total": sum(flt(lot.get("custom_estimated_value")) for lot in permitted_lots),
		"currency": master.currency,
	}
	return {"tender": master.as_dict(), "lots": permitted_lots, "summary": summary}


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
