"""Pure helpers for the multi-currency Payment Entry rounding residual.

When a foreign-currency payable is settled, the invoice was translated to the
company (reporting) currency at one rate and the payment at another — or at the
same rate but rounded per-invoice across several references. The sub-cent
residual in BASE currency is a realized exchange gain/loss (IAS 21 §28 /
ASC 830-20-35-1), not a user error. ERPNext blocks submit with
"Difference Amount must be zero"; the fix is to auto-book a tiny residual to the
company Exchange Gain/Loss account, keeping the transaction-currency amount
(the user-typed amount) as ground truth.

This module only decides *whether* a difference is a tolerable rounding residual
and how large the tolerance is. The Frappe layer (money.py) does the booking.
Frappe-free so it runs under `python -m unittest`.
"""

from __future__ import annotations

# Currencies ERPNext stores with zero decimal places (smallest unit = 1).
# A "penny" residual in these currencies is a whole unit, not 0.01.
ZERO_DECIMAL_CURRENCIES = frozenset(
	{
		"UZS",
		"JPY",
		"KRW",
		"VND",
		"IDR",
		"CLP",
		"PYG",
		"RWF",
		"XOF",
		"XAF",
		"BIF",
		"DJF",
		"GNF",
		"KMF",
		"MGA",
		"VUV",
		"XPF",
		"ISK",
		"HUF",
	}
)


def base_precision_for(currency: str | None) -> int:
	"""Decimal places for a currency's base amounts (0 for whole-unit currencies)."""
	return 0 if (currency or "").upper() in ZERO_DECIMAL_CURRENCIES else 2


def residual_tolerance(n_references: int, base_precision: int = 2) -> float:
	"""Largest base-currency difference still treated as a rounding residual.

	Each allocated invoice can contribute up to one smallest-unit of rounding,
	so the tolerance scales with the number of references (plus a small cushion).
	A difference larger than this is a real allocation error, not rounding.
	"""
	unit = 10.0 ** (-base_precision) if base_precision > 0 else 1.0
	n = n_references if isinstance(n_references, int) and n_references > 0 else 0
	tol = unit * (n + 2)
	return round(tol, base_precision) if base_precision > 0 else tol


def within_tolerance(difference_amount, tolerance) -> bool:
	"""True only for a non-zero difference no larger than the tolerance."""
	try:
		d = abs(float(difference_amount))
		tol = float(tolerance)
	except TypeError, ValueError:
		return False
	return 0.0 < d <= tol + 1e-9
