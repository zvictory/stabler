"""Pure remittance pricing — no Frappe, no DB.

One percentage, one rounding, three figures (ADR-002 of
``docs/plans/2026-08-16-remittance-operations-center.md``)::

    Exclusive   the cashier types the principal P
                commission = round(P * pct / 100)
                tendered   = P + commission           <- the plug, never rounded

    Inclusive   the cashier types the tendered amount T
                commission = round(T * pct / (100 + pct))
                principal  = T - commission           <- the plug, never rounded

The percentage is always a percentage **of the principal**, in both modes. That
is what lets one sentence ("our commission is 1%") mean one thing: at 1%,
Exclusive 1000 charges 10.00 and Inclusive 1000 charges 9.90 — both are exactly
1% of their own principal.

Rounding is HALF_UP at the currency's precision. One rule, no per-currency
branch. Exactly one figure per branch is rounded and the third is the plug, so
``principal + commission == tendered`` closes to the minor unit by construction
rather than by a second rounding.

The two modes are **not** inverses (ADR-007, measured over 55,000 consecutive
minor units: 274 amounts drift at pct 0.50, 545 at pct 1.00, always by exactly
one minor unit). Deriving the principal first and plugging the commission drifts
on the same count, so no reordering of the formula repairs it. Therefore the
caller stores the triple this function returns and never recomputes it on a read
path — receipt, detail, refund and reconciliation all read the stored figures.

Garbage safety, deliberately unlike ``_budget.py`` and ``_fx_revaluation.py``,
which coerce junk to 0: here the inputs are what a cashier typed against real
cash on the counter, and a silent 0 would price a transfer at no commission or
hand back a triple the doctype then refuses to store. Every bad input raises
``PricingError`` instead.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: Canonical modes. These are the Remittance Transfer ``commission_mode`` Select
#: options verbatim — the July helper spelled them lower-case, which would have
#: matched no stored row.
EXCLUSIVE = "Exclusive"
INCLUSIVE = "Inclusive"
MODES = (EXCLUSIVE, INCLUSIVE)

_MODES_BY_KEY = {mode.lower(): mode for mode in MODES}

_HUNDRED = Decimal("100")


class PricingError(ValueError):
	"""Refuse to price rather than return a triple that cannot be stored."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _d(value: object, label: str) -> Decimal:
	"""Coerce to Decimal; raise rather than invent a number."""
	if isinstance(value, Decimal):
		return value
	try:
		# str() first: Decimal(0.1) would carry the binary tail into the cent.
		return Decimal(str(value).strip())
	except (InvalidOperation, TypeError, ValueError):
		raise PricingError(f"{label} is not a number: {value!r}") from None


def _quantize(value: Decimal, precision: int) -> Decimal:
	"""Round to `precision` decimal places (ROUND_HALF_UP)."""
	quantum = Decimal(10) ** -precision
	return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _normalise_mode(mode: object) -> str:
	try:
		key = str(mode).strip().lower()
	except (TypeError, ValueError):
		key = ""
	if key not in _MODES_BY_KEY:
		raise PricingError(f"commission_mode must be one of {MODES}, not {mode!r}")
	return _MODES_BY_KEY[key]


def _normalise_precision(precision: object) -> int:
	try:
		places = int(precision)
	except (TypeError, ValueError):
		raise PricingError(f"precision is not a whole number: {precision!r}") from None
	if places < 0:
		raise PricingError(f"precision cannot be negative: {precision!r}")
	return places


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def price_transfer(
	*,
	mode: object,
	amount: object,
	commission_pct: object,
	precision: int = 2,
) -> dict:
	"""Price one transfer from the single figure the cashier typed.

	Parameters
	----------
	mode:
		``"Exclusive"`` (`amount` is the principal) or ``"Inclusive"``
		(`amount` is what the customer puts on the counter). Matched
		case-insensitively; anything else raises.
	amount:
		The typed figure, in the send currency. Must already be expressible at
		`precision` — see the currency-precision guard below.
	commission_pct:
		Percentage of the principal, as typed by the cashier (``1.00`` = 1%).
		Zero is valid and means a free transfer.
	precision:
		Decimal places of the **send** currency, from ERPNext Currency
		metadata (UZS → 0, USD → 2). Never hard-coded per currency here.

	Returns
	-------
	dict:
	  mode            – str, canonical
	  commission_pct  – Decimal, as supplied
	  principal       – Decimal, the base the percentage was applied to
	  commission      – Decimal, the only rounded figure
	  tendered        – Decimal, what the customer hands over
	  precision       – int, the precision all three are expressed at

	Raises
	------
	PricingError:
	  * non-numeric or non-positive `amount`, negative `commission_pct`
	  * `amount` carrying more decimals than the currency has — accepting it
	    would round the plug at storage time and break the triple
	  * Inclusive pricing where the commission would swallow the whole
	    principal, which is what Remittance Transfer.validate() rejects
	"""
	mode = _normalise_mode(mode)
	places = _normalise_precision(precision)

	pct = _d(commission_pct, "commission_pct")
	if pct < 0:
		raise PricingError(f"commission_pct cannot be negative: {commission_pct!r}")

	typed = _d(amount, "amount")
	if typed <= 0:
		raise PricingError(f"amount must be positive: {amount!r}")
	if typed != _quantize(typed, places):
		raise PricingError(
			f"amount {typed} carries more than {places} decimal places; "
			"a sub-unit amount cannot be stored and would break the triple"
		)

	if mode == EXCLUSIVE:
		principal = typed
		commission = _quantize(principal * pct / _HUNDRED, places)
		tendered = principal + commission
	else:
		tendered = typed
		commission = _quantize(tendered * pct / (_HUNDRED + pct), places)
		principal = tendered - commission
		if principal <= 0:
			raise PricingError(f"commission {commission} cannot be the whole amount tendered {tendered}")

	return {
		"mode": mode,
		"commission_pct": pct,
		"principal": principal,
		"commission": commission,
		"tendered": tendered,
		"precision": places,
	}
