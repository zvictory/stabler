"""Dashboard aggregates for Stabler.

Computes KPIs and trends directly from ERPNext tables. All queries are
parameterised (no string interpolation of user values).
"""

from __future__ import annotations

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import flt, getdate

from stabler.api._common import _require_company
from stabler.api._money import money_epsilon
from stabler.api.approvals import _assert_company_scope
from stabler.api.organization import _can_access_module

# ---------------------------------------------------------------------------
# Whitelists — guard f-string table/column interpolation against future misuse

_ALLOWED_INVOICE_DOCTYPES: frozenset[str] = frozenset({"Sales Invoice", "Purchase Invoice"})
_ALLOWED_DATE_FIELDS: frozenset[str] = frozenset({"posting_date"})
_ALLOWED_AMOUNT_FIELDS: frozenset[str] = frozenset({"base_grand_total", "grand_total"})


# ---------------------------------------------------------------------------
# Date helpers


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
# Currency helpers


def _dominant_currency(company: str) -> str:
	"""Currency with the largest all-time SI base revenue for this company. Cached 300 s."""
	cache_key = f"stabler:dashboard:dominant:{company}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	rows = frappe.db.sql(
		"""
		SELECT currency
		FROM `tabSales Invoice`
		WHERE company = %(company)s AND docstatus = 1
		GROUP BY currency
		ORDER BY SUM(base_grand_total) DESC
		LIMIT 1
		""",
		{"company": company},
	)
	result = rows[0][0] if rows else (frappe.db.get_value("Company", company, "default_currency") or "USD")
	frappe.cache().set_value(cache_key, result, expires_in_sec=300)
	return result


def _by_currency(rows) -> list[dict]:
	"""Filter near-zero rows, sort by base magnitude desc, return [{currency, amount}].

	The `base` column (base-currency equivalent, used only for ordering) is dropped
	from the output — callers receive document/account-currency amounts only.
	"""
	filtered = [r for r in rows if abs(flt(r.get("base", 0))) >= money_epsilon()]
	filtered.sort(key=lambda r: abs(flt(r.get("base", 0))), reverse=True)
	return [{"currency": r["currency"], "amount": flt(r["amount"], 2)} for r in filtered]


# ---------------------------------------------------------------------------
# Summary KPIs


@frappe.whitelist()
def summary(company: str):
	"""Return per-currency cash / AR / AP / revenue-MTD for the dashboard tiles."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company = _require_company(company)
	if not _can_access_module(frappe.session.user, "dashboard"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	today = getdate()
	month_start = _month_start(today)
	prev_month_start = _shift_month(month_start, -1)
	prev_month_end = _last_day_of_month(prev_month_start)

	dominant = _dominant_currency(company)
	cash = _cash_balance_by_currency(company)
	ar = _outstanding_by_currency("Sales Invoice", company)
	ap = _outstanding_by_currency("Purchase Invoice", company)
	revenue_mtd = _revenue_between_by_currency(company, month_start, today)

	# Trend uses dominant-currency document totals (grand_total, not base).
	revenue_mtd_dom = next((r["amount"] for r in revenue_mtd if r["currency"] == dominant), 0.0)
	revenue_prev = _revenue_dominant_between(company, dominant, prev_month_start, prev_month_end)

	trend_pct = None
	if revenue_prev:
		trend_pct = ((revenue_mtd_dom - revenue_prev) / revenue_prev) * 100.0

	return {
		"company": company,
		"dominant_currency": dominant,
		"cash": cash,
		"ar": ar,
		"ap": ap,
		"revenue_mtd": revenue_mtd,
		"revenue_trend_pct": flt(trend_pct, 2) if trend_pct is not None else None,
	}


def _cash_balance_by_currency(company: str) -> list[dict]:
	"""GL Cash/Bank balance per account currency (account-currency amounts)."""
	cache_key = f"stabler:dashboard:cash_ccy:{company}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	rows = frappe.db.sql(
		"""
		SELECT a.account_currency AS currency,
		       COALESCE(SUM(gle.debit_in_account_currency - gle.credit_in_account_currency), 0) AS amount,
		       COALESCE(SUM(gle.debit - gle.credit), 0) AS base
		FROM `tabGL Entry` gle
		JOIN `tabAccount` a ON a.name = gle.account
		WHERE gle.company = %(company)s
		  AND gle.is_cancelled = 0
		  AND a.account_type IN ('Cash', 'Bank')
		GROUP BY a.account_currency
		""",
		{"company": company},
		as_dict=True,
	)
	result = _by_currency(rows)
	frappe.cache().set_value(cache_key, result, expires_in_sec=300)
	return result


def _outstanding_by_currency(doctype: str, company: str) -> list[dict]:
	"""Sum of outstanding_amount per document currency for submitted non-cancelled invoices."""
	if doctype not in _ALLOWED_INVOICE_DOCTYPES:
		frappe.throw(f"Invalid doctype for outstanding total: {doctype}")
	cache_key = f"stabler:dashboard:outstanding_ccy:{doctype}:{company}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	table = f"tab{doctype}"
	rows = frappe.db.sql(
		f"""
		SELECT currency,
		       COALESCE(SUM(outstanding_amount), 0) AS amount,
		       COALESCE(SUM(outstanding_amount * conversion_rate), 0) AS base
		FROM `{table}`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND status NOT IN ('Cancelled', 'Closed')
		GROUP BY currency
		""",
		{"company": company},
		as_dict=True,
	)
	result = _by_currency(rows)
	frappe.cache().set_value(cache_key, result, expires_in_sec=300)
	return result


def _revenue_between_by_currency(company: str, start: date, end: date) -> list[dict]:
	"""SI grand_total (document currency) per currency for the given date range."""
	cache_key = f"stabler:dashboard:revenue_ccy:{company}:{start}:{end}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	rows = frappe.db.sql(
		"""
		SELECT currency,
		       COALESCE(SUM(grand_total), 0) AS amount,
		       COALESCE(SUM(base_grand_total), 0) AS base
		FROM `tabSales Invoice`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND posting_date BETWEEN %(start)s AND %(end)s
		GROUP BY currency
		""",
		{"company": company, "start": start, "end": end},
		as_dict=True,
	)
	result = _by_currency(rows)
	frappe.cache().set_value(cache_key, result, expires_in_sec=300)
	return result


def _revenue_dominant_between(company: str, currency: str, start: date, end: date) -> float:
	"""SI grand_total for the dominant currency in the date range (used for trend computation)."""
	cache_key = f"stabler:dashboard:revenue_dom:{company}:{currency}:{start}:{end}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	rows = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(grand_total), 0)
		FROM `tabSales Invoice`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND currency = %(currency)s
		  AND posting_date BETWEEN %(start)s AND %(end)s
		""",
		{"company": company, "currency": currency, "start": start, "end": end},
	)
	result = flt(rows[0][0]) if rows else 0.0
	frappe.cache().set_value(cache_key, result, expires_in_sec=300)
	return result


# ---------------------------------------------------------------------------
# 12-month revenue / expense trend


@frappe.whitelist()
def revenue_trend(company: str, months: int = 12):
	"""Monthly revenue & expense for the past `months` months in the dominant currency."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company = _require_company(company)
	if not _can_access_module(frappe.session.user, "dashboard"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	months = max(1, min(36, int(months)))

	dominant = _dominant_currency(company)
	today = getdate()
	start = _shift_month(_month_start(today), -(months - 1))
	end = _last_day_of_month(today)

	revenue_rows = _monthly_totals_by_currency(
		"Sales Invoice", "posting_date", "grand_total", company, start, end, dominant
	)
	expense_rows = _monthly_totals_by_currency(
		"Purchase Invoice", "posting_date", "grand_total", company, start, end, dominant
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

	return {"months": labels, "revenue": revenue, "expense": expense, "currency": dominant}


def _monthly_totals_by_currency(
	doctype: str,
	date_field: str,
	amount_field: str,
	company: str,
	start: date,
	end: date,
	currency: str,
):
	"""Monthly document-currency totals filtered to a specific transaction currency."""
	if doctype not in _ALLOWED_INVOICE_DOCTYPES:
		frappe.throw(f"Invalid doctype for monthly totals: {doctype}")
	if date_field not in _ALLOWED_DATE_FIELDS:
		frappe.throw(f"Invalid date field: {date_field}")
	if amount_field not in _ALLOWED_AMOUNT_FIELDS:
		frappe.throw(f"Invalid amount field: {amount_field}")
	cache_key = f"stabler:dashboard:monthly_ccy:{doctype}:{company}:{currency}:{start}:{end}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	table = f"tab{doctype}"
	result = frappe.db.sql(
		f"""
		SELECT DATE_FORMAT({date_field}, '%%Y-%%m') AS m,
		       COALESCE(SUM({amount_field}), 0) AS total
		FROM `{table}`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND currency = %(currency)s
		  AND {date_field} BETWEEN %(start)s AND %(end)s
		GROUP BY m
		ORDER BY m
		""",
		{"company": company, "currency": currency, "start": start, "end": end},
		as_dict=True,
	)
	frappe.cache().set_value(cache_key, result, expires_in_sec=300)
	return result


# ---------------------------------------------------------------------------
# Recent activity feed


@frappe.whitelist()
def recent_activity(company: str, limit: int = 10):
	"""Latest submitted documents across SI, PI, Payment Entry, Journal Entry."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company = _require_company(company)
	if not _can_access_module(frappe.session.user, "dashboard"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	limit = max(1, min(50, int(limit)))

	base_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	rows = frappe.db.sql(
		"""
		SELECT * FROM (
			SELECT 'Sales Invoice' AS doctype, name, customer_name AS party,
			       grand_total AS amount, currency, status,
			       posting_date, modified
			FROM `tabSales Invoice`
			WHERE company = %(company)s AND docstatus = 1
			ORDER BY modified DESC
			LIMIT %(limit)s
		) si

		UNION ALL

		SELECT * FROM (
			SELECT 'Purchase Invoice' AS doctype, name, supplier_name AS party,
			       grand_total AS amount, currency, status,
			       posting_date, modified
			FROM `tabPurchase Invoice`
			WHERE company = %(company)s AND docstatus = 1
			ORDER BY modified DESC
			LIMIT %(limit)s
		) pi

		UNION ALL

		SELECT * FROM (
			SELECT 'Payment Entry' AS doctype, name,
			       COALESCE(party_name, party) AS party,
			       paid_amount AS amount,
			       paid_from_account_currency AS currency,
			       status, posting_date, modified
			FROM `tabPayment Entry`
			WHERE company = %(company)s AND docstatus = 1
			ORDER BY modified DESC
			LIMIT %(limit)s
		) pe

		UNION ALL

		SELECT * FROM (
			SELECT 'Journal Entry' AS doctype, name, voucher_type AS party,
			       total_debit AS amount, %(base_currency)s AS currency,
			       'Submitted' AS status, posting_date, modified
			FROM `tabJournal Entry`
			WHERE company = %(company)s AND docstatus = 1
			ORDER BY modified DESC
			LIMIT %(limit)s
		) je

		ORDER BY modified DESC
		LIMIT %(limit)s
		""",
		{"company": company, "limit": limit, "base_currency": base_currency},
		as_dict=True,
	)

	return [
		{
			"doctype": r["doctype"],
			"name": r["name"],
			"title": r["name"],
			"party": r["party"] or "",
			"amount": flt(r["amount"], 2),
			"currency": r.get("currency") or base_currency,
			"status": r["status"],
			"date": str(r["posting_date"]) if r["posting_date"] else "",
		}
		for r in rows
	]
