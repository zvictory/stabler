"""Per-employee financial summary for the People master-detail view.

One call gathers everything the Employees detail pane shows for a worker:
their advance balance + movements, their salary-payable balance + payments,
the net salaries already emitted to ERPNext, and recent payroll periods.
All money lives on the GL (party = Employee), so we read it straight from
GL Entry — the same source the advance and salary-payment modules use.
"""

from __future__ import annotations

import frappe
from stabler.api.approvals import _assert_company_scope
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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

	# ── All party=Employee GL across EVERY account (why erpnext-ui shows them) ─
	# Read every GL Entry where this worker is the Employee party, on any account
	# (Employee Credits Payable, Advances, Creditors …). Credit-normal net:
	# positive = we owe the worker, negative = the worker owes us.
	gl = frappe.db.sql(
		"""
		SELECT posting_date, creation, account, account_currency, voucher_type, voucher_no,
		       debit_in_account_currency AS debit, credit_in_account_currency AS credit
		FROM `tabGL Entry`
		WHERE company = %(c)s AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0
		ORDER BY posting_date DESC, creation DESC
		LIMIT 200
		""",
		{"c": company, "e": employee},
		as_dict=True,
	)
	# Skip pure FX-revaluation rows — base-currency-only "Exchange Gain Or Loss"
	# entries with ZERO account-currency movement. They don't change the account-
	# currency balance (net_owed is summed separately over all GL), so here they
	# would only add empty rows to the ledger.
	transactions = [{
		"posting_date": str(m["posting_date"]) if m.get("posting_date") else None,
		"_creation": str(m.get("creation") or ""),
		"account": m.get("account"),
		"label": (m.get("account") or "").split(" - ")[0],
		"currency": m.get("account_currency") or base_ccy,
		"voucher_type": m.get("voucher_type"),
		"voucher_no": m.get("voucher_no"),
		"debit": flt(m.get("debit")),
		"credit": flt(m.get("credit")),
		"docstatus": 1,
	} for m in gl if abs(flt(m.get("debit"))) > 0.005 or abs(flt(m.get("credit"))) > 0.005]

	# Draft Journal Entries aren't in the GL yet — surface them so they can be
	# reviewed, submitted or deleted from the ledger (transactions CRUD).
	drafts = frappe.db.sql(
		"""
		SELECT je.posting_date, je.creation, jea.account, jea.account_currency,
		       je.name AS voucher_no,
		       jea.debit_in_account_currency AS debit, jea.credit_in_account_currency AS credit
		FROM `tabJournal Entry Account` jea
		JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE je.company = %(c)s AND je.docstatus = 0
		  AND jea.party_type = 'Employee' AND jea.party = %(e)s
		ORDER BY je.posting_date DESC, je.creation DESC
		LIMIT 50
		""",
		{"c": company, "e": employee},
		as_dict=True,
	)
	draft_txns = [{
		"posting_date": str(d["posting_date"]) if d.get("posting_date") else None,
		"_creation": str(d.get("creation") or ""),
		"account": d.get("account"),
		"label": (d.get("account") or "").split(" - ")[0],
		"currency": d.get("account_currency") or base_ccy,
		"voucher_type": "Journal Entry",
		"voucher_no": d.get("voucher_no"),
		"debit": flt(d.get("debit")),
		"credit": flt(d.get("credit")),
		"docstatus": 0,
	} for d in drafts]
	transactions = sorted(draft_txns + transactions,
	                      key=lambda r: (r.get("posting_date") or "", r.get("_creation") or ""), reverse=True)

	net = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(credit_in_account_currency) - SUM(debit_in_account_currency), 0) AS net
		FROM `tabGL Entry`
		WHERE company = %(c)s AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0
		""",
		{"c": company, "e": employee},
	)
	net_owed = flt(net[0][0]) if net and net[0] else 0.0

	brk = frappe.db.sql(
		"""
		SELECT account, account_currency,
		       SUM(credit_in_account_currency) - SUM(debit_in_account_currency) AS bal
		FROM `tabGL Entry`
		WHERE company = %(c)s AND party_type = 'Employee' AND party = %(e)s
		  AND ifnull(is_cancelled, 0) = 0
		GROUP BY account, account_currency
		HAVING ABS(SUM(credit_in_account_currency) - SUM(debit_in_account_currency)) > 0.005
		ORDER BY ABS(SUM(credit_in_account_currency) - SUM(debit_in_account_currency)) DESC
		""",
		{"c": company, "e": employee},
		as_dict=True,
	)
	breakdown = [
		{"account": b["account"], "label": (b["account"] or "").split(" - ")[0],
		 "currency": b.get("account_currency") or base_ccy, "balance": flt(b["bal"])}
		for b in brk
	]
	display_currency = (breakdown[0]["currency"] if breakdown else None) or base_ccy

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
		"transactions": transactions,
		"breakdown": breakdown,
		"periods": periods,
	}


@frappe.whitelist()
def employee_net_balances(company: str, search: str = "", limit: int = 1000) -> dict:
	"""Per-employee net balance across ALL party=Employee GL accounts (for the list).

	Net = SUM(credit - debit) in account currency; positive = we owe the worker.
	Reads every account the worker is a party on — Employee Credits Payable,
	advances, creditors — so balances actually appear.
	"""
	_require_pay_role()
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	base_ccy = frappe.get_cached_value("Company", company, "default_currency") or ""
	# Group by party AND account currency so each worker's balance carries ITS OWN
	# original currency (UZS), not the base (USD). The detail pane does the same via
	# display_currency, so the list and the detail agree.
	rows = frappe.db.sql(
		"""
		SELECT party, account_currency AS currency,
		       SUM(credit_in_account_currency) - SUM(debit_in_account_currency) AS net
		FROM `tabGL Entry`
		WHERE company = %(c)s AND party_type = 'Employee'
		  AND ifnull(is_cancelled, 0) = 0 AND party IS NOT NULL AND party != ''
		GROUP BY party, account_currency
		""",
		{"c": company},
		as_dict=True,
	)
	totals: dict = {}
	by_ccy: dict = {}
	for r in rows:
		amt = flt(r["net"])
		totals[r["party"]] = totals.get(r["party"], 0.0) + amt
		by_ccy.setdefault(r["party"], {})
		ccy = r["currency"] or base_ccy
		by_ccy[r["party"]][ccy] = by_ccy[r["party"]].get(ccy, 0.0) + amt
	# Per-employee display currency = the account currency carrying the most weight.
	currencies = {p: max(m, key=lambda c: abs(m[c])) for p, m in by_ccy.items() if m}
	return {"balances": totals, "currencies": currencies, "base_currency": base_ccy}
