"""Whole-UZS residual allocation for payroll (Frappe-free, unit-testable).

UZS has no fractional unit, so every amount that hits the ledger must be a whole
so'm. When several amounts are rounded independently, the sum of the rounded
parts drifts from the rounded total by a few so'm — the "rounding residual".
Silently tolerating that residual (the old ``slip_variance`` ±1000 UZS band)
leaves the itemised component rows failing to tie out to the engine's net pay.

This module allocates the residual deterministically with the **largest-
remainder (Hamilton) method**: round every part down/half-up, then hand the
leftover so'm one at a time to the parts whose dropped fraction was largest, so:

    sum(rounded_parts) == round(target_total)      exactly, always.

Both helpers are pure functions over floats/Decimals and run under plain
``python -m unittest``. The Frappe service layer supplies the raw amounts and
persists the whole-UZS results.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def _d(value) -> Decimal:
	"""Coerce to Decimal via str() so float artefacts don't leak in."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value or 0))


def _round_half_up(value: Decimal) -> int:
	"""Round a Decimal to the nearest whole unit, half away from zero."""
	return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_uzs(value) -> int:
	"""Round any number to whole UZS, half away from zero (single source of
	truth for whole-so'm rounding — replaces scattered ``math.floor(x + 0.5)``,
	which drifts for negative amounts and on float-representation edge cases)."""
	return _round_half_up(_d(value))


def largest_remainder_round(values, target_total=None) -> list[int]:
	"""Round ``values`` to whole UZS so they sum EXACTLY to the rounded target.

	Args:
		values: iterable of numbers (float/Decimal/int) — the raw part amounts.
		target_total: the whole this must sum to. When ``None``, the target is
			``round(sum(values))`` — i.e. make the parts self-consistent.

	Returns:
		A list of ints, same length/order as ``values``, whose sum equals
		``round(target_total)``. Signs are preserved. An empty input returns
		an empty list.

	Method (largest-remainder / Hamilton):
		1. floor each value toward zero-adjusted half-up base, tracking the
		   fractional remainder that was dropped;
		2. the leftover so'm (target − sum of bases) is handed out one unit at a
		   time to the parts with the largest remainders (or reclaimed from the
		   smallest when the residual is negative).
	"""
	vals = [_d(v) for v in values]
	if not vals:
		return []

	target = _round_half_up(sum(vals)) if target_total is None else _round_half_up(_d(target_total))

	# Base = truncate toward zero; remainder = signed fractional part.
	bases = [int(v.to_integral_value(rounding="ROUND_DOWN")) for v in vals]
	remainders = [v - _d(b) for v, b in zip(vals, bases, strict=True)]

	residual = target - sum(bases)
	# Hand out (or reclaim) whole units by remainder magnitude.
	order = sorted(range(len(vals)), key=lambda i: remainders[i], reverse=(residual >= 0))
	step = 1 if residual >= 0 else -1
	for k in range(abs(int(residual))):
		bases[order[k % len(order)]] += step
	return bases


def distribute_amount(total, weights) -> list[int]:
	"""Split a whole-UZS ``total`` across recipients by ``weights``.

	Every share is a whole so'm and the shares sum EXACTLY to ``round(total)``
	— the canonical use is splitting a KPI/bonus pool across employees, or a
	prorated base across periods, without losing or inventing a so'm.

	Args:
		total: the pool to distribute (rounded to whole UZS internally).
		weights: iterable of non-negative weights (float/Decimal/int).

	Returns:
		A list of ints, one per weight, summing to ``round(total)``. When all
		weights are zero (or empty), the residual falls on the first recipient
		so nothing is lost; an empty ``weights`` returns an empty list.
	"""
	ws = [_d(w) for w in weights]
	if not ws:
		return []
	tgt = _round_half_up(_d(total))
	wsum = sum(ws)
	if wsum <= 0:
		# No basis to weight by — put the whole amount on the first recipient.
		out = [0] * len(ws)
		out[0] = tgt
		return out
	raw = [_d(tgt) * w / wsum for w in ws]
	return largest_remainder_round(raw, target_total=tgt)
