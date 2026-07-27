"""Manage holidays and payroll periods from inside Stabler (no Desk trip).

Holiday Lists drive attendance shading and payroll working-days; Payroll Periods
bound each pay run. Both lived in ERPNext Desk — these endpoints surface lean
CRUD so HR can edit them in the SPA. All writes are role-gated and idempotent.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate

from stabler.api.approvals import _assert_company_scope

_HR_ROLES = frozenset(
	("Accounts Manager", "Payroll Manager", "HR Manager", "System Manager", "Stabler Admin")
)


def _require_hr() -> None:
	if not (set(frappe.get_roles()) & _HR_ROLES):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# ── Holiday lists ────────────────────────────────────────────────────────────
@frappe.whitelist()
def list_holiday_lists(company: str = "") -> dict:
	"""All holiday lists + which one is this company's default."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_hr()
	lists = frappe.get_all(
		"Holiday List",
		fields=["name", "holiday_list_name", "from_date", "to_date", "total_holidays"],
		order_by="from_date desc",
		limit_page_length=0,
	)
	default = frappe.get_cached_value("Company", company, "default_holiday_list") if company else None
	for r in lists:
		r["is_default"] = r["name"] == default
	return {"lists": lists, "default": default}


@frappe.whitelist()
def holiday_list_detail(name: str) -> dict:
	"""A holiday list with its holidays (sorted by date)."""
	_require_hr()
	doc = frappe.get_doc("Holiday List", name)
	holidays = sorted(
		(
			{
				"holiday_date": str(h.holiday_date),
				"description": h.description or "",
				"weekly_off": int(bool(h.weekly_off)),
			}
			for h in doc.holidays
		),
		key=lambda h: h["holiday_date"],
	)
	return {
		"name": doc.name,
		"from_date": str(doc.from_date) if doc.from_date else "",
		"to_date": str(doc.to_date) if doc.to_date else "",
		"holidays": holidays,
	}


@frappe.whitelist()
def add_holiday(holiday_list: str, holiday_date: str, description: str = "", weekly_off: int = 0) -> dict:
	"""Add one holiday (idempotent — skips if the date already exists)."""
	_require_hr()
	doc = frappe.get_doc("Holiday List", holiday_list)
	target = getdate(holiday_date)
	if any(getdate(h.holiday_date) == target for h in doc.holidays):
		return {"added": False, "reason": "exists"}
	doc.append(
		"holidays",
		{"holiday_date": holiday_date, "description": description or _("Holiday"), "weekly_off": int(weekly_off or 0)},
	)
	doc.total_holidays = len(doc.holidays)
	doc.save(ignore_permissions=False)
	return {"added": True}


@frappe.whitelist()
def remove_holiday(holiday_list: str, holiday_date: str) -> dict:
	"""Remove every holiday row on the given date."""
	_require_hr()
	doc = frappe.get_doc("Holiday List", holiday_list)
	target = getdate(holiday_date)
	keep = [h for h in doc.holidays if getdate(h.holiday_date) != target]
	removed = len(doc.holidays) - len(keep)
	if not removed:
		return {"removed": 0}
	doc.set("holidays", keep)
	doc.total_holidays = len(doc.holidays)
	doc.save(ignore_permissions=False)
	return {"removed": removed}


@frappe.whitelist()
def set_company_holiday_list(company: str, holiday_list: str) -> dict:
	"""Point a company at a default holiday list."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_hr()
	if not frappe.db.exists("Holiday List", holiday_list):
		frappe.throw(_("Holiday list {0} not found.").format(holiday_list))
	frappe.db.set_value("Company", company, "default_holiday_list", holiday_list)
	return {"company": company, "default_holiday_list": holiday_list}


# ── Payroll periods ──────────────────────────────────────────────────────────
@frappe.whitelist()
def list_payroll_periods(company: str = "") -> dict:
	"""Payroll periods for a company (or all)."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_hr()
	if not frappe.db.exists("DocType", "Payroll Period"):
		return {"periods": [], "supported": False}
	filters = {"company": company} if company else {}
	periods = frappe.get_all(
		"Payroll Period",
		filters=filters,
		fields=["name", "company", "start_date", "end_date"],
		order_by="start_date desc",
		limit_page_length=0,
	)
	return {"periods": periods, "supported": True}


@frappe.whitelist()
def upsert_payroll_period(company: str, start_date: str, end_date: str, name: str = "") -> dict:
	"""Create or update a payroll period (start must precede end)."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_hr()
	if getdate(end_date) < getdate(start_date):
		frappe.throw(_("End date cannot be before start date."))
	if name and frappe.db.exists("Payroll Period", name):
		doc = frappe.get_doc("Payroll Period", name)
		if doc.company != company:
			frappe.throw(_("Period belongs to another company."))
		doc.start_date = start_date
		doc.end_date = end_date
		doc.save(ignore_permissions=False)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Payroll Period",
				"company": company,
				"start_date": start_date,
				"end_date": end_date,
			}
		).insert(ignore_permissions=False)
	return {"name": doc.name}
