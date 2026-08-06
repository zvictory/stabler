"""Pure budget-variance helpers — no Frappe, no DB.

Computes variance between a budgeted amount and the actual amount for one
account/cost-centre/period cell, plus a rolled-up summary across multiple cells.

Terminology (standard management-accounting convention):
  For revenue accounts:  actual > budget → FAVORABLE  (we earned more than planned)
  For cost accounts:     actual < budget → FAVORABLE  (we spent less than planned)
  The caller supplies `account_type` to indicate which convention applies.

  "account_type" accepted values:
    * "Income"  / "income"  / "revenue" → revenue convention
    * anything else (Expense, Liability, Asset, …) → cost convention

Divide-by-zero safety: variance_pct is None when budget is 0.
Garbage-safety: non-numeric inputs are treated as 0.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_INCOME_TYPES = {"income", "revenue"}  # lower-cased


def _d(v) -> Decimal:
	"""Coerce to Decimal; 0 on garbage."""
	if isinstance(v, Decimal):
		return v
	try:
		return Decimal(str(v))
	except InvalidOperation, TypeError, ValueError:
		return Decimal("0")


def _quantize(value: Decimal, precision: int = 2) -> Decimal:
	places = max(0, int(precision))
	quantum = Decimal(10) ** -places
	return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _is_income(account_type: str) -> bool:
	return (account_type or "").strip().lower() in _INCOME_TYPES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_variance(
	*,
	budget: object,
	actual: object,
	account_type: str = "Expense",
	precision: int = 2,
) -> dict:
	"""Compute variance for one budget cell.

	Parameters
	----------
	budget:
		Planned amount (base currency).  Zero is valid (means no budget allocated).
	actual:
		Actual amount realised in the period.
	account_type:
		ERPNext Account.account_type value.  Controls favorable/unfavorable
		interpretation.  "Income" / "revenue" → higher actual is favorable;
		anything else → lower actual is favorable.
	precision:
		Decimal places for monetary output.

	Returns
	-------
	dict:
	  budget          – Decimal
	  actual          – Decimal
	  variance        – Decimal  (actual − budget; positive = we exceeded budget)
	  variance_pct    – Decimal | None  (None when budget == 0)
	  status          – "favorable" | "unfavorable" | "on_budget"
	  account_type    – str, as supplied
	"""
	b = _quantize(_d(budget), precision)
	a = _quantize(_d(actual), precision)
	variance = _quantize(a - b, precision)

	# variance_pct: percentage relative to budget (may be negative)
	if b == 0:
		variance_pct = None
	else:
		raw_pct = (variance / b) * Decimal("100")
		variance_pct = _quantize(raw_pct, 2)

	# Favorable/unfavorable
	income = _is_income(account_type)
	if variance == 0:
		status = "on_budget"
	elif income:
		# For income: actual > budget is favorable
		status = "favorable" if variance > 0 else "unfavorable"
	else:
		# For costs: actual < budget is favorable (we underspent)
		status = "favorable" if variance < 0 else "unfavorable"

	return {
		"budget": b,
		"actual": a,
		"variance": variance,
		"variance_pct": variance_pct,
		"status": status,
		"account_type": account_type,
	}


def compute_variance_report(rows: list[dict], precision: int = 2) -> dict:
	"""Aggregate compute_variance across multiple budget rows.

	Each element of `rows` must have at minimum:
	  account, period, budget, actual
	And optionally: cost_center, account_type, currency.

	Returns:
	  {
	    "rows": [each row merged with its compute_variance result],
	    "totals": {budget, actual, variance},
	    "favorable_count": int,
	    "unfavorable_count": int,
	    "on_budget_count": int,
	  }
	"""
	out_rows = []
	total_budget = Decimal("0")
	total_actual = Decimal("0")
	total_variance = Decimal("0")
	counts = {"favorable": 0, "unfavorable": 0, "on_budget": 0}

	for r in rows or []:
		result = compute_variance(
			budget=r.get("budget", 0),
			actual=r.get("actual", 0),
			account_type=r.get("account_type", "Expense"),
			precision=precision,
		)
		merged = dict(r)
		merged.update(result)
		out_rows.append(merged)
		total_budget += result["budget"]
		total_actual += result["actual"]
		total_variance += result["variance"]
		counts[result["status"]] = counts.get(result["status"], 0) + 1

	return {
		"rows": out_rows,
		"totals": {
			"budget": _quantize(total_budget, precision),
			"actual": _quantize(total_actual, precision),
			"variance": _quantize(total_variance, precision),
		},
		"favorable_count": counts.get("favorable", 0),
		"unfavorable_count": counts.get("unfavorable", 0),
		"on_budget_count": counts.get("on_budget", 0),
	}
