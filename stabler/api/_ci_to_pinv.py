"""CI → Purchase Invoice conversion math (WP-I5, Frappe-free, unit-testable).

When a Commercial Invoice is delivered, its ``agreed_total`` moves from virtual
import exposure (design doc §3 layer C) into real GL A/P: a Purchase Invoice is
opened at ``agreed_total`` and the advance Payment Entries already paid to the
supplier are allocated against it. This module does the arithmetic only — line
building, ``agreed_total`` reconciliation, and the greedy advance allocation —
plus the no-double-count invariant that ties back to ``_import_exposure``.

Ground rules (design doc §3.1):
  * The Purchase Invoice opens A/P at ``agreed_total``. ``docs_total`` is a
    customs-declaration figure and NEVER enters the PInv / GL.
  * Advances are real submitted Payment Entries (party = supplier). Allocation
    is greedy: each advance contributes up to its ``unallocated_amount``, capped
    so the running total never exceeds the invoice total.
  * After conversion the CI is "closed" for exposure (``has_purchase_invoice``)
    so the same money is never counted in both exposure and A/P.
"""

from __future__ import annotations


def _amt(v) -> float:
	try:
		return float(v or 0)
	except (TypeError, ValueError):
		return 0.0


def reconciles(a, b, eps: float = 0.5) -> bool:
	"""True when two money figures agree within ``eps`` (kuruş-level check)."""
	return abs(_amt(a) - _amt(b)) <= eps


def pinv_lines_from_ci_items(items) -> list[dict]:
	"""Purchase Invoice item rows from Commercial Invoice items.

	Carries item_code / qty / rate / amount. Rows without an item are skipped
	(a CI line must reference an item to become a GL A/P line). ``amount`` is
	preserved as given so the invoice total is Σ line amounts — the agreed
	figure, never re-derived from qty×rate (weak-currency truncation, K-rules).
	"""
	lines: list[dict] = []
	for it in items or []:
		row = it or {}
		code = row.get("item") or row.get("item_code")
		if not code:
			continue
		lines.append(
			{
				"item_code": code,
				"qty": _amt(row.get("qty")),
				"rate": _amt(row.get("rate")),
				"amount": _amt(row.get("amount")),
			}
		)
	return lines


def lines_total(lines) -> float:
	"""Σ of line ``amount`` (the invoice grand total before taxes)."""
	return round(sum(_amt((ln or {}).get("amount")) for ln in (lines or [])), 2)


def plan_advance_allocation(invoice_total, advances) -> dict:
	"""Greedily allocate advance Payment Entries against an invoice total.

	``advances`` = iterable of {name, unallocated_amount}. Each advance
	contributes up to its unallocated amount, capped so the running allocation
	never exceeds ``invoice_total``. When rows carry ``proforma_invoice``,
	``ci_amount`` and ``advance_percentage``, every PI gets one proportional cap
	shared by all of its bank/cash Payment Entries. Returns the per-advance plan
	plus the remaining outstanding the supplier must still be paid.
	"""
	remaining = round(_amt(invoice_total), 2)
	allocations: list[dict] = []
	pi_remaining: dict[str, float] = {}
	for adv in advances or []:
		a = adv or {}
		pi = str(a.get("proforma_invoice") or "").strip()
		if not pi or pi in pi_remaining:
			continue
		pct = _amt(a.get("advance_percentage"))
		ci_amount = _amt(a.get("ci_amount"))
		pi_remaining[pi] = round(max(ci_amount * pct / 100.0, 0.0), 2)
	for adv in advances or []:
		a = adv or {}
		if remaining <= 0:
			break
		avail = max(_amt(a.get("unallocated_amount")) - _amt(a.get("reserved_amount")), 0.0)
		if avail <= 0:
			continue
		pi = str(a.get("proforma_invoice") or "").strip()
		pi_cap = pi_remaining.get(pi) if pi else None
		if pi_cap is not None and pi_cap <= 0:
			continue
		alloc = round(min(avail, remaining, pi_cap if pi_cap is not None else remaining), 2)
		if alloc <= 0:
			continue
		allocations.append({"payment_entry": a.get("name"), "amount": alloc})
		remaining = round(remaining - alloc, 2)
		if pi_cap is not None:
			pi_remaining[pi] = round(pi_cap - alloc, 2)
	total_allocated = round(sum(x["amount"] for x in allocations), 2)
	return {
		"allocations": allocations,
		"total_allocated": total_allocated,
		"outstanding_after": round(_amt(invoice_total) - total_allocated, 2),
	}


def build_pi_advance_ledger(*, pi_total, advance_percentage, payments, ci_movements) -> dict:
	"""Build the audit-friendly running ledger shown on PI and CI screens.

	Draft Payment Entries stay visible but contribute no available credit. Draft
	Purchase Invoices reserve their proportional share; submitted invoices move
	the same amount into the posted allocation bucket.
	"""
	total = round(_amt(pi_total), 2)
	pct = round(_amt(advance_percentage), 2)
	events: list[dict] = []
	advance_paid = 0.0
	for payment in payments or []:
		row = payment or {}
		posted = int(_amt(row.get("docstatus"))) == 1
		paid_amount = round(_amt(row.get("paid_amount")), 2) if posted else 0.0
		usable_amount = row.get("usable_amount") if "usable_amount" in row else paid_amount
		usable_amount = round(_amt(usable_amount), 2) if posted else 0.0
		advance_paid = round(advance_paid + paid_amount, 2)
		events.append(
			{
				"posting_date": row.get("posting_date"),
				"entry_type": "Advance Payment",
				"reference": row.get("name"),
				"status": row.get("ledger_status") or ("Posted" if posted else "Pending Approval"),
				"ci_amount": 0.0,
				"advance_in": usable_amount,
				"requested_advance_out": 0.0,
				"sort_order": 0,
			}
		)

	for movement in ci_movements or []:
		row = movement or {}
		ci_amount = round(_amt(row.get("ci_amount")), 2)
		status = row.get("status") if row.get("status") in {"Posted", "Planned"} else "Unallocated"
		requested = row.get("advance_out")
		if requested is None:
			requested = ci_amount * pct / 100.0 if status != "Unallocated" else 0.0
		events.append(
			{
				"posting_date": row.get("posting_date"),
				"entry_type": {
					"Posted": "CI Allocation",
					"Planned": "CI Reservation",
					"Unallocated": "CI Created",
				}[status],
				"reference": row.get("ci_name"),
				"purchase_invoice": row.get("purchase_invoice"),
				"status": status,
				"ci_amount": ci_amount,
				"advance_in": 0.0,
				"requested_advance_out": round(_amt(requested), 2),
				"sort_order": 1,
			}
		)

	events.sort(
		key=lambda row: (
			str(row.get("posting_date") or ""),
			row["sort_order"],
			str(row.get("reference") or ""),
		)
	)
	running_advance = 0.0
	running_pi = total
	allocated = reserved = total_ci = 0.0
	rows: list[dict] = []
	for event in events:
		running_advance = round(running_advance + event["advance_in"], 2)
		advance_out = round(min(event["requested_advance_out"], running_advance), 2)
		running_advance = round(running_advance - advance_out, 2)
		ci_amount = event["ci_amount"]
		if ci_amount > 0:
			total_ci = round(total_ci + ci_amount, 2)
			running_pi = round(max(total - total_ci, 0.0), 2)
			if event["status"] == "Posted":
				allocated = round(allocated + advance_out, 2)
			elif event["status"] == "Planned":
				reserved = round(reserved + advance_out, 2)
		rows.append(
			{
				"posting_date": event.get("posting_date"),
				"entry_type": event["entry_type"],
				"reference": event.get("reference"),
				"purchase_invoice": event.get("purchase_invoice"),
				"status": event["status"],
				"pi_total_cost": total,
				"ci_amount": ci_amount,
				"advance_in": event["advance_in"],
				"advance_out": advance_out,
				"running_advance_balance": running_advance,
				"running_pi_cost": running_pi,
				"ci_outstanding": round(max(ci_amount - advance_out, 0.0), 2),
			}
		)

	return {
		"summary": {
			"pi_total_cost": total,
			"advance_percentage": pct,
			"advance_paid": advance_paid,
			"advance_allocated": allocated,
			"advance_reserved": reserved,
			"advance_available": round(max(running_advance, 0.0), 2),
			"total_ci_amount": total_ci,
			"remaining_pi_cost": round(max(total - total_ci, 0.0), 2),
			"remaining_vendor_payments": round(max(total - advance_paid, 0.0), 2),
		},
		"rows": rows,
	}


def invoice_drift(agreed_total, ci_lines, invoiced_total, pinv_lines, eps: float = 0.5) -> dict:
	"""What the CI says NOW versus what its Purchase Invoice actually booked.

	A Commercial Invoice keeps living after it is invoiced — a price is
	corrected, a line is added, boxes are re-counted. The submitted Purchase
	Invoice cannot follow along (ERPNext submitted docs are immutable), so the
	two quietly diverge and the A/P stops describing the deal. This compares
	them and names the difference; nothing is repaired here.

	Sign convention: ``delta_total`` positive = the CI now claims MORE than was
	invoiced (we under-booked the payable). Line comparison is by item code,
	summed per item (a CI may carry the same item on several lines).

	Never clamps: an over-booked invoice shows a negative delta rather than
	being hidden behind max(0, …).
	"""

	def _by_item(lines):
		out: dict[str, dict] = {}
		for ln in lines or []:
			row = ln or {}
			code = row.get("item_code") or row.get("item")
			if not code:
				continue
			cur = out.setdefault(str(code), {"qty": 0.0, "amount": 0.0})
			cur["qty"] = round(cur["qty"] + _amt(row.get("qty")), 4)
			cur["amount"] = round(cur["amount"] + _amt(row.get("amount")), 2)
		return out

	now, booked = _by_item(ci_lines), _by_item(pinv_lines)
	changed, added, removed = [], [], []
	for code in sorted(set(now) | set(booked)):
		a, b = now.get(code), booked.get(code)
		if a and not b:
			added.append({"item_code": code, "amount": a["amount"], "qty": a["qty"]})
		elif b and not a:
			removed.append({"item_code": code, "amount": b["amount"], "qty": b["qty"]})
		elif not reconciles(a["amount"], b["amount"], eps) or abs(a["qty"] - b["qty"]) > 0.0001:
			changed.append(
				{
					"item_code": code,
					"amount_now": a["amount"],
					"amount_booked": b["amount"],
					"qty_now": a["qty"],
					"qty_booked": b["qty"],
					"delta": round(a["amount"] - b["amount"], 2),
				}
			)

	delta_total = round(_amt(agreed_total) - _amt(invoiced_total), 2)
	return {
		"in_sync": abs(delta_total) <= eps and not (changed or added or removed),
		"agreed_total": round(_amt(agreed_total), 2),
		"invoiced_total": round(_amt(invoiced_total), 2),
		"delta_total": delta_total,
		"lines_changed": changed,
		"lines_added": added,
		"lines_removed": removed,
	}


def no_double_count(exposure_before, exposure_after, pinv_total, eps: float = 0.5) -> bool:
	"""Invariant: the exposure that a conversion removes equals the A/P it opens.

	The agreed_total leaves virtual import exposure (layer C) and appears on the
	Purchase Invoice (real A/P). If both moved by the same amount, the money was
	never counted twice and never vanished into a gap.
	"""
	return reconciles(_amt(exposure_before) - _amt(exposure_after), pinv_total, eps)
