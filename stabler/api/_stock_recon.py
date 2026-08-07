"""Pure stock-reconciliation prep logic — no Frappe, no DB.

Surfacing ERPNext **Stock Reconciliation** (count-to-actual) in the SPA: the
operator enters a physically counted quantity per item/warehouse; ERPNext posts
the Stock Ledger difference on submit. This module does the pure part — figure
out which lines actually changed and summarise the variance — so we send ERPNext
only the lines that differ and can show the operator a clear before/after.

Nothing here writes stock; it only shapes input. Unit tested with no bench.
"""

from __future__ import annotations

_EPS = 1e-6


def _f(v) -> float:
	try:
		return float(v)
	except (TypeError, ValueError):
		return 0.0


def is_changed(current_qty, counted_qty, eps: float = _EPS) -> bool:
	"""True when the counted qty differs from the system qty beyond epsilon."""
	return abs(_f(counted_qty) - _f(current_qty)) > eps


def prepare_reconciliation(rows: list[dict]) -> dict:
	"""From raw count rows, return the changed lines + a variance summary.

	``rows``: [{item_code, warehouse, current_qty, counted_qty, valuation_rate?}].
	Returns {lines, summary}:
	  lines = changed rows only, each with ``qty`` = counted and ``variance_qty`` /
	          ``variance_value``;
	  summary = {changed_count, total_qty_delta, total_value_delta, line_count}.
	"""
	lines: list[dict] = []
	total_qty_delta = 0.0
	total_value_delta = 0.0
	for r in rows or []:
		item = (r.get("item_code") or "").strip()
		warehouse = (r.get("warehouse") or "").strip()
		if not item or not warehouse:
			continue
		current = _f(r.get("current_qty"))
		counted = _f(r.get("counted_qty"))
		if not is_changed(current, counted):
			continue
		val_rate = _f(r.get("valuation_rate"))
		variance_qty = counted - current
		variance_value = variance_qty * val_rate
		total_qty_delta += variance_qty
		total_value_delta += variance_value
		lines.append(
			{
				"item_code": item,
				"warehouse": warehouse,
				"qty": counted,  # the counted (target) qty ERPNext reconciles to
				"current_qty": current,
				"variance_qty": variance_qty,
				"valuation_rate": val_rate,
				"variance_value": variance_value,
			}
		)
	return {
		"lines": lines,
		"summary": {
			"changed_count": len(lines),
			"line_count": len(rows or []),
			"total_qty_delta": total_qty_delta,
			"total_value_delta": total_value_delta,
		},
	}
