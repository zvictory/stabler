"""Report Center — unified report endpoints.

Every report returns the same shape so one frontend engine (ReportTable.vue) can
render any of them and route any drill-down:

    {
      "columns": [{"key","label","type","align","drill"?,"doctype"?}],
      "rows":    [ {..}, .. ],
      "totals":  {col_key: number, ..},     # optional footer row
      "meta":    {"basis","currency","from","to","note"}
    }

Conventions (the Critic's non-negotiables):
  - Submitted documents only (docstatus = 1); cancelled excluded.
  - Returns are netted automatically — credit/return invoices carry negative
    totals, so SUM() already subtracts them.
  - Accrual basis (invoice posting_date) by default; stated in meta.basis.
  - Never sum across currencies; group by currency. (UZS-only today.)
"""

from __future__ import annotations

import frappe
from stabler.api.approvals import _assert_company_scope
from frappe import _
from frappe.utils import flt

from stabler.api._common import _require_company
from stabler.api.sales import _sales_report_dates, _sales_report_period_expr


def _base_currency(company: str) -> str:
    return frappe.get_cached_value("Company", company, "default_currency") or "UZS"


def _shape(columns, rows, totals=None, meta=None) -> dict:
    return {"columns": columns, "rows": rows, "totals": totals or {}, "meta": meta or {}}


def _decode_list(v):
    """Live callers pass a JSON-stringified array (query param); export.py's
    _call_source already runs frappe.parse_json once, so it hands us a list."""
    if v is None:
        return []
    return frappe.parse_json(v) if isinstance(v, str) else (v or [])


def _in_clause(sql_field: str, key: str, values, params: dict) -> str:
    """Build ` AND <sql_field> IN %(key)s`, or "" if values is empty (an empty
    IN () is invalid SQL — no filter is the correct behaviour for an empty pick)."""
    vals = _decode_list(values)
    if not vals:
        return ""
    params[key] = tuple(vals)
    return f" AND {sql_field} IN %({key})s"


_SORT_DIR = {"asc": "ASC", "desc": "DESC"}


def _order_by(sort_by, sort_dir, allow_map: dict, default_key: str, default_dir: str = "desc") -> str:
    """allow_map maps frontend sort keys -> whitelisted SQL column expressions,
    so user input never reaches the query string directly (no injection)."""
    col = allow_map.get(sort_by) or allow_map[default_key]
    direction = _SORT_DIR.get((sort_dir or "").lower(), _SORT_DIR[default_dir])
    return f" ORDER BY {col} {direction}"


def _sort_rows(rows, sort_by, sort_dir, allow_keys, default_key):
    """Post-query stable sort for Python-computed columns (e.g. margin_pct)
    that don't exist as SQL expressions."""
    key = sort_by if sort_by in allow_keys else default_key
    reverse = (sort_dir or "desc").lower() != "asc"
    return sorted(rows, key=lambda r: (r.get(key) is None, r.get(key)), reverse=reverse)


def _customer_gl_balances(company: str) -> dict:
    """Per-customer live receivable straight from the GL party ledger — the SAME
    source the Customer Center uses (list_customers_with_balances), so the report
    ties 1:1 to it.

    All-time, all vouchers (invoices, payments, JEs, advances, credit notes),
    signed (+ = customer owes us), in the receivable account's own currency, with
    the Payment-Entry account-currency drift correction applied. This is the real
    receivable — NOT SUM(Sales Invoice.outstanding_amount), which ignores
    unallocated payments / on-account credits and is date-bounded.
    """
    rows = frappe.db.sql(
        """
        SELECT party,
               SUM(debit_in_account_currency - credit_in_account_currency) AS balance_acc,
               MAX(account_currency) AS account_currency
        FROM `tabGL Entry`
        WHERE company = %(company)s AND party_type = 'Customer' AND is_cancelled = 0
        GROUP BY party
        """,
        {"company": company},
        as_dict=True,
    )
    # PE party-leg drift: GL stores credit_in_account_currency = base÷rate, which can
    # differ from the user-entered PE.paid_amount by sub-units. Correct it so the
    # report ties to the ledger exactly (single-leg-per-party PEs only).
    drift_rows = frappe.db.sql(
        """
        SELECT g.party AS party,
               SUM(
                 (CASE WHEN g.debit_in_account_currency > 0
                       THEN (CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
                                  WHEN g.account = pe.paid_to   THEN pe.received_amount
                                  ELSE 0 END)
                       ELSE -(CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
                                   WHEN g.account = pe.paid_to   THEN pe.received_amount
                                   ELSE 0 END)
                  END)
                 - (g.debit_in_account_currency - g.credit_in_account_currency)
               ) AS drift
        FROM `tabGL Entry` g
        JOIN `tabPayment Entry` pe ON pe.name = g.voucher_no
        JOIN (
          SELECT voucher_no FROM `tabGL Entry`
          WHERE voucher_type = 'Payment Entry' AND company = %(company)s
            AND party_type = 'Customer' AND is_cancelled = 0
          GROUP BY voucher_no HAVING COUNT(*) = 1
        ) single ON single.voucher_no = g.voucher_no
        WHERE g.voucher_type = 'Payment Entry' AND g.company = %(company)s
          AND g.party_type = 'Customer' AND g.is_cancelled = 0
        GROUP BY g.party
        """,
        {"company": company},
        as_dict=True,
    )
    drift = {r["party"]: flt(r["drift"]) for r in drift_rows}
    return {
        r["party"]: {
            "balance": flt(r["balance_acc"]) + drift.get(r["party"], 0.0),
            "currency": r["account_currency"],
        }
        for r in rows
    }


# ---------------------------------------------------------------------------
# Sales by Customer — Summary → Detail → Document (reference report)
# ---------------------------------------------------------------------------
_SALES_BY_CUSTOMER_SORT_KEYS = {"customer_name", "total", "invoice_count", "balance"}


@frappe.whitelist()
def sales_by_customer(
    company: str,
    from_date: str,
    to_date: str,
    customers=None,
    items=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    base_ccy = _base_currency(company)
    items = _decode_list(items)

    if items:
        # QuickBooks-style item filter: branch to a line-level query. "Sales"
        # becomes pre-tax net (SUM(sii.amount)); the invoice-level balance can't
        # be split by item, so the Balance column is dropped entirely.
        params = {"company": company, "from_date": start, "to_date": end}
        conds = _in_clause("si.customer", "customers", customers, params)
        conds += _in_clause("sii.item_code", "items", items, params)
        rows = frappe.db.sql(
            f"""
            SELECT si.customer, si.customer_name,
                   COUNT(DISTINCT si.name) AS invoice_count,
                   SUM(sii.amount) AS total
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.company = %(company)s AND si.docstatus = 1
              AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
              {conds}
            GROUP BY si.customer, si.customer_name
            {_order_by(sort_by, sort_dir, {"customer_name": "si.customer_name", "total": "total", "invoice_count": "invoice_count"}, "total")}
            LIMIT 1000
            """,
            params,
            as_dict=True,
        )
        for r in rows:
            r["invoice_count"] = int(r["invoice_count"] or 0)
            r["total"] = flt(r["total"])
        totals = {
            "invoice_count": sum(r["invoice_count"] for r in rows),
            "total": sum(r["total"] for r in rows),
        }
        columns = [
            {"key": "customer_name", "label": _("Customer"), "type": "text", "drill": "detail"},
            {"key": "invoice_count", "label": _("Invoices"), "type": "int", "align": "end"},
            {"key": "total", "label": _("Sales"), "type": "money", "align": "end"},
        ]
        meta = {
            "basis": _("Line-level (pre-tax) — item-filtered"),
            "currency": base_ccy,
            "from": str(start),
            "to": str(end),
            "note": _("Item filter active — figures are line-level (pre-tax); invoice balance/outstanding is not shown because it cannot be split by item."),
            "drill_report": "customer_balance_detail",
            "drill_param": "customer",
        }
        return _shape(columns, rows, totals, meta)

    # No item filter: existing header-level behaviour (grand_total + real GL balance).
    # Sales = period (accrual). Balance = the real GL receivable (all-time), joined
    # per customer so the report shows the SAME number as the Customer Center.
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("customer", "customers", customers, params)
    sales = frappe.db.sql(
        f"""
        SELECT customer, customer_name,
               COUNT(*) AS invoice_count,
               SUM(grand_total) AS total
        FROM `tabSales Invoice`
        WHERE company = %(company)s AND docstatus = 1
          AND posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY customer, customer_name
        ORDER BY total DESC, customer_name ASC
        LIMIT 1000
        """,
        params,
        as_dict=True,
    )
    bal = _customer_gl_balances(company)
    rows = []
    for r in sales:
        b = bal.get(r.customer) or {}
        rows.append({
            "customer": r.customer,
            "customer_name": r.customer_name,
            "invoice_count": int(r.invoice_count or 0),
            "total": flt(r.total),
            "balance": flt(b.get("balance") or 0),
            "currency": b.get("currency") or base_ccy,
        })
    rows = _sort_rows(rows, sort_by, sort_dir, _SALES_BY_CUSTOMER_SORT_KEYS, "total")
    totals = {
        "invoice_count": sum(r["invoice_count"] for r in rows),
        "total": sum(r["total"] for r in rows),
        "balance": sum(r["balance"] for r in rows),
    }
    columns = [
        {"key": "customer_name", "label": _("Customer"), "type": "text", "drill": "detail"},
        {"key": "invoice_count", "label": _("Invoices"), "type": "int", "align": "end"},
        {"key": "total", "label": _("Sales"), "type": "money", "align": "end"},
        {"key": "balance", "label": _("Balance"), "type": "money", "align": "end"},
    ]
    meta = {
        "basis": _("Accrual (invoice date)"),
        "currency": base_ccy,
        "from": str(start),
        "to": str(end),
        "note": _("Sales = selected period · Balance = current receivable (all-time, all vouchers — ties to the Customer Center). Click a customer to see the ledger behind the balance."),
        "drill_report": "customer_balance_detail",
        "drill_param": "customer",
    }
    return _shape(columns, rows, totals, meta)


_CUSTOMER_BALANCE_SUMMARY_SORT_KEYS = {"customer_name", "customer_group", "territory", "balance"}


@frappe.whitelist()
def customer_balance_summary(
    company: str,
    only_with_balance: int = 1,
    customers=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    """QuickBooks-style Customer Balance Summary: every customer's CURRENT
    receivable (all-time, all vouchers), period-independent. Same source as the
    Customer Center (list_customers_with_balances), so the numbers tie 1:1.
    """
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    from stabler.api.sales import list_customers_with_balances

    data = list_customers_with_balances(
        company, limit=100000, only_with_balance=int(only_with_balance or 0)
    )
    base_ccy = _base_currency(company)
    customer_set = set(_decode_list(customers))
    rows = []
    for r in data.get("rows", []):
        if customer_set and r.get("name") not in customer_set:
            continue
        rows.append({
            "customer": r.get("name"),
            "customer_name": r.get("customer_name"),
            "customer_group": r.get("customer_group"),
            "territory": r.get("territory"),
            "balance": flt(r.get("balance_acc") or 0),
            "currency": r.get("account_currency") or r.get("company_currency") or base_ccy,
        })
    rows = _sort_rows(rows, sort_by, sort_dir, _CUSTOMER_BALANCE_SUMMARY_SORT_KEYS, "balance")
    totals = {"balance": sum(r["balance"] for r in rows)}
    columns = [
        {"key": "customer_name", "label": _("Customer"), "type": "text", "drill": "detail"},
        {"key": "customer_group", "label": _("Group"), "type": "text"},
        {"key": "territory", "label": _("Territory"), "type": "text"},
        {"key": "balance", "label": _("Balance"), "type": "money", "align": "end"},
    ]
    meta = {
        "basis": _("Live receivable (all-time, all vouchers)"),
        "currency": base_ccy,
        "note": _("Current AR balance per customer — click a row to see the ledger behind the balance."),
        "drill_report": "customer_balance_detail",
        "drill_param": "customer",
    }
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def sales_by_customer_detail(company: str, from_date: str, to_date: str, customer: str) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    if not customer or not frappe.db.exists("Customer", customer):
        frappe.throw(_("Customer is required."), frappe.ValidationError)
    start, end = _sales_report_dates(from_date, to_date)
    rows = frappe.db.sql(
        """
        SELECT name, posting_date, due_date, currency, status,
               grand_total, outstanding_amount, is_return
        FROM `tabSales Invoice`
        WHERE company = %(company)s AND customer = %(customer)s AND docstatus = 1
          AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        ORDER BY posting_date DESC, name DESC
        LIMIT 1000
        """,
        {"company": company, "customer": customer, "from_date": start, "to_date": end},
        as_dict=True,
    )
    totals = {
        "grand_total": sum(flt(r.grand_total) for r in rows),
        "outstanding_amount": sum(flt(r.outstanding_amount) for r in rows),
    }
    columns = [
        {"key": "name", "label": _("Invoice"), "type": "text", "drill": "document", "doctype": "Sales Invoice"},
        {"key": "posting_date", "label": _("Date"), "type": "date"},
        {"key": "status", "label": _("Status"), "type": "text"},
        {"key": "grand_total", "label": _("Amount"), "type": "money", "align": "end"},
        {"key": "outstanding_amount", "label": _("Outstanding"), "type": "money", "align": "end"},
    ]
    meta = {
        "basis": _("Accrual (invoice date)"),
        "currency": _base_currency(company),
        "from": str(start),
        "to": str(end),
        "title": frappe.db.get_value("Customer", customer, "customer_name") or customer,
    }
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def customer_balance_detail(company: str, customer: str, from_date: str = None, to_date: str = None) -> dict:
    """Drill from the summary Balance → the full ledger that PRODUCES it.

    Every voucher behind the receivable (invoices, payments, journal entries),
    oldest→newest running balance ending exactly at the customer's Balance. Same
    source as the Customer Center ledger, so it reconciles 1:1. `from_date`/
    `to_date` are accepted (the summary passes them) but ignored — the ledger is
    all-time so the running balance ties to the all-time Balance.
    """
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    if not customer or not frappe.db.exists("Customer", customer):
        frappe.throw(_("Customer is required."), frappe.ValidationError)
    from stabler.api.sales import customer_ledger

    led = customer_ledger(company, customer)  # full history → reconciles to Balance
    ccy = led.get("account_currency") or _base_currency(company)
    run = flt(led.get("opening_acc") or 0)
    rows = []
    for e in led.get("entries", []):
        d = flt(e.get("debit_in_account_currency"))
        c = flt(e.get("credit_in_account_currency"))
        run += d - c
        # Skip pure FX-revaluation rows (base-only "Exchange Gain Or Loss") — zero
        # account-currency movement, so they don't change the running balance; they
        # would only add empty rows to this account-currency ledger.
        if abs(d) < 0.005 and abs(c) < 0.005:
            continue
        rows.append({
            "posting_date": e.get("posting_date"),
            "voucher_type": e.get("voucher_type"),
            "voucher_no": e.get("voucher_no"),
            "remarks": e.get("remarks"),
            "debit": d,
            "credit": c,
            "balance": run,
            "currency": ccy,
        })
    rows.reverse()  # newest first for display
    totals = {"balance": flt(led.get("closing_acc") or 0)}
    columns = [
        {"key": "posting_date", "label": _("Date"), "type": "date"},
        {"key": "voucher_no", "label": _("Voucher"), "type": "text"},
        {"key": "voucher_type", "label": _("Type"), "type": "text"},
        {"key": "debit", "label": _("Debit"), "type": "money", "align": "end"},
        {"key": "credit", "label": _("Credit"), "type": "money", "align": "end"},
        {"key": "balance", "label": _("Balance"), "type": "money", "align": "end"},
    ]
    meta = {
        "basis": _("Ledger — all vouchers (reconciles to the balance)"),
        "currency": ccy,
        "note": _("Every voucher behind the balance: invoices, payments, journal entries."),
        "title": frappe.db.get_value("Customer", customer, "customer_name") or customer,
    }
    return _shape(columns, rows, totals, meta)


# ---------------------------------------------------------------------------
# Sales by Item — Summary → Detail → Document
# ---------------------------------------------------------------------------
_ITEM_LINES_SORT_MAP = {
    "item_name": "sii.item_name",
    "item_group": "item_group",
    "qty": "qty",
    "revenue": "revenue",
    "invoice_count": "invoice_count",
}


def _item_lines(company, start, end, customers=None, items=None, sort_by=None, sort_dir=None):
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("si.customer", "customers", customers, params)
    conds += _in_clause("sii.item_code", "items", items, params)
    order = _order_by(sort_by, sort_dir, _ITEM_LINES_SORT_MAP, "revenue")
    return frappe.db.sql(
        f"""
        SELECT sii.item_code, sii.item_name,
               COALESCE(i.item_group, sii.item_group) AS item_group,
               SUM(sii.qty) AS qty,
               SUM(sii.amount) AS revenue,
               COUNT(DISTINCT si.name) AS invoice_count
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabItem` i ON i.name = sii.item_code
        WHERE si.company = %(company)s AND si.docstatus = 1
          AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY sii.item_code, sii.item_name, COALESCE(i.item_group, sii.item_group)
        {order}
        LIMIT 5000
        """,
        params,
        as_dict=True,
    )


@frappe.whitelist()
def sales_by_item(
    company: str,
    from_date: str,
    to_date: str,
    customers=None,
    items=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    rows = _item_lines(company, start, end, customers, items, sort_by, sort_dir)
    totals = {"qty": sum(flt(r.qty) for r in rows), "revenue": sum(flt(r.revenue) for r in rows)}
    columns = [
        {"key": "item_name", "label": _("Item"), "type": "text", "drill": "detail"},
        {"key": "item_group", "label": _("Group"), "type": "text"},
        {"key": "qty", "label": _("Qty"), "type": "number", "align": "end"},
        {"key": "revenue", "label": _("Sales"), "type": "money", "align": "end"},
        {"key": "invoice_count", "label": _("Invoices"), "type": "int", "align": "end"},
    ]
    meta = {
        "basis": _("Accrual (invoice date)"),
        "currency": _base_currency(company),
        "from": str(start),
        "to": str(end),
        "note": _("Submitted invoices; returns netted."),
        "drill_param": "item_code",
    }
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def sales_by_item_detail(company: str, from_date: str, to_date: str, item_code: str) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    if not item_code:
        frappe.throw(_("Item is required."), frappe.ValidationError)
    start, end = _sales_report_dates(from_date, to_date)
    rows = frappe.db.sql(
        """
        SELECT si.name, si.posting_date, si.customer_name,
               sii.qty, sii.rate, sii.amount
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.company = %(company)s AND si.docstatus = 1
          AND sii.item_code = %(item_code)s
          AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
        ORDER BY si.posting_date DESC, si.name DESC
        LIMIT 1000
        """,
        {"company": company, "item_code": item_code, "from_date": start, "to_date": end},
        as_dict=True,
    )
    totals = {"qty": sum(flt(r.qty) for r in rows), "amount": sum(flt(r.amount) for r in rows)}
    columns = [
        {"key": "name", "label": _("Invoice"), "type": "text", "drill": "document", "doctype": "Sales Invoice"},
        {"key": "posting_date", "label": _("Date"), "type": "date"},
        {"key": "customer_name", "label": _("Customer"), "type": "text"},
        {"key": "qty", "label": _("Qty"), "type": "number", "align": "end"},
        {"key": "rate", "label": _("Rate"), "type": "money", "align": "end"},
        {"key": "amount", "label": _("Amount"), "type": "money", "align": "end"},
    ]
    meta = {
        "currency": _base_currency(company),
        "title": frappe.db.get_value("Item", item_code, "item_name") or item_code,
    }
    return _shape(columns, rows, totals, meta)


# ---------------------------------------------------------------------------
# Item ABC analysis (Pareto by value concentration)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def item_abc(
    company: str,
    from_date: str,
    to_date: str,
    metric: str = "revenue",
    a_threshold: float = 80,
    b_threshold: float = 95,
    customers=None,
    items=None,
) -> dict:
    """Rank items descending by metric (revenue|qty), compute cumulative %, and
    classify A (≤a%), B (≤b%), C (rest). Drills into Sales by Item detail.

    Note: the ABC rank/cum_pct order is intrinsic to the report (always by
    metric) — it does not take a sort_by/sort_dir override the way plain
    summary reports do."""
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    metric = "qty" if metric == "qty" else "revenue"
    a_t, b_t = flt(a_threshold), flt(b_threshold)

    rows = _item_lines(company, start, end, customers, items)
    rows = [r for r in rows if flt(r[metric]) > 0]
    rows.sort(key=lambda r: -flt(r[metric]))
    grand = sum(flt(r[metric]) for r in rows) or 1.0

    cum = 0.0
    counts = {"A": 0, "B": 0, "C": 0}
    for i, r in enumerate(rows, start=1):
        val = flt(r[metric])
        cum += val
        cum_pct = round(cum / grand * 100, 1)
        r["rank"] = i
        r["pct"] = round(val / grand * 100, 1)
        r["cum_pct"] = cum_pct
        r["abc"] = "A" if cum_pct <= a_t else ("B" if cum_pct <= b_t else "C")
        counts[r["abc"]] += 1

    columns = [
        {"key": "rank", "label": "#", "type": "int", "align": "end"},
        {"key": "item_name", "label": _("Item"), "type": "text", "drill": "detail"},
        {"key": "abc", "label": _("Class"), "type": "badge"},
        {"key": metric, "label": _("Sales") if metric == "revenue" else _("Qty"),
         "type": "money" if metric == "revenue" else "number", "align": "end"},
        {"key": "pct", "label": _("% of total"), "type": "percent", "align": "end"},
        {"key": "cum_pct", "label": _("Cumulative %"), "type": "percent", "align": "end"},
    ]
    meta = {
        "currency": _base_currency(company),
        "from": str(start),
        "to": str(end),
        "note": _("A ≤ {0}%, B ≤ {1}%, C rest — by {2}. Submitted; returns netted.").format(
            int(a_t), int(b_t), _("revenue") if metric == "revenue" else _("quantity")
        ),
        "counts": counts,
        "drill_param": "item_code",
    }
    return _shape(columns, rows, {}, meta)


def _abc_classify(rows, metric, a_t, b_t):
    rows = [r for r in rows if flt(r[metric]) > 0]
    rows.sort(key=lambda r: -flt(r[metric]))
    grand = sum(flt(r[metric]) for r in rows) or 1.0
    cum = 0.0
    counts = {"A": 0, "B": 0, "C": 0}
    for i, r in enumerate(rows, start=1):
        v = flt(r[metric])
        cum += v
        cp = round(cum / grand * 100, 1)
        r["rank"] = i
        r["pct"] = round(v / grand * 100, 1)
        r["cum_pct"] = cp
        r["abc"] = "A" if cp <= a_t else ("B" if cp <= b_t else "C")
        counts[r["abc"]] += 1
    return rows, counts


@frappe.whitelist()
def customer_abc(
    company: str,
    from_date: str,
    to_date: str,
    a_threshold: float = 80,
    b_threshold: float = 95,
    customers=None,
    items=None,
) -> dict:
    """Pareto ranking of customers by revenue. Drills to Sales by Customer detail.

    Note: no sort_by/sort_dir here — ABC rank is always ordered by the metric
    (revenue) via _abc_classify, same as item_abc/supplier_abc."""
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    items = _decode_list(items)
    note = _("A ≤ {0}%, B ≤ {1}%, C rest — by revenue.").format(int(flt(a_threshold)), int(flt(b_threshold)))

    if items:
        # Item filter active: rank by line-level (pre-tax) revenue instead of grand_total.
        params = {"company": company, "from_date": start, "to_date": end}
        conds = _in_clause("si.customer", "customers", customers, params)
        conds += _in_clause("sii.item_code", "items", items, params)
        rows = frappe.db.sql(
            f"""
            SELECT si.customer, si.customer_name,
                   SUM(sii.amount) AS revenue,
                   COUNT(DISTINCT si.name) AS invoice_count
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.company = %(company)s AND si.docstatus = 1
              AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
              {conds}
            GROUP BY si.customer, si.customer_name
            """,
            params,
            as_dict=True,
        )
        note = _("Item filter active — figures are line-level (pre-tax). ") + note
    else:
        params = {"company": company, "from_date": start, "to_date": end}
        conds = _in_clause("customer", "customers", customers, params)
        rows = frappe.db.sql(
            f"""
            SELECT customer, customer_name, SUM(grand_total) AS revenue, COUNT(*) AS invoice_count
            FROM `tabSales Invoice`
            WHERE company = %(company)s AND docstatus = 1
              AND posting_date BETWEEN %(from_date)s AND %(to_date)s
              {conds}
            GROUP BY customer, customer_name
            """,
            params,
            as_dict=True,
        )
    rows, counts = _abc_classify(rows, "revenue", flt(a_threshold), flt(b_threshold))
    columns = [
        {"key": "rank", "label": "#", "type": "int", "align": "end"},
        {"key": "customer_name", "label": _("Customer"), "type": "text", "drill": "detail"},
        {"key": "abc", "label": _("Class"), "type": "badge"},
        {"key": "revenue", "label": _("Sales"), "type": "money", "align": "end"},
        {"key": "pct", "label": _("% of total"), "type": "percent", "align": "end"},
        {"key": "cum_pct", "label": _("Cumulative %"), "type": "percent", "align": "end"},
    ]
    meta = {
        "currency": _base_currency(company), "from": str(start), "to": str(end),
        "note": note,
        "counts": counts, "drill_param": "customer",
    }
    return _shape(columns, rows, {}, meta)


# ---------------------------------------------------------------------------
# Purchases by Supplier — Summary → Detail → Document; + Supplier ABC
# ---------------------------------------------------------------------------
_PURCHASES_BY_SUPPLIER_SORT_MAP = {
    "supplier_name": "supplier_name", "total": "total",
    "invoice_count": "invoice_count", "outstanding": "outstanding",
}
_PURCHASES_BY_SUPPLIER_ITEM_SORT_MAP = {
    "supplier_name": "supplier_name", "total": "total", "invoice_count": "invoice_count",
}


@frappe.whitelist()
def purchases_by_supplier(
    company: str,
    from_date: str,
    to_date: str,
    customers=None,
    items=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    base_ccy = _base_currency(company)
    items = _decode_list(items)

    if items:
        # QuickBooks-style item filter: branch to a line-level query. "Purchases"
        # becomes pre-tax net (SUM(pii.amount)); outstanding can't be split by
        # item, so that column is dropped entirely.
        params = {"company": company, "from_date": start, "to_date": end}
        conds = _in_clause("pi.supplier", "customers", customers, params)
        conds += _in_clause("pii.item_code", "items", items, params)
        rows = frappe.db.sql(
            f"""
            SELECT pi.supplier, pi.supplier_name,
                   COUNT(DISTINCT pi.name) AS invoice_count,
                   SUM(pii.amount) AS total
            FROM `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pi.company = %(company)s AND pi.docstatus = 1
              AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s
              {conds}
            GROUP BY pi.supplier, pi.supplier_name
            {_order_by(sort_by, sort_dir, _PURCHASES_BY_SUPPLIER_ITEM_SORT_MAP, "total")}
            LIMIT 1000
            """,
            params,
            as_dict=True,
        )
        for r in rows:
            r["invoice_count"] = int(r["invoice_count"] or 0)
            r["total"] = flt(r["total"])
        totals = {
            "invoice_count": sum(r["invoice_count"] for r in rows),
            "total": sum(r["total"] for r in rows),
        }
        columns = [
            {"key": "supplier_name", "label": _("Supplier"), "type": "text", "drill": "detail"},
            {"key": "invoice_count", "label": _("Bills"), "type": "int", "align": "end"},
            {"key": "total", "label": _("Purchases"), "type": "money", "align": "end"},
        ]
        meta = {
            "basis": _("Line-level (pre-tax) — item-filtered"),
            "currency": base_ccy,
            "from": str(start),
            "to": str(end),
            "note": _("Item filter active — figures are line-level (pre-tax); outstanding is not shown because it cannot be split by item."),
            "drill_param": "supplier",
        }
        return _shape(columns, rows, totals, meta)

    # No item filter: existing header-level behaviour (grand_total + outstanding_amount).
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("supplier", "customers", customers, params)
    rows = frappe.db.sql(
        f"""
        SELECT supplier, supplier_name, currency,
               COUNT(*) AS invoice_count,
               SUM(grand_total) AS total,
               SUM(outstanding_amount) AS outstanding
        FROM `tabPurchase Invoice`
        WHERE company = %(company)s AND docstatus = 1
          AND posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY supplier, supplier_name, currency
        {_order_by(sort_by, sort_dir, _PURCHASES_BY_SUPPLIER_SORT_MAP, "total")}
        LIMIT 1000
        """,
        params,
        as_dict=True,
    )
    totals = {
        "invoice_count": sum(int(r.invoice_count or 0) for r in rows),
        "total": sum(flt(r.total) for r in rows),
        "outstanding": sum(flt(r.outstanding) for r in rows),
    }
    columns = [
        {"key": "supplier_name", "label": _("Supplier"), "type": "text", "drill": "detail"},
        {"key": "invoice_count", "label": _("Bills"), "type": "int", "align": "end"},
        {"key": "total", "label": _("Purchases"), "type": "money", "align": "end"},
        {"key": "outstanding", "label": _("Outstanding"), "type": "money", "align": "end"},
    ]
    meta = {
        "basis": _("Accrual (bill date)"), "currency": base_ccy,
        "from": str(start), "to": str(end),
        "note": _("Submitted bills; returns netted."), "drill_param": "supplier",
    }
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def purchases_by_supplier_detail(company: str, from_date: str, to_date: str, supplier: str) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    if not supplier or not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier is required."), frappe.ValidationError)
    start, end = _sales_report_dates(from_date, to_date)
    rows = frappe.db.sql(
        """
        SELECT name, posting_date, currency, status, grand_total, outstanding_amount
        FROM `tabPurchase Invoice`
        WHERE company = %(company)s AND supplier = %(supplier)s AND docstatus = 1
          AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        ORDER BY posting_date DESC, name DESC
        LIMIT 1000
        """,
        {"company": company, "supplier": supplier, "from_date": start, "to_date": end},
        as_dict=True,
    )
    totals = {
        "grand_total": sum(flt(r.grand_total) for r in rows),
        "outstanding_amount": sum(flt(r.outstanding_amount) for r in rows),
    }
    columns = [
        {"key": "name", "label": _("Bill"), "type": "text", "drill": "document", "doctype": "Purchase Invoice"},
        {"key": "posting_date", "label": _("Date"), "type": "date"},
        {"key": "status", "label": _("Status"), "type": "text"},
        {"key": "grand_total", "label": _("Amount"), "type": "money", "align": "end"},
        {"key": "outstanding_amount", "label": _("Outstanding"), "type": "money", "align": "end"},
    ]
    meta = {
        "currency": _base_currency(company),
        "title": frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier,
    }
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def supplier_abc(
    company: str,
    from_date: str,
    to_date: str,
    a_threshold: float = 80,
    b_threshold: float = 95,
    customers=None,
    items=None,
) -> dict:
    """Pareto ranking of suppliers by spend. Drills to Purchases by Supplier detail.

    Note: no sort_by/sort_dir here — ABC rank is always ordered by the metric
    (spend) via _abc_classify, same as item_abc/customer_abc."""
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    items = _decode_list(items)
    note = _("A ≤ {0}%, B ≤ {1}%, C rest — by spend.").format(int(flt(a_threshold)), int(flt(b_threshold)))

    if items:
        # Item filter active: rank by line-level (pre-tax) spend instead of grand_total.
        params = {"company": company, "from_date": start, "to_date": end}
        conds = _in_clause("pi.supplier", "customers", customers, params)
        conds += _in_clause("pii.item_code", "items", items, params)
        rows = frappe.db.sql(
            f"""
            SELECT pi.supplier, pi.supplier_name,
                   SUM(pii.amount) AS spend,
                   COUNT(DISTINCT pi.name) AS invoice_count
            FROM `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pi.company = %(company)s AND pi.docstatus = 1
              AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s
              {conds}
            GROUP BY pi.supplier, pi.supplier_name
            """,
            params,
            as_dict=True,
        )
        note = _("Item filter active — figures are line-level (pre-tax). ") + note
    else:
        params = {"company": company, "from_date": start, "to_date": end}
        conds = _in_clause("supplier", "customers", customers, params)
        rows = frappe.db.sql(
            f"""
            SELECT supplier, supplier_name, SUM(grand_total) AS spend, COUNT(*) AS invoice_count
            FROM `tabPurchase Invoice`
            WHERE company = %(company)s AND docstatus = 1
              AND posting_date BETWEEN %(from_date)s AND %(to_date)s
              {conds}
            GROUP BY supplier, supplier_name
            """,
            params,
            as_dict=True,
        )
    rows, counts = _abc_classify(rows, "spend", flt(a_threshold), flt(b_threshold))
    columns = [
        {"key": "rank", "label": "#", "type": "int", "align": "end"},
        {"key": "supplier_name", "label": _("Supplier"), "type": "text", "drill": "detail"},
        {"key": "abc", "label": _("Class"), "type": "badge"},
        {"key": "spend", "label": _("Spend"), "type": "money", "align": "end"},
        {"key": "pct", "label": _("% of total"), "type": "percent", "align": "end"},
        {"key": "cum_pct", "label": _("Cumulative %"), "type": "percent", "align": "end"},
    ]
    meta = {
        "currency": _base_currency(company), "from": str(start), "to": str(end),
        "note": note,
        "counts": counts, "drill_param": "supplier",
    }
    return _shape(columns, rows, {}, meta)


# ---------------------------------------------------------------------------
# Inventory aging / slow-moving / dead stock — on-hand vs sales velocity
# ---------------------------------------------------------------------------
@frappe.whitelist()
def inventory_aging(
    company: str, from_date: str, to_date: str, items=None, sort_by=None, sort_dir=None
) -> dict:
    """Current on-hand value vs sales in the period. Flags Dead (no sales),
    Slow (>1 period of cover) and Moving stock. Drills to the item's sales."""
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    from frappe.utils import date_diff

    period_days = max(1, date_diff(end, start) + 1)

    params = {"company": company}
    item_filter = _in_clause("b.item_code", "items", items, params)
    onhand = frappe.db.sql(
        f"""
        SELECT b.item_code,
               i.item_name, i.item_group,
               SUM(b.actual_qty) AS on_hand,
               SUM(b.stock_value) AS value
        FROM `tabBin` b
        JOIN `tabWarehouse` w ON w.name = b.warehouse AND w.company = %(company)s
        LEFT JOIN `tabItem` i ON i.name = b.item_code
        WHERE 1=1 {item_filter}
        GROUP BY b.item_code, i.item_name, i.item_group
        HAVING SUM(b.actual_qty) > 0
        """,
        params,
        as_dict=True,
    )
    sold = dict(
        frappe.db.sql(
            """
            SELECT sii.item_code, SUM(sii.qty)
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.company = %(company)s AND si.docstatus = 1
              AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
            GROUP BY sii.item_code
            """,
            {"company": company, "from_date": start, "to_date": end},
        )
    )
    rows = []
    for r in onhand:
        s = flt(sold.get(r["item_code"], 0))
        r["sold"] = s
        if s <= 0:
            r["days_of_cover"] = None
            r["status"] = "Dead"
        else:
            cover = flt(r["on_hand"]) / (s / period_days)
            r["days_of_cover"] = round(cover, 0)
            r["status"] = "Slow" if cover > period_days else "Moving"
        rows.append(r)
    rows = _sort_rows(
        rows, sort_by, sort_dir,
        {"item_name", "item_group", "on_hand", "value", "sold", "days_of_cover"},
        "value",
    )

    totals = {"value": sum(flt(r["value"]) for r in rows)}
    columns = [
        {"key": "item_name", "label": _("Item"), "type": "text", "drill": "detail"},
        {"key": "item_group", "label": _("Group"), "type": "text"},
        {"key": "on_hand", "label": _("On hand"), "type": "number", "align": "end"},
        {"key": "value", "label": _("Value"), "type": "money", "align": "end"},
        {"key": "sold", "label": _("Sold"), "type": "number", "align": "end"},
        {"key": "days_of_cover", "label": _("Days of cover"), "type": "number", "align": "end"},
        {"key": "status", "label": _("Status"), "type": "badge"},
    ]
    meta = {
        "currency": _base_currency(company), "from": str(start), "to": str(end),
        "note": _("On-hand value vs {0}-day sales. Dead = no sales in period.").format(period_days),
        "drill_param": "item_code",
    }
    return _shape(columns, rows, totals, meta)


# ---------------------------------------------------------------------------
# Batch expiry — perishable stock at risk (ice-cream critical)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def inventory_expiry(company: str, horizon_days: int = 60, items=None) -> dict:
    """On-hand batches with their expiry, flagged Expired / Expiring (≤horizon) /
    OK. Returns empty with a note if batch tracking isn't enabled.

    Note: always ordered by expiry_date ASC (soonest-expiring first) — this is
    intrinsic to the report, like item_abc/customer_abc, and does not take a
    sort_by/sort_dir override."""
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    from frappe.utils import date_diff, nowdate

    columns = [
        {"key": "batch_no", "label": _("Batch"), "type": "text"},
        {"key": "item_name", "label": _("Item"), "type": "text"},
        {"key": "expiry_date", "label": _("Expiry"), "type": "date"},
        {"key": "days_to_expiry", "label": _("Days left"), "type": "int", "align": "end"},
        {"key": "qty", "label": _("On hand"), "type": "number", "align": "end"},
        {"key": "value", "label": _("Value"), "type": "money", "align": "end"},
        {"key": "status", "label": _("Status"), "type": "badge"},
    ]
    base = {"currency": _base_currency(company)}
    if not frappe.db.exists("DocType", "Batch") or not frappe.get_meta("Batch").has_field("expiry_date"):
        return _shape(columns, [], {}, {**base, "note": _("Batch tracking is not enabled.")})

    horizon = int(horizon_days or 60)
    params = {"company": company}
    item_filter = _in_clause("sle.item_code", "items", items, params)
    rows = frappe.db.sql(
        f"""
        SELECT sle.batch_no, sle.item_code,
               i.item_name, i.valuation_rate,
               bt.expiry_date,
               SUM(sle.actual_qty) AS qty
        FROM `tabStock Ledger Entry` sle
        JOIN `tabBatch` bt ON bt.name = sle.batch_no
        LEFT JOIN `tabItem` i ON i.name = sle.item_code
        WHERE sle.company = %(company)s
          AND sle.batch_no IS NOT NULL AND sle.batch_no != ''
          AND bt.expiry_date IS NOT NULL
          {item_filter}
        GROUP BY sle.batch_no, sle.item_code, i.item_name, i.valuation_rate, bt.expiry_date
        HAVING SUM(sle.actual_qty) > 0
        ORDER BY bt.expiry_date ASC
        LIMIT 2000
        """,
        params,
        as_dict=True,
    )
    today = nowdate()
    out = []
    for r in rows:
        d = date_diff(r["expiry_date"], today)
        r["days_to_expiry"] = d
        r["value"] = round(flt(r["qty"]) * flt(r.get("valuation_rate")), 2)
        r["status"] = "Expired" if d < 0 else ("Expiring" if d <= horizon else "OK")
        r.pop("valuation_rate", None)
        out.append(r)
    totals = {"value": sum(flt(r["value"]) for r in out)}
    meta = {
        **base,
        "note": _("Batches expiring within {0} days are flagged. Value at item valuation rate.").format(horizon),
    }
    return _shape(columns, out, totals, meta)


# ---------------------------------------------------------------------------
# Gross margin — revenue − COGS. COGS = line incoming_rate (actual buying rate
# at sale) falling back to the item's moving-average valuation. Lines with no
# cost are counted and surfaced, so margins are never silently overstated.
# ---------------------------------------------------------------------------
def _cost_expr() -> str:
    has_incoming = frappe.get_meta("Sales Invoice Item").has_field("incoming_rate")
    if has_incoming:
        return "COALESCE(NULLIF(sii.incoming_rate, 0), i.valuation_rate, 0)"
    return "COALESCE(i.valuation_rate, 0)"


def _margin_rows(rows):
    for r in rows:
        rev = flt(r["revenue"])
        cogs = flt(r["cogs"])
        r["margin"] = round(rev - cogs, 2)
        r["margin_pct"] = round((rev - cogs) / rev * 100, 1) if rev else 0
    return rows


def _margin_meta(company, start, end, zero_cost):
    note = _("Revenue − COGS (line buying rate, fallback item valuation). Submitted; returns netted.")
    if zero_cost:
        note += " " + _("⚠ {0} line(s) had no cost — verify item valuation; margin may be overstated.").format(zero_cost)
    return {"currency": _base_currency(company), "from": str(start), "to": str(end), "note": note}


_MARGIN_SORT_KEYS = {"revenue", "cogs", "margin", "margin_pct", "qty"}
_MARGIN_ITEM_SORT_KEYS = _MARGIN_SORT_KEYS | {"item_name", "item_group"}
_MARGIN_CUSTOMER_SORT_KEYS = _MARGIN_SORT_KEYS | {"customer_name", "invoice_count"}


@frappe.whitelist()
def gross_margin_by_item(
    company: str,
    from_date: str,
    to_date: str,
    customers=None,
    items=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    cost = _cost_expr()
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("si.customer", "customers", customers, params)
    conds += _in_clause("sii.item_code", "items", items, params)
    rows = frappe.db.sql(
        f"""
        SELECT sii.item_code, sii.item_name,
               COALESCE(i.item_group, sii.item_group) AS item_group,
               SUM(sii.qty) AS qty,
               SUM(sii.amount) AS revenue,
               SUM(sii.qty * {cost}) AS cogs,
               SUM(CASE WHEN {cost} = 0 THEN 1 ELSE 0 END) AS zero_cost
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabItem` i ON i.name = sii.item_code
        WHERE si.company = %(company)s AND si.docstatus = 1
          AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY sii.item_code, sii.item_name, COALESCE(i.item_group, sii.item_group)
        ORDER BY (SUM(sii.amount) - SUM(sii.qty * {cost})) DESC
        LIMIT 5000
        """,
        params,
        as_dict=True,
    )
    _margin_rows(rows)
    # margin_pct is Python-computed, not a SQL expression — sort happens after the query.
    rows = _sort_rows(rows, sort_by, sort_dir, _MARGIN_ITEM_SORT_KEYS, "margin")
    zero_cost = sum(int(r.get("zero_cost") or 0) for r in rows)
    totals = {
        "revenue": sum(flt(r["revenue"]) for r in rows),
        "cogs": sum(flt(r["cogs"]) for r in rows),
        "margin": sum(flt(r["margin"]) for r in rows),
    }
    columns = [
        {"key": "item_name", "label": _("Item"), "type": "text", "drill": "detail"},
        {"key": "item_group", "label": _("Group"), "type": "text"},
        {"key": "qty", "label": _("Qty"), "type": "number", "align": "end"},
        {"key": "revenue", "label": _("Sales"), "type": "money", "align": "end"},
        {"key": "cogs", "label": _("COGS"), "type": "money", "align": "end"},
        {"key": "margin", "label": _("Margin"), "type": "money", "align": "end"},
        {"key": "margin_pct", "label": _("Margin %"), "type": "percent", "align": "end"},
    ]
    meta = {**_margin_meta(company, start, end, zero_cost), "drill_param": "item_code"}
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def gross_margin_by_customer(
    company: str,
    from_date: str,
    to_date: str,
    customers=None,
    items=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    cost = _cost_expr()
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("si.customer", "customers", customers, params)
    conds += _in_clause("sii.item_code", "items", items, params)
    rows = frappe.db.sql(
        f"""
        SELECT si.customer, si.customer_name,
               COUNT(DISTINCT si.name) AS invoice_count,
               SUM(sii.amount) AS revenue,
               SUM(sii.qty * {cost}) AS cogs,
               SUM(CASE WHEN {cost} = 0 THEN 1 ELSE 0 END) AS zero_cost
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabItem` i ON i.name = sii.item_code
        WHERE si.company = %(company)s AND si.docstatus = 1
          AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY si.customer, si.customer_name
        ORDER BY (SUM(sii.amount) - SUM(sii.qty * {cost})) DESC
        LIMIT 2000
        """,
        params,
        as_dict=True,
    )
    _margin_rows(rows)
    # margin_pct is Python-computed, not a SQL expression — sort happens after the query.
    rows = _sort_rows(rows, sort_by, sort_dir, _MARGIN_CUSTOMER_SORT_KEYS, "margin")
    zero_cost = sum(int(r.get("zero_cost") or 0) for r in rows)
    totals = {
        "revenue": sum(flt(r["revenue"]) for r in rows),
        "cogs": sum(flt(r["cogs"]) for r in rows),
        "margin": sum(flt(r["margin"]) for r in rows),
    }
    columns = [
        {"key": "customer_name", "label": _("Customer"), "type": "text", "drill": "detail"},
        {"key": "invoice_count", "label": _("Invoices"), "type": "int", "align": "end"},
        {"key": "revenue", "label": _("Sales"), "type": "money", "align": "end"},
        {"key": "cogs", "label": _("COGS"), "type": "money", "align": "end"},
        {"key": "margin", "label": _("Margin"), "type": "money", "align": "end"},
        {"key": "margin_pct", "label": _("Margin %"), "type": "percent", "align": "end"},
    ]
    meta = {**_margin_meta(company, start, end, zero_cost), "drill_param": "customer"}
    return _shape(columns, rows, totals, meta)


_SALES_BY_SALESPERSON_SORT_MAP = {
    "sales_person": "sales_person", "currency": "si.currency",
    "total": "total", "invoice_count": "invoice_count",
}


@frappe.whitelist()
def sales_by_salesperson(
    company: str,
    from_date: str,
    to_date: str,
    customers=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("si.customer", "customers", customers, params)
    rows = frappe.db.sql(
        f"""
        SELECT COALESCE(st.sales_person, 'Unassigned') AS sales_person,
               si.currency,
               SUM(CASE
                   WHEN st.sales_person IS NULL THEN si.grand_total
                   ELSE si.grand_total * COALESCE(st.allocated_percentage, 100) / 100
               END) AS total,
               COUNT(DISTINCT si.name) AS invoice_count
        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Team` st ON st.parent = si.name AND st.parenttype = 'Sales Invoice'
        WHERE si.company = %(company)s
          AND si.docstatus = 1
          AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY COALESCE(st.sales_person, 'Unassigned'), si.currency
        {_order_by(sort_by, sort_dir, _SALES_BY_SALESPERSON_SORT_MAP, "total")}
        LIMIT 500
        """,
        params,
        as_dict=True,
    )
    totals = {
        "total": sum(flt(r.total) for r in rows),
        "invoice_count": sum(flt(r.invoice_count) for r in rows),
    }
    columns = [
        {"key": "sales_person", "label": _("Salesperson"), "type": "text"},
        {"key": "currency", "label": _("Currency"), "type": "text"},
        {"key": "total", "label": _("Total"), "type": "money", "align": "end"},
        {"key": "invoice_count", "label": _("Invoices"), "type": "int", "align": "end"},
    ]
    meta = {
        "basis": "posting_date",
        "currency": _base_currency(company),
        "from": start,
        "to": end,
        "note": _(
            "Submitted Sales Invoices only. Revenue allocated by Sales Team percentage; "
            "unassigned invoices credited in full to 'Unassigned'."
        ),
    }
    return _shape(columns, rows, totals, meta)


_SALES_ORDERS_SORT_MAP = {
    "customer_name": "customer_name", "currency": "currency",
    "order_count": "order_count", "booked": "booked",
    "to_deliver": "to_deliver", "to_bill": "to_bill",
}


@frappe.whitelist()
def sales_orders(
    company: str,
    from_date: str,
    to_date: str,
    customers=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("customer", "customers", customers, params)
    rows = frappe.db.sql(
        f"""
        SELECT customer, customer_name, currency,
               COUNT(*) AS order_count,
               SUM(grand_total) AS booked,
               SUM(grand_total * (100 - COALESCE(per_delivered, 0)) / 100) AS to_deliver,
               SUM(grand_total * (100 - COALESCE(per_billed, 0)) / 100) AS to_bill
        FROM `tabSales Order`
        WHERE company = %(company)s
          AND docstatus = 1
          AND transaction_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY customer, customer_name, currency
        {_order_by(sort_by, sort_dir, _SALES_ORDERS_SORT_MAP, "booked")}
        LIMIT 500
        """,
        params,
        as_dict=True,
    )
    totals = {
        "order_count": sum(flt(r.order_count) for r in rows),
        "booked": sum(flt(r.booked) for r in rows),
        "to_deliver": sum(flt(r.to_deliver) for r in rows),
        "to_bill": sum(flt(r.to_bill) for r in rows),
    }
    columns = [
        {"key": "customer_name", "label": _("Customer"), "type": "text"},
        {"key": "currency", "label": _("Currency"), "type": "text"},
        {"key": "order_count", "label": _("Orders"), "type": "int", "align": "end"},
        {"key": "booked", "label": _("Booked"), "type": "money", "align": "end"},
        {"key": "to_deliver", "label": _("To Deliver"), "type": "money", "align": "end"},
        {"key": "to_bill", "label": _("To Bill"), "type": "money", "align": "end"},
    ]
    meta = {
        "basis": "transaction_date",
        "currency": _base_currency(company),
        "from": start,
        "to": end,
        "note": _("Submitted Sales Orders only — booked (committed) value, not invoiced revenue."),
    }
    return _shape(columns, rows, totals, meta)


_SALES_TREND_SORT_MAP = {
    "period": "period", "currency": "si.currency",
    "total": "total", "outstanding": "outstanding", "invoice_count": "invoice_count",
}


@frappe.whitelist()
def sales_trend(
    company: str,
    from_date: str,
    to_date: str,
    granularity: str = "month",
    customers=None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    start, end = _sales_report_dates(from_date, to_date)
    period_expr = _sales_report_period_expr(granularity)
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("si.customer", "customers", customers, params)
    rows = frappe.db.sql(
        f"""
        SELECT {period_expr} AS period,
               si.currency,
               SUM(si.grand_total) AS total,
               SUM(si.outstanding_amount) AS outstanding,
               COUNT(*) AS invoice_count
        FROM `tabSales Invoice` si
        WHERE si.company = %(company)s
          AND si.docstatus = 1
          AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY {period_expr}, si.currency
        {_order_by(sort_by, sort_dir, _SALES_TREND_SORT_MAP, "period", default_dir="asc")}
        """,
        params,
        as_dict=True,
    )
    totals = {
        "total": sum(flt(r.total) for r in rows),
        "outstanding": sum(flt(r.outstanding) for r in rows),
        "invoice_count": sum(flt(r.invoice_count) for r in rows),
    }
    columns = [
        {"key": "period", "label": _("Period"), "type": "text"},
        {"key": "currency", "label": _("Currency"), "type": "text"},
        {"key": "total", "label": _("Total"), "type": "money", "align": "end"},
        {"key": "outstanding", "label": _("Outstanding"), "type": "money", "align": "end"},
        {"key": "invoice_count", "label": _("Invoices"), "type": "int", "align": "end"},
    ]
    meta = {
        "basis": "posting_date",
        "currency": _base_currency(company),
        "from": start,
        "to": end,
        "note": _("Submitted Sales Invoices only, grouped by %s.")
        % (_("day") if granularity == "day" else _("month")),
    }
    return _shape(columns, rows, totals, meta)
