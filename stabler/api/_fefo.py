"""FEFO (first-expired-first-out) allocation maths.

Pure functions, no frappe import — the allocation rules for perishable stock
are the part worth testing exhaustively, so they live away from the ORM.

Why FEFO and not FIFO: frozen meat is sold against a shelf life, not against a
purchase order date. A batch received later can easily expire sooner (different
production date, different supplier), so ordering by receipt date silently ages
out stock that is still saleable while shipping stock that is about to expire.
"""

from __future__ import annotations

#: Batches within this many days of expiry are called out as urgent.
EXPIRY_URGENT_DAYS = 30
#: Batches within this window are worth watching but not urgent.
EXPIRY_WARN_DAYS = 90


def expiry_bucket(days_left) -> str:
    """Classify a batch by remaining shelf life.

    ``days_left`` may be None for a batch with no expiry recorded — that is a
    data gap, not a fresh batch, so it gets its own bucket rather than being
    quietly treated as safe.
    """
    if days_left is None:
        return "unknown"
    if days_left < 0:
        return "expired"
    if days_left <= EXPIRY_URGENT_DAYS:
        return "urgent"
    if days_left <= EXPIRY_WARN_DAYS:
        return "soon"
    return "ok"


def sort_fefo(batches):
    """Order batches first-expired-first.

    Batches with no expiry sort last: we cannot prove they are the oldest, and
    shipping an unknown-expiry batch ahead of a dated one destroys the audit
    trail. Ties break on batch id so the order is stable and reproducible.
    """
    def key(b):
        exp = b.get("expiry_date")
        return (exp is None, exp or "", str(b.get("batch_no") or ""))

    return sorted(batches, key=key)


def allocate_fefo(needed_qty, batches, *, allow_expired: bool = False):
    """Split ``needed_qty`` across ``batches``, nearest expiry first.

    ``batches`` is a list of ``{"batch_no", "qty", "expiry_date", "days_left"}``.
    Returns ``{"lines": [...], "allocated": float, "shortfall": float,
    "skipped_expired": [...]}``.

    Expired batches are skipped unless ``allow_expired`` is set — an expired
    batch is not a stock shortage to be quietly filled, it is an exception a
    human has to see. The caller decides whether to override.

    A shortfall is reported rather than raised: the picking screen wants to show
    "we can cover 800 of the 1000 kg you asked for", not fail outright.
    """
    remaining = _pos(needed_qty)
    lines = []
    skipped = []

    for b in sort_fefo(batches):
        available = _pos(b.get("qty"))
        if available <= 0:
            continue
        if not allow_expired and expiry_bucket(b.get("days_left")) == "expired":
            # Report every expired batch in the pool, not just the ones the
            # allocation happened to reach. Expired stock sitting in the bin is
            # a fact the picker needs regardless of today's order size.
            skipped.append(b.get("batch_no"))
            continue
        if remaining <= 0:
            continue
        take = min(available, remaining)
        lines.append({
            "batch_no": b.get("batch_no"),
            "qty": _round(take),
            "expiry_date": b.get("expiry_date"),
            "days_left": b.get("days_left"),
            "bucket": expiry_bucket(b.get("days_left")),
        })
        remaining = _round(remaining - take)

    return {
        "lines": lines,
        "allocated": _round(_pos(needed_qty) - remaining),
        "shortfall": _round(remaining),
        "skipped_expired": skipped,
    }


def summarise(batches) -> dict:
    """Roll a batch list up for a stock screen: totals per expiry bucket."""
    out = {"total_qty": 0.0, "batch_count": 0, "expired": 0.0, "urgent": 0.0,
           "soon": 0.0, "ok": 0.0, "unknown": 0.0, "nearest_expiry": None}
    for b in sort_fefo(batches):
        qty = _pos(b.get("qty"))
        if qty <= 0:
            continue
        out["total_qty"] = _round(out["total_qty"] + qty)
        out["batch_count"] += 1
        out[expiry_bucket(b.get("days_left"))] = _round(
            out[expiry_bucket(b.get("days_left"))] + qty
        )
        if out["nearest_expiry"] is None and b.get("expiry_date"):
            out["nearest_expiry"] = b.get("expiry_date")
    return out


def _pos(v) -> float:
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return f if f > 0 else 0.0


def _round(v) -> float:
    # Stock quantities are kg with 3-decimal precision in ERPNext defaults;
    # rounding here keeps float residue out of the allocation arithmetic.
    return round(float(v), 3)
