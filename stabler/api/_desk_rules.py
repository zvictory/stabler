"""Pure derivation engine for Operations Desk daily work plan (Frappe-free).

Converts a dictionary of system facts into a list of prioritized work items.
Zero manual task persistence: every item is deterministically derived.
"""

from __future__ import annotations

import datetime

from stabler.api import _procurement_policy as _policy

SEVERITY = ["overdue", "today", "soon", "info"]
_SEVERITY_WEIGHT = {s: idx for idx, s in enumerate(SEVERITY)}


def _parse_date(val: str | None) -> datetime.date | None:
	if not val:
		return None
	try:
		return datetime.date.fromisoformat(str(val).strip())
	except (ValueError, TypeError):
		return None


def build_plan(facts: dict | None, today: str) -> dict:
	"""Build the daily work plan from facts.

	Returns:
	    {
	        "items": list[dict],
	        "skipped": int
	    }
	"""
	facts = facts or {}
	items: list[dict] = []
	skipped = 0

	today_date = _parse_date(today)
	if not today_date:
		today_date = datetime.date.today()
		today_str = today_date.isoformat()
	else:
		today_str = today

	# 1. Open Lots (bid_due, bid_soon, policy_gap)
	for lot in facts.get("lots") or []:
		deal = lot.get("deal") or lot.get("name")
		label = lot.get("label") or deal or "Lot"
		stage = (lot.get("stage") or "").lower()
		result = (lot.get("result") or "").lower()
		assigned_to = lot.get("assigned_to")
		sq_count = int(lot.get("sq_count") or 0)
		bid_deadline_raw = lot.get("bid_deadline")

		# Skip closed/finished lots if result is won/lost/cancelled
		if result in ("won", "lost", "cancelled"):
			continue

		bid_deadline = None
		if bid_deadline_raw:
			bid_deadline = _parse_date(bid_deadline_raw)
			if not bid_deadline:
				skipped += 1

		# Check bid_due & bid_soon
		if bid_deadline:
			diff_days = (today_date - bid_deadline).days
			if diff_days > 0:
				items.append(
					{
						"kind": "bid_due",
						"title": f"Bid due: {label}",
						"why": f"Deadline past by {diff_days} day{'s' if diff_days > 1 else ''}",
						"owner": assigned_to,
						"due": bid_deadline_raw,
						"severity": "overdue",
						"route": f"/tender/crm?deal={deal}",
						"reference_doctype": "CRM Deal",
						"reference_name": deal,
					}
				)
			elif diff_days == 0:
				items.append(
					{
						"kind": "bid_due",
						"title": f"Bid due: {label}",
						"why": f"{sq_count}/{_policy.MIN_QUOTATIONS} quotes · deadline today",
						"owner": assigned_to,
						"due": bid_deadline_raw,
						"severity": "today",
						"route": f"/tender/crm?deal={deal}",
						"reference_doctype": "CRM Deal",
						"reference_name": deal,
					}
				)
			elif 0 < (-diff_days) <= 3:
				items.append(
					{
						"kind": "bid_soon",
						"title": f"Bid deadline soon: {label}",
						"why": f"{sq_count}/{_policy.MIN_QUOTATIONS} quotes · deadline in {-diff_days} day{'s' if (-diff_days) > 1 else ''}",
						"owner": assigned_to,
						"due": bid_deadline_raw,
						"severity": "soon",
						"route": f"/tender/crm?deal={deal}",
						"reference_doctype": "CRM Deal",
						"reference_name": deal,
					}
				)

		# Check policy_gap
		if stage == "sourcing" and sq_count < _policy.MIN_QUOTATIONS:
			items.append(
				{
					"kind": "policy_gap",
					"title": f"Missing supplier quotes: {label}",
					"why": f"{sq_count}/{_policy.MIN_QUOTATIONS} quotes collected "
					f"(minimum {_policy.MIN_QUOTATIONS} required)",
					"owner": assigned_to,
					"due": bid_deadline_raw or today_str,
					"severity": "today",
					"route": f"/tender/crm?deal={deal}",
					"reference_doctype": "CRM Deal",
					"reference_name": deal,
				}
			)

	# 2. Orphan Lots (no_parent)
	for o in facts.get("orphan_lots") or []:
		name = o.get("name") or o.get("deal")
		# The row has to name the lot the way its owner would. `name` is the deal
		# id; four lots of the same buyer look identical under it.
		label = o.get("label") or name
		org = o.get("organization") or "—"
		items.append(
			{
				"kind": "no_parent",
				"title": f"Orphan lot without parent tender: {label}",
				"why": f"Organization {org} has no parent tender master",
				"owner": o.get("assigned_to"),
				"due": today_str,
				"severity": "info",
				"route": f"/tender/crm?deal={name}",
				"reference_doctype": "CRM Deal",
				"reference_name": name,
			}
		)

	# 3. Won without PO (won_no_po)
	for w in facts.get("won_without_po") or []:
		if isinstance(w, dict):
			deal_name = w.get("name") or w.get("deal")
			label = w.get("label") or deal_name
			owner = w.get("assigned_to")
		else:
			deal_name = str(w)
			label = deal_name
			owner = None

		items.append(
			{
				"kind": "won_no_po",
				"title": f"Won lot awaiting Purchase Order: {label}",
				"why": "Lot won but no Purchase Order issued",
				"owner": owner,
				"due": today_str,
				"severity": "today",
				"route": f"/tender/crm?deal={deal_name}",
				"reference_doctype": "CRM Deal",
				"reference_name": deal_name,
			}
		)

	# 4. Late Deliveries (po_late)
	for po in facts.get("po_late") or []:
		po_no = po.get("po") or po.get("name")
		supplier = po.get("supplier") or "Supplier"
		sched_raw = po.get("schedule_date")
		per_received = float(po.get("per_received") or 0.0)

		sched_date = _parse_date(sched_raw) if sched_raw else None
		if sched_raw and not sched_date:
			skipped += 1

		if sched_date and sched_date < today_date and per_received < 100.0:
			diff = (today_date - sched_date).days
			items.append(
				{
					"kind": "po_late",
					"title": f"Late delivery: {po_no}",
					"why": f"Supplier {supplier} delivery past by {diff} day{'s' if diff > 1 else ''} ({per_received:.0f}% received)",
					"owner": po.get("owner"),
					"due": sched_raw,
					"severity": "overdue",
					"route": f"/purchasing/orders/{po_no}",
					"reference_doctype": "Purchase Order",
					"reference_name": po_no,
				}
			)

	# 5. Due / Overdue Invoices (invoice_due)
	for inv in facts.get("unpaid") or []:
		name = inv.get("name")
		due_raw = inv.get("due_date")
		outstanding = float(inv.get("outstanding") or 0.0)
		dt = inv.get("doctype") or "Purchase Invoice"

		due_date = _parse_date(due_raw) if due_raw else None
		if due_raw and not due_date:
			skipped += 1

		if due_date and due_date <= today_date:
			diff = (today_date - due_date).days
			if diff > 0:
				severity = "overdue"
				why = f"Overdue by {diff} day{'s' if diff > 1 else ''} (Outstanding: {outstanding:,.2f})"
			else:
				severity = "today"
				why = f"Due today (Outstanding: {outstanding:,.2f})"

			route = f"/purchasing/invoices/{name}" if dt == "Purchase Invoice" else f"/sales/invoices/{name}"
			items.append(
				{
					"kind": "invoice_due",
					"title": f"Invoice payment due: {name}",
					"why": why,
					"owner": inv.get("owner"),
					"due": due_raw,
					"severity": severity,
					"route": route,
					"reference_doctype": dt,
					"reference_name": name,
				}
			)

	# 6. Pending Approvals (approval_pending)
	for app in facts.get("approvals") or []:
		if isinstance(app, dict):
			app_name = app.get("name")
			ref_dt = app.get("reference_doctype") or "Document"
			ref_name = app.get("reference_name") or app_name
			req_by = app.get("requested_by") or "user"
			owner = app.get("assigned_to")
		else:
			app_name = str(app)
			ref_dt = "Document"
			ref_name = app_name
			req_by = "user"
			owner = None

		if ref_dt == "Purchase Order":
			route = f"/purchasing/orders/{ref_name}"
		elif ref_dt == "Purchase Invoice":
			route = f"/purchasing/invoices/{ref_name}"
		elif ref_dt in ("CRM Deal", "Tender"):
			route = f"/tender/crm?deal={ref_name}"
		else:
			route = f"/approvals/{app_name}"

		items.append(
			{
				"kind": "approval_pending",
				"title": f"Approval required: {ref_dt} {ref_name}",
				"why": f"Requested by {req_by}",
				"owner": owner,
				"due": today_str,
				"severity": "today",
				"route": route,
				"reference_doctype": ref_dt,
				"reference_name": ref_name,
			}
		)

	# Sort items deterministically: severity_weight -> due -> title
	def _sort_key(item: dict):
		sev_w = _SEVERITY_WEIGHT.get(item.get("severity", "info"), 99)
		due_s = item.get("due") or "9999-99-99"
		title_s = item.get("title") or ""
		return (sev_w, due_s, title_s)

	items.sort(key=_sort_key)

	return {"items": items, "skipped": skipped}
