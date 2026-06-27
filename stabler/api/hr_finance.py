"""Per-employee financial summary for the People master-detail view.

One call gathers everything the Employees detail pane shows for a worker:
their advance balance + movements, their salary-payable balance + payments,
the net salaries already emitted to ERPNext, and recent payroll periods.
All money lives on the GL (party = Employee), so we read it straight from
GL Entry — the same source the advance and salary-payment modules use.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from stabler.api._common import _require_company

_PAY_ROLES = {"HR Manager", "Payroll Manager", "Accounts Manager", "System Manager", "Stabler Admin"}
_NET_COMPONENT = "Stabler Net Pay"
_SUMMARY = "Stabler Payroll Attendance Summary"


def _require_pay_role() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	if not (set(frappe.get_roles()) & _PAY_ROLES):
		frappe.throw(_("You need a payroll/HR role to view employee finances."), frappe.PermissionError)


def _party_movements(company: str, account: str, employee: str, limit: int = 50) -> list[dict]:
	rows = frappe.db.sql(
		"""
		SELECT posting_date, voucher_type, voucher_no, debit, credit, remarks
		FROM `tabGL Entry`
		WHERE company = %(c)s AND account = %(a)s
		  AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0
		ORDER BY posting_date DESC, creation DESC
		LIMIT %(lim)s
		""",
		{"c": company, "a": account, "e": employee, "lim": int(limit)},
		as_dict=True,
	)
	for m in rows:
		m["posting_date"] = str(m["posting_date"]) if m.get("posting_date") else None
		m["debit"] = flt(m["debit"])
		m["credit"] = flt(m["credit"])
	return rows


@frappe.whitelist()
def employee_financials(company: str, employee: str) -> dict:
	"""Balances + salaries + advances + salary payments for one employee."""
	_require_pay_role()
	_require_company(company)
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Unknown employee: {0}").format(employee))

	emp = frappe.db.get_value(
		"Employee",
		employee,
		["employee_name", "department", "designation", "status", "image",
		 "cell_number", "date_of_joining", "custom_base_salary"],
		as_dict=True,
	) or {}
	base_ccy = frappe.get_cached_value("Company", company, "default_currency") or ""

	# ── Advances (Employee Advances account) ──────────────────────────────────
	advance = {"account": None, "outstanding": 0.0, "movements": []}
	try:
		from stabler.api.employee_advance import _advance_account, _balances

		acc = _advance_account(company)
		advance = {
			"account": acc,
			"outstanding": flt(_balances(company, acc).get(employee, 0.0)),
			"movements": _party_movements(company, acc, employee),
		}
	except Exception:
		pass

	# ── Salary payable (accrued but unpaid) ───────────────────────────────────
	payable = {"account": None, "outstanding": 0.0, "movements": []}
	try:
		from stabler.api.salary_payment import _payable_balances, _salary_payable_account

		acc = _salary_payable_account(company)
		payable = {
			"account": acc,
			"outstanding": flt(_payable_balances(company, acc).get(employee, 0.0)),
			"movements": _party_movements(company, acc, employee),
		}
	except Exception:
		pass

	# ── Net salaries already emitted to ERPNext ───────────────────────────────
	salaries = frappe.get_all(
		"Additional Salary",
		filters={"employee": employee, "salary_component": _NET_COMPONENT, "docstatus": ["<", 2]},
		fields=["name", "payroll_date", "amount", "type", "docstatus"],
		order_by="payroll_date desc",
		limit_page_length=24,
	)
	for s in salaries:
		s["payroll_date"] = str(s.get("payroll_date") or "")
		s["amount"] = flt(s.get("amount"))

	# ── Recent payroll periods ────────────────────────────────────────────────
	periods = frappe.get_all(
		_SUMMARY,
		filters={"company": company, "employee": employee},
		fields=["name", "payroll_period", "status"],
		order_by="payroll_period desc",
		limit_page_length=12,
	)

	return {
		"employee": employee,
		"profile": emp,
		"base_currency": base_ccy,
		"advance": advance,
		"payable": payable,
		"salaries": salaries,
		"periods": periods,
	}
