"""Budget vs Actual — thin Frappe layer surfacing ERPNext Budget doctype.

Endpoints:
  list_budgets          — list Budget docs for a company/fiscal year
  get_budget            — fetch one Budget doc
  budget_vs_actual      — report: budget vs GL actuals per account/cost-centre/period

Design: ERPNext Budget doctype stores budget allocations; we read GL Entry
for actuals. We do NOT replicate ERPNext's budget-check enforcement (that lives
in erpnext/accounts/utils.py validate_expense_against_budget). We only surface
the read side for the Stabler SPA.

Guest is rejected at the whitelist level.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from stabler.api._budget import compute_variance_report
from stabler.api._common import _assert_can_read, _require_company
from stabler.api.approvals import _assert_company_scope


def _reject_guest() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _base_currency(company: str) -> str:
	return frappe.get_cached_value("Company", company, "default_currency") or ""


def _validate_dates(from_date: str, to_date: str):
	"""Return (start, end) as date strings; throw on bad input."""
	try:
		start = getdate(from_date) if from_date else getdate(today())
		end   = getdate(to_date)   if to_date   else getdate(today())
	except Exception:
		frappe.throw(_("Invalid date value."), frappe.ValidationError)
	if end < start:
		frappe.throw(_("to_date must be >= from_date."), frappe.ValidationError)
	return str(start), str(end)


# ---------------------------------------------------------------------------
# list_budgets
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_budgets(
	company: str,
	fiscal_year: str = "",
	cost_center: str = "",
	limit: int = 100,
) -> list:
	"""List Budget docs for a company (optionally filtered by fiscal year / cost centre)."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_reject_guest()
	_require_company(company)
	if not frappe.has_permission("Budget", "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters: dict = {"company": company}
	if fiscal_year:
		if not frappe.db.exists("Fiscal Year", fiscal_year):
			frappe.throw(_("Unknown Fiscal Year: {0}").format(fiscal_year), frappe.ValidationError)
		filters["fiscal_year"] = fiscal_year
	if cost_center:
		if not frappe.db.exists("Cost Center", cost_center):
			frappe.throw(_("Unknown Cost Center: {0}").format(cost_center), frappe.ValidationError)
		filters["cost_center"] = cost_center

	docs = frappe.get_all(
		"Budget",
		filters=filters,
		fields=[
			"name", "company", "fiscal_year", "cost_center",
			"action_if_annual_budget_exceeded",
			"action_if_accumulated_monthly_budget_exceeded",
			"docstatus",
		],
		order_by="fiscal_year desc, name asc",
		limit=int(limit),
	)
	return docs


# ---------------------------------------------------------------------------
# get_budget
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_budget(name: str) -> dict:
	"""Fetch one Budget doc by name (full document with accounts child table)."""
	_reject_guest()
	if not name:
		frappe.throw(_("Name is required."), frappe.ValidationError)
	_assert_can_read("Budget", name)
	doc = frappe.get_doc("Budget", name)
	return doc.as_dict()


# ---------------------------------------------------------------------------
# budget_vs_actual — main report
# ---------------------------------------------------------------------------

@frappe.whitelist()
def budget_vs_actual(
	company: str,
	from_date: str = "",
	to_date: str = "",
	fiscal_year: str = "",
	cost_center: str = "",
) -> dict:
	"""Return a budget-vs-actual variance report for a company/period.

	Reads budget allocations from the ERPNext Budget doctype (Budget Account
	child table, monthly_distribution or flat-rate) and actual debit/credit
	movements from GL Entry for the same period and accounts.

	Response shape (mirrors reports.py _shape):
	  {
	    "columns": [...],
	    "rows": [{account, cost_center, period, budget, actual, variance,
	              variance_pct, status, account_type}],
	    "totals": {budget, actual, variance},
	    "meta": {currency, from, to, favorable_count, unfavorable_count, on_budget_count},
	  }
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_reject_guest()
	_require_company(company)
	if not frappe.has_permission("Budget", "read"):
		frappe.throw(_("Not permitted to read Budget."), frappe.PermissionError)
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("Not permitted to read GL entries."), frappe.PermissionError)

	start, end = _validate_dates(from_date, to_date)
	base_ccy = _base_currency(company)

	# -------------------------------------------------------------------
	# 1. Collect budget allocations from submitted Budget docs
	# -------------------------------------------------------------------
	bgt_filters: dict = {"company": company, "docstatus": 1}
	if fiscal_year:
		bgt_filters["fiscal_year"] = fiscal_year
	if cost_center:
		bgt_filters["cost_center"] = cost_center

	budget_docs = frappe.get_all(
		"Budget",
		filters=bgt_filters,
		fields=["name", "cost_center", "fiscal_year"],
	)

	# Map (account, cost_center) → budgeted amount (sum across matching docs)
	budget_map: dict = {}		# key: (account, cost_center)
	account_type_map: dict = {}	# key: account → account_type

	for bdoc in budget_docs:
		ba_rows = frappe.get_all(
			"Budget Account",
			filters={"parent": bdoc.name, "parenttype": "Budget"},
			fields=["account", "budget_amount"],
		)
		cc = bdoc.cost_center or ""
		for ba in ba_rows:
			key = (ba.account, cc)
			budget_map[key] = budget_map.get(key, 0.0) + flt(ba.budget_amount)
			if ba.account not in account_type_map:
				acc_type = frappe.get_cached_value("Account", ba.account, "account_type") or "Expense"
				account_type_map[ba.account] = acc_type

	# -------------------------------------------------------------------
	# 2. Fetch GL actuals for the period (parameterised SQL)
	# -------------------------------------------------------------------
	cc_filter_sql = ""
	gl_params: dict = {
		"company": company,
		"from_date": start,
		"to_date": end,
	}
	if cost_center:
		cc_filter_sql = "AND gl.cost_center = %(cost_center)s"
		gl_params["cost_center"] = cost_center

	actuals_rows = frappe.db.sql(
		f"""
		SELECT
			gl.account,
			gl.cost_center,
			SUM(gl.debit - gl.credit) AS net_movement
		FROM `tabGL Entry` gl
		WHERE gl.company = %(company)s
			AND gl.is_cancelled = 0
			AND gl.posting_date BETWEEN %(from_date)s AND %(to_date)s
			{cc_filter_sql}
		GROUP BY gl.account, gl.cost_center
		""",
		gl_params,
		as_dict=True,
	)

	actuals_map: dict = {}	# key: (account, cost_center) → net_movement
	for row in actuals_rows:
		key = (row.account, row.cost_center or "")
		actuals_map[key] = flt(row.net_movement)

	# -------------------------------------------------------------------
	# 3. Build unified row set (union of budget keys + actuals keys)
	# -------------------------------------------------------------------
	all_keys = set(budget_map.keys()) | set(actuals_map.keys())

	input_rows = []
	for account, cc in sorted(all_keys):
		acc_type = account_type_map.get(account)
		if not acc_type:
			acc_type = frappe.get_cached_value("Account", account, "account_type") or "Expense"
			account_type_map[account] = acc_type
		input_rows.append({
			"account": account,
			"cost_center": cc,
			"period": f"{start} – {end}",
			"budget": budget_map.get((account, cc), 0.0),
			"actual": actuals_map.get((account, cc), 0.0),
			"account_type": acc_type,
			"currency": base_ccy,
		})

	# -------------------------------------------------------------------
	# 4. Pure variance calc
	# -------------------------------------------------------------------
	report = compute_variance_report(input_rows)

	# -------------------------------------------------------------------
	# 5. Shape response (mirrors reports.py _shape convention)
	# -------------------------------------------------------------------
	columns = [
		{"key": "account",      "label": _("Account"),      "type": "text"},
		{"key": "cost_center",  "label": _("Cost Centre"),  "type": "text"},
		{"key": "period",       "label": _("Period"),       "type": "text"},
		{"key": "budget",       "label": _("Budget"),       "type": "money",   "align": "end"},
		{"key": "actual",       "label": _("Actual"),       "type": "money",   "align": "end"},
		{"key": "variance",     "label": _("Variance"),     "type": "money",   "align": "end"},
		{"key": "variance_pct", "label": _("Var %"),        "type": "percent", "align": "end"},
		{"key": "status",       "label": _("Status"),       "type": "badge"},
	]

	# Convert Decimal → float for JSON serialisation
	out_rows = []
	for r in report["rows"]:
		out = dict(r)
		for k in ("budget", "actual", "variance"):
			out[k] = float(out[k]) if out[k] is not None else 0.0
		vp = out.get("variance_pct")
		out["variance_pct"] = float(vp) if vp is not None else None
		out_rows.append(out)

	totals = {k: float(v) for k, v in report["totals"].items()}

	meta = {
		"currency": base_ccy,
		"from": start,
		"to": end,
		"fiscal_year": fiscal_year or "",
		"cost_center": cost_center or "",
		"favorable_count":   report["favorable_count"],
		"unfavorable_count": report["unfavorable_count"],
		"on_budget_count":   report["on_budget_count"],
		"note": _("Submitted budgets vs GL actuals (debit − credit). Income favorable = actual > budget; cost favorable = actual < budget."),
	}

	return {
		"columns": columns,
		"rows": out_rows,
		"totals": totals,
		"meta": meta,
	}
