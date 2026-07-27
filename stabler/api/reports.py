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
from frappe import _
from frappe.utils import flt

from stabler.api._common import _require_company
from stabler.api._money import money_epsilon
from stabler.api.approvals import _assert_company_scope
from stabler.api.organization import module_map_for
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


def _customer_gl_balances(company: str, as_of: str | None = None) -> dict:
    """Per-customer receivable straight from the GL party ledger — the SAME source
    the Customer Center uses (list_customers_with_balances), so the report ties to it.

    All vouchers (invoices, payments, JEs, advances, credit notes), signed
    (+ = customer owes us), in the receivable account's own currency, with the
    Payment-Entry account-currency drift correction applied. When `as_of` is given
    the balance is computed AS OF that date (posting_date <= as_of) — a QuickBooks
    style historical balance that changes with the report's To date; otherwise it is
    the all-time current receivable.
    """
    date_cond = " AND posting_date <= %(as_of)s" if as_of else ""
    g_date_cond = " AND g.posting_date <= %(as_of)s" if as_of else ""
    params = {"company": company}
    if as_of:
        params["as_of"] = as_of
    rows = frappe.db.sql(
        f"""
        SELECT party,
               SUM(debit_in_account_currency - credit_in_account_currency) AS balance_acc,
               MAX(account_currency) AS account_currency
        FROM `tabGL Entry`
        WHERE company = %(company)s AND party_type = 'Customer' AND is_cancelled = 0{date_cond}
        GROUP BY party
        """,
        params,
        as_dict=True,
    )
    # PE party-leg drift: GL stores credit_in_account_currency = base÷rate, which can
    # differ from the user-entered PE.paid_amount by sub-units. Correct it so the
    # report ties to the ledger exactly (single-leg-per-party PEs only).
    drift_rows = frappe.db.sql(
        f"""
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
          AND g.party_type = 'Customer' AND g.is_cancelled = 0{g_date_cond}
        GROUP BY g.party
        """,
        params,
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


def _supplier_gl_balances(company: str, as_of: str | None = None) -> dict:
    """Per-supplier payable from the GL party ledger (+ = we owe the supplier), in
    the account's own currency. All-time by default; when `as_of` is given the
    balance is computed AS OF that date (posting_date <= as_of) — QuickBooks-style.
    (No PE sub-unit drift correction here — it's a material-level payable balance.)
    """
    date_cond = " AND posting_date <= %(as_of)s" if as_of else ""
    params = {"company": company}
    if as_of:
        params["as_of"] = as_of
    rows = frappe.db.sql(
        f"""
        SELECT party,
               SUM(credit_in_account_currency - debit_in_account_currency) AS balance_acc,
               MAX(account_currency) AS account_currency
        FROM `tabGL Entry`
        WHERE company = %(company)s AND party_type = 'Supplier' AND is_cancelled = 0{date_cond}
        GROUP BY party
        """,
        params,
        as_dict=True,
    )
    return {
        r["party"]: {"balance": flt(r["balance_acc"]), "currency": r["account_currency"]}
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
    conds = _in_clause("si.customer", "customers", customers, params)
    # Join Customer for the CANONICAL name and GROUP BY the customer id, so a renamed
    # customer (old invoices carry the old customer_name) collapses to ONE row instead
    # of splitting into duplicates that each show the same party balance.
    sales = frappe.db.sql(
        f"""
        SELECT si.customer AS customer, c.customer_name AS customer_name,
               COUNT(*) AS invoice_count,
               SUM(si.grand_total) AS total
        FROM `tabSales Invoice` si
        JOIN `tabCustomer` c ON c.name = si.customer
        WHERE si.company = %(company)s AND si.docstatus = 1
          AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY si.customer, c.customer_name
        ORDER BY total DESC, customer_name ASC
        LIMIT 1000
        """,
        params,
        as_dict=True,
    )
    # Balance AS OF the report's To date (QuickBooks-style) — changes with the date.
    bal = _customer_gl_balances(company, as_of=end)
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
        "note": _("Sales = selected period · Balance = receivable as of the To date (changes with the date, QuickBooks-style). Click a customer to see the ledger behind the balance."),
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
def agreement_receivables(
    company: str,
    only_with_balance: int = 1,
    customers=None,
    agreements=None,
) -> dict:
    """Live customer receivables grouped by native ERPNext Contract.

    Submitted Sales Invoices remain the financial source of truth. The Contract
    link is an allocation dimension only; payments reduce the same invoice
    outstanding amount automatically. Unlinked invoices are returned separately
    so they cannot silently disappear from the customer balance.
    """
    _require_company(company)
    _assert_company_scope(company)
    if not module_map_for(company).get("agreements"):
        frappe.throw(_("Agreement management is not enabled for {0}.").format(company), frappe.PermissionError)

    customer_values = _decode_list(customers)
    agreement_values = _decode_list(agreements)
    params = {"company": company}
    filters = ["si.company = %(company)s", "si.docstatus = 1"]
    if customer_values:
        params["customers"] = tuple(customer_values)
        filters.append("si.customer IN %(customers)s")
    if agreement_values:
        params["agreements"] = tuple(agreement_values)
        filters.append("si.custom_agreement IN %(agreements)s")
    if int(only_with_balance or 0):
        filters.append("ABS(si.outstanding_amount) > 0.0001")

    rows = frappe.db.sql(
        f"""
        SELECT
            si.customer,
            si.customer_name,
            si.custom_agreement AS agreement,
            COALESCE(ct.custom_agreement_no, '') AS agreement_no,
            COALESCE(ct.custom_original_currency, si.currency) AS agreement_currency,
            si.currency,
            COUNT(DISTINCT si.name) AS invoice_count,
            SUM(si.outstanding_amount) AS balance,
            MAX(si.due_date) AS latest_due_date
        FROM `tabSales Invoice` si
        LEFT JOIN `tabContract` ct ON ct.name = si.custom_agreement
        WHERE {' AND '.join(filters)}
        GROUP BY si.customer, si.customer_name, si.custom_agreement,
                 ct.custom_agreement_no, ct.custom_original_currency, si.currency
        HAVING ABS(SUM(si.outstanding_amount)) > 0.0001
            OR %(include_zero)s = 1
        -- Rank by the base-currency value so a 1M UZS row does not outrank a
        -- 100k USD row. This is a sort key only; it is never selected or shown
        -- (CLAUDE.md: amounts render in their original transaction currency).
        ORDER BY SUM(si.outstanding_amount * si.conversion_rate) DESC,
                 si.customer_name ASC, agreement_no ASC
        LIMIT 5000
        """,
        {**params, "include_zero": 0 if int(only_with_balance or 0) else 1},
        as_dict=True,
    )
    for row in rows:
        row["agreement_no"] = row.get("agreement_no") or _("Unlinked")
        row["invoice_count"] = int(row.get("invoice_count") or 0)
        row["balance"] = flt(row.get("balance"))

    columns = [
        {"key": "customer_name", "label": _("Customer"), "type": "text"},
        {"key": "agreement_no", "label": _("Agreement"), "type": "text"},
        {"key": "agreement_currency", "label": _("Currency"), "type": "text"},
        {"key": "invoice_count", "label": _("Invoices"), "type": "int", "align": "end"},
        {"key": "balance", "label": _("Outstanding"), "type": "money", "align": "end"},
        {"key": "latest_due_date", "label": _("Latest due date"), "type": "date"},
    ]
    return _shape(
        columns,
        rows,
        {
            "invoice_count": sum(row["invoice_count"] for row in rows),
            "balance": sum(row["balance"] for row in rows),
        },
        {
            "basis": _("Submitted Sales Invoices, live outstanding balance"),
            "currency": _base_currency(company),
            "note": _("Grouped by Contract. Unlinked invoices are shown separately; transaction and base currency are never mixed."),
            "drill_report": "customer_balance_detail",
            "drill_param": "customer",
        },
    )


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
    eps = money_epsilon(ccy)
    run = flt(led.get("opening_acc") or 0)
    rows = []
    for e in led.get("entries", []):
        d = flt(e.get("debit_in_account_currency"))
        c = flt(e.get("credit_in_account_currency"))
        run += d - c
        # Skip pure FX-revaluation rows (base-only "Exchange Gain Or Loss") — zero
        # account-currency movement, so they don't change the running balance; they
        # would only add empty rows to this account-currency ledger.
        if abs(d) < eps and abs(c) < eps:
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

    # No item filter: Purchases = period (accrual); Balance = real GL payable AS OF
    # the To date (QuickBooks-style), consistent with Sales by Customer. Join Supplier
    # for the canonical name + GROUP BY supplier id so renamed suppliers don't split.
    params = {"company": company, "from_date": start, "to_date": end}
    conds = _in_clause("pi.supplier", "customers", customers, params)
    purch = frappe.db.sql(
        f"""
        SELECT pi.supplier AS supplier, s.supplier_name AS supplier_name,
               COUNT(*) AS invoice_count,
               SUM(pi.grand_total) AS total
        FROM `tabPurchase Invoice` pi
        JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE pi.company = %(company)s AND pi.docstatus = 1
          AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {conds}
        GROUP BY pi.supplier, s.supplier_name
        ORDER BY total DESC, supplier_name ASC
        LIMIT 1000
        """,
        params,
        as_dict=True,
    )
    bal = _supplier_gl_balances(company, as_of=end)
    rows = []
    for r in purch:
        b = bal.get(r.supplier) or {}
        rows.append({
            "supplier": r.supplier,
            "supplier_name": r.supplier_name,
            "invoice_count": int(r.invoice_count or 0),
            "total": flt(r.total),
            "balance": flt(b.get("balance") or 0),
            "currency": b.get("currency") or base_ccy,
        })
    rows = _sort_rows(rows, sort_by, sort_dir, {"supplier_name", "total", "invoice_count", "balance"}, "total")
    totals = {
        "invoice_count": sum(r["invoice_count"] for r in rows),
        "total": sum(r["total"] for r in rows),
        "balance": sum(r["balance"] for r in rows),
    }
    columns = [
        {"key": "supplier_name", "label": _("Supplier"), "type": "text", "drill": "detail"},
        {"key": "invoice_count", "label": _("Bills"), "type": "int", "align": "end"},
        {"key": "total", "label": _("Purchases"), "type": "money", "align": "end"},
        {"key": "balance", "label": _("Balance"), "type": "money", "align": "end"},
    ]
    meta = {
        "basis": _("Accrual (bill date)"), "currency": base_ccy,
        "from": str(start), "to": str(end),
        "note": _("Purchases = selected period · Balance = payable as of the To date (changes with the date). Click a supplier to see the bills."),
        "drill_param": "supplier",
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


# ---------------------------------------------------------------------------
# Ombor (Warehouse) — stock-movement reports
#
# Source table: `tabStock Ledger Entry` (the append-only stock ledger). Every
# report here is READ-ONLY: company-scoped (_assert_company_scope), gated on the
# caller holding "read" on Stock Ledger Entry, and built with fully parametric
# SQL — values are ALWAYS bound via %(name)s params, never spliced into the query
# string. No frappe.db.commit() (these are pure reads).
# ---------------------------------------------------------------------------


def _assert_can_read_stock_ledger() -> None:
    """Doctype-level read gate for the stock-movement reports.

    Company scope alone protects tenant isolation, but Stock Ledger Entry is
    sensitive inventory data — a user with no read access to it must not pull it
    through a report endpoint. Throw a PermissionError (403) when not permitted.
    """
    if not frappe.has_permission("Stock Ledger Entry", "read"):
        frappe.throw(_("Not permitted to read Stock Ledger Entry"), frappe.PermissionError)


@frappe.whitelist()
def stock_movement_summary(
    company: str,
    from_date: str,
    to_date: str,
    warehouse: str = "",
) -> dict:
    """Per-item opening/in/out/closing summary over a date window.

    Uses window functions to pin the opening (first SLE's balance-before) and
    closing (last SLE's balance-after) per item×warehouse, then buckets the
    movements by voucher type. `recon` surfaces any residual the buckets don't
    explain (should be ~0 when every movement is one of the tracked vouchers).
    """
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    _assert_can_read_stock_ledger()
    params = {
        "company": company,
        "from_date": from_date,
        "to_date": to_date,
        "warehouse": warehouse or "",
    }
    rows = frappe.db.sql(
        """
        WITH sle AS (
            SELECT item_code, warehouse, actual_qty, qty_after_transaction, voucher_type,
                ROW_NUMBER() OVER (PARTITION BY item_code, warehouse
                    ORDER BY posting_date, posting_time, creation) AS rn_asc,
                ROW_NUMBER() OVER (PARTITION BY item_code, warehouse
                    ORDER BY posting_date DESC, posting_time DESC, creation DESC) AS rn_desc
            FROM `tabStock Ledger Entry`
            WHERE is_cancelled = 0 AND company = %(company)s
                AND posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND (%(warehouse)s = '' OR warehouse = %(warehouse)s)
        ),
        bounds AS (
            SELECT item_code,
                SUM(CASE WHEN rn_asc = 1 THEN qty_after_transaction - actual_qty ELSE 0 END) AS opening,
                SUM(CASE WHEN rn_desc = 1 THEN qty_after_transaction ELSE 0 END) AS closing
            FROM sle GROUP BY item_code
        ),
        moves AS (
            SELECT item_code,
                SUM(CASE WHEN voucher_type = 'Stock Entry' AND actual_qty > 0 THEN actual_qty ELSE 0 END) AS se_in,
                SUM(CASE WHEN voucher_type = 'Purchase Invoice' AND actual_qty > 0 THEN actual_qty ELSE 0 END) AS pi_in,
                SUM(CASE WHEN voucher_type = 'Sales Invoice' AND actual_qty > 0 THEN actual_qty ELSE 0 END) AS cn_in,
                SUM(CASE WHEN voucher_type = 'Sales Invoice' AND actual_qty < 0 THEN -actual_qty ELSE 0 END) AS si_out
            FROM sle GROUP BY item_code
        )
        SELECT b.item_code, i.item_name,
            ROUND(b.opening, 2) opening, ROUND(m.se_in, 2) se_in, ROUND(m.pi_in, 2) pi_in,
            ROUND(m.cn_in, 2) cn_in, ROUND(m.si_out, 2) si_out,
            ROUND(b.closing - (b.opening + m.se_in + m.pi_in + m.cn_in - m.si_out), 2) recon,
            ROUND(b.closing, 2) closing
        FROM bounds b
        LEFT JOIN moves m ON m.item_code = b.item_code
        LEFT JOIN `tabItem` i ON i.name = b.item_code
        WHERE (m.se_in <> 0 OR m.pi_in <> 0 OR m.cn_in <> 0 OR m.si_out <> 0)
        ORDER BY i.item_name
        """,
        params,
        as_dict=True,
    )
    totals = {
        "opening": sum(flt(r.opening) for r in rows),
        "se_in": sum(flt(r.se_in) for r in rows),
        "pi_in": sum(flt(r.pi_in) for r in rows),
        "cn_in": sum(flt(r.cn_in) for r in rows),
        "si_out": sum(flt(r.si_out) for r in rows),
        "recon": sum(flt(r.recon) for r in rows),
        "closing": sum(flt(r.closing) for r in rows),
    }
    columns = [
        {"key": "item_code", "label": _("Item"), "type": "text"},
        {"key": "item_name", "label": _("Name"), "type": "text"},
        {"key": "opening", "label": _("Opening Balance"), "type": "number", "align": "end", "negRed": True},
        {"key": "se_in", "label": _("SE In"), "type": "number", "align": "end"},
        {"key": "pi_in", "label": _("PI In"), "type": "number", "align": "end"},
        {"key": "cn_in", "label": _("CN Return"), "type": "number", "align": "end"},
        {"key": "si_out", "label": _("SI Out"), "type": "number", "align": "end"},
        {"key": "recon", "label": _("Adjustment"), "type": "number", "align": "end", "negRed": True},
        {"key": "closing", "label": _("Closing Balance"), "type": "number", "align": "end", "negRed": True},
    ]
    meta = {
        "basis": "posting_date",
        "from": from_date,
        "to": to_date,
        "warehouse": warehouse or "",
    }
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def stock_daily_kpi(
    company: str,
    from_date: str,
    to_date: str,
    warehouse: str = "",
) -> dict:
    """Movement KPI rolled up by document type × direction (in / out / return).

    Collapses the ledger into a handful of KPI rows (Stock Entry in, Sales
    Invoice out, Credit-Note return, Purchase Invoice in) — count of lines and
    total absolute quantity per bucket.
    """
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    _assert_can_read_stock_ledger()
    params = {
        "company": company,
        "from_date": from_date,
        "to_date": to_date,
        "warehouse": warehouse or "",
    }
    rows = frappe.db.sql(
        """
        SELECT turi, yonalish, COUNT(*) cnt, ROUND(SUM(miqdor), 2) jami FROM (
            SELECT
                CASE WHEN voucher_type = 'Stock Entry' AND actual_qty > 0 THEN 'Stock Entry'
                     WHEN voucher_type = 'Sales Invoice' AND actual_qty < 0 THEN 'Sales Invoice'
                     WHEN voucher_type = 'Sales Invoice' AND actual_qty > 0 THEN 'Credit Note'
                     WHEN voucher_type = 'Purchase Invoice' AND actual_qty > 0 THEN 'Purchase Invoice'
                     ELSE 'Boshqa' END AS turi,
                CASE WHEN voucher_type = 'Sales Invoice' AND actual_qty < 0 THEN 'Chiqim'
                     WHEN voucher_type = 'Sales Invoice' AND actual_qty > 0 THEN 'Qaytish'
                     ELSE 'Kirim' END AS yonalish,
                ABS(actual_qty) miqdor
            FROM `tabStock Ledger Entry`
            WHERE is_cancelled = 0 AND company = %(company)s
                AND posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND (%(warehouse)s = '' OR warehouse = %(warehouse)s)
                AND voucher_type IN ('Stock Entry', 'Sales Invoice', 'Purchase Invoice')
        ) x WHERE turi <> 'Boshqa' GROUP BY turi, yonalish ORDER BY turi
        """,
        params,
        as_dict=True,
    )
    totals = {
        "cnt": sum(flt(r.cnt) for r in rows),
        "jami": sum(flt(r.jami) for r in rows),
    }
    columns = [
        {"key": "turi", "label": _("Document Type"), "type": "text"},
        {"key": "yonalish", "label": _("Direction"), "type": "text"},
        {"key": "cnt", "label": _("Count"), "type": "int", "align": "end"},
        {"key": "jami", "label": _("Quantity"), "type": "number", "align": "end"},
    ]
    meta = {
        "basis": "posting_date",
        "from": from_date,
        "to": to_date,
        "warehouse": warehouse or "",
    }
    return _shape(columns, rows, totals, meta)


@frappe.whitelist()
def stock_ledger_detail(
    company: str,
    from_date: str,
    to_date: str,
    warehouse: str = "",
    voucher_type: str = "",
    limit: int = 500,
) -> dict:
    """Raw stock-ledger lines for the window, most-recent first.

    Always LIMIT-bounded (default 500, hard cap 5000) so a wide date range can
    never stream an unbounded result set. The frontend links each voucher to its
    in-SPA document route (never the Frappe Desk).
    """
    _require_company(company)
    _assert_company_scope(company)  # tenant isolation: reject a foreign company arg
    _assert_can_read_stock_ledger()
    row_limit = min(max(int(limit or 500), 1), 5000)
    params = {
        "company": company,
        "from_date": from_date,
        "to_date": to_date,
        "warehouse": warehouse or "",
        "voucher_type": voucher_type or "",
        "limit": row_limit,
    }
    rows = frappe.db.sql(
        """
        SELECT posting_date, posting_time, item_code, warehouse, voucher_type, voucher_no,
            ROUND(actual_qty, 2) actual_qty, ROUND(qty_after_transaction, 2) qty_after
        FROM `tabStock Ledger Entry`
        WHERE is_cancelled = 0 AND company = %(company)s
            AND posting_date BETWEEN %(from_date)s AND %(to_date)s
            AND (%(warehouse)s = '' OR warehouse = %(warehouse)s)
            AND (%(voucher_type)s = '' OR voucher_type = %(voucher_type)s)
        ORDER BY posting_date DESC, posting_time DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    columns = [
        {"key": "posting_date", "label": _("Date"), "type": "date"},
        {"key": "item_code", "label": _("Item"), "type": "text"},
        {"key": "warehouse", "label": _("Warehouse"), "type": "text"},
        {"key": "voucher_type", "label": _("Voucher Type"), "type": "text"},
        {"key": "voucher_no", "label": _("Voucher No"), "type": "text", "drill": "document"},
        {"key": "actual_qty", "label": _("Qty"), "type": "number", "align": "end", "negRed": True},
        {"key": "qty_after", "label": _("Balance"), "type": "number", "align": "end"},
    ]
    meta = {
        "basis": "posting_date",
        "from": from_date,
        "to": to_date,
        "warehouse": warehouse or "",
        "voucher_type": voucher_type or "",
        "limit": row_limit,
        "row_count": len(rows),
    }
    return _shape(columns, rows, totals=None, meta=meta)


# ---------------------------------------------------------------------------
# 1. PI Progress Report (reports/pi-progress/)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_pi_progress_report(
    company: str,
    search: str | None = None,
    vendor: str | None = None,
    pi_group: str | None = None,
    status: str | None = None,
    sort_by: str = "-date",
) -> dict:
    """PI Progress Report — lifecycle tracking for each proforma invoice."""
    _require_company(company)
    _assert_company_scope(company)

    conditions = ["pi.company = %(company)s", "pi.status != 'CANCELLED'"]
    params = {"company": company}

    if search and search.strip():
        s = f"%{search.strip()}%"
        params["search"] = s
        conditions.append(
            "(pi.supplier_pi_ref LIKE %(search)s OR pi.name LIKE %(search)s OR pi.supplier LIKE %(search)s OR supp.supplier_name LIKE %(search)s OR pi.import_pi_group LIKE %(search)s)"
        )
    if vendor and vendor.strip():
        params["vendor"] = vendor.strip()
        conditions.append("pi.supplier = %(vendor)s")
    if pi_group and pi_group.strip():
        params["pi_group"] = pi_group.strip()
        conditions.append("pi.import_pi_group = %(pi_group)s")
    if status and status.strip():
        params["status"] = status.strip()
        conditions.append("pi.status = %(status)s")

    where_clause = " AND ".join(conditions)
    pis = frappe.db.sql(
        f"""
        SELECT pi.name, pi.supplier_pi_ref, pi.supplier, supp.supplier_name,
               pi.import_pi_group, pi.pi_date, pi.status, pi.currency,
               IFNULL(pi.agreed_total, 0) agreed_total,
               IFNULL(pi.docs_total, 0) docs_total,
               IFNULL(pi.cash_difference, 0) cash_difference,
               IFNULL(pi.advance_pct, 0) advance_pct
        FROM `tabProforma Invoice` pi
        LEFT JOIN `tabSupplier` supp ON supp.name = pi.supplier
        WHERE {where_clause}
        ORDER BY pi.pi_date DESC, pi.name DESC
        """,
        params,
        as_dict=True,
    )

    rows = []
    grand_agreed = 0.0
    grand_advance = 0.0
    grand_allocated = 0.0
    grand_70_paid = 0.0

    for pi in pis:
        pi_name = pi["name"]
        agreed_total = flt(pi["agreed_total"])
        docs_total = flt(pi["docs_total"])
        cash_diff = flt(pi["cash_difference"])

        # Fetch advance payments
        advances = frappe.db.sql(
            """
            SELECT name, paid_amount, mode_of_payment, posting_date
            FROM `tabPayment Entry`
            WHERE docstatus = 1 AND payment_type = 'Pay'
              AND (party = %(supplier)s)
              AND (custom_pi_ref = %(pi_name)s OR reference_no LIKE %(pi_ref)s)
            """,
            {"supplier": pi["supplier"], "pi_name": pi_name, "pi_ref": f"%{pi_name}%"},
            as_dict=True,
        )
        total_advance = sum(flt(a["paid_amount"]) for a in advances)
        advance_bank = total_advance * (flt(pi["advance_pct"]) / 100.0) if pi["advance_pct"] else total_advance
        advance_cash = total_advance - advance_bank
        advance_pct = (total_advance / agreed_total * 100.0) if agreed_total > 0 else flt(pi["advance_pct"])

        # Fetch linked CIs
        cis = frappe.db.get_all(
            "Commercial Invoice",
            filters={"supplier": pi["supplier"], "import_pi_group": pi["import_pi_group"]},
            fields=["name", "ci_number", "status", "agreed_total", "docs_total"],
        ) if pi["import_pi_group"] else frappe.db.sql(
            """
            SELECT DISTINCT ci.name, ci.ci_number, ci.status, ci.agreed_total, ci.docs_total
            FROM `tabCommercial Invoice` ci
            JOIN `tabCommercial Invoice PO Link` pol ON pol.commercial_invoice = ci.name
            WHERE pol.purchase_order = %(pi_name)s OR ci.import_pi_group = %(pi_group)s
            """,
            {"pi_name": pi_name, "pi_group": pi["import_pi_group"] or ""},
            as_dict=True,
        )

        ci_count = len(cis)
        total_allocated = sum(flt(c["agreed_total"]) for c in cis)
        allocation_pct = (total_allocated / total_advance * 100.0) if total_advance > 0 else 0.0

        # Fetch 70% payments on linked CIs
        total_70_paid = sum(flt(c["agreed_total"]) * 0.7 for c in cis if c["status"] in ("GATE_IN", "ON_BOARD", "IN_TRANSIT", "DISCHARGED", "AVAILABLE", "ARRIVED_AT_IRAN", "DELIVERED_TO_UZBEKISTAN", "CLOSED"))

        balance_amount = max(0.0, agreed_total - total_advance)
        pct_70 = (total_70_paid / balance_amount * 100.0) if balance_amount > 0 else 0.0
        overall_pct = min(100.0, (advance_pct * 0.4) + (min(100.0, allocation_pct) * 0.3) + (min(100.0, pct_70) * 0.3))

        grand_agreed += agreed_total
        grand_advance += total_advance
        grand_allocated += total_allocated
        grand_70_paid += total_70_paid

        rows.append({
            "pi_name": pi_name,
            "supplier_pi_ref": pi["supplier_pi_ref"] or pi_name,
            "vendor": pi["supplier"],
            "vendor_name": pi["supplier_name"] or pi["supplier"],
            "import_pi_group": pi["import_pi_group"] or "",
            "pi_date": str(pi["pi_date"]) if pi["pi_date"] else None,
            "status": pi["status"],
            "currency": pi["currency"] or "USD",
            "agreed_total": agreed_total,
            "docs_total": docs_total,
            "cash_difference": cash_diff,
            "advance_bank": advance_bank,
            "advance_cash": advance_cash,
            "total_advance": total_advance,
            "advance_pct": round(advance_pct, 1),
            "ci_count": ci_count,
            "total_allocated": total_allocated,
            "allocation_pct": round(allocation_pct, 1),
            "total_70_paid": total_70_paid,
            "overall_pct": round(overall_pct, 1),
        })

    # Python sort if specified
    if sort_by:
        reverse = sort_by.startswith("-")
        key = sort_by.lstrip("-")
        rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=reverse)

    grand_remaining = grand_agreed - grand_advance - grand_70_paid

    return {
        "rows": rows,
        "totals": {
            "pi_count": len(rows),
            "grand_agreed": grand_agreed,
            "grand_advance": grand_advance,
            "grand_allocated": grand_allocated,
            "grand_70_paid": grand_70_paid,
            "grand_remaining": grand_remaining,
        },
    }


# ---------------------------------------------------------------------------
# 2. PI Group Container Status Report (reports/pi-group-container-status/)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_pi_group_container_status_report(
    company: str,
    pi_group: str | None = None,
    vendor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
) -> dict:
    """PI Group Container Status Report — per-PIGroup planned FCL and container lifecycle counts."""
    _require_company(company)
    _assert_company_scope(company)

    conditions = ["pg.company = %(company)s"]
    params = {"company": company}

    if pi_group and pi_group.strip():
        params["pi_group"] = pi_group.strip()
        conditions.append("pg.name = %(pi_group)s")
    if vendor and vendor.strip():
        params["vendor"] = vendor.strip()
        conditions.append("pg.vendor = %(vendor)s")

    where_clause = " AND ".join(conditions)
    groups = frappe.db.sql(
        f"""
        SELECT pg.name, pg.group_title, pg.vendor, supp.supplier_name, pg.creation
        FROM `tabImport PI Group` pg
        LEFT JOIN `tabSupplier` supp ON supp.name = pg.vendor
        WHERE {where_clause}
        ORDER BY pg.creation DESC
        """,
        params,
        as_dict=True,
    )

    rows = []
    grand_buckets = {"ORIGIN": 0, "TRANSIT": 0, "DESTINATION": 0, "DELIVERED": 0}
    grand_fcl = 0.0
    grand_pending = 0.0
    grand_containers = 0
    grand_ci_count = 0
    grand_agreed_total = 0.0

    for g in groups:
        gid = g["name"]
        member_pis = frappe.db.get_all(
            "Proforma Invoice",
            filters={"import_pi_group": gid},
            fields=["name", "supplier_pi_ref", "pi_date", "status", "agreed_total"],
        )

        if not member_pis and pi_group:
            continue

        date_list = [p["pi_date"] for p in member_pis if p.get("pi_date")]
        date_min = str(min(date_list)) if date_list else None
        date_max = str(max(date_list)) if date_list else None

        planned_fcl = sum(
            flt(it.boxes / 1400.0) if (it.boxes and it.boxes > 500) else 1.0
            for p in member_pis
            for it in frappe.db.get_all("Proforma Invoice Item", filters={"parent": p["name"]}, fields=["boxes"])
        ) or len(member_pis)

        cis = frappe.db.get_all(
            "Commercial Invoice",
            filters={"import_pi_group": gid},
            fields=["name", "status", "agreed_total"],
        )
        ci_count = len(cis)

        containers = frappe.db.sql(
            """
            SELECT cnt.name, cnt.status, ci.status as ci_status
            FROM `tabImport Container` cnt
            JOIN `tabCommercial Invoice` ci ON ci.name = cnt.commercial_invoice
            WHERE ci.import_pi_group = %(gid)s
            """,
            {"gid": gid},
            as_dict=True,
        )

        buckets = {"ORIGIN": 0, "TRANSIT": 0, "DESTINATION": 0, "DELIVERED": 0}
        for cnt in containers:
            st = (cnt.get("ci_status") or cnt.get("status") or "").upper()
            if st in ("DRAFT", "BOOKED", "STUFFED", "GATE_IN", "ON_BOARD"):
                buckets["ORIGIN"] += 1
            elif st in ("IN_TRANSIT", "DISCHARGED", "AVAILABLE", "ARRIVED_AT_IRAN"):
                buckets["TRANSIT"] += 1
            elif st in ("CUSTOMS_CLEARANCE", "RELEASED"):
                buckets["DESTINATION"] += 1
            elif st in ("DELIVERED_TO_UZBEKISTAN", "DELIVERED", "CLOSED"):
                buckets["DELIVERED"] += 1

        container_total = len(containers)
        pending_containers = max(0.0, planned_fcl - container_total)
        agreed_total = sum(flt(p["agreed_total"]) for p in member_pis)
        pending_amount = max(0.0, agreed_total - sum(flt(c["agreed_total"]) for c in cis))

        for k in grand_buckets:
            grand_buckets[k] += buckets[k]
        grand_fcl += planned_fcl
        grand_pending += pending_containers
        grand_containers += container_total
        grand_ci_count += ci_count
        grand_agreed_total += agreed_total

        rows.append({
            "group_code": gid,
            "group_title": g["group_title"] or gid,
            "vendor_name": g["supplier_name"] or g["vendor"] or "—",
            "pi_count": len(member_pis),
            "ci_count": ci_count,
            "pis": [p["supplier_pi_ref"] or p["name"] for p in member_pis],
            "date_min": date_min,
            "date_max": date_max,
            "planned_fcl": round(planned_fcl, 1),
            "pending_containers": round(pending_containers, 1),
            "buckets": buckets,
            "container_total": container_total,
            "agreed_total": agreed_total,
            "pending_amount": pending_amount,
        })

    return {
        "rows": rows,
        "totals": {
            "group_count": len(rows),
            "grand_ci_count": grand_ci_count,
            "grand_fcl": round(grand_fcl, 1),
            "grand_pending": round(grand_pending, 1),
            "grand_buckets": grand_buckets,
            "grand_containers": grand_containers,
            "grand_agreed_total": grand_agreed_total,
        },
    }


# ---------------------------------------------------------------------------
# 3. Sales Detail Report (reports/sales-detail/)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_sales_detail_report(
    company: str,
    start_date: str | None = None,
    end_date: str | None = None,
    customer: str | None = None,
    product: str | None = None,
    currency: str | None = None,
    status: str | None = None,
    sort_by: str = "date",
) -> dict:
    """Sales detail report — data sourced from Sales Invoices & Line Items."""
    _require_company(company)
    _assert_company_scope(company)

    conditions = ["si.company = %(company)s", "si.docstatus = 1"]
    params = {"company": company}

    if start_date:
        params["start_date"] = start_date
        conditions.append("si.posting_date >= %(start_date)s")
    if end_date:
        params["end_date"] = end_date
        conditions.append("si.posting_date <= %(end_date)s")
    if customer and customer.strip():
        params["customer"] = customer.strip()
        conditions.append("si.customer = %(customer)s")
    if product and product.strip():
        params["product"] = product.strip()
        conditions.append("sii.item_code = %(product)s")
    if currency and currency.strip():
        params["currency"] = currency.strip()
        conditions.append("si.currency = %(currency)s")
    if status == "PAID":
        conditions.append("si.outstanding_amount <= 0")

    where_clause = " AND ".join(conditions)
    raw_rows = frappe.db.sql(
        f"""
        SELECT si.posting_date, si.name as invoice_number, si.customer,
               cust.customer_name, cust.custom_parent_customer,
               sii.item_code, item.item_name,
               IFNULL(sii.qty, 0) total_kg,
               IFNULL(sii.rate, 0) rate,
               IFNULL(sii.amount, 0) amount,
               si.currency
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabCustomer` cust ON cust.name = si.customer
        LEFT JOIN `tabItem` item ON item.name = sii.item_code
        WHERE {where_clause}
        ORDER BY si.posting_date DESC, si.name DESC
        """,
        params,
        as_dict=True,
    )

    rows = []
    total_sales = 0.0
    total_kg = 0.0
    total_boxes = 0

    for r in raw_rows:
        kg = flt(r["total_kg"])
        rate = flt(r["rate"])
        amt = flt(r["amount"])
        boxes = round(kg / 20.0) if kg > 0 else 0
        box_kg = 20.0 if boxes > 0 else 0.0

        total_sales += amt
        total_kg += kg
        total_boxes += boxes

        rows.append({
            "posting_date": str(r["posting_date"]) if r["posting_date"] else None,
            "invoice_number": r["invoice_number"],
            "customer": r["customer"],
            "customer_name": r["customer_name"] or r["customer"],
            "parent_customer": r["custom_parent_customer"] or "",
            "item_code": r["item_code"],
            "item_name": r["item_name"] or r["item_code"],
            "boxes": boxes,
            "box_kg": box_kg,
            "total_kg": kg,
            "rate": rate,
            "amount": amt,
            "currency": r["currency"] or "UZS",
        })

    return {
        "rows": rows,
        "totals": {
            "row_count": len(rows),
            "total_sales": total_sales,
            "total_kg": total_kg,
            "total_boxes": total_boxes,
        },
    }


# ---------------------------------------------------------------------------
# 4. Payments Register Report (reports/payments-register/)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_payments_register_report(
    company: str,
    start_date: str | None = None,
    end_date: str | None = None,
    customer_name: str | None = None,
    customer_type: str | None = None,
    account: str | None = None,
) -> dict:
    """Payments Register — submitted Receive Payment Entries with details & USD equivalent."""
    _require_company(company)
    _assert_company_scope(company)

    conditions = ["pe.company = %(company)s", "pe.docstatus = 1", "pe.payment_type = 'Receive'"]
    params = {"company": company}

    if start_date:
        params["start_date"] = start_date
        conditions.append("pe.posting_date >= %(start_date)s")
    if end_date:
        params["end_date"] = end_date
        conditions.append("pe.posting_date <= %(end_date)s")
    if customer_name and customer_name.strip():
        params["customer_name"] = customer_name.strip()
        if customer_type == "parent":
            conditions.append("cust.custom_parent_customer = %(customer_name)s")
        else:
            conditions.append("(pe.party = %(customer_name)s OR cust.customer_name LIKE %(cust_like)s)")
            params["cust_like"] = f"%{customer_name.strip()}%"
    if account and account.strip():
        params["account"] = account.strip()
        conditions.append("pe.paid_to = %(account)s")

    where_clause = " AND ".join(conditions)
    pes = frappe.db.sql(
        f"""
        SELECT pe.name, pe.posting_date, pe.reference_no, pe.party, cust.customer_name,
               cust.custom_parent_customer, pe.mode_of_payment, pe.paid_to, pe.remarks,
               IFNULL(pe.paid_amount, 0) paid_amount,
               IFNULL(pe.paid_amount_in_company_currency, pe.paid_amount) uzs_amount,
               IFNULL(pe.source_exchange_rate, 1.0) fx_rate, pe.paid_from_account_currency
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabCustomer` cust ON cust.name = pe.party
        WHERE {where_clause}
        ORDER BY pe.posting_date DESC, pe.name DESC
        """,
        params,
        as_dict=True,
    )

    rows = []
    uzs_total = 0.0
    usd_total = 0.0

    for pe in pes:
        pe_name = pe["name"]
        uzs = flt(pe["uzs_amount"])
        cbu_rate = flt(frappe.db.get_value("Currency Exchange", {"from_currency": "USD", "to_currency": "UZS"}, "exchange_rate")) or 12800.0
        usd = uzs / cbu_rate if cbu_rate > 0 else 0.0

        refs = frappe.db.get_all(
            "Payment Entry Reference",
            filters={"parent": pe_name},
            fields=["reference_name"],
        )
        allocated_invoices = [r["reference_name"] for r in refs if r.get("reference_name")]

        uzs_total += uzs
        usd_total += usd

        rows.append({
            "posting_date": str(pe["posting_date"]) if pe["posting_date"] else None,
            "name": pe_name,
            "reference_no": pe["reference_no"] or "",
            "uzs_amount": uzs,
            "counterparty": pe["customer_name"] or pe["party"] or "—",
            "parent_customer": pe["custom_parent_customer"] or "",
            "method": pe["mode_of_payment"] or "Bank",
            "paid_to": pe["paid_to"] or "",
            "remarks": pe["remarks"] or "",
            "category": "Customer Payment",
            "allocated_invoices": allocated_invoices,
            "fx_rate": cbu_rate,
            "usd_amount": round(usd, 2),
        })

    return {
        "rows": rows,
        "totals": {
            "row_count": len(rows),
            "uzs_total": uzs_total,
            "usd_total": round(usd_total, 2),
        },
    }
