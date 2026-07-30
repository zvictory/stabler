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
	never exceeds ``invoice_total``. Returns the per-advance plan plus the
	remaining outstanding the supplier must still be paid.
	"""
	remaining = round(_amt(invoice_total), 2)
	allocations: list[dict] = []
	for adv in advances or []:
		a = adv or {}
		if remaining <= 0:
			break
		avail = _amt(a.get("unallocated_amount"))
		if avail <= 0:
			continue
		alloc = round(min(avail, remaining), 2)
		if alloc <= 0:
			continue
		allocations.append({"payment_entry": a.get("name"), "amount": alloc})
		remaining = round(remaining - alloc, 2)
	total_allocated = round(sum(x["amount"] for x in allocations), 2)
	return {
		"allocations": allocations,
		"total_allocated": total_allocated,
		"outstanding_after": round(_amt(invoice_total) - total_allocated, 2),
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
					"amount_now": a["amount"], "amount_booked": b["amount"],
					"qty_now": a["qty"], "qty_booked": b["qty"],
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
