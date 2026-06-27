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


def _emp_account(company: str) -> str | None:
	"""The account workers' advances + salaries run through — anchor the ledger on
	it so the panel mirrors that GL account exactly. Detects an account named like
	'Employee Credits Payable' (any currency); None ⇒ fall back to every account
	the employee is a party on."""
	row = frappe.db.sql(
		"""SELECT name FROM `tabAccount`
		   WHERE company = %(c)s AND is_group = 0
		     AND (name LIKE %(p1)s OR name LIKE %(p2)s)
		   ORDER BY (account_type = 'Payable') DESC, name ASC LIMIT 1""",
		{"c": company, "p1": "%Employee Credit%", "p2": "%Employee Credits Payable%"},
	)
	return row[0][0] if row else None


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

	# ── Vendor-style ledger ───────────────────────────────────────────────────
	# Anchor on the Employee Credits Payable account (where the worker advances +
	# salaries are booked); if that account isn't found, fall back to every account
	# the worker is a party on. Read in the account's own currency.
	emp_acc = _emp_account(company)
	acc_clause = "AND account = %(acc)s" if emp_acc else ""
	params = {"c": company, "e": employee, "acc": emp_acc}
	gl = frappe.db.sql(
		f"""
		SELECT posting_date, creation, account, account_currency, voucher_type, voucher_no,
		       debit_in_account_currency AS debit, credit_in_account_currency AS credit, remarks
		FROM `tabGL Entry`
		WHERE company = %(c)s AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0 {acc_clause}
		ORDER BY posting_date DESC, creation DESC
		LIMIT 200
		""",
		params,
		as_dict=True,
	)
	txns = []
	for m in gl:
		txns.append({
			"posting_date": str(m["posting_date"]) if m.get("posting_date") else None,
			"_creation": str(m.get("creation") or ""),
			"account": m.get("account"),
			"label": (m.get("account") or "").split(" - ")[0],  # short account name
			"voucher_type": m.get("voucher_type"),
			"voucher_no": m.get("voucher_no"),
			"debit": flt(m.get("debit")),
			"credit": flt(m.get("credit")),
		})

	# Net "we owe the employee" across ALL party accounts (credit-normal). Computed
	# over the full history, not just the 200 shown, so the anchor is exact.
	totals = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(credit_in_account_currency) - SUM(debit_in_account_currency), 0) AS net
		FROM `tabGL Entry`
		WHERE company = %(c)s AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0 {acc_clause}
		""",
		params,
	)
	net_owed = flt(totals[0][0]) if totals and totals[0] else 0.0

	# Per-account breakdown (so the gross composition is visible for audit).
	brk = frappe.db.sql(
		f"""
		SELECT account, account_currency,
		       SUM(credit_in_account_currency) - SUM(debit_in_account_currency) AS bal
		FROM `tabGL Entry`
		WHERE company = %(c)s AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0 {acc_clause}
		GROUP BY account, account_currency
		HAVING ABS(bal) > 0.005
		ORDER BY ABS(bal) DESC
		""",
		params,
		as_dict=True,
	)
	breakdown = [
		{"account": b["account"], "label": (b["account"] or "").split(" - ")[0],
		 "currency": b.get("account_currency") or base_ccy, "balance": flt(b["bal"])}
		for b in brk
	]
	# Display currency = the currency carrying the largest balance, else base.
	display_currency = (breakdown[0]["currency"] if breakdown else None) or base_ccy

	# Recent payroll periods (context).
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
		"display_currency": display_currency,
		"net_owed": net_owed,
		"transactions": txns,
		"breakdown": breakdown,
		"periods": periods,
	}


@frappe.whitelist()
def employee_net_balances(company: str, search: str = "", limit: int = 1000) -> dict:
	"""Per-employee net balance across ALL party=Employee GL accounts (for the list).

	Net = SUM(credit - debit) in account currency; positive = we owe the worker.
	"""
	_require_pay_role()
	_require_company(company)
	emp_acc = _emp_account(company)
	acc_clause = "AND gl.account = %(acc)s" if emp_acc else ""
	rows = frappe.db.sql(
		f"""
		SELECT gl.party AS employee,
		       SUM(gl.credit_in_account_currency) - SUM(gl.debit_in_account_currency) AS net,
		       MAX(gl.account_currency) AS currency
		FROM `tabGL Entry` gl
		WHERE gl.company = %(c)s AND gl.party_type = 'Employee'
		  AND ifnull(gl.is_cancelled, 0) = 0 {acc_clause}
		GROUP BY gl.party
		""",
		{"c": company, "acc": emp_acc},
		as_dict=True,
	)
	base_ccy = frappe.get_cached_value("Company", company, "default_currency") or ""
	out = {r["employee"]: flt(r["net"]) for r in rows}
	ccy = next((r["currency"] for r in rows if r.get("currency")), base_ccy)
	return {"balances": out, "currency": ccy or base_ccy}
