"""HR Overview — one aggregate call that powers the HR landing cockpit.

Returns an action-first payload: the work queue that needs the manager today,
today's attendance pulse with a 7-day trend, this month's payroll readiness,
outstanding advances (salary-sensitive → role-gated), and a workforce snapshot.

Composes existing read endpoints + a few cheap COUNT/GROUP BY queries so the
landing page is a single fast request. Company-scoped; money figures are hidden
for users without a payroll-visible role.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, add_days, get_first_day, today

from stabler.api._common import _require_company
from stabler.api.hr import _user_can_see_salary
from stabler.api.hr_payroll import attendance_dashboard, period_readiness


def _current_period() -> str:
	d = getdate(today())
	return f"{d.year:04d}-{d.month:02d}"


def _present_pct(dash: dict, headcount: int) -> float:
	if not headcount:
		return 0.0
	return round(100.0 * flt(dash.get("present") or 0) / headcount, 0)


def _workforce(company: str) -> dict:
	headcount = frappe.db.count("Employee", {"company": company, "status": "Active"})
	by_dept = frappe.db.sql(
		"""
		SELECT COALESCE(NULLIF(department, ''), 'Unassigned') AS dept, COUNT(*) AS n
		FROM `tabEmployee`
		WHERE company = %(c)s AND status = 'Active'
		GROUP BY dept ORDER BY n DESC LIMIT 6
		""",
		{"c": company},
		as_dict=True,
	)
	month_start = get_first_day(today())
	joiners = frappe.db.count(
		"Employee", {"company": company, "status": "Active", "date_of_joining": [">=", month_start]}
	)
	return {"headcount": headcount, "by_dept": by_dept, "joiners_this_month": joiners}


def _data_gaps(company: str) -> dict:
	"""Cheap counts of records that block payroll or look unfinished."""
	base_zero = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabEmployee`
		WHERE company = %(c)s AND status = 'Active'
		  AND (custom_base_salary IS NULL OR custom_base_salary = 0)
		""",
		{"c": company},
	)[0][0]
	profile_gaps = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabEmployee`
		WHERE company = %(c)s AND status = 'Active'
		  AND (department IS NULL OR department = '' OR department LIKE 'Unassigned%%'
		       OR designation IS NULL OR designation = '' OR designation = '—')
		""",
		{"c": company},
	)[0][0]
	return {"base_salary_zero": int(base_zero), "profile_gaps": int(profile_gaps)}


def _advances(company: str, can_see_money: bool) -> dict:
	if not can_see_money:
		return {"visible": False}
	try:
		from stabler.api.employee_advance import _advance_account, _balances

		balances = _balances(company, _advance_account(company))
	except Exception:
		return {"visible": True, "configured": False, "total": 0.0, "count": 0, "top": []}
	owing = {e: b for e, b in balances.items() if flt(b) > 0.005}
	top_names = sorted(owing, key=lambda e: owing[e], reverse=True)[:3]
	name_map = {
		r["name"]: r.get("employee_name") or r["name"]
		for r in frappe.get_all("Employee", filters={"name": ["in", top_names or [""]]}, fields=["name", "employee_name"])
	}
	return {
		"visible": True,
		"configured": True,
		"total": round(sum(owing.values()), 2),
		"count": len(owing),
		"top": [{"employee_name": name_map.get(e, e), "amount": round(flt(owing[e]), 2)} for e in top_names],
	}


@frappe.whitelist()
def hr_overview(company: str) -> dict:
	"""Single payload for the HR landing cockpit."""
	_require_company(company)
	can_money = _user_can_see_salary()
	period = _current_period()

	dash_today = attendance_dashboard(company) or {}
	wf = _workforce(company)
	headcount = wf["headcount"]

	# 7-day attendance trend (present % today vs a week ago).
	try:
		dash_prev = attendance_dashboard(company, date=str(add_days(today(), -7))) or {}
	except Exception:
		dash_prev = {}
	pct_today = _present_pct(dash_today, headcount)
	pct_prev = _present_pct(dash_prev, headcount)

	gaps = _data_gaps(company)

	try:
		readiness = period_readiness(company, period) or {}
	except Exception:
		readiness = {}

	return {
		"company": company,
		"period": period,
		"can_see_money": can_money,
		"attendance": {
			"present": int(dash_today.get("present") or 0),
			"absent": int(dash_today.get("absent") or 0),
			"late": int(dash_today.get("late") or 0),
			"on_leave": int(dash_today.get("on_leave") or 0),
			"total_marked": int(dash_today.get("total_marked") or 0),
			"present_pct": pct_today,
			"present_pct_delta": round(pct_today - pct_prev, 0),
		},
		"queue": {
			"open_exceptions": int(dash_today.get("open_exceptions") or 0),
			"pending_corrections": int(dash_today.get("pending_corrections") or 0),
			"payroll_impacting_pending": int(dash_today.get("payroll_impacting_pending") or 0),
			"base_salary_zero": gaps["base_salary_zero"],
			"profile_gaps": gaps["profile_gaps"],
		},
		"payroll": {
			"period": period,
			"can_lock": bool(readiness.get("can_lock")),
			"already_locked": bool((readiness.get("ctx") or {}).get("already_locked")),
			"summary_count": int(readiness.get("summary_count") or 0),
			"headcount": headcount,
			"blockers": readiness.get("blockers") or [],
		},
		"advances": _advances(company, can_money),
		"workforce": wf,
	}


@frappe.whitelist()
def data_health(company: str) -> dict:
	"""The employees behind each Overview data-gap tile, so they can be fixed.

	Each list item carries enough to act: employee id + name + department +
	what's missing, with a link target of the employee profile. The base-salary
	list is salary-sensitive → only returned to payroll-visible roles.
	"""
	_require_company(company)
	can_money = _user_can_see_salary()

	rows = frappe.get_all(
		"Employee",
		filters={"company": company, "status": "Active"},
		fields=[
			"name", "employee_name", "department", "designation",
			"custom_base_salary", "custom_work_mode", "custom_region", "date_of_joining",
		],
		order_by="employee_name asc",
		limit=0,
	)

	base_zero, profile_gaps, comp_gaps = [], [], []
	for e in rows:
		dept_missing = not e.get("department") or str(e.get("department") or "").startswith("Unassigned")
		desg_missing = not e.get("designation") or e.get("designation") == "—"
		if dept_missing or desg_missing:
			miss = []
			if dept_missing:
				miss.append("department")
			if desg_missing:
				miss.append("designation")
			profile_gaps.append({"employee": e["name"], "employee_name": e.get("employee_name") or e["name"], "department": e.get("department"), "missing": miss})
		if can_money and not flt(e.get("custom_base_salary")):
			base_zero.append({"employee": e["name"], "employee_name": e.get("employee_name") or e["name"], "department": e.get("department")})
		if not e.get("custom_work_mode") or not e.get("custom_region"):
			comp_gaps.append({"employee": e["name"], "employee_name": e.get("employee_name") or e["name"], "department": e.get("department")})

	return {
		"company": company,
		"can_see_money": can_money,
		"base_salary_zero": base_zero,
		"profile_gaps": profile_gaps,
		"comp_config_gaps": comp_gaps,
	}
