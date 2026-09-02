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
	_parse_intake,
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

	# A label is not an id. This list was `{"id": v, "label": v}` -- the key said
	# "label" and held the id, so the desk's role picker rendered `logist` at the
	# user and `t()` handed it straight back, because none of the four ids is a key
	# in any catalogue (measured 2026-09-02: en.csv has `Sourcing` and `Declarant`
	# capitalised, and no `logist` or `director` in any case). A field that lies
	# about what it holds invites the next screen to render it too, and this one had
	# exactly one consumer, so the id now travels alone. Display names live in the
	# client's literal-keyed VIEW_LABEL map (OperationsDesk.vue, the same idiom as
	# TenderDocumentsPanel.vue:29) -- literal because t() is harvested by scanning
	# the source, so a name computed here could never be translated there.
	available_views = [{"id": v} for v in raw_views]

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
		"assigned_to",
		"custom_tender_master",
		"custom_lot_no",
		"lot_no",
		"custom_tender_stage",
		"stage",
		"custom_bid_deadline",
		"bid_deadline",
		"expected_closing",
		"custom_delivery_deadline",
		"custom_tender_result",
		"custom_tender_risk",
		"status",
		"custom_tender_intake",
	]
	for fld in potential_fields:
		if frappe.db.has_column("CRM Deal", fld):
			deal_fields.append(fld)

	deals_raw = frappe.get_all(
		"CRM Deal", filters={"company": company}, fields=deal_fields, limit_page_length=0
	)

	has_intake = "custom_tender_intake" in deal_fields

	deals = []
	for d in deals_raw:
		# The bid deadline lives inside the custom_tender_intake JSON, not in a
		# column. Measured on mikas 2026-08-01: of the three sources tried below,
		# custom_bid_deadline, bid_deadline AND expected_closing are all absent
		# from CRM Deal, so every has_column guard above dropped them and the
		# lookup was unconditionally None. The desk therefore emitted zero
		# bid_due / bid_soon rows -- the one thing a tender desk exists to say --
		# while the CRM board, tender.py and tender_master.py read the same
		# deadline out of intake and showed it fine. A real column still wins
		# where a site has one; intake is what actually holds the data today.
		# The same measurement holds for the other four facts this desk reasons
		# with. custom_lot_no, custom_delivery_deadline, custom_tender_result and
		# assigned_to are all absent from CRM Deal too -- no patch in
		# stabler/patches/ creates any of them -- so each lookup below was
		# unconditionally None and the rules built on them could not fire:
		#   lot_no      -> the orphan-lot rule never triggered, and every card
		#                  fell back to the deal id, so four lots of the same
		#                  buyer were indistinguishable on the board
		#   delivery    -> no delivery_due / delivery_soon row, ever
		#   result      -> team load counted won and lost lots as still open,
		#                  and "won without PO" found nothing to chase
		#   assigned_to -> assignment was invisible: the sourcing filter and the
		#                  team-load split both collapsed onto the document owner
		# A real column still wins where a site has one; intake is what holds the
		# data today (24 write sites in api/tender.py, none of them a column).
		intake = _parse_intake(d.get("custom_tender_intake")) if has_intake else {}
		lot_no = d.get("custom_lot_no") or d.get("lot_no") or intake.get("lot_no")
		deals.append(
			{
				"name": d["name"],
				"organization": d.get("organization"),
				"owner": d.get("owner"),
				"assigned_to": d.get("assigned_to") or intake.get("assigned_to") or d.get("owner"),
				"custom_tender_master": d.get("custom_tender_master"),
				"custom_lot_no": lot_no,
				# What a human calls this row. The lot number is the tender's own
				# name; the buyer organisation is how it is discussed; the deal id is
				# the last resort because it says nothing to the person reading it.
				"label": lot_no or d.get("organization") or d["name"],
				"custom_tender_stage": d.get("custom_tender_stage") or d.get("stage"),
				"custom_bid_deadline": (
					d.get("custom_bid_deadline")
					or d.get("bid_deadline")
					or intake.get("bid_deadline")
					or d.get("expected_closing")
				),
				"custom_delivery_deadline": (
					d.get("custom_delivery_deadline") or intake.get("delivery_deadline")
				),
				"custom_tender_result": (
					d.get("custom_tender_result") or intake.get("result") or d.get("status")
				),
				"custom_tender_risk": d.get("custom_tender_risk"),
			}
		)

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
			limit_page_length=0,
		)
		for r in sq_rows:
			ref = r.get("custom_crm_deal")
			if ref:
				sq_counts[ref] = sq_counts.get(ref, 0) + 1

	# 3. Batched Orphan Lots
	#
	# "Orphan" only means something where parents exist. Reading the lot number
	# out of intake (above) woke this rule up for the first time -- and on a
	# company that does not use Tender Master at all it would have fired for
	# EVERY lot, burying the desk's real work under an info row per deal. A
	# board that cries about all thirteen says nothing about any of them.
	#
	# So the rule needs one linked lot somewhere in the company before it will
	# call the others orphans. That is also the honest reading: with no parent
	# anywhere, a lot is not orphaned, it is simply a site that files tenders
	# flat.
	company_uses_parents = any(d.get("custom_tender_master") for d in deals)
	orphan_lots = [
		{
			"name": d["name"],
			"label": d.get("label") or d["name"],
			"organization": d.get("organization"),
			"assigned_to": d.get("assigned_to") or d.get("owner"),
		}
		for d in deals
		if company_uses_parents and d.get("custom_lot_no") and not d.get("custom_tender_master")
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
			limit_page_length=0,
		)
		for p in po_rows:
			if p.get("custom_crm_deal"):
				linked_pos.add(p["custom_crm_deal"])

	won_without_po = [
		{
			"name": d["name"],
			"label": d.get("label") or d["name"],
			"assigned_to": d.get("assigned_to") or d.get("owner"),
		}
		for d in won_deals
		if d["name"] not in linked_pos
	]

	# 5. Batched Late POs
	late_pos_raw = frappe.get_all(
		"Purchase Order",
		filters={"company": company, "docstatus": 1, "per_received": ["<", 100]},
		fields=["name", "supplier", "schedule_date", "per_received", "owner"],
		limit_page_length=0,
	)
	po_late = [
		{
			"po": p["name"],
			"supplier": p.get("supplier"),
			"schedule_date": str(p.get("schedule_date")),
			"per_received": float(p.get("per_received") or 0.0),
			"owner": p.get("owner"),
		}
		for p in late_pos_raw
		if p.get("schedule_date") and str(p.get("schedule_date")) < today_str
	]

	# 6. Batched Overdue/Due Invoices
	unpaid_raw = frappe.get_all(
		"Purchase Invoice",
		filters={"company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
		fields=["name", "due_date", "outstanding_amount", "owner"],
		limit_page_length=0,
	)
	unpaid = [
		{
			"doctype": "Purchase Invoice",
			"name": p["name"],
			"due_date": str(p.get("due_date")),
			"outstanding": float(p.get("outstanding_amount") or 0.0),
			"owner": p.get("owner"),
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
			"label": d.get("label") or d["name"],
			"parent_tender": d.get("custom_tender_master"),
			"lot_no": d.get("custom_lot_no"),
			"stage": d.get("custom_tender_stage"),
			"bid_deadline": str(d.get("custom_bid_deadline")) if d.get("custom_bid_deadline") else None,
			# CARRIED AND UNREAD, on purpose. Measured 2026-09-02: _desk_rules.py
			# contains zero occurrences of delivery_deadline -- there is no delivery
			# rule, and the calendar used to advertise one ("Bid · delivery · due").
			# The screen stopped promising it (D19); the fact stays because it is
			# resolved correctly after a real bug fix and it is the evidence that a
			# delivery rule is writable at all. Write that rule and the sublabel may
			# say "delivery" again -- test_operations_desk_source.py asserts the two
			# move together, in both directions.
			"delivery_deadline": str(d.get("custom_delivery_deadline"))
			if d.get("custom_delivery_deadline")
			else None,
			"sq_count": sq_counts.get(d["name"], 0),
			"assigned_to": d.get("assigned_to") or d.get("owner"),
			"result": d.get("custom_tender_result"),
			"risk": d.get("custom_tender_risk"),
		}
		for d in deals
	]

	facts = {
		"lots": lots_fact,
		"orphan_lots": orphan_lots,
		"won_without_po": won_without_po,
		"po_late": po_late,
		"unpaid": unpaid,
		"approvals": all_pending_approvals,
	}

	plan_res = _desk_rules.build_plan(facts, today_str)
	plan_items = plan_res["items"]

	# The two cards state their own rule: "Awaiting my approval / decision is
	# yours" and "Waiting others / you requested, someone else answers". They
	# partition one queue, so every pending request belongs to exactly one.
	#
	# There is no `assigned_to` on a Stabler Approval Request -- the queue is
	# shared among approvers and `list_pending` is already gated by
	# `_require_approver()`. What it does give each row is `self_made`: did I
	# raise this. That is the whole distinction, because you cannot approve your
	# own request.
	#
	# The old expression tested a key that does not exist, then OR'd in
	# `requested_by != user` (right) and `oversight` (wrong). For a director the
	# `oversight` term swallowed their OWN requests into "yours to decide" --
	# decisions the card promised were actionable and were not -- and left
	# `waiting_others` structurally 0, since nothing could fall outside a set
	# that already held everything.
	def _mine_to_raise(a: dict) -> bool:
		return bool(a.get("self_made") or a.get("requested_by") == user)

	decisions = [a for a in all_pending_approvals if isinstance(a, dict) and not _mine_to_raise(a)]

	waiting_others = [a for a in all_pending_approvals if isinstance(a, dict) and _mine_to_raise(a)]

	due_today_cnt = len([i for i in plan_items if i.get("due") == today_str or i.get("severity") == "today"])
	overdue_cnt = len([i for i in plan_items if i.get("severity") == "overdue"])

	counters = {
		"due_today": due_today_cnt,
		"overdue": overdue_cnt,
		"awaiting_me": len(decisions),
		"waiting_others": len(waiting_others),
	}

	# 8. Build 7-day calendar
	calendar_days = []
	for d_offset in range(max(1, days_cnt)):
		dt_cur = today_date + datetime.timedelta(days=d_offset)
		dt_str = dt_cur.isoformat()
		day_items = [i for i in plan_items if i.get("due") == dt_str]
		calendar_days.append({"date": dt_str, "count": len(day_items), "items": day_items[:2]})

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
		# WHICH CALENDAR DAY this answer reasoned with. Every severity, all four
		# counters and the calendar window come off `today_str` above -- the SITE's
		# timezone via frappe.utils.today() -- while the client re-filtered the
		# identical predicate with the browser's local date, because the server had
		# never said what its own date was. Same predicate, different clock: between
		# 00:00 and 05:00 in Tashkent (UTC+5) against a UTC host the two disagree,
		# and the Today chip and the list it filters to then show different numbers,
		# each half internally consistent. `today_str`, not a second read of
		# today(): a request that straddles midnight must not ship counters computed
		# for one day labelled with the next.
		"today": today_str,
		"generated_at": now(),
	}
