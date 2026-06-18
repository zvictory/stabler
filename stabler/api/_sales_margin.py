"""Pure margin math for the Sales Reports page — no frappe import, unit-testable.

Revenue and COGS must both be in the SAME currency (we use company/base currency
in the SQL: base_net_amount for revenue, qty * base-currency cost for COGS), so
margin and margin % are always currency-consistent.
"""

from __future__ import annotations


def margin_fields(revenue_base, cogs_base) -> dict:
	"""Return {margin, margin_pct} from base-currency revenue and COGS.

	- margin = revenue - cogs, rounded to 2 dp.
	- margin_pct = margin / revenue * 100, rounded to 1 dp; 0.0 when revenue is 0
	  (avoid divide-by-zero; a zero-revenue group has no meaningful percentage).
	"""
	rev = float(revenue_base or 0)
	cogs = float(cogs_base or 0)
	margin = round(rev - cogs, 2)
	pct = round((rev - cogs) / rev * 100, 1) if rev else 0.0
	return {"margin": margin, "margin_pct": pct}


def attach_margins(rows, *, revenue_key: str = "base_net_revenue", cogs_key: str = "cogs"):
	"""Mutate each row dict in place, adding `margin` and `margin_pct`."""
	for r in rows:
		r.update(margin_fields(r.get(revenue_key), r.get(cogs_key)))
	return rows
