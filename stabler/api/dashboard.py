"""Dashboard aggregates for Stabler.

Computes KPIs and trends directly from ERPNext tables. All queries are
parameterised (no string interpolation of user values).
"""

from __future__ import annotations

from datetime import date, timedelta

import frappe
from frappe.utils import flt, getdate


# ---------------------------------------------------------------------------
# Helpers


def _require_company(company: str | None) -> str:
	if not company:
		frappe.throw("company is required")
	if not frappe.db.exists("Company", company):
		frappe.throw(f"Unknown company: {company}")
	return company


def _month_start(d: date) -> date:
	return d.replace(day=1)


def _shift_month(d: date, months: int) -> date:
	"""Move `d` by ±months, snapped to first of month."""
	year = d.year + (d.month - 1 + months) // 12
	month = (d.month - 1 + months) % 12 + 1
	return date(year, month, 1)


def _last_day_of_month(d: date) -> date:
	nxt = _shift_month(_month_start(d), 1)
	return nxt - timedelta(days=1)


# ---------------------------------------------------------------------------
# Summary KPIs


@frappe.whitelist()
def summary(company: str):
	"""Return cash / AR / AP / revenue-MTD for the dashboard tiles."""
	company = _require_company(company)
	today = getdate()
	month_start = _month_start(today)
	prev_month_start = _shift_month(month_start, -1)
	prev_month_end = _last_day_of_month(prev_month_start)

	cash = _cash_balance(company)
	ar = _outstanding_total("Sales Invoice", company)
	ap = _outstanding_total("Purchase Invoice", company)
	revenue_mtd = _revenue_between(company, month_start, today)
	revenue_prev = _revenue_between(company, prev_month_start, prev_month_end)

	trend_pct = None
	if revenue_prev:
		trend_pct = ((revenue_mtd - revenue_prev) / revenue_prev) * 100.0

	return {
		"company": company,
		"cash": flt(cash, 2),
		"ar": flt(ar, 2),
		"ap": flt(ap, 2),
		"revenue_mtd": flt(revenue_mtd, 2),
		"revenue_prev": flt(revenue_prev, 2),
		"revenue_trend_pct": flt(trend_pct, 2) if trend_pct is not None else None,
	}


def _cash_balance(company: str) -> float:
	"""Sum of balances on Cash + Bank ledger accounts for the company."""
	rows = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(gle.debit - gle.credit), 0) AS bal
		FROM `tabGL Entry` gle
		JOIN `tabAccount` a ON a.name = gle.account
		WHERE gle.company = %(company)s
		  AND gle.is_cancelled = 0
		  AND a.account_type IN ('Cash', 'Bank')
		""",
		{"company": company},
	)
	return flt(rows[0][0]) if rows else 0.0


def _outstanding_total(doctype: str, company: str) -> float:
	"""Sum of outstanding_amount on submitted, non-cancelled invoices."""
	rows = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(outstanding_amount), 0)
		FROM `tab{doctype}`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND status NOT IN ('Cancelled', 'Closed')
		""",
		{"company": company},
	)
	return flt(rows[0][0]) if rows else 0.0


def _revenue_between(company: str, start: date, end: date) -> float:
	rows = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(base_grand_total), 0)
		FROM `tabSales Invoice`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND posting_date BETWEEN %(start)s AND %(end)s
		""",
		{"company": company, "start": start, "end": end},
	)
	return flt(rows[0][0]) if rows else 0.0


# ---------------------------------------------------------------------------
# 12-month revenue / expense trend


@frappe.whitelist()
def revenue_trend(company: str, months: int = 12):
	"""Monthly revenue & expense series for the past `months` months (inclusive)."""
	company = _require_company(company)
	months = max(1, min(36, int(months)))

	today = getdate()
	start = _shift_month(_month_start(today), -(months - 1))
	end = _last_day_of_month(today)

	revenue_rows = _monthly_totals(
		"Sales Invoice", "posting_date", "base_grand_total", company, start, end
	)
	expense_rows = _monthly_totals(
		"Purchase Invoice", "posting_date", "base_grand_total", company, start, end
	)

	labels, revenue, expense = [], [], []
	cursor = _month_start(start)
	rev_map = {r["m"]: flt(r["total"]) for r in revenue_rows}
	exp_map = {r["m"]: flt(r["total"]) for r in expense_rows}
	while cursor <= end:
		key = cursor.strftime("%Y-%m")
		labels.append(cursor.strftime("%b %y"))
		revenue.append(flt(rev_map.get(key, 0.0), 2))
		expense.append(flt(exp_map.get(key, 0.0), 2))
		cursor = _shift_month(cursor, 1)

	return {"months": labels, "revenue": revenue, "expense": expense}


def _monthly_totals(
	doctype: str, date_field: str, amount_field: str, company: str, start: date, end: date
):
	return frappe.db.sql(
		f"""
		SELECT DATE_FORMAT({date_field}, '%%Y-%%m') AS m,
		       COALESCE(SUM({amount_field}), 0) AS total
		FROM `tab{doctype}`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND {date_field} BETWEEN %(start)s AND %(end)s
		GROUP BY m
		ORDER BY m
		""",
		{"company": company, "start": start, "end": end},
		as_dict=True,
	)


# ---------------------------------------------------------------------------
# Recent activity feed


@frappe.whitelist()
def recent_activity(company: str, limit: int = 10):
	"""Latest submitted documents across SI, PI, Payment Entry, Journal Entry."""
	company = _require_company(company)
	limit = max(1, min(50, int(limit)))

	base_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	queries = [
		(
			"Sales Invoice",
			"customer",
			"customer_name",
			"grand_total",
			"status",
			"posting_date",
		),
		(
			"Purchase Invoice",
			"supplier",
			"supplier_name",
			"grand_total",
			"status",
			"posting_date",
		),
	]

	items: list[dict] = []
	for doctype, party_field, party_name, amount_field, status_field, date_field in queries:
		rows = frappe.db.sql(
			f"""
			SELECT name, {party_field} AS party_id, {party_name} AS party,
			       {amount_field} AS amount, {status_field} AS status,
			       {date_field} AS posting_date, currency
			FROM `tab{doctype}`
			WHERE company = %(company)s AND docstatus = 1
			ORDER BY modified DESC
			LIMIT %(limit)s
			""",
			{"company": company, "limit": limit},
			as_dict=True,
		)
		for r in rows:
			items.append(
				{
					"doctype": doctype,
					"name": r["name"],
					"title": r["name"],
					"party": r["party"] or r["party_id"],
					"amount": flt(r["amount"], 2),
					"currency": r.get("currency") or base_currency,
					"status": r["status"],
					"date": str(r["posting_date"]) if r["posting_date"] else "",
					"modified": str(r.get("modified", "")),
				}
			)

	# Payment Entry
	pe_rows = frappe.db.sql(
		"""
		SELECT name, party, party_name, paid_amount, status, posting_date,
		       paid_from_account_currency
		FROM `tabPayment Entry`
		WHERE company = %(company)s AND docstatus = 1
		ORDER BY modified DESC
		LIMIT %(limit)s
		""",
		{"company": company, "limit": limit},
		as_dict=True,
	)
	for r in pe_rows:
		items.append(
			{
				"doctype": "Payment Entry",
				"name": r["name"],
				"title": r["name"],
				"party": r["party_name"] or r["party"],
				"amount": flt(r["paid_amount"], 2),
				"currency": r.get("paid_from_account_currency") or base_currency,
				"status": r["status"],
				"date": str(r["posting_date"]) if r["posting_date"] else "",
			}
		)

	# Journal Entry — totals always in base (company) currency.
	je_rows = frappe.db.sql(
		"""
		SELECT name, total_debit, posting_date, voucher_type
		FROM `tabJournal Entry`
		WHERE company = %(company)s AND docstatus = 1
		ORDER BY modified DESC
		LIMIT %(limit)s
		""",
		{"company": company, "limit": limit},
		as_dict=True,
	)
	for r in je_rows:
		items.append(
			{
				"doctype": "Journal Entry",
				"name": r["name"],
				"title": r["name"],
				"party": r["voucher_type"],
				"amount": flt(r["total_debit"], 2),
				"currency": base_currency,
				"status": "Submitted",
				"date": str(r["posting_date"]) if r["posting_date"] else "",
			}
		)

	items.sort(key=lambda x: x.get("date", ""), reverse=True)
	return items[:limit]
