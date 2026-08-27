"""Pure discount → net-rate math for transaction lines — no frappe, unit-testable.

ERPNext derives a line's `rate` from `price_list_rate × (1 − discount_percentage/100)`
only when `rate` is empty, or when a Pricing Rule is attached — see
erpnext/controllers/taxes_and_totals.py::calculate_item_values. Stabler writes
`rate` itself on every line it builds, so that branch never ran and the discount
fields never reached the money: `amount` stayed at qty × the full rate, and
`discount_amount` was then overwritten by the same function with
`price_list_rate − rate`, erasing a per-unit discount outright.

The SPA meanwhile computes qty × rate × (1 − pct/100) for the same line, so the
screen showed a discount the document did not have. Measured on anjan
2026-08-27: SAL-ORD-2026-15847 carried 4 % on all thirteen lines and a grand
total identical to the undiscounted sum.

So the discount is applied HERE, before the line reaches ERPNext. The rate we
are handed is the line's GROSS unit price; `rate` becomes the net price and
`price_list_rate` keeps the gross — which is also what makes ERPNext recompute
`discount_amount` back to exactly the discount that was entered instead of to
a rounding artefact.

The rule is ERPNext's own and must stay identical to the SPA's copy in
public/js/pages/sales/SalesOrderLines.vue: percentage WINS over amount, and
`discount_amount` is a per-UNIT reduction (rate − amount), never a sum taken off
the whole line.
"""

from __future__ import annotations


def net_rate(rate, discount_percentage=0.0, discount_amount=0.0) -> float:
	"""The unit rate ERPNext should bill, after the line discount.

	Clamped at zero: a discount can make a line free, never negative.
	"""
	gross = float(rate or 0.0)
	pct = float(discount_percentage or 0.0)
	amount = float(discount_amount or 0.0)
	if pct > 0:
		return max(gross * (1.0 - pct / 100.0), 0.0)
	if amount > 0:
		return max(gross - amount, 0.0)
	return gross
