"""Central monetary-tolerance helper (Frappe-free, unit-testable).

A monetary residual is "zero" only if it is smaller than half the currency's
smallest representable unit. That threshold is currency metadata, NOT the
hard-coded ``0.005`` that was scattered across the API layer:

  * 2-dp currencies (USD, EUR, UZS, ...) -> 0.005   (half a cent)
  * 0-dp currencies (JPY, KRW, VND, ...) -> 0.5     (half a whole unit)
  * 3-dp currencies (BHD, KWD, OMR)      -> 0.0005

Which class a currency falls into is a property of THE SITE, not of ISO 4217 —
see the note over ``ZERO_DECIMAL_CURRENCIES``. UZS sat in the 0-dp class until
2026-08-20 on the tiyin argument; ERPNext stores it at precision 2 on every
tenant, so ``0.5`` was calling forty kopecks of recorded difference "noise".

The zero-decimal currency set lives in one place (``_fx_residual``); this module
reuses it so there is a single source of truth for currency precision.
"""

from __future__ import annotations

from stabler.api._fx_residual import base_precision_for

# Backward-compatible default: half a cent, for an unknown/2-dp currency.
DEFAULT_MONEY_EPSILON = 0.005


def money_epsilon(currency: str | None = None) -> float:
	"""Half the smallest representable unit of ``currency``.

	Residuals with absolute value below this are treated as zero. When
	``currency`` is unknown, falls back to the 2-dp default (0.005), so existing
	2-dp call sites keep identical behaviour.
	"""
	precision = base_precision_for(currency)
	if precision <= 0:
		# Whole-unit currency (UZS, JPY, ...): half of one unit.
		return 0.5
	return 0.5 * (10.0**-precision)
