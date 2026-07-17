"""KTS post-clearance customs-amendment math (WP-I15, Frappe-free).

Uzbek customs can revise a cleared GTD's value upward after the fact (KTS),
creating extra duty + extra VAT + possibly a penalty. Each piece has a DIFFERENT
accounting destination — this module computes the deltas and routes them:

  * extra duty + extra excise  → CAPITALIZED into stock (a delta Landed Cost
    Voucher), because they are part of the cost of bringing inventory in;
  * extra import VAT           → Input VAT (recoverable asset), never stock;
  * penalty / fine             → P&L expense, never stock (IAS 2 §16(c): abnormal
    amounts are excluded from the cost of inventory).

Deltas may be negative (a downward revision / refund); signs pass through.
Only the amendment vs the original is compared — the original GTD is never
edited (audit trail).
"""

from __future__ import annotations


def _amt(v) -> float:
	try:
		return float(v or 0)
	except (TypeError, ValueError):
		return 0.0


def amendment_delta(original: dict, amended: dict, penalty=0) -> dict:
	"""Route a KTS amendment into its three accounting buckets.

	``original`` / ``amended`` = {duty_amount, excise_amount, vat_amount} of the
	cleared GTD and the amending GTD. ``penalty`` is the fine (already a positive
	cost, if any).
	"""
	o, a = original or {}, amended or {}
	duty_delta = round(_amt(a.get("duty_amount")) - _amt(o.get("duty_amount")), 2)
	excise_delta = round(_amt(a.get("excise_amount")) - _amt(o.get("excise_amount")), 2)
	vat_delta = round(_amt(a.get("vat_amount")) - _amt(o.get("vat_amount")), 2)
	pen = round(_amt(penalty), 2)
	capitalized = round(duty_delta + excise_delta, 2)
	return {
		"duty_delta": duty_delta,
		"excise_delta": excise_delta,
		"vat_delta": vat_delta,
		"penalty": pen,
		# GL routing:
		"capitalized_delta": capitalized,        # → delta LCV → Stock In Hand
		"input_vat_delta": vat_delta,            # → Input VAT (asset)
		"pl_expense": pen,                        # → P&L (penalty only)
		"total_extra_payable": round(capitalized + vat_delta + pen, 2),
	}


def gl_routing(delta: dict) -> list[dict]:
	"""Human/UI-friendly routing lines with the target account TYPE per bucket."""
	d = delta or {}
	lines = []
	if _amt(d.get("capitalized_delta")):
		lines.append({
			"bucket": "capitalized",
			"amount": _amt(d.get("capitalized_delta")),
			"account_hint": "Expenses Included In Valuation → Stock (delta LCV)",
		})
	if _amt(d.get("input_vat_delta")):
		lines.append({
			"bucket": "input_vat",
			"amount": _amt(d.get("input_vat_delta")),
			"account_hint": "Input VAT / recoverable (asset — never stock)",
		})
	if _amt(d.get("pl_expense")):
		lines.append({
			"bucket": "penalty",
			"amount": _amt(d.get("pl_expense")),
			"account_hint": "Customs penalty (P&L expense — never stock)",
		})
	return lines
