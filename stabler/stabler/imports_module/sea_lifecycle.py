"""Shared sea lifecycle — the CI owns the voyage, containers follow it.

Frappe-free.

THE PROBLEM THIS ADDRESSES
--------------------------
Commercial Invoice and Import Container carry the *same* status pipeline
(BOOKED → … → DELIVERED_TO_UZBEKISTAN), maintained independently. One voyage,
two hand-kept copies of where it is. They drift, and nothing today notices: a
CI can say ON_BOARD while its containers still say STUFFED, and both screens
look authoritative.

The design settles the ownership question: the CI is the source of truth for
the sea leg, containers display it. Physical facts that genuinely belong to one
container — its packing list, a damaged seal — stay on the container and are
represented separately; they must not move the shared status.

WHY THIS MODULE ONLY MEASURES
-----------------------------
Removing the container's status field would rewrite live rows on 243 invoices,
and nobody has counted how far they have actually drifted. So the first step
reports the gap and offers an explicit, auditable push. Silent auto-sync would
destroy the evidence of how bad the problem was before anyone could look at it.
"""

from __future__ import annotations

#: The voyage, in order. Position matters: a container behind its CI is stale,
#: a container ahead of its CI is a contradiction that a human must resolve.
SEA_PIPELINE = [
    "BOOKED",
    "STUFFED",
    "GATE_IN",
    "ON_BOARD",
    "IN_TRANSIT",
    "DISCHARGED",
    "AVAILABLE",
    "ARRIVED_AT_IRAN",
    "DELIVERED_TO_UZBEKISTAN",
]

#: Not part of the voyage — a cancelled container is not "behind", it is out.
TERMINAL = {"Cancelled"}


def rank(status) -> int:
    """Position in the voyage, or -1 for cancelled/unknown."""
    try:
        return SEA_PIPELINE.index(str(status or ""))
    except ValueError:
        return -1


def drift(ci_status, container_status) -> dict:
    """How a container's status relates to its invoice's.

    Returns ``{"state", "steps"}`` where state is one of:
      ``aligned``       same point in the voyage
      ``behind``        container has not been advanced yet — the common case
      ``ahead``         container is further than the invoice — a contradiction
      ``cancelled``     container is out of the voyage
      ``unknown``       a status outside the pipeline

    ``steps`` is the absolute distance, so a report can sort by severity.
    """
    if str(container_status or "") in TERMINAL:
        return {"state": "cancelled", "steps": 0}

    ci_rank, c_rank = rank(ci_status), rank(container_status)
    if ci_rank < 0 or c_rank < 0:
        return {"state": "unknown", "steps": 0}
    if ci_rank == c_rank:
        return {"state": "aligned", "steps": 0}
    if c_rank < ci_rank:
        return {"state": "behind", "steps": ci_rank - c_rank}
    return {"state": "ahead", "steps": c_rank - ci_rank}


def syncable(ci_status, container_status) -> bool:
    """May this container be pushed forward to the invoice's status?

    Only a container that is *behind* can be pushed, and only along the
    pipeline. Pushing an ``ahead`` container would move it backwards, which is
    a correction with its own reason-required workflow, not a sync. A cancelled
    container is never touched.
    """
    return drift(ci_status, container_status)["state"] == "behind"


def summarise(ci_status, containers) -> dict:
    """Fleet view for one invoice.

    ``containers`` is a list of ``{"name", "container_number", "status"}``.
    Returns counts per state plus the rows that need attention, so the CI panel
    can say "3 of 4 containers are behind" without the caller re-deriving it.
    """
    out = {
        "ci_status": ci_status,
        "total": 0,
        "aligned": 0,
        "behind": 0,
        "ahead": 0,
        "cancelled": 0,
        "unknown": 0,
        "rows": [],
    }
    for c in containers or []:
        d = drift(ci_status, c.get("status"))
        out["total"] += 1
        out[d["state"]] += 1
        out["rows"].append({
            "name": c.get("name"),
            "container_number": c.get("container_number"),
            "status": c.get("status"),
            "state": d["state"],
            "steps": d["steps"],
            "syncable": d["state"] == "behind",
        })
    # Worst first: contradictions, then the most stale.
    order = {"ahead": 0, "unknown": 1, "behind": 2, "aligned": 3, "cancelled": 4}
    out["rows"].sort(key=lambda r: (order.get(r["state"], 9), -r["steps"],
                                    str(r["container_number"] or "")))
    out["in_sync"] = out["behind"] == 0 and out["ahead"] == 0 and out["unknown"] == 0
    return out


def path(from_status, to_status):
    """The statuses a container must pass through to catch up, in order.

    The container controller enforces one step at a time, so a sync that jumps
    three stations has to walk them. Returns [] when there is nothing to walk.
    """
    a, b = rank(from_status), rank(to_status)
    if a < 0 or b < 0 or b <= a:
        return []
    return SEA_PIPELINE[a + 1 : b + 1]
