"""Installment (Murabaha) module — riba-free car financing.

Islamic finance cost-plus model:
  total       = cost + disclosed_markup     (fixed, no balance interest)
  downpayment = total × dp_percent / 100   (default 20%)
  financed    = total − downpayment
  installment = financed / term_months     (equal, last absorbs rounding)

Two sides:
  Sell → Sales Invoice + payment_schedule   (car sold to customer)
  Buy  → Purchase Invoice + payment_schedule (car bought from supplier)

Each side can carry different markup rates.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, add_months

from stabler.api._common import _require_company, _assert_can_read


def _round2(n) -> float:
    return round(float(flt(n)), 2)


def _build_schedule(
    cost: float,
    markup: float,
    dp_percent: float,
    term_months: int,
    start_date: str,
) -> dict:
    """
    Return the authoritative Murabaha payment schedule.

    Row 0 = downpayment (due on start_date).
    Rows 1..n = monthly installments (due on successive months).

    Sum of all amounts == total exactly (last row absorbs rounding residual).
    invoice_portion per row sums to 100.0 exactly (last row forced).
    """
    total = _round2(cost + markup)
    downpay = _round2(total * dp_percent / 100)
    financed = _round2(total - downpay)
    n = int(term_months)
    if n < 1:
        frappe.throw("term_months must be at least 1.")
    if total <= 0:
        frappe.throw("cost + markup must be positive.")

    base_inst = _round2(financed / n)

    rows = []

    # Row 0: downpayment
    rows.append(
        {
            "due_date": start_date,
            "payment_amount": downpay,
            "invoice_portion": None,  # filled below
            "outstanding": downpay,
            "paid_amount": 0.0,
            "description": "Downpayment",
        }
    )

    # Rows 1..n: installments
    for i in range(1, n + 1):
        due = str(add_months(getdate(start_date), i))
        rows.append(
            {
                "due_date": due,
                "payment_amount": base_inst,
                "invoice_portion": None,
                "outstanding": base_inst,
                "paid_amount": 0.0,
                "description": f"Installment {i}/{n}",
            }
        )

    # Absorb rounding residual in last row so sum == total exactly
    current_sum = _round2(sum(r["payment_amount"] for r in rows))
    residual = _round2(total - current_sum)
    rows[-1]["payment_amount"] = _round2(rows[-1]["payment_amount"] + residual)
    rows[-1]["outstanding"] = rows[-1]["payment_amount"]

    # invoice_portion: percentage of total, last forced so sum == 100
    running_portion = 0.0
    for idx, row in enumerate(rows):
        if idx < len(rows) - 1:
            portion = round(row["payment_amount"] / total * 100, 6)
            row["invoice_portion"] = portion
            running_portion += portion
        else:
            row["invoice_portion"] = round(100.0 - running_portion, 6)

    return {
        "total": total,
        "downpayment": downpay,
        "financed": financed,
        "installment": base_inst,
        "rows": rows,
    }


@frappe.whitelist()
def preview_schedule(
    cost: float | str,
    markup: float | str,
    dp_percent: float | str = 20,
    term_months: int | str = 12,
    start_date: str | None = None,
) -> dict:
    """
    Return the full schedule without persisting anything.
    Used by the NewContract form for live preview.
    """
    if not start_date:
        from frappe.utils import today
        start_date = today()
    return _build_schedule(
        float(flt(cost)),
        float(flt(markup)),
        float(flt(dp_percent)),
        int(term_months),
        start_date,
    )


@frappe.whitelist()
def list_cars(
    company: str,
    search: str = "",
    limit: int = 100,
) -> list:
    """List ERPNext Items in Item Group 'Vehicles' (or any group)."""
    _require_company(company)
    filters: dict = {"disabled": 0, "is_stock_item": 1}
    if search:
        filters["item_name"] = ["like", f"%{search}%"]
    return frappe.get_all(
        "Item",
        filters=filters,
        fields=["name", "item_name", "item_group", "description"],
        order_by="item_name asc",
        limit=int(limit),
    )


def _create_invoice(
    side: str,
    company: str,
    party: str,
    car_item: str,
    cost: float,
    markup: float,
    dp_percent: float,
    term_months: int,
    start_date: str,
    posting_date: str,
    remarks: str | None,
    submit: bool,
) -> dict:
    """
    Internal helper — creates Sales Invoice (sell) or Purchase Invoice (buy)
    with a pre-populated payment_schedule.
    """
    schedule = _build_schedule(float(flt(cost)), float(flt(markup)), float(flt(dp_percent)), int(term_months), start_date)
    total = schedule["total"]

    if side == "sell":
        doctype = "Sales Invoice"
        party_field = "customer"
        party_account_field = "debit_to"
        party_account = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Receivable", "is_group": 0},
            "name",
        )
    else:
        doctype = "Purchase Invoice"
        party_field = "supplier"
        party_account_field = "credit_to"
        party_account = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Payable", "is_group": 0},
            "name",
        )

    income_expense_account = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "root_type": "Income" if side == "sell" else "Expense",
            "is_group": 0,
        },
        "name",
    )

    doc_data: dict = {
        "doctype": doctype,
        "company": company,
        party_field: party,
        "posting_date": getdate(posting_date) if posting_date else getdate(start_date),
        "due_date": schedule["rows"][-1]["due_date"],
        "payment_terms_template": None,
        "remarks": remarks or f"Murabaha ({side}): {car_item}",
        "items": [
            {
                "item_code": car_item,
                "qty": 1,
                "rate": total,
                "amount": total,
                **({"income_account": income_expense_account} if side == "sell" else {"expense_account": income_expense_account}),
            }
        ],
        # Pre-populate payment_schedule BEFORE insert so ERPNext's
        # set_payment_schedule() sees a non-empty schedule and leaves it untouched.
        "payment_schedule": [
            {
                "due_date": row["due_date"],
                "payment_amount": row["payment_amount"],
                "invoice_portion": row["invoice_portion"],
                "outstanding": row["outstanding"],
                "paid_amount": row["paid_amount"],
                "description": row["description"],
            }
            for row in schedule["rows"]
        ],
        # Custom flag so list_contracts can filter by this field
        "stabler_installment_plan": 1,
    }

    if party_account:
        doc_data[party_account_field] = party_account

    doc = frappe.get_doc(doc_data)
    doc.insert(ignore_permissions=True)

    if submit:
        doc.submit()

    frappe.db.commit()

    return {
        "name": doc.name,
        "grand_total": total,
        "docstatus": doc.docstatus,
        "schedule": schedule,
    }


@frappe.whitelist()
def create_sell_contract(
    company: str,
    customer: str,
    car_item: str,
    cost: float | str,
    markup: float | str,
    dp_percent: float | str = 20,
    term_months: int | str = 12,
    start_date: str | None = None,
    posting_date: str | None = None,
    remarks: str | None = None,
    submit: int | str = 0,
) -> dict:
    """Create a Murabaha Sell contract (Sales Invoice + payment_schedule)."""
    _require_company(company)
    if not start_date:
        from frappe.utils import today
        start_date = today()
    return _create_invoice(
        side="sell",
        company=company,
        party=customer,
        car_item=car_item,
        cost=float(flt(cost)),
        markup=float(flt(markup)),
        dp_percent=float(flt(dp_percent)),
        term_months=int(term_months),
        start_date=start_date,
        posting_date=posting_date or start_date,
        remarks=remarks,
        submit=bool(int(submit)),
    )


@frappe.whitelist()
def create_buy_contract(
    company: str,
    supplier: str,
    car_item: str,
    cost: float | str,
    markup: float | str,
    dp_percent: float | str = 20,
    term_months: int | str = 12,
    start_date: str | None = None,
    posting_date: str | None = None,
    remarks: str | None = None,
    submit: int | str = 0,
) -> dict:
    """Create a Murabaha Buy contract (Purchase Invoice + payment_schedule)."""
    _require_company(company)
    if not start_date:
        from frappe.utils import today
        start_date = today()
    return _create_invoice(
        side="buy",
        company=company,
        party=supplier,
        car_item=car_item,
        cost=float(flt(cost)),
        markup=float(flt(markup)),
        dp_percent=float(flt(dp_percent)),
        term_months=int(term_months),
        start_date=start_date,
        posting_date=posting_date or start_date,
        remarks=remarks,
        submit=bool(int(submit)),
    )


@frappe.whitelist()
def list_contracts(
    company: str,
    side: str = "sell",
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
) -> list:
    """List Murabaha contracts (Sales or Purchase Invoices with stabler_installment_plan=1)."""
    _require_company(company)
    from stabler.api.money import _date_filters

    clauses, params = _date_filters(from_date, to_date)
    params["company"] = company
    params["limit"] = max(1, min(500, int(limit)))

    if side == "buy":
        doctype_table = "tabPurchase Invoice"
        party_field = "supplier"
    else:
        doctype_table = "tabSales Invoice"
        party_field = "customer"

    qualified = [c.replace("posting_date", "inv.posting_date") for c in clauses]
    where_parts = [
        "inv.company = %(company)s",
        "inv.stabler_installment_plan = 1",
        "inv.docstatus < 2",
        *qualified,
    ]
    where = " AND ".join(where_parts)

    return frappe.db.sql(
        f"""
        SELECT
            inv.name,
            inv.posting_date,
            inv.{party_field} AS party,
            inv.grand_total,
            inv.currency,
            inv.outstanding_amount,
            inv.docstatus
        FROM `{doctype_table}` inv
        WHERE {where}
        ORDER BY inv.posting_date DESC, inv.name DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )


@frappe.whitelist()
def contract_detail(name: str, side: str = "sell") -> dict:
    """Return contract header + full payment_schedule rows."""
    doctype = "Sales Invoice" if side == "sell" else "Purchase Invoice"
    _assert_can_read(doctype, name)
    doc = frappe.get_doc(doctype, name)
    schedule = [
        {
            "due_date": str(row.due_date),
            "payment_amount": row.payment_amount,
            "invoice_portion": row.invoice_portion,
            "outstanding": row.outstanding,
            "paid_amount": row.paid_amount,
            "description": row.get("description") or "",
        }
        for row in (doc.payment_schedule or [])
    ]
    party_field = "customer" if side == "sell" else "supplier"
    return {
        "name": doc.name,
        "side": side,
        "party": getattr(doc, party_field, ""),
        "posting_date": str(doc.posting_date),
        "grand_total": doc.grand_total,
        "outstanding_amount": doc.outstanding_amount,
        "currency": doc.currency,
        "remarks": doc.remarks or "",
        "docstatus": doc.docstatus,
        "payment_schedule": schedule,
    }


@frappe.whitelist()
def calendar_events(
    company: str,
    side: str = "sell",
    month: str | None = None,
) -> list:
    """
    Return payment_schedule rows whose due_date falls in `month` (yyyy-mm).
    Used by InstallmentCalendar.vue to populate the month grid.
    """
    _require_company(company)
    if not month:
        from frappe.utils import today
        month = today()[:7]

    year, mon = month.split("-")
    from_date = f"{year}-{mon}-01"
    import calendar as _cal
    last_day = _cal.monthrange(int(year), int(mon))[1]
    to_date = f"{year}-{mon}-{last_day:02d}"

    if side == "buy":
        doctype_table = "tabPurchase Invoice"
        sched_table = "tabPurchase Invoice Payment"
    else:
        doctype_table = "tabSales Invoice"
        sched_table = "tabSales Invoice Payment"

    return frappe.db.sql(
        f"""
        SELECT
            ps.due_date AS date,
            inv.name   AS contract_id,
            inv.name   AS label,
            ps.payment_amount AS amount,
            inv.currency,
            ps.outstanding,
            ps.paid_amount
        FROM `{sched_table}` ps
        JOIN `{doctype_table}` inv ON inv.name = ps.parent
        WHERE inv.company = %(company)s
          AND inv.stabler_installment_plan = 1
          AND inv.docstatus < 2
          AND ps.due_date BETWEEN %(from_date)s AND %(to_date)s
        ORDER BY ps.due_date ASC
        """,
        {"company": company, "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )
