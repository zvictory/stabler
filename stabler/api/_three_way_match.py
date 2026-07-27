"""Pure three-way-match logic — no Frappe, no DB.

Three-way match = reconcile **Purchase Order** (what we ordered + agreed price),
**Purchase Receipt** (what we actually received), and **Vendor Bill / Purchase
Invoice** (what we are being charged) before paying. It is the classic AP
control that stops paying for goods not ordered, not received, or at a price we
never agreed.

Scope note (guardrail): ERPNext already enforces an **amount-based Over Billing
Allowance** natively (Accounts Settings). We do **not** re-implement that. This
module adds the two checks ERPNext does not surface prominently:

  * **rate variance** — billed rate vs the PO rate beyond a tolerance, and
  * **billed-qty vs received-qty** — billing for more units than were received.

Everything here is a deterministic function of its inputs, so it is unit tested
with no bench. The Frappe layer (``_accounts.validate_purchase_invoice``) fetches
the PO/PR rows and feeds normalized dicts in.
"""

from __future__ import annotations

# Exception severities. "block" stops submission when enforcement is on;
# "warn" is always advisory.
BLOCK = "block"
WARN = "warn"


def _f(v) -> float:
	try:
		return float(v)
	except (TypeError, ValueError):
		return 0.0


def _pct_over(actual: float, allowed: float) -> float:
	"""How far `actual` exceeds `allowed`, as a fraction of allowed (>=0)."""
	allowed = _f(allowed)
	if allowed <= 0:
		return 0.0
	diff = _f(actual) - allowed
	return diff / allowed if diff > 0 else 0.0


def _rate_variance(bill_rate: float, po_rate: float) -> float:
	"""Absolute relative difference between bill rate and PO rate (>=0)."""
	po_rate = _f(po_rate)
	if po_rate <= 0:
		return 0.0
	return abs(_f(bill_rate) - po_rate) / po_rate


def evaluate_line(line: dict, *, qty_tol_pct: float, rate_tol_pct: float) -> list[dict]:
	"""Evaluate one Purchase-Invoice line against its PO/PR references.

	``line`` keys (all optional except idx/item):
	  idx, item_code, bill_qty, bill_rate,
	  po_qty, po_rate          (from the referenced PO row),
	  received_qty             (from the referenced PR row, if any).

	Tolerances are percentages (e.g. 5 = 5%). Returns a list of exception dicts.
	"""
	q_tol = _f(qty_tol_pct) / 100.0
	r_tol = _f(rate_tol_pct) / 100.0
	exc: list[dict] = []
	idx = line.get("idx")
	item = line.get("item_code") or ""

	bill_qty = _f(line.get("bill_qty"))
	bill_rate = _f(line.get("bill_rate"))
	po_qty = line.get("po_qty")
	po_rate = line.get("po_rate")
	received_qty = line.get("received_qty")

	# 1. Rate variance vs PO (only when a PO rate is known and > 0).
	if po_rate is not None and _f(po_rate) > 0:
		var = _rate_variance(bill_rate, po_rate)
		if var > r_tol:
			exc.append(
				{
					"idx": idx,
					"item_code": item,
					"type": "rate_variance",
					"severity": BLOCK,
					"detail": "Billed rate {0} differs from PO rate {1} by {2:.1%} (tolerance {3:.1%}).".format(
						bill_rate, _f(po_rate), var, r_tol
					),
				}
			)

	# 2. Billed qty vs received qty — paying for more than received.
	if received_qty is not None:
		over = _pct_over(bill_qty, _f(received_qty))
		if over > q_tol:
			exc.append(
				{
					"idx": idx,
					"item_code": item,
					"type": "over_received",
					"severity": BLOCK,
					"detail": "Billed qty {0} exceeds received qty {1} by {2:.1%} (tolerance {3:.1%}).".format(
						bill_qty, _f(received_qty), over, q_tol
					),
				}
			)

	# 3. Billed qty vs ordered qty — advisory (ERPNext's Over Billing Allowance
	#    is the hard amount cap; this is a soft qty heads-up).
	if po_qty is not None and _f(po_qty) > 0:
		over = _pct_over(bill_qty, _f(po_qty))
		if over > q_tol:
			exc.append(
				{
					"idx": idx,
					"item_code": item,
					"type": "over_ordered",
					"severity": WARN,
					"detail": "Billed qty {0} exceeds ordered qty {1} by {2:.1%}.".format(
						bill_qty, _f(po_qty), over
					),
				}
			)

	return exc


def evaluate_invoice(lines: list[dict], *, qty_tol_pct: float, rate_tol_pct: float) -> dict:
	"""Evaluate all lines. Returns {exceptions, blocking, has_block}.

	``blocking`` is the subset with severity == BLOCK.
	"""
	exceptions: list[dict] = []
	for line in lines or []:
		exceptions.extend(evaluate_line(line, qty_tol_pct=qty_tol_pct, rate_tol_pct=rate_tol_pct))
	blocking = [e for e in exceptions if e["severity"] == BLOCK]
	return {"exceptions": exceptions, "blocking": blocking, "has_block": bool(blocking)}
