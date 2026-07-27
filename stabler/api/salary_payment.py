"""Salary accrual + multi-employee payout — pure-JE, accrual model.

Flow (matches "we accrue, then pay to clear Accounts Payable"):

  1. Accrue a locked period:  Dr Salary Expense (total)
                              Cr Salary Payable  (per employee, party=Employee)
     → each employee now carries an outstanding payable balance.

  2. Pay employees:           Dr Salary Payable  (per employee, party=Employee)
                              Cr Bank/Cash       (one total line)
     → clears the payable. One Journal Entry covers many employees at once.

Balances are read straight from the GL (party=Employee on the payable account),
exactly like the employee-advance module — no extra ledger doctype.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from stabler.api._common import _require_company
from stabler.api._money import money_epsilon
from stabler.api.approvals import _assert_company_scope
from stabler.api.money import create_journal_entry, list_cash_bank_accounts, submit_journal_entry

_SUMMARY = "Stabler Payroll Attendance Summary"
_PAY_ROLES = {"HR Manager", "Payroll Manager", "Accounts Manager", "System Manager", "Stabler Admin"}
_ACCRUAL_MARKER = "stabler-salary-accrual"
_PAYOUT_MARKER = "stabler-salary-payout"


def _require_pay_role() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	if not (set(frappe.get_roles()) & _PAY_ROLES):
		frappe.throw(_("You need a payroll/HR role to run salary payments."), frappe.PermissionError)


# ── Account resolution ───────────────────────────────────────────────────────
def _leaf_account(company: str, where: str, params: dict) -> str | None:
	row = frappe.db.sql(
		f"SELECT name FROM `tabAccount` WHERE company = %(c)s AND is_group = 0 AND ({where}) "
		f"ORDER BY name ASC LIMIT 1",
		{"c": company, **params},
	)
	return row[0][0] if row else None


def _salary_payable_account(company: str, override: str = "") -> str:
	if override:
		return override
	acc = _leaf_account(
		company,
		"account_type = 'Payable' AND (name LIKE %(p1)s OR name LIKE %(p2)s OR name LIKE %(p3)s)",
		{"p1": "%Salary Payable%", "p2": "%Wages Payable%", "p3": "%Maosh%"},
	) or _leaf_account(company, "account_type = 'Payable'", {})
	if not acc:
		frappe.throw(
			_(
				"No Salary Payable account found for {0}. Create a Payable account "
				"(e.g. 'Salary Payable') or pass one explicitly."
			).format(company)
		)
	return acc


def _salary_expense_account(company: str, override: str = "") -> str:
	if override:
		return override
	acc = _leaf_account(
		company,
		"root_type = 'Expense' AND (name LIKE %(p1)s OR name LIKE %(p2)s OR name LIKE %(p3)s)",
		{"p1": "%Salar%", "p2": "%Wages%", "p3": "%Maosh%"},
	)
	if not acc:
		frappe.throw(
			_(
				"No Salary Expense account found for {0}. Create an Expense account "
				"(e.g. 'Salaries') or pass one explicitly."
			).format(company)
		)
	return acc


def _payable_balances(company: str, account: str) -> dict:
	"""employee -> outstanding payable (credit - debit) on the payable account."""
	rows = frappe.db.sql(
		"""
		SELECT party AS employee, SUM(credit) - SUM(debit) AS balance
		FROM `tabGL Entry`
		WHERE company = %(company)s AND account = %(account)s
		  AND party_type = 'Employee' AND ifnull(is_cancelled, 0) = 0
		GROUP BY party
		""",
		{"company": company, "account": account},
		as_dict=True,
	)
	return {r["employee"]: flt(r["balance"]) for r in rows}


# ── Period nets (engine) ─────────────────────────────────────────────────────
def _locked_nets(company: str, payroll_period: str) -> list[dict]:
	from stabler.api.hr_pay import preview_payroll_pay

	names = frappe.get_all(
		_SUMMARY,
		filters={"company": company, "payroll_period": payroll_period, "status": "Locked"},
		fields=["name", "employee", "employee_name"],
		limit_page_length=0,
	)
	out = []
	for s in names:
		net = flt(preview_payroll_pay(s["name"]).get("net"))
		if net:
			out.append({"employee": s["employee"], "employee_name": s["employee_name"], "net": net})
	return out


# ── Accrual ──────────────────────────────────────────────────────────────────
@frappe.whitelist()
def accrue_payroll_period(
	company: str,
	payroll_period: str,
	expense_account: str = "",
	payable_account: str = "",
	posting_date: str = "",
) -> dict:
	"""Book the locked period's nets as a payable (Dr expense / Cr payable per employee).

	Idempotent: if a submitted accrual JE already exists for this period, returns it.
	"""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg

	remark = f"{_ACCRUAL_MARKER}:{payroll_period}"
	existing = frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": remark, "docstatus": ["<", 2]},
		pluck="name",
		limit=1,
	)
	if existing:
		return {"journal_entry": existing[0], "created": False, "reason": "exists"}

	nets = _locked_nets(company, payroll_period)
	if not nets:
		return {"journal_entry": None, "created": False, "reason": "no_locked_nets"}

	payable = _salary_payable_account(company, payable_account)
	expense = _salary_expense_account(company, expense_account)
	total = round(sum(n["net"] for n in nets))

	rows = [{"account": expense, "debit": total, "credit": 0}]
	for n in nets:
		rows.append(
			{
				"account": payable,
				"party_type": "Employee",
				"party": n["employee"],
				"debit": 0,
				"credit": round(n["net"]),
			}
		)
	je = create_journal_entry(
		company=company,
		posting_date=posting_date or today(),
		accounts=rows,
		user_remark=remark,
	)
	submit_journal_entry(je["name"])
	return {"journal_entry": je["name"], "created": True, "employees": len(nets), "total": total}


@frappe.whitelist()
def accrue_employee_salary(
	company: str,
	employee: str,
	month: str,
	amount: float | str,
	expense_account: str = "",
	payable_account: str = "",
	posting_date: str = "",
) -> dict:
	"""Accrue ONE employee's salary for a month (erpnext-ui style per-employee assign).

	Books Dr Salary Expense / Cr Salary Payable[Employee] as a DRAFT Journal Entry,
	so it surfaces in the employee ledger for review before submission. Idempotent
	per (employee, month): refuses if a non-cancelled accrual for that pair exists.
	`month` is YYYY-MM.
	"""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not employee:
		frappe.throw(_("Employee is required."))
	amt = round(flt(amount))
	if amt <= 0:
		frappe.throw(_("Amount must be greater than zero."))

	remark = f"{_ACCRUAL_MARKER}-emp:{employee}:{month}"
	existing = frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": remark, "docstatus": ["<", 2]},
		pluck="name",
		limit=1,
	)
	if existing:
		return {"journal_entry": existing[0], "created": False, "reason": "exists"}

	payable = _salary_payable_account(company, payable_account)
	expense = _salary_expense_account(company, expense_account)
	rows = [
		{"account": expense, "debit": amt, "credit": 0},
		{"account": payable, "party_type": "Employee", "party": employee, "debit": 0, "credit": amt},
	]
	je = create_journal_entry(
		company=company,
		posting_date=posting_date or today(),
		accounts=rows,
		user_remark=remark,
	)
	return {"journal_entry": je["name"], "created": True, "amount": amt}


# ── Balances + payout ────────────────────────────────────────────────────────
@frappe.whitelist()
def payable_account(company: str) -> dict:
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	acc = _salary_payable_account(company)
	return {
		"account": acc,
		"currency": frappe.db.get_value("Account", acc, "account_currency")
		or frappe.get_cached_value("Company", company, "default_currency"),
	}


@frappe.whitelist()
def salary_payable_balances(company: str, search: str = "", limit: int = 500) -> dict:
	"""Employees with an outstanding salary payable (owed but not yet paid)."""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	account = _salary_payable_account(company)
	balances = _payable_balances(company, account)
	eps = money_epsilon(frappe.get_cached_value("Company", company, "default_currency"))
	names = [e for e, b in balances.items() if b > eps]
	if not names:
		return {"account": account, "rows": [], "total_outstanding": 0.0}

	emps = frappe.get_all(
		"Employee",
		filters={"name": ["in", names]},
		fields=["name", "employee_name", "department", "designation"],
	)
	emp_map = {e["name"]: e for e in emps}
	s = (search or "").lower().strip()
	rows = []
	for name in names:
		e = emp_map.get(name, {"name": name})
		label = e.get("employee_name") or name
		if s and s not in label.lower() and s not in name.lower():
			continue
		rows.append(
			{
				"employee": name,
				"employee_name": label,
				"department": e.get("department"),
				"outstanding": balances.get(name, 0.0),
			}
		)
	rows.sort(key=lambda r: r["employee_name"].lower())
	return {
		"account": account,
		"rows": rows[: int(limit or 500)],
		"total_outstanding": round(sum(r["outstanding"] for r in rows)),
	}


@frappe.whitelist()
def pay_salaries(
	company: str, employees: str | list, paid_from: str, posting_date: str = "", payable_account: str = ""
) -> dict:
	"""Pay several employees in ONE Journal Entry (Dr payable[Employee] / Cr bank).

	`employees` is a JSON array of employee names (each paid their full outstanding
	payable) or of {employee, amount} objects to pay a partial amount.
	"""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if isinstance(employees, str):
		employees = json.loads(employees or "[]")
	if not employees:
		frappe.throw(_("Select at least one employee to pay."))
	if not paid_from:
		frappe.throw(_("Pick the bank/cash account to pay from."))

	account = _salary_payable_account(company, payable_account)
	balances = _payable_balances(company, account)

	rows = []
	total = 0.0
	paid = []
	for item in employees:
		emp = item if isinstance(item, str) else item.get("employee")
		outstanding = flt(balances.get(emp, 0.0))
		amount = (
			outstanding
			if isinstance(item, str) or item.get("amount") in (None, "")
			else flt(item.get("amount"))
		)
		amount = min(round(amount), round(outstanding))  # never overpay the payable
		if amount <= 0:
			continue
		rows.append(
			{"account": account, "party_type": "Employee", "party": emp, "debit": amount, "credit": 0}
		)
		total += amount
		paid.append({"employee": emp, "amount": amount})
	if not rows:
		frappe.throw(_("Nothing to pay — selected employees have no outstanding balance."))

	rows.append({"account": paid_from, "debit": 0, "credit": round(total)})
	je = create_journal_entry(
		company=company,
		posting_date=posting_date or today(),
		accounts=rows,
		voucher_type="Bank Entry",
		user_remark=f"{_PAYOUT_MARKER}: {len(paid)} {_('employees')}",
	)
	submit_journal_entry(je["name"])
	return {"journal_entry": je["name"], "paid": paid, "total": round(total), "count": len(paid)}


@frappe.whitelist()
def list_pay_accounts(company: str) -> list:
	"""Cash/bank accounts to pay salaries from (the Cr side)."""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	return list_cash_bank_accounts(company)
