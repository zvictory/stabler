"""Pure bank-reconciliation match scoring — no Frappe, no DB.

Phase 2 of bank reconciliation: rank existing system vouchers (Payment Entry /
Journal Entry) as match candidates for an unreconciled bank statement line, so
the operator can one-click reconcile. The actual reconciliation is done by
ERPNext (stamping ``clearance_date`` via the Bank Transaction ``payment_entries``
table) — this module only *scores* candidates.

Scoring is tuned for Uzbekistan, where names are transliterated inconsistently
across ru/uz/uzc but the **INN/STIR** and the **amount** are stable:

  amount exact            +50   (near-zero score if amounts differ materially)
  same posting date       +20   (decaying with date distance)
  reference number match  +20
  counterparty INN match  +15   (or payee name appears in the description)

Total is capped at 100 and banded high (>=80) / medium (>=50) / low.
Everything is a deterministic function of its inputs → unit tested with no bench.

Phase 2 additions:
  - Journal Entry lines are also ranked as candidates (voucher_type="Journal Entry").
  - INN/STIR on the bank statement row boosts the score when the candidate
    party's INN matches (already in original; now exposed for JE rows too).
  - ``allocate_partial`` splits one bank-line amount across multiple vouchers
    (or one voucher across multiple lines) with exact integer/decimal precision
    so allocations sum to the source amount with no residual drift.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation

HIGH = "high"
MEDIUM = "medium"
LOW = "low"


def _f(v) -> float:
	try:
		return float(v)
	except TypeError, ValueError:
		return 0.0


def _days_apart(a: str | None, b: str | None) -> int | None:
	"""Whole days between two yyyy-mm-dd strings, or None if unparseable."""
	if not a or not b:
		return None
	import datetime as _dt

	try:
		da = _dt.date.fromisoformat(a[:10])
		db = _dt.date.fromisoformat(b[:10])
	except ValueError:
		return None
	return abs((da - db).days)


def score_match(bank_line: dict, candidate: dict) -> dict:
	"""Score how well a candidate voucher matches a bank line (0..100 + band).

	bank_line: {amount, date, reference, counterparty_inn, description}
	candidate: {amount, date, reference, party_inn, party_name, voucher_type, voucher_no}

	Works for both Payment Entry and Journal Entry candidates.  For JE rows the
	caller should populate ``reference`` from ``cheque_no`` / ``user_remark`` and
	``party_inn`` from the supplier/customer INN on the linked party.
	"""
	score = 0.0
	reasons: list[str] = []

	b_amt = abs(_f(bank_line.get("amount")))
	c_amt = abs(_f(candidate.get("amount")))

	# Amount — the hard signal. Exact (to the cent) dominates; a material
	# difference caps the whole match low.
	if b_amt > 0:
		diff = abs(b_amt - c_amt)
		rel = diff / b_amt
		if diff <= 0.01:
			score += 50
			reasons.append("amount exact")
		elif rel <= 0.01:
			score += 40
			reasons.append("amount within 1%")
		elif rel <= 0.05:
			score += 20
			reasons.append("amount within 5%")
		else:
			# Amounts don't agree — this is almost certainly not the voucher.
			return {"score": 0, "band": LOW, "reasons": ["amount mismatch"]}

	# Date proximity.
	d = _days_apart(bank_line.get("date"), candidate.get("date"))
	if d is not None:
		if d == 0:
			score += 20
			reasons.append("same date")
		elif d <= 3:
			score += 15
			reasons.append(f"{d}d apart")
		elif d <= 7:
			score += 8
			reasons.append(f"{d}d apart")

	# Reference number.
	b_ref = (bank_line.get("reference") or "").strip()
	c_ref = (candidate.get("reference") or "").strip()
	if b_ref and c_ref and b_ref == c_ref:
		score += 20
		reasons.append("reference match")

	# Counterparty INN/STIR (stable across transliteration), or payee name in
	# the bank line's payment-purpose description.
	b_inn = (bank_line.get("counterparty_inn") or "").strip()
	c_inn = (candidate.get("party_inn") or "").strip()
	desc = (bank_line.get("description") or "").lower()
	party = (candidate.get("party_name") or "").strip().lower()
	if b_inn and c_inn and b_inn == c_inn:
		score += 15
		reasons.append("INN match")
	elif party and len(party) >= 4 and party in desc:
		score += 12
		reasons.append("payee in purpose")

	score = min(score, 100.0)
	band = HIGH if score >= 80 else MEDIUM if score >= 50 else LOW
	return {"score": round(score), "band": band, "reasons": reasons}


def rank_candidates(bank_line: dict, candidates: list[dict]) -> list[dict]:
	"""Score and sort candidates best-first; each gets its scoring attached."""
	scored = []
	for c in candidates or []:
		s = score_match(bank_line, c)
		row = dict(c)
		row["match_score"] = s["score"]
		row["match_band"] = s["band"]
		row["match_reasons"] = s["reasons"]
		scored.append(row)
	scored.sort(key=lambda r: r["match_score"], reverse=True)
	return scored


# ---------------------------------------------------------------------------
# Partial allocation helper
# ---------------------------------------------------------------------------


def allocate_partial(
	total: str | int | float,
	voucher_amounts: list[str | int | float],
	*,
	precision: int = 2,
) -> list[str]:
	"""Split *total* across vouchers using the amounts they each need.

	Returns a list of allocation strings (same length as ``voucher_amounts``)
	that sum **exactly** to ``total`` with no residual drift.  The last voucher
	absorbs any rounding remainder so the invariant always holds.

	``precision`` is the decimal places used when rounding each tranche.
	UZS callers pass ``precision=0``.

	Rules:
	  - Each tranche is proportional to its voucher's amount relative to the sum
	    of all voucher amounts.  If only one voucher is in the list the whole
	    ``total`` goes to it.
	  - If a voucher amount is zero (or the sum is zero) the tranche is zero
	    except for the last item which gets the residual.
	  - Allocations are non-negative: negatives in voucher_amounts are treated
	    as their absolute value for proportioning.
	  - The returned strings are decimal-exact (e.g. "1234.56") suitable for
	    direct use in ERPNext ``allocated_amount`` fields.

	Raises ``ValueError`` if ``total`` is negative or ``voucher_amounts`` is
	empty.
	"""
	if not voucher_amounts:
		raise ValueError("voucher_amounts must not be empty")

	_q = Decimal(10) ** -precision  # quantize target, e.g. Decimal("0.01")

	try:
		T = Decimal(str(total))
	except InvalidOperation:
		raise ValueError(f"Invalid total: {total!r}")
	if T < 0:
		raise ValueError(f"total must be non-negative, got {total!r}")

	vamts = []
	for v in voucher_amounts:
		try:
			vamts.append(abs(Decimal(str(v))))
		except InvalidOperation:
			raise ValueError(f"Invalid voucher amount: {v!r}")

	total_v = sum(vamts)
	result: list[Decimal] = []

	if total_v == 0:
		# All vouchers are zero — give everything to the last one.
		for _i in range(len(vamts) - 1):
			result.append(Decimal("0"))
		result.append(T.quantize(_q, rounding=ROUND_DOWN))
	else:
		running = Decimal("0")
		for i, va in enumerate(vamts):
			if i == len(vamts) - 1:
				# Last item: exact residual to avoid drift.
				tranche = T - running
			else:
				tranche = (T * va / total_v).quantize(_q, rounding=ROUND_DOWN)
				running += tranche
			result.append(tranche)

	# Sanity check: sum must equal T (the last-item residual guarantees this).
	assert sum(result) == T, f"allocate_partial invariant broken: {sum(result)} != {T}"

	return [str(r) for r in result]
