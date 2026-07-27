"""Pure FX-revaluation helpers — no Frappe, no DB.

Computes the unrealised gain/loss delta for a single foreign-currency account
balance when the current market rate differs from the rate already in the books.

Formula (IAS 21 §23 / ASC 830-20-35):
    delta = balance_in_account_ccy × (new_rate − book_rate)

A positive delta means the base-currency value has risen → unrealised GAIN.
A negative delta means the base-currency value has fallen → unrealised LOSS.

Precision contract:
  * All monetary arithmetic uses Python Decimal with ROUND_HALF_UP.
  * `precision` is the number of decimal places for the *base currency*
    (e.g. UZS → 0, USD → 2, KWD → 3).  Caller supplies it from ERPNext
    Currency.smallest_currency_fraction_value metadata; we never hard-code 2.
  * `rate_precision` defaults to 6 (minimum per multi-currency rules); callers
    may pass a larger value for sub-cent currencies.

Garbage-safety:
  * Any non-numeric input is treated as 0.
  * Zero book_rate and zero new_rate both yield delta = 0 (no crash).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _d(v) -> Decimal:
	"""Coerce any value to Decimal; return 0 on garbage."""
	if isinstance(v, Decimal):
		return v
	try:
		return Decimal(str(v))
	except InvalidOperation, TypeError, ValueError:
		return Decimal("0")


def _quantize(value: Decimal, precision: int) -> Decimal:
	"""Round `value` to `precision` decimal places (ROUND_HALF_UP)."""
	places = max(0, int(precision))
	quantum = Decimal(10) ** -places
	return value.quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_fx_delta(
	*,
	balance_in_account_ccy: object,
	new_rate: object,
	book_rate: object,
	precision: int = 2,
	rate_precision: int = 6,
) -> dict:
	"""Compute the unrealised FX gain/loss delta for one account.

	Parameters
	----------
	balance_in_account_ccy:
		The account's net balance expressed in the *account* (foreign) currency.
		Positive = debit-natured asset/expense balance.
		Negative = credit-natured liability/income balance.
	new_rate:
		Current market exchange rate: 1 unit of account currency = `new_rate`
		units of base currency.  Must be ≥ 6 decimal places of precision.
	book_rate:
		The weighted-average rate already reflected in the GL.  Zero or missing
		means no previous revaluation → treated as 0.
	precision:
		Decimal places for the *base* currency (from Currency metadata).
	rate_precision:
		Decimal places to preserve for rates (default 6, minimum per rules).

	Returns
	-------
	dict with keys:
	  balance_in_account_ccy  – Decimal, as supplied (rounded to rate_precision)
	  new_rate                 – Decimal (rounded to rate_precision)
	  book_rate                – Decimal (rounded to rate_precision)
	  rate_diff                – Decimal  (new_rate − book_rate)
	  delta                    – Decimal  gain (+) or loss (−), in base currency
	  gain_loss                – "gain" | "loss" | "nil"
	"""
	rp = max(6, int(rate_precision))
	bal = _quantize(_d(balance_in_account_ccy), rp)
	nr = _quantize(_d(new_rate), rp)
	br = _quantize(_d(book_rate), rp)

	rate_diff = nr - br
	raw_delta = bal * rate_diff
	delta = _quantize(raw_delta, precision)

	if delta > 0:
		gain_loss = "gain"
	elif delta < 0:
		gain_loss = "loss"
	else:
		gain_loss = "nil"

	return {
		"balance_in_account_ccy": bal,
		"new_rate": nr,
		"book_rate": br,
		"rate_diff": rate_diff,
		"delta": delta,
		"gain_loss": gain_loss,
	}


def summarize_revaluation(account_rows: list[dict], base_precision: int = 2) -> dict:
	"""Aggregate per-account deltas into a revaluation summary.

	Each element of `account_rows` must be a dict with keys accepted by
	``compute_fx_delta`` plus ``account`` (str) and optionally ``currency`` (str).

	Returns:
	  {
	    "rows": [per-account result merged with account/currency],
	    "total_gain": Decimal,
	    "total_loss": Decimal,
	    "net_delta": Decimal,   # total_gain + total_loss (loss is negative)
	  }
	"""
	rows = []
	total_gain = Decimal("0")
	total_loss = Decimal("0")

	for r in account_rows or []:
		result = compute_fx_delta(
			balance_in_account_ccy=r.get("balance_in_account_ccy", 0),
			new_rate=r.get("new_rate", 0),
			book_rate=r.get("book_rate", 0),
			precision=base_precision,
		)
		result["account"] = r.get("account", "")
		result["currency"] = r.get("currency", "")
		rows.append(result)
		if result["delta"] > 0:
			total_gain += result["delta"]
		elif result["delta"] < 0:
			total_loss += result["delta"]

	net = _quantize(total_gain + total_loss, base_precision)
	return {
		"rows": rows,
		"total_gain": _quantize(total_gain, base_precision),
		"total_loss": _quantize(total_loss, base_precision),
		"net_delta": net,
	}
