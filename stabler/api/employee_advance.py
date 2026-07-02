"""Employee salary advances — pay workers in advance and track their real
outstanding balance straight from the general ledger.

Model (per the product decision):
  * Balance source  = a dedicated "Employee Advances" receivable account with the
    employee as the GL party. Outstanding = SUM(debit) - SUM(credit) on that
    account for the employee. Paying an advance debits it; payroll recovery
    credits it, so the figure always reconciles to the books.
  * Payment         = a Payment Entry (type "Pay", party_type "Employee") from a
    cash/bank account into the advance account — reuses money.create_payment_entry.
  * Recovery        = a manual per-period deduction entered in the Computed Pay
    screen (see hr_pay), which feeds the payroll engine's `advance` line.

Salary-sensitive → gated to payroll/HR roles, company-scoped.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from stabler.api._common import _require_company
from stabler.api.approvals import _assert_company_scope
from stabler.api.money import create_payment_entry, list_cash_bank_accounts

_PAY_ROLES = {"HR Manager", "Payroll Manager", "Accounts Manager", "System Manager", "Stabler Admin"}


def _require_pay_role() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required."), frappe.PermissionError)
	if not (set(frappe.get_roles()) & _PAY_ROLES):
		frappe.throw(_("You need a payroll/HR role to manage employee advances."), frappe.PermissionError)


def _advance_account(company: str) -> str:
	"""Resolve the company's Employee Advances account.

	Prefers Company.default_employee_advance_account; otherwise falls back to a
	non-group account whose name/type looks like an employee-advance account.
	Throws a clear, actionable error when none is configured.
	"""
	acc = frappe.db.get_value("Company", company, "default_employee_advance_account")
	if acc:
		return acc
	# Fallback: a leaf account whose name looks like an employee-advance receivable.
	row = frappe.db.sql(
		"""
		SELECT name FROM `tabAccount`
		WHERE company = %(c)s AND is_group = 0
		  AND (name LIKE %(p1)s OR name LIKE %(p2)s)
		ORDER BY (account_type = 'Receivable') DESC, name ASC
		LIMIT 1
		""",
		{"c": company, "p1": "%Employee Advance%", "p2": "%Advances Paid%"},
	)
	if row:
		return row[0][0]
	frappe.throw(
		_(
			"No Employee Advances account is configured for {0}. Set the company's "
			"default Employee Advance account (or create an account named "
			"'Employee Advances')."
		).format(company)
	)


def _employee_advance_account(company: str, employee: str) -> str:
	"""Çalışanın avanslarının aktığı hesap, kendi para biriminde.

	Müşteri/tedarikçi akışını (money.party_payment_defaults) yansıtır:
	get_party_account, çalışanın mevcut defter girişlerinin para birimine uyan
	hesabı çözer (UZS çalışan için UZS), böylece Payment Entry party-GLE para
	birimi doğrulamasını geçer. Henüz GL geçmişi olmayan yeni çalışanda şirket
	avans hesabına düşer.
	"""
	from erpnext.accounts.party import get_party_account

	return get_party_account("Employee", party=employee, company=company) or _advance_account(company)


@frappe.whitelist()
def advance_account(company: str) -> dict:
	"""The resolved advance account + its currency (for the UI)."""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	acc = _advance_account(company)
	return {
		"account": acc,
		"currency": frappe.db.get_value("Account", acc, "account_currency")
		or frappe.get_cached_value("Company", company, "default_currency"),
	}


def _balances(company: str, account: str) -> dict:
	"""Map of employee -> outstanding advance in the account's OWN currency.

	Sums the account-currency GL columns (not base) so the balance reads in the
	account's original currency — e.g. UZS for an Employee Advances - UZS account
	even when the company base currency is USD.
	"""
	rows = frappe.db.sql(
		"""
		SELECT party AS employee,
		       SUM(debit_in_account_currency) - SUM(credit_in_account_currency) AS balance
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND account = %(account)s
		  AND party_type = 'Employee'
		  AND ifnull(is_cancelled, 0) = 0
		GROUP BY party
		""",
		{"company": company, "account": account},
		as_dict=True,
	)
	return {r["employee"]: flt(r["balance"]) for r in rows}


@frappe.whitelist()
def employee_advance_balances(
	company: str, search: str = "", only_outstanding: int = 1, limit: int = 200
) -> dict:
	"""Employees with their outstanding advance balance (human-readable names).

	only_outstanding=1 returns only employees who currently owe an advance.
	"""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	account = _advance_account(company)
	balances = _balances(company, account)

	out: list[dict] = []
	if int(only_outstanding or 0):
		names = [e for e, b in balances.items() if abs(b) > 0.005]
		if not names:
			return {"account": account, "rows": [], "total_outstanding": 0.0}
		emps = frappe.get_all(
			"Employee",
			filters={"name": ["in", names]},
			fields=["name", "employee_name", "department", "designation"],
		)
		emp_map = {e["name"]: e for e in emps}
		s = (search or "").lower().strip()
		for name in names:
			e = emp_map.get(name, {"name": name})
			label = e.get("employee_name") or name
			if s and s not in label.lower() and s not in name.lower():
				continue
			out.append(
				{
					"employee": name,
					"employee_name": label,
					"department": e.get("department"),
					"designation": e.get("designation"),
					"outstanding": balances.get(name, 0.0),
				}
			)
	else:
		emps = frappe.get_all(
			"Employee",
			filters={"company": company, "status": "Active"},
			or_filters=(
				[
					["employee_name", "like", f"%{search}%"],
					["name", "like", f"%{search}%"],
				]
				if search
				else None
			),
			fields=["name", "employee_name", "department", "designation"],
			limit=int(limit),
			order_by="employee_name asc",
		)
		for e in emps:
			out.append(
				{
					"employee": e["name"],
					"employee_name": e.get("employee_name") or e["name"],
					"department": e.get("department"),
					"designation": e.get("designation"),
					"outstanding": balances.get(e["name"], 0.0),
				}
			)

	out.sort(key=lambda r: flt(r["outstanding"]), reverse=True)
	out = out[: int(limit)]
	return {
		"account": account,
		"rows": out,
		"total_outstanding": round(sum(flt(r["outstanding"]) for r in out), 2),
	}


@frappe.whitelist()
def employee_advance_detail(company: str, employee: str) -> dict:
	"""One employee's advance balance + recent GL movements (newest first)."""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Unknown employee: {0}").format(employee))
	account = _advance_account(company)
	movements = frappe.db.sql(
		"""
		SELECT posting_date, voucher_type, voucher_no, debit, credit, remarks
		FROM `tabGL Entry`
		WHERE company = %(company)s AND account = %(account)s
		  AND party_type = 'Employee' AND party = %(employee)s
		  AND ifnull(is_cancelled, 0) = 0
		ORDER BY posting_date DESC, creation DESC
		LIMIT 100
		""",
		{"company": company, "account": account, "employee": employee},
		as_dict=True,
	)
	for m in movements:
		m["posting_date"] = str(m["posting_date"]) if m.get("posting_date") else None
	balances = _balances(company, account)
	return {
		"employee": employee,
		"employee_name": frappe.db.get_value("Employee", employee, "employee_name") or employee,
		"account": account,
		"outstanding": balances.get(employee, 0.0),
		"movements": movements,
	}


@frappe.whitelist()
def list_pay_accounts(company: str) -> list:
	"""Cash/bank accounts to pay an advance from (paid_from picker)."""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	return list_cash_bank_accounts(company)


@frappe.whitelist()
def pay_employee_advance(
	company: str,
	employee: str,
	amount: float | str,
	paid_from: str,
	posting_date: str | None = None,
	mode_of_payment: str | None = None,
	reference_no: str | None = None,
	remark: str | None = None,
	submit: int = 1,
) -> dict:
	"""Pay a salary advance: a Payment Entry (Pay, party Employee) that moves cash
	into the Employee Advances account, raising the worker's outstanding balance.

	Routes through money.create_payment_entry, so it inherits the maker-checker
	approval guard, posting-window freeze, and audit logging automatically.
	"""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Unknown employee: {0}").format(employee))
	amt = flt(amount)
	if amt <= 0:
		frappe.throw(_("Advance amount must be greater than zero."))
	account = _employee_advance_account(company, employee)

	res = create_payment_entry(
		company=company,
		posting_date=str(getdate(posting_date)) if posting_date else today(),
		payment_type="Pay",
		party_type="Employee",
		party=employee,
		paid_from=paid_from,
		paid_to=account,
		paid_amount=amt,
		mode_of_payment=mode_of_payment,
		reference_no=reference_no,
		submit=int(submit or 0),
	)
	# Stamp a readable purpose on the entry without blocking the payment.
	try:
		if res.get("name") and remark:
			frappe.db.set_value("Payment Entry", res["name"], "remarks", remark, update_modified=False)
	except Exception:
		pass
	return res
