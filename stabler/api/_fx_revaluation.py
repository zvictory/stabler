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

`find_unpriced_positions` is the one function here that is not arithmetic: it
decides which positions must not be revalued at all, because the formula above
is only meaningful when someone actually published `new_rate`.
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
	except (InvalidOperation, TypeError, ValueError):
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


def find_unpriced_positions(positions) -> list[dict]:
	"""Return the positions that would be revalued at a rate nobody published.

	Why this exists rather than a reminder to publish the rate: nothing on the
	ERPNext path treats a missing rate as an error.

	  * `erpnext/setup/utils.py:145-154` — no Currency Exchange row, the external
	    API attempt fails, `except` returns **0.0**.  With Currency Exchange
	    Settings disabled it returns 0.0 even earlier (:98-99).
	  * `erpnext/accounts/doctype/exchange_rate_revaluation/`
	    `exchange_rate_revaluation.py:264-266` — `new_exchange_rate = 0`, so
	    `new_balance_in_base_currency = balance x 0 = 0`, and the row's
	    `gain_loss` becomes the negative of the whole book value.

	A drawer holding real money is therefore revalued to ZERO and its entire
	balance is booked as an FX loss, with no exception raised anywhere on that
	path.  The silence is the defect; this function is what breaks it.  USDT is
	the live instance (ADR-006 makes a USDT desk an ordinary Cash leaf, and
	`tasks/cbu_rate_refresh.py` has no USDT source), but the rule is not about
	USDT: any currency whose rate was never written fails the same way.

	Parameters
	----------
	positions:
		Iterable of mappings with keys ``account``, ``currency``, ``balance``
		(in the *account* currency), ``balance_base`` (the same position in the
		*base* currency) and ``rate`` (account ccy -> base).

	Returns
	-------
	The subset that still holds money on **both** sides of the ledger while
	``rate`` is zero, negative or non-numeric, each as
	``{account, currency, balance, rate}`` with Decimal amounts.  Empty list =
	every position is priced.

	Both balances are read because ERPNext's own zero-balance handling is an
	OR, not an XOR (`exchange_rate_revaluation.py:243-244`):

	    acc.zero_balance = True if (acc.balance == 0
	                                or acc.balance_in_account_currency == 0) else False

	and *every* row it marks that way is given `new_exchange_rate = 0`
	deliberately.  The two sub-cases split at :287:

	  * account-currency balance zero, base balance not — a drained drawer with
	    a base-currency residue; the row is zeroed and written off (:287-292).
	  * base balance zero, account-currency balance not — the netted
	    foreign-currency receivable/payable the zero_balance branch exists to
	    clear.  Its else-branch (:293-305) writes rate 0 **and** a non-zero
	    `gain_loss`, so the row survives `fetch_and_calculate_accounts_data`
	    and `remove_accounts_without_gain_loss` and reaches this rule intact.

	Reading ``balance`` alone therefore refuses a document ERPNext produced
	correctly, and refuses it with no way out: ERPNext forces rate 0 on those
	rows whatever Currency Exchange says, so the Currency Exchange record the
	refusal demands would not clear it.  We derive the condition from the two
	balances rather than from the ``zero_balance`` field so the rule keeps
	holding if that flag's definition changes — the flag is a conclusion drawn
	from these same two numbers, and it is stored on a document a Desk user can
	edit.

	A ``balance_base`` that is absent or ``None`` is **not** a zero: only a
	value that is actually there and actually zero earns the exemption, so a
	caller that forgets to map the field keeps being refused rather than
	switching the guard off silently.

	A negative balance — a foreign-currency liability — is flagged like any
	other: zeroing a debt fabricates a gain exactly as zeroing an asset
	fabricates a loss.
	"""
	unpriced = []
	for p in positions or []:
		balance = _d(p.get("balance"))
		if balance == 0:
			continue
		balance_base = p.get("balance_base")
		if balance_base is not None and _d(balance_base) == 0:
			continue
		rate = _d(p.get("rate"))
		if rate > 0:
			continue
		unpriced.append(
			{
				"account": p.get("account") or "",
				"currency": p.get("currency") or "",
				"balance": balance,
				"rate": rate,
			}
		)
	return unpriced
