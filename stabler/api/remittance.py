"""Remittance module — international money transfer posted as Journal Entries.

Each remittance is a 3-leg JE:
  Debit  cash_in_account      send_currency   cash_in_amount
  Credit payout_account       receive_currency payout_amount
  Credit commission_account   (native ccy)    commission_amount

Commission modes:
  inclusive → sender pays `amount`, receiver gets `amount − fee`
  exclusive → sender pays `amount + fee`, receiver gets `amount`

Invariant: cash_in_base == payout_base + commission_base  (balances by construction).
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

from stabler.api._common import _require_company, _assert_can_read
from stabler.api.money import (
    _round2,
    _validate_account,
    bank_cash_accounts,
    _date_filters,
    journal_entry_detail,
    get_exchange_rate_for_currencies,
)


CORRIDORS = [
    {"from_city": "Tashkent", "to_city": "Istanbul", "label": "Tashkent → Istanbul"},
    {"from_city": "Moscow", "to_city": "Dubai", "label": "Moscow → Dubai"},
]

REMITTANCE_CURRENCIES = ["USD", "EUR", "USDT"]


@frappe.whitelist()
def remittance_accounts(company: str) -> dict:
    """Return account pools for the remittance form selectors."""
    _require_company(company)
    cash = bank_cash_accounts(company)
    income = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Income",
            "is_group": 0,
            "disabled": 0,
        },
        fields=["name", "account_currency"],
        order_by="name asc",
    )
    return {
        "cash_accounts": cash,
        "payout_accounts": cash,
        "commission_accounts": income,
    }


@frappe.whitelist()
def list_corridors() -> list:
    """Static corridor list (Tashkent→Istanbul, Moscow→Dubai)."""
    return CORRIDORS


@frappe.whitelist()
def create_remittance(
    company: str,
    posting_date: str,
    cash_in_account: str,
    payout_account: str,
    commission_account: str,
    send_currency: str,
    receive_currency: str,
    amount: float | str,
    commission: float | str | None = None,
    commission_mode: str = "exclusive",
    commission_percent: float | str | None = None,
    exchange_rate: float | str | None = None,
    corridor: str | None = None,
    sender_name: str | None = None,
    receiver_name: str | None = None,
    memo: str | None = None,
    submit: int | str = 1,
) -> dict:
    """
    Post a remittance as a 3-leg Journal Entry and optionally submit it.

    commission_percent: when supplied, derives the absolute commission.
                        Exclusive: commission = round2(amount × pct / 100).
                        Inclusive: amount is the gross the sender hands over;
                          principal = round2(amount / (1 + pct/100)),
                          commission = round2(amount − principal).
                        Takes precedence over `commission`.
    exchange_rate:      send_currency → receive_currency conversion.
                        Only needed for cross-currency transfers.
                        If omitted for cross-currency, fetched from ERPNext FX.
    """
    _require_company(company)
    amount = _round2(amount)
    if commission_percent is not None:
        rate = flt(commission_percent) / 100.0
        if commission_mode == "inclusive":
            # Sender hands over `amount` gross; rate applies to the net principal.
            principal = _round2(amount / (1 + rate))
            commission = _round2(amount - principal)
        else:  # exclusive — `amount` IS the principal; fee adds on top
            commission = _round2(amount * rate)
    else:
        commission = _round2(commission or 0)

    if commission_mode == "inclusive":
        cash_in_send = amount
        payout_send = _round2(amount - commission)
        commission_send = commission
    elif commission_mode == "exclusive":
        cash_in_send = _round2(amount + commission)
        payout_send = amount
        commission_send = commission
    else:
        frappe.throw(f"Invalid commission_mode: {commission_mode!r}. Use 'inclusive' or 'exclusive'.")

    if cash_in_send <= 0:
        frappe.throw("Transfer amount must be positive.")
    if commission_send < 0:
        frappe.throw("Commission must be non-negative.")

    # Validate all three accounts belong to this company
    _validate_account(cash_in_account, company, 1)
    _validate_account(payout_account, company, 2)
    comm_acct_info = _validate_account(commission_account, company, 3)

    base_currency = frappe.db.get_value("Company", company, "default_currency") or "UZS"

    # --- exchange rates ---
    # send_currency → base
    if send_currency == base_currency:
        send_to_base = 1.0
    else:
        send_to_base = _round2(
            get_exchange_rate_for_currencies(send_currency, base_currency, posting_date)
        )

    # receive_currency → base
    if receive_currency == send_currency:
        receive_to_base = send_to_base
    elif receive_currency == base_currency:
        receive_to_base = 1.0
    else:
        receive_to_base = _round2(
            get_exchange_rate_for_currencies(receive_currency, base_currency, posting_date)
        )

    # payout amount in receive_currency
    if receive_currency == send_currency:
        payout_receive = payout_send
    else:
        if exchange_rate:
            s2r = _round2(exchange_rate)
        else:
            s2r = _round2(
                get_exchange_rate_for_currencies(send_currency, receive_currency, posting_date)
            )
        payout_receive = _round2(payout_send * s2r)

    # --- base totals (anchored so JE balances exactly) ---
    cash_in_base = _round2(cash_in_send * send_to_base)
    payout_base = _round2(payout_receive * receive_to_base)
    commission_base = _round2(cash_in_base - payout_base)  # exact balance

    if commission_base < 0:
        frappe.throw("Commission base amount is negative — check exchange rates and commission.")

    # per-leg exchange_rate for commission account (back-solve)
    comm_acct_currency = comm_acct_info.get("account_currency") or base_currency
    if comm_acct_currency == send_currency:
        comm_in_acct = commission_send
        comm_rate = _round2(commission_base / commission_send) if commission_send else send_to_base
    elif comm_acct_currency == base_currency:
        comm_in_acct = commission_base
        comm_rate = 1.0
    else:
        # Unusual — commission account in a third currency; post in base equivalent
        comm_in_acct = commission_base
        comm_rate = 1.0

    multi_currency = int(send_currency != base_currency or receive_currency != base_currency)

    # Build user_remark
    parts = []
    if corridor:
        parts.append(corridor)
    if sender_name:
        parts.append(f"From: {sender_name}")
    if receiver_name:
        parts.append(f"To: {receiver_name}")
    if memo:
        parts.append(memo)
    remark = " | ".join(parts) if parts else "Remittance"

    je = frappe.get_doc(
        {
            "doctype": "Journal Entry",
            "posting_date": getdate(posting_date),
            "company": company,
            "voucher_type": "Journal Entry",
            "multi_currency": multi_currency,
            "user_remark": remark,
            "cheque_no": f"Rem-{posting_date}",
            "cheque_date": getdate(posting_date),
            "accounts": [
                # Leg 1 — Debit: cash collected from sender
                {
                    "account": cash_in_account,
                    "account_currency": send_currency,
                    "exchange_rate": send_to_base,
                    "debit_in_account_currency": cash_in_send,
                    "debit": cash_in_base,
                    "credit_in_account_currency": 0,
                    "credit": 0,
                    "user_remark": remark,
                },
                # Leg 2 — Credit: payout to receiver
                {
                    "account": payout_account,
                    "account_currency": receive_currency,
                    "exchange_rate": _round2(payout_base / payout_receive) if payout_receive else receive_to_base,
                    "credit_in_account_currency": payout_receive,
                    "credit": payout_base,
                    "debit_in_account_currency": 0,
                    "debit": 0,
                    "user_remark": remark,
                },
                # Leg 3 — Credit: commission income
                {
                    "account": commission_account,
                    "account_currency": comm_acct_currency,
                    "exchange_rate": comm_rate,
                    "credit_in_account_currency": comm_in_acct,
                    "credit": commission_base,
                    "debit_in_account_currency": 0,
                    "debit": 0,
                    "user_remark": remark,
                },
            ],
        }
    )
    je.insert(ignore_permissions=True)
    if int(submit):
        je.submit()
    frappe.db.commit()
    return {"name": je.name, "docstatus": je.docstatus}


@frappe.whitelist()
def list_remittances(
    company: str,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
) -> list:
    """List remittance JEs for this company (cheque_no LIKE 'Rem-%')."""
    _require_company(company)
    clauses, params = _date_filters(from_date, to_date)
    params["company"] = company
    params["limit"] = max(1, min(500, int(limit)))
    qualified = [c.replace("posting_date", "je.posting_date") for c in clauses]
    where = " AND ".join(
        ["je.company = %(company)s", "je.cheque_no LIKE 'Rem-%%'", "je.docstatus < 2", *qualified]
    )
    return frappe.db.sql(
        f"""
        SELECT
            je.name,
            je.posting_date,
            je.user_remark,
            je.cheque_no,
            je.docstatus,
            je.multi_currency,
            je.total_debit  AS total_debit_base,
            je.total_credit AS total_credit_base,
            c.default_currency AS base_currency,
            COALESCE(
                (SELECT debit_in_account_currency
                   FROM `tabJournal Entry Account`
                  WHERE parent = je.name AND debit_in_account_currency > 0
                  LIMIT 1),
                je.total_debit
            ) AS send_amount,
            COALESCE(
                (SELECT account_currency
                   FROM `tabJournal Entry Account`
                  WHERE parent = je.name AND debit_in_account_currency > 0
                  LIMIT 1),
                c.default_currency
            ) AS send_currency
        FROM `tabJournal Entry` je
        JOIN `tabCompany` c ON c.name = je.company
        WHERE {where}
        ORDER BY je.posting_date DESC, je.name DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )


@frappe.whitelist()
def remittance_detail(name: str) -> dict:
    """Return full remittance detail (delegates to journal_entry_detail)."""
    _assert_can_read("Journal Entry", name)
    return journal_entry_detail(name)
