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
from frappe.utils import flt, getdate, add_months, today

from stabler.api._common import _require_company, _assert_can_read
from stabler.api.money import payment_defaults_for_invoice


def _round2(n) -> float:
    return round(float(flt(n)), 2)


def _invoice_doctype(side: str) -> str:
    if side == "buy":
        return "Purchase Invoice"
    if side == "sell":
        return "Sales Invoice"
    frappe.throw("side must be 'sell' or 'buy'.")


def _schedule_state(row) -> dict:
    return {
        "name": row.name,
        "due_date": str(row.due_date),
        "payment_amount": _round2(row.payment_amount),
        "paid_amount": _round2(row.paid_amount),
        "outstanding": _round2(row.outstanding),
        "description": row.get("description") or "",
    }


def _allocate_collection(doc, amount: float) -> list[dict]:
    remaining = _round2(amount)
    allocations: list[dict] = []
    rows = sorted(
        enumerate(doc.payment_schedule or []),
        key=lambda item: (getdate(item[1].due_date), item[0]),
    )
    for idx, row in rows:
        if remaining <= 0:
            break
        row_outstanding = _round2(row.outstanding)
        if row_outstanding <= 0:
            continue
        applied = _round2(min(remaining, row_outstanding))
        before = _schedule_state(row)
        after_paid = _round2(before["paid_amount"] + applied)
        after_outstanding = _round2(before["outstanding"] - applied)
        allocations.append(
            {
                "row_index": idx,
                "row_name": before["name"],
                "due_date": before["due_date"],
                "description": before["description"],
                "payment_amount": before["payment_amount"],
                "previous_paid": before["paid_amount"],
                "previous_outstanding": before["outstanding"],
                "allocated_amount": applied,
                "paid_amount": after_paid,
                "outstanding": after_outstanding,
            }
        )
        remaining = _round2(remaining - applied)
    return allocations


def _apply_collection_to_schedule(doc, allocations: list[dict]) -> None:
    for allocation in allocations:
        frappe.db.set_value(
            "Payment Schedule",
            allocation["row_name"],
            {
                "paid_amount": allocation["paid_amount"],
                "outstanding": allocation["outstanding"],
            },
            update_modified=False,
        )


def _collection_preview_payload(doc, allocations: list[dict], amount: float) -> dict:
    remaining_balance = _round2(flt(doc.outstanding_amount) - amount)
    return {
        "contract": doc.name,
        "amount": _round2(amount),
        "currency": doc.currency,
        "remaining_balance": remaining_balance,
        "allocations": allocations,
    }


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
    """Stock items with on-hand qty (this company) + valuation, for the picker."""
    _require_company(company)
    needle = f"%{search}%"
    return frappe.db.sql(
        """
        SELECT
            i.name, i.item_name, i.item_group, i.stock_uom,
            COALESCE(i.valuation_rate, i.last_purchase_rate, 0) AS valuation_rate,
            COALESCE((
                SELECT SUM(b.actual_qty)
                FROM `tabBin` b
                JOIN `tabWarehouse` w ON w.name = b.warehouse
                WHERE b.item_code = i.name AND w.company = %(company)s
            ), 0) AS actual_qty
        FROM `tabItem` i
        WHERE i.disabled = 0 AND i.is_stock_item = 1
          AND (%(search)s = '' OR i.item_name LIKE %(needle)s OR i.name LIKE %(needle)s)
        ORDER BY i.item_name ASC
        LIMIT %(limit)s
        """,
        {"company": company, "search": search or "", "needle": needle, "limit": int(limit)},
        as_dict=True,
    )


def _company_default_warehouse(company: str) -> str | None:
    wh = frappe.get_cached_value("Company", company, "default_warehouse")
    if wh:
        return wh
    return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


@frappe.whitelist()
def quick_create_item(
    company: str,
    item_name: str,
    opening_qty: float = 0,
    rate: float = 0,
) -> dict:
    """Create a stock item inline and, if qty+rate given, post an opening receipt.

    Lets the New Contract form add a product to inventory without leaving the
    page — the item then behaves like any other stock item in the system.
    """
    _require_company(company)
    if not (item_name or "").strip():
        frappe.throw("Item name is required.")
    if not frappe.has_permission("Item", "create"):
        frappe.throw("Not permitted to create items.", frappe.PermissionError)

    item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_name": item_name.strip(),
            "item_group": item_group,
            "stock_uom": frappe.db.get_value("UOM", {"enabled": 1}, "name") or "Nos",
            "is_stock_item": 1,
        }
    ).insert()

    qty = flt(opening_qty)
    basic_rate = flt(rate)
    warehouse = _company_default_warehouse(company)
    if qty > 0 and warehouse:
        se = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Receipt",
                "company": company,
                "items": [
                    {
                        "item_code": item.name,
                        "qty": qty,
                        "t_warehouse": warehouse,
                        "basic_rate": basic_rate or None,
                    }
                ],
            }
        )
        se.insert()
        se.submit()
    elif basic_rate > 0:
        frappe.db.set_value("Item", item.name, "valuation_rate", basic_rate)

    actual = frappe.db.sql(
        """
        SELECT COALESCE(SUM(b.actual_qty), 0)
        FROM `tabBin` b JOIN `tabWarehouse` w ON w.name = b.warehouse
        WHERE b.item_code = %(item)s AND w.company = %(company)s
        """,
        {"item": item.name, "company": company},
    )[0][0]
    return {
        "name": item.name,
        "item_name": item.item_name,
        "stock_uom": item.stock_uom,
        "actual_qty": flt(actual),
        "valuation_rate": flt(basic_rate) or flt(frappe.db.get_value("Item", item.name, "valuation_rate")),
    }


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

    from stabler.api._accounts import resolve_party_account

    party_type = "Customer" if side == "sell" else "Supplier"
    currency = frappe.db.get_value(party_type, party, "default_currency")
    if not currency:
        currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"

    if side == "sell":
        doctype = "Sales Invoice"
        party_field = "customer"
        party_account_field = "debit_to"
    else:
        doctype = "Purchase Invoice"
        party_field = "supplier"
        party_account_field = "credit_to"

    party_account = resolve_party_account(party_type, party, company, currency)

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
        "currency": currency,
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
            "state": (
                "paid"
                if flt(row.outstanding) <= 0
                else "partial"
                if flt(row.paid_amount) > 0
                else "overdue"
                if getdate(row.due_date) < getdate(today())
                else "upcoming"
            ),
            "description": row.get("description") or "",
        }
        for row in (doc.payment_schedule or [])
    ]
    party_field = "customer" if side == "sell" else "supplier"
    party = getattr(doc, party_field, "")
    party_doctype = "Customer" if side == "sell" else "Supplier"
    name_field = "customer_name" if side == "sell" else "supplier_name"
    party_name = frappe.db.get_value(party_doctype, party, name_field) if party else ""
    party_mobile = _party_mobile(party_doctype, party) if party else ""
    return {
        "name": doc.name,
        "side": side,
        "party": party,
        "party_name": party_name or party,
        "party_mobile": party_mobile,
        "posting_date": str(doc.posting_date),
        "grand_total": doc.grand_total,
        "outstanding_amount": doc.outstanding_amount,
        "currency": doc.currency,
        "remarks": doc.remarks or "",
        "docstatus": doc.docstatus,
        "payment_schedule": schedule,
    }


def _party_mobile(party_doctype: str, party: str) -> str:
    """Best-effort mobile number from the party's primary contact."""
    pc_field = "customer_primary_contact" if party_doctype == "Customer" else None
    contact = None
    if pc_field:
        contact = frappe.db.get_value(party_doctype, party, pc_field)
    if not contact:
        # Fall back to any linked Contact via Dynamic Link.
        contact = frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": party_doctype, "link_name": party, "parenttype": "Contact"},
            "parent",
        )
    if not contact:
        return ""
    return frappe.db.get_value("Contact", contact, "mobile_no") or frappe.db.get_value("Contact", contact, "phone") or ""


@frappe.whitelist()
def collect_payment(
    contract: str,
    side: str = "sell",
    amount: float | str = 0,
    mode_of_payment: str | None = None,
    bank_account: str | None = None,
    posting_date: str | None = None,
    dry_run: int | str = 0,
) -> dict:
    """Collect a partial Murabaha installment payment.

    The same allocator powers preview (`dry_run=1`) and submit, so the UI can
    never display a different row allocation than the one saved to ERPNext.
    """
    doctype = _invoice_doctype(side)
    _assert_can_read(doctype, contract)
    doc = frappe.get_doc(doctype, contract)
    _require_company(doc.company)
    if not doc.get("stabler_installment_plan"):
        frappe.throw("Contract is not a Stabler installment plan.")
    if doc.docstatus != 1:
        frappe.throw("Only submitted contracts can be collected.")

    paid = _round2(amount)
    if paid <= 0:
        frappe.throw("Collection amount must be greater than zero.")
    total_outstanding = _round2(doc.outstanding_amount)
    if paid > total_outstanding:
        frappe.throw(
            f"Collection amount exceeds remaining contract balance ({total_outstanding:.2f} {doc.currency})."
        )

    allocations = _allocate_collection(doc, paid)
    allocated_total = _round2(sum(r["allocated_amount"] for r in allocations))
    if allocated_total != paid:
        frappe.throw("Payment schedule is out of sync with contract outstanding amount.")

    if int(dry_run):
        return _collection_preview_payload(doc, allocations, paid)

    if not mode_of_payment:
        frappe.throw("Mode of payment is required.")
    if not bank_account:
        frappe.throw("Cash/bank account is required.")

    defaults = payment_defaults_for_invoice(doc.company, doctype, contract)
    pe = frappe.new_doc("Payment Entry")
    pe.company = doc.company
    pe.posting_date = getdate(posting_date or today())
    pe.payment_type = defaults["payment_type"]
    pe.party_type = defaults["party_type"]
    pe.party = defaults["party"]
    if defaults["payment_type"] == "Receive":
        pe.paid_from = defaults["party_account"]
        pe.paid_to = bank_account
    else:
        pe.paid_from = bank_account
        pe.paid_to = defaults["party_account"]
    pe.paid_amount = paid
    pe.received_amount = paid
    pe.mode_of_payment = mode_of_payment
    pe.reference_no = f"INST-{contract}"
    pe.reference_date = pe.posting_date
    pe.append(
        "references",
        {
            "reference_doctype": doctype,
            "reference_name": contract,
            "total_amount": flt(doc.grand_total),
            "outstanding_amount": total_outstanding,
            "allocated_amount": paid,
        },
    )
    pe.setup_party_account_field()
    pe.set_missing_values()

    try:
        pe.insert(ignore_permissions=False)
        # System auto-collection against an existing installment schedule —
        # not a discretionary clerk payment, so it bypasses maker-checker.
        pe.flags.ignore_approval_gate = True
        pe.submit()
        _apply_collection_to_schedule(doc, allocations)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise

    updated = frappe.get_doc(doctype, contract)
    return {
        **_collection_preview_payload(updated, allocations, paid),
        "payment_entry": pe.name,
        "docstatus": pe.docstatus,
        "outstanding_amount": _round2(updated.outstanding_amount),
    }


@frappe.whitelist()
def overdue_rows(company: str, side: str = "sell") -> list:
    """Rows past due with remaining outstanding balance."""
    _require_company(company)
    doctype = _invoice_doctype(side)
    doctype_table = "tabPurchase Invoice" if side == "buy" else "tabSales Invoice"
    party_field = "supplier" if side == "buy" else "customer"
    return frappe.db.sql(
        f"""
        SELECT
            inv.name AS contract,
            inv.{party_field} AS party,
            inv.currency,
            ps.due_date,
            ps.payment_amount,
            ps.paid_amount,
            ps.outstanding,
            DATEDIFF(CURDATE(), ps.due_date) AS days_overdue
        FROM `tabPayment Schedule` ps
        JOIN `{doctype_table}` inv ON inv.name = ps.parent
        WHERE inv.company = %(company)s
          AND inv.stabler_installment_plan = 1
          AND inv.docstatus = 1
          AND ps.parenttype = %(doctype)s
          AND ps.due_date < CURDATE()
          AND ps.outstanding > 0
        ORDER BY ps.due_date ASC, inv.name ASC
        """,
        {"company": company, "doctype": doctype},
        as_dict=True,
    )


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
        doctype = "Purchase Invoice"
        doctype_table = "tabPurchase Invoice"
        party_field = "supplier"
        party_table = "tabSupplier"
        party_name_col = "supplier_name"
    else:
        doctype = "Sales Invoice"
        doctype_table = "tabSales Invoice"
        party_field = "customer"
        party_table = "tabCustomer"
        party_name_col = "customer_name"
    sched_table = "tabPayment Schedule"

    return frappe.db.sql(
        f"""
        SELECT
            ps.due_date AS date,
            inv.name   AS contract_id,
            inv.{party_field} AS party,
            COALESCE(pt.{party_name_col}, inv.{party_field}) AS label,
            ps.payment_amount AS amount,
            inv.currency,
            ps.outstanding,
            ps.paid_amount,
            CASE
                WHEN ps.outstanding <= 0 THEN 'paid'
                WHEN ps.paid_amount > 0 THEN 'partial'
                WHEN ps.due_date < CURDATE() THEN 'overdue'
                ELSE 'upcoming'
            END AS state
        FROM `{sched_table}` ps
        JOIN `{doctype_table}` inv ON inv.name = ps.parent
        LEFT JOIN `{party_table}` pt ON pt.name = inv.{party_field}
        WHERE inv.company = %(company)s
          AND inv.stabler_installment_plan = 1
          AND inv.docstatus < 2
          AND ps.parenttype = %(doctype)s
          AND ps.due_date BETWEEN %(from_date)s AND %(to_date)s
        ORDER BY ps.due_date ASC
        """,
        {"company": company, "doctype": doctype, "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )
