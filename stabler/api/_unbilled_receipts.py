"""Unbilled Purchase Receipt (GR/IR) exposure math — Frappe-free.

Goods arrive weeks before the supplier's invoice. ERPNext already books that
gap: a submitted Purchase Receipt debits the warehouse and credits **Stock
Received But Not Billed** (SRBNB); the Purchase Invoice later debits SRBNB
against Accounts Payable and clears it. So the SRBNB balance *is* the company's
unbilled-goods exposure.

Nothing in this app prompts anyone to raise that invoice, so a shipment can be
received, sold, and never billed — SRBNB then never clears and profit is
overstated in the month the goods landed. Acumatica ships the report that names
those receipts as *Purchase Accrual Balance by Period* (PO402000), SAP as
*Reconcile GR/IR Accounts*; ERPNext has ``per_billed`` on the Purchase Receipt
and no report. This module is the arithmetic behind ours.

Only arithmetic lives here — no ``import frappe`` — so every edge below is
unit-testable without a bench (stabler/tests/test_unbilled_receipts.py).

Buckets, by age of the receipt in days as of the report date:

  b_0_30     0-30   normal payment cycle, nothing to do
  b_31_60   31-60   chase the supplier for the invoice
  b_61_90   61-90   written confirmation from the supplier
  b_90_plus   91+   escalate: the stock is most likely sold already

``per_billed`` is an ERPNext Percent field, and every degenerate value it can
carry is pinned here rather than left to each caller:

  ``None`` / ``""`` / non-numeric -> 0 -> the receipt counts as FULLY UNBILLED.
      Deliberate direction, and the risky-looking one. Reading an unusable
      per_billed as "billed" would delete exposure from the report and make
      SRBNB look clean, which is the exact failure this report exists to catch.
      Reading it as unbilled can only over-state the exposure, and the report's
      SRBNB reconciliation line then shows the over-statement instead of hiding
      it. A report that under-states what the company owes is worse than one
      that over-states it. (The SQL side agrees: the endpoint filters on
      ``COALESCE(per_billed, 0) < 100``, because ``per_billed < 100`` is NULL —
      and therefore false — for a NULL percentage, which would silently drop
      the most-exposed receipts from the report entirely.)
  ``> 100`` -> 100 -> zero unbilled, never negative. ERPNext permits over-billing
      within tolerance; an over-billed receipt is an AP over-accrual, a
      different defect, and letting it return a negative number would net down
      real exposure carried by other receipts inside the same total.
  ``< 0`` -> 0 -> fully unbilled, same reasoning as blank.

Nothing here raises. A bad row degrades to a number a report can print.

Money is company currency and rounded to 2 decimals; per-currency display
precision (UZS is 0-dp) is the caller's job.
"""

from __future__ import annotations

import math

#: Bucket keys, youngest first. The endpoint returns these exact names in its
#: ``totals`` block and accepts one of them as its ``bucket`` filter.
BUCKETS = ("b_0_30", "b_31_60", "b_61_90", "b_90_plus")

#: Inclusive age bounds in days per bucket; ``None`` means open-ended. The
#: endpoint's SQL bucket filter reads these bounds instead of repeating the
#: edges in a DATEDIFF predicate, so the SQL and ``bucket_of`` below cannot
#: drift apart. ``b_0_30`` has no lower bound on purpose: a receipt posted on
#: the report date is 0 days old, and a back-dated or clock-skewed row must land
#: in the youngest bucket rather than drop out of the bucket split while still
#: counting in the total.
BUCKET_BOUNDS: dict[str, tuple[int | None, int | None]] = {
	"b_0_30": (None, 30),
	"b_31_60": (31, 60),
	"b_61_90": (61, 90),
	"b_90_plus": (91, None),
}


def _num(value) -> float:
	"""Coerce anything to a finite float. Unusable input is 0.0, never a raise.

	NaN and infinity are folded to 0.0 as well: either one would poison every
	sum it touches downstream and turn a whole report into ``NaN``.
	"""
	if value is None or value == "":
		return 0.0
	try:
		out = float(value)
	except (TypeError, ValueError):
		return 0.0
	if not math.isfinite(out):
		return 0.0
	return out


def billed_percent(per_billed) -> float:
	"""ERPNext ``per_billed`` clamped into 0..100 — see the module docstring."""
	pct = _num(per_billed)
	if pct <= 0.0:
		return 0.0
	if pct >= 100.0:
		return 100.0
	return pct


def unbilled_amount(base_grand_total, per_billed) -> float:
	"""Company-currency value received and not yet billed.

	``base_grand_total`` must be the receipt's COMPANY-currency total
	(``base_grand_total``), never the transaction-currency ``grand_total``: this
	importer posts receipts in USD and reports in UZS, and summing mixed
	currencies is meaningless.

	Floored at zero, because exposure is never negative (over-billing, a
	returned line that slipped the scope filter). ``base * (1 - per_billed/100)``
	is a proportional approximation — ERPNext derives ``per_billed`` from billed
	amount, so taxes need not clear SRBNB in the same proportion. The endpoint's
	SRBNB-vs-GL ``difference`` is the check on that approximation, which is why
	it is reported instead of assumed away.
	"""
	base = _num(base_grand_total)
	remaining = base * (100.0 - billed_percent(per_billed)) / 100.0
	return round(max(remaining, 0.0), 2)


def bucket_of(age_days) -> str:
	"""Which BUCKETS key an age falls in; bounds are inclusive on both edges.

	An unreadable or negative age lands in the youngest bucket so that its money
	stays inside the bucket split rather than vanishing from it.
	"""
	age = int(_num(age_days))
	for key in BUCKETS:
		low, high = BUCKET_BOUNDS[key]
		if (low is None or age >= low) and (high is None or age <= high):
			return key
	return BUCKETS[0]  # unreachable while BUCKET_BOUNDS covers the whole line


def annotate_rows(rows) -> list[dict]:
	"""Copy each raw receipt row with the three report fields added.

	``rows`` = iterable of {base_grand_total, per_billed, age_days, ...} exactly
	as the SQL layer returns it (``age_days`` from ``DATEDIFF``); any other key
	passes through untouched. Input rows are never mutated, so the caller's SQL
	result stays usable. Row order is the caller's (SQL ``ORDER BY``), not this
	function's.
	"""
	out: list[dict] = []
	for raw in rows or []:
		row = dict(raw or {})
		age = max(int(_num(row.get("age_days"))), 0)
		row["age_days"] = age
		row["bucket"] = bucket_of(age)
		row["unbilled_amount"] = unbilled_amount(row.get("base_grand_total"), row.get("per_billed"))
		out.append(row)
	return out


def reconciliation_comparable(as_of_iso: str, today_iso: str) -> bool:
	"""Whether the SRBNB ledger balance and this report's total measure one instant.

	The ledger side of the reconciliation is genuinely historical — the endpoint
	sums ``tabGL Entry`` up to ``as_of``. The receipt side is not. It values each
	row from ``per_billed``, which ERPNext overwrites in place when an invoice is
	submitted and which therefore carries no date at all. So on a back-dated run
	the list answers *unbilled now* while the ledger answers *owed then*, and
	subtracting them measures the invoices raised in between.

	Raising those invoices is the most ordinary thing an accountant does, and the
	screen renders a non-zero difference as an accusation that someone posted
	outside the receipt chain. Refusing the comparison is the whole point of this
	predicate: a report that accuses the innocent gets switched off, and then it
	catches nothing at all.

	A forward-dated ``as_of`` stays comparable. ERPNext refuses a future posting
	date on a Purchase Receipt, so no receipt can appear between today and a
	future cut-off and both sides still describe the same set. (A future-dated
	*invoice* can still skew it; ERPNext permits those. That skew is out of reach
	of any flag and needs billing state to be derived per date instead.)

	Both arguments are ISO ``YYYY-MM-DD`` strings, which sort lexicographically
	exactly as the dates do. Strings and not ``date`` objects because this module
	may not import frappe, and frappe hands its callers ``today()`` as ``str``
	while ``getdate()`` returns ``date`` — comparing the two raises ``TypeError``
	on the default page load, the one path that must never break.
	"""
	return as_of_iso >= today_iso


def summarise(rows) -> dict:
	"""Report header over annotated rows: total, per-bucket split, receipt count.

	Every figure is COMPANY currency (each row's ``unbilled_amount``), so the
	total is addable across the USD imports receipts and the UZS local ones
	alike. ``receipts`` counts every row handed in, including a row whose
	exposure rounds to zero — it is the row count the screen displays.

	A row whose ``bucket`` is missing or unrecognised is re-bucketed from its
	``age_days`` instead of being skipped, which keeps
	``total_unbilled == sum(buckets)`` true. The screen prints both numbers, so
	money leaking out of the split and into the total alone would be invisible.
	"""
	out: dict = {"total_unbilled": 0.0}
	for key in BUCKETS:
		out[key] = 0.0
	out["receipts"] = 0
	for raw in rows or []:
		row = raw or {}
		amount = _num(row.get("unbilled_amount"))
		bucket = row.get("bucket")
		if bucket not in BUCKETS:
			bucket = bucket_of(row.get("age_days"))
		out["total_unbilled"] += amount
		out[bucket] += amount
		out["receipts"] += 1
	out["total_unbilled"] = round(out["total_unbilled"], 2)
	for key in BUCKETS:
		out[key] = round(out[key], 2)
	return out
