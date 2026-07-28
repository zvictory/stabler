"""PI Group Container Status — pure bucketing and pending rules.

Frappe-free, so the map that decides which report column a container lands in
can be tested exhaustively without a site.

THE SPEC (msaerp parity)
------------------------
A container's bucket is decided by the STATUS OF ITS PARENT Commercial
Invoice, folded into four stations of the journey:

    ORIGIN       BOOKED, STUFFED, GATE_IN
    TRANSIT      ON_BOARD, IN_TRANSIT, DISCHARGED
    DESTINATION  AVAILABLE, ARRIVED_AT_IRAN
    DELIVERED    DELIVERED_TO_UZBEKISTAN

Cancelled is out of the journey — excluded from every bucket AND from the
total, so `total == sum(buckets)` always holds. A silently dropped container
would break that invariant and the report would stop adding up.

HONESTY RULES (beyond the spec)
-------------------------------
Pending values are raw subtractions, never clamped to zero. A negative
pending means more containers/value shipped than the contract planned —
that is a data signal the operator must see, not a rendering inconvenience.
"""

from __future__ import annotations

BUCKET_ORDER = ["ORIGIN", "TRANSIT", "DESTINATION", "DELIVERED"]

BUCKETS = {
    "BOOKED": "ORIGIN",
    "STUFFED": "ORIGIN",
    "GATE_IN": "ORIGIN",
    "ON_BOARD": "TRANSIT",
    "IN_TRANSIT": "TRANSIT",
    "DISCHARGED": "TRANSIT",
    "AVAILABLE": "DESTINATION",
    "ARRIVED_AT_IRAN": "DESTINATION",
    "DELIVERED_TO_UZBEKISTAN": "DELIVERED",
}

#: Out of the journey entirely — not "behind", not a bucket.
EXCLUDED = {"Cancelled", "CANCELLED"}


def bucket_of(ci_status) -> str | None:
    """Bucket for a container, from its parent CI's status.

    Returns None for cancelled/unknown — the caller must EXCLUDE such rows
    from the total as well, or the invariant total == sum(buckets) breaks.
    """
    s = str(ci_status or "")
    if s in EXCLUDED:
        return None
    return BUCKETS.get(s)


def tally(ci_statuses, amounts=None):
    """Fold container/CI rows into bucket counts (and optionally amounts).

    ``ci_statuses``: iterable of parent-CI statuses, one per container (or one
    per CI when tallying amounts). ``amounts``: matching iterable of values.
    Returns ``{"counts", "amounts", "total", "amount_total"}`` where totals
    include only bucketed rows — cancelled/unknown never inflate them.
    """
    counts = {k: 0 for k in BUCKET_ORDER}
    sums = {k: 0.0 for k in BUCKET_ORDER}
    total = 0
    amount_total = 0.0
    vals = list(amounts) if amounts is not None else None
    for i, st in enumerate(ci_statuses):
        b = bucket_of(st)
        if b is None:
            continue
        counts[b] += 1
        total += 1
        if vals is not None:
            v = float(vals[i] or 0)
            sums[b] += v
            amount_total += v
    return {"counts": counts, "amounts": sums, "total": total, "amount_total": amount_total}


def pending_containers(planned_fcl, container_total, cro_count=0) -> float:
    """Planned − shipped − CRO. Raw: negative means over-shipment, show it."""
    return float(planned_fcl or 0) - float(container_total or 0) - float(cro_count or 0)


def pending_amount(pi_agreed_total, ci_agreed_sum) -> float:
    """PI contract value − value already on CIs. Raw, never clamped."""
    return float(pi_agreed_total or 0) - float(ci_agreed_sum or 0)
