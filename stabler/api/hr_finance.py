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
	# Use the account-currency columns so movements read in the account's own
	# (original) currency — UZS — regardless of the company base currency.
	rows = frappe.db.sql(
		"""
		SELECT posting_date, creation, voucher_type, voucher_no,
		       debit_in_account_currency AS debit, credit_in_account_currency AS credit, remarks
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
		m["_creation"] = str(m.pop("creation", "") or "")
		m["posting_date"] = str(m["posting_date"]) if m.get("posting_date") else None
		m["debit"] = flt(m["debit"])
		m["credit"] = flt(m["credit"])
	return rows


def _acct_ccy(account: str | None, fallback: str) -> str:
	if not account:
		return fallback
	return frappe.db.get_value("Account", account, "account_currency") or fallback


def _payable_balance_acc(company: str, account: str, employee: str) -> float:
	"""Outstanding salary payable for one employee in the account's own currency."""
	row = frappe.db.sql(
		"""
		SELECT SUM(credit_in_account_currency) - SUM(debit_in_account_currency) AS bal
		FROM `tabGL Entry`
		WHERE company = %(c)s AND account = %(a)s
		  AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0
		""",
		{"c": company, "a": account, "e": employee},
	)
	return flt(row[0][0]) if row and row[0] else 0.0


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

	# ── Advances (Employee Advances account) — in the account's own currency ──
	advance = {"account": None, "currency": base_ccy, "outstanding": 0.0, "movements": []}
	try:
		from stabler.api.employee_advance import _advance_account, _balances

		acc = _advance_account(company)
		advance = {
			"account": acc,
			"currency": _acct_ccy(acc, base_ccy),
			"outstanding": flt(_balances(company, acc).get(employee, 0.0)),
			"movements": _party_movements(company, acc, employee),
		}
	except Exception:
		pass

	# ── Salary payable (accrued but unpaid) — in the account's own currency ───
	payable = {"account": None, "currency": base_ccy, "outstanding": 0.0, "movements": []}
	try:
		from stabler.api.salary_payment import _salary_payable_account

		acc = _salary_payable_account(company)
		payable = {
			"account": acc,
			"currency": _acct_ccy(acc, base_ccy),
			"outstanding": _payable_balance_acc(company, acc, employee),
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

	# ── Unified vendor-style ledger ───────────────────────────────────────────
	# Treat the employee as one payable party: merge both accounts' movements into
	# a single chronological ledger. For BOTH accounts the effect on "net we owe
	# the employee" is (credit - debit), so a single running balance works:
	#   salary accrual  → Credit (we owe more)
	#   salary payment  → Debit  (we owe less)
	#   advance paid    → Debit  (early payment; can push the balance negative)
	#   advance recovered (from salary) → Credit
	txns = []
	for m in advance.get("movements", []):
		txns.append({**m, "source": "Advance"})
	for m in payable.get("movements", []):
		txns.append({**m, "source": "Salary"})
	txns.sort(key=lambda r: (r.get("posting_date") or "", r.get("_creation") or ""), reverse=True)
	txns = txns[:80]
	# Net payable to the employee = what we owe (payable) minus what they owe us
	# (outstanding advance). Positive = we owe them; negative = they owe us.
	net_owed = flt(payable["outstanding"]) - flt(advance["outstanding"])

	return {
		"employee": employee,
		"profile": emp,
		"base_currency": base_ccy,
		# Display currency for the detail pane — the account's own currency (UZS).
		"display_currency": payable.get("currency") or advance.get("currency") or base_ccy,
		"net_owed": net_owed,
		"transactions": txns,
		"advance": advance,
		"payable": payable,
		"salaries": salaries,
		"periods": periods,
	}
