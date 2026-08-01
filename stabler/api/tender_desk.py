"""Operations Desk API (Package 3).

Provides role-based daily work plan, decision box, 7-day calendar, and team load
derived deterministically from source documents without manual task records.
"""

from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import now, today

from stabler.api import _desk_rules
from stabler.api.approvals import list_pending
from stabler.api.tender import (
    _assert_company_scope,
    _is_tender_oversight,
    _require_company,
    _require_tender,
    _require_tender_view,
    _tender_views,
)


@frappe.whitelist()
def operations_desk(company: str, view: str | None = None, days: int = 7) -> dict:
    """Operations Desk endpoint for role-based daily work plan and decision box."""
    _require_company(company)
    _assert_company_scope(company)
    _require_tender(company)

    user = frappe.session.user
    raw_views = _tender_views(user)
    if not raw_views:
        frappe.throw(_("Access denied to Operations Desk."), frappe.PermissionError)

    available_views = [{"id": v, "label": v} for v in raw_views]

    if view:
        _require_tender_view(view, company)
    else:
        view = raw_views[0]

    oversight = _is_tender_oversight(user)
    today_str = today()
    today_date = datetime.date.fromisoformat(today_str)
    try:
        days_cnt = int(days)
    except (ValueError, TypeError):
        days_cnt = 7

    # 1. Fetch CRM Deals for company (Batched with column checks)
    deal_fields = ["name", "organization", "owner"]
    potential_fields = [
        "assigned_to", "custom_tender_master", "custom_lot_no", "lot_no",
        "custom_tender_stage", "stage", "custom_bid_deadline", "bid_deadline",
        "expected_closing", "custom_delivery_deadline", "custom_tender_result",
        "custom_tender_risk", "status"
    ]
    for fld in potential_fields:
        if frappe.db.has_column("CRM Deal", fld):
            deal_fields.append(fld)

    deals_raw = frappe.get_all(
        "CRM Deal",
        filters={"company": company},
        fields=deal_fields,
        limit_page_length=0
    )

    deals = []
    for d in deals_raw:
        deals.append({
            "name": d["name"],
            "organization": d.get("organization"),
            "owner": d.get("owner"),
            "assigned_to": d.get("assigned_to") or d.get("owner"),
            "custom_tender_master": d.get("custom_tender_master"),
            "custom_lot_no": d.get("custom_lot_no") or d.get("lot_no"),
            "custom_tender_stage": d.get("custom_tender_stage") or d.get("stage"),
            "custom_bid_deadline": d.get("custom_bid_deadline") or d.get("bid_deadline") or d.get("expected_closing"),
            "custom_delivery_deadline": d.get("custom_delivery_deadline"),
            "custom_tender_result": d.get("custom_tender_result") or d.get("status"),
            "custom_tender_risk": d.get("custom_tender_risk")
        })

    # Permission filter: sourcing role sees only assigned or owned deals
    if not oversight and view == "sourcing":
        deals = [d for d in deals if (d.get("assigned_to") == user or d.get("owner") == user)]

    deal_names = [d["name"] for d in deals if d.get("name")]

    # 2. Batched SQ counts (api/tender.py:2174 pattern)
    sq_counts: dict[str, int] = {}
    if deal_names:
        sq_rows = frappe.get_all(
            "Supplier Quotation",
            filters={"custom_crm_deal": ["in", deal_names], "docstatus": ["<", 2]},
            fields=["custom_crm_deal"],
            limit_page_length=0
        )
        for r in sq_rows:
            ref = r.get("custom_crm_deal")
            if ref:
                sq_counts[ref] = sq_counts.get(ref, 0) + 1

    # 3. Batched Orphan Lots
    orphan_lots = [
        {
            "name": d["name"],
            "organization": d.get("organization"),
            "assigned_to": d.get("assigned_to") or d.get("owner")
        }
        for d in deals
        if d.get("custom_lot_no") and not d.get("custom_tender_master")
    ]

    # 4. Batched Won without PO
    won_deals = [d for d in deals if (d.get("custom_tender_result") or "").lower() == "won"]
    won_deal_names = [d["name"] for d in won_deals]
    linked_pos = set()
    if won_deal_names:
        po_rows = frappe.get_all(
            "Purchase Order",
            filters={"company": company, "docstatus": ["<", 2]},
            fields=["custom_crm_deal"],
            limit_page_length=0
        )
        for p in po_rows:
            if p.get("custom_crm_deal"):
                linked_pos.add(p["custom_crm_deal"])

    won_without_po = [
        {
            "name": d["name"],
            "label": d.get("name"),
            "assigned_to": d.get("assigned_to") or d.get("owner")
        }
        for d in won_deals
        if d["name"] not in linked_pos
    ]

    # 5. Batched Late POs
    late_pos_raw = frappe.get_all(
        "Purchase Order",
        filters={"company": company, "docstatus": 1, "per_received": ["<", 100]},
        fields=["name", "supplier", "schedule_date", "per_received", "owner"],
        limit_page_length=0
    )
    po_late = [
        {
            "po": p["name"],
            "supplier": p.get("supplier"),
            "schedule_date": str(p.get("schedule_date")),
            "per_received": float(p.get("per_received") or 0.0),
            "owner": p.get("owner")
        }
        for p in late_pos_raw
        if p.get("schedule_date") and str(p.get("schedule_date")) < today_str
    ]

    # 6. Batched Overdue/Due Invoices
    unpaid_raw = frappe.get_all(
        "Purchase Invoice",
        filters={"company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "due_date", "outstanding_amount", "owner"],
        limit_page_length=0
    )
    unpaid = [
        {
            "doctype": "Purchase Invoice",
            "name": p["name"],
            "due_date": str(p.get("due_date")),
            "outstanding": float(p.get("outstanding_amount") or 0.0),
            "owner": p.get("owner")
        }
        for p in unpaid_raw
        if p.get("due_date") and str(p.get("due_date")) <= today_str
    ]

    # 7. Approvals Cohort
    # list_pending returns {"requests": [...], "total": n, "can_approve": bool} --
    # the rows live under "requests". Passing the envelope itself made _desk_rules
    # iterate the dict, i.e. its three KEYS, so the desk showed three phantom
    # "Approval required: Document requests / total / can_approve" rows while every
    # real pending approval was silently dropped (measured 2026-08-01 on mikas).
    try:
        all_pending_approvals = list_pending(company=company).get("requests") or []
    except Exception:
        all_pending_approvals = []

    # Map facts for _desk_rules
    lots_fact = [
        {
            "deal": d["name"],
            "label": d.get("name"),
            "parent_tender": d.get("custom_tender_master"),
            "lot_no": d.get("custom_lot_no"),
            "stage": d.get("custom_tender_stage"),
            "bid_deadline": str(d.get("custom_bid_deadline")) if d.get("custom_bid_deadline") else None,
            "delivery_deadline": str(d.get("custom_delivery_deadline")) if d.get("custom_delivery_deadline") else None,
            "sq_count": sq_counts.get(d["name"], 0),
            "assigned_to": d.get("assigned_to") or d.get("owner"),
            "result": d.get("custom_tender_result"),
            "risk": d.get("custom_tender_risk")
        }
        for d in deals
    ]

    facts = {
        "lots": lots_fact,
        "orphan_lots": orphan_lots,
        "won_without_po": won_without_po,
        "po_late": po_late,
        "unpaid": unpaid,
        "approvals": all_pending_approvals
    }

    plan_res = _desk_rules.build_plan(facts, today_str)
    plan_items = plan_res["items"]

    # Filter decisions (approvals assigned to user)
    decisions = [
        a for a in all_pending_approvals
        if isinstance(a, dict) and (a.get("assigned_to") == user or a.get("requested_by") != user or oversight)
    ]

    waiting_others = [
        a for a in all_pending_approvals
        if isinstance(a, dict) and a.get("requested_by") == user and a not in decisions
    ]

    due_today_cnt = len([i for i in plan_items if i.get("due") == today_str or i.get("severity") == "today"])
    overdue_cnt = len([i for i in plan_items if i.get("severity") == "overdue"])

    counters = {
        "due_today": due_today_cnt,
        "overdue": overdue_cnt,
        "awaiting_me": len(decisions),
        "waiting_others": len(waiting_others)
    }

    # 8. Build 7-day calendar
    calendar_days = []
    for d_offset in range(max(1, days_cnt)):
        dt_cur = today_date + datetime.timedelta(days=d_offset)
        dt_str = dt_cur.isoformat()
        day_items = [i for i in plan_items if i.get("due") == dt_str]
        calendar_days.append({
            "date": dt_str,
            "count": len(day_items),
            "items": day_items[:2]
        })

    # 9. Team Load (Oversight role only)
    team_load = []
    if oversight:
        users_map: dict[str, dict] = {}
        for d in deals:
            owner = d.get("assigned_to") or d.get("owner") or "Unassigned"
            if owner not in users_map:
                users_map[owner] = {"user": owner, "open_lots": 0, "overdue_lots": 0, "won_lots": 0}

            result = (d.get("custom_tender_result") or "").lower()
            if result not in ("won", "lost", "cancelled"):
                users_map[owner]["open_lots"] += 1

            if result == "won":
                users_map[owner]["won_lots"] += 1

            bd_str = str(d.get("custom_bid_deadline")) if d.get("custom_bid_deadline") else None
            if bd_str and bd_str < today_str and result not in ("won", "lost", "cancelled"):
                users_map[owner]["overdue_lots"] += 1

        team_load = list(users_map.values())

    curr = frappe.get_cached_value("Company", company, "default_currency") or "USD"

    return {
        "counters": counters,
        "plan": plan_items,
        "decisions": decisions,
        "calendar": calendar_days,
        "team_load": team_load,
        "currency": curr or "USD",
        "view": view,
        "views": available_views,
        "generated_at": now()
    }
