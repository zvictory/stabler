"""Port-transfer departure gate — which conditions stop a truck leaving Iran.

Frappe-free, so the rule that decides whether goods may physically move can be
tested exhaustively without a site.

WHY THIS GATE EXISTS
--------------------
There is no Truck-to-Container or Truck-to-GTD allocation in the model, and the
design forbids inventing one. That has a hard consequence: when only some of a
CI's customs declarations are cleared, there is no sound way to say *which*
trucks that clearance authorises. Releasing a truck on partial clearance would
be a guess dressed as a rule.

So the gate is deliberately all-or-nothing per CI: every declaration marked
`required_for_departure` must be cleared, and the veterinary certificate must be
valid, before any truck on that CI may advance to DEPARTED_IRAN. A manager may
override, but only with a reason, and the reason is recorded.
"""

from __future__ import annotations

#: The transition this gate protects. Trucks may move freely before and after.
GATED_TRANSITION = ("PENDING", "DEPARTED_IRAN")


def is_cleared(declaration) -> bool:
    """A GTD counts as cleared only when Approved *and* stamped with a date.

    Same definition the Landed Cost Voucher uses (customs_declaration.
    approved_gtd_for_ci). Approved-without-a-date means the paperwork is
    accepted but the goods are not yet released, which is exactly the state
    this gate must catch.
    """
    return bool(
        declaration
        and str(declaration.get("status") or "") == "Approved"
        and declaration.get("cleared_date")
    )


def departure_blockers(declarations, *, vet_valid: bool, required_only: bool = True):
    """Reasons this CI's trucks may not depart yet.

    ``declarations`` is a list of ``{"gtd_number", "status", "cleared_date",
    "required_for_departure"}``. Returns a list of
    ``{"code", "gtd_number"}`` — empty means clear to go.

    Codes:
      ``no_required_declaration``  nothing is marked as required for departure
      ``declaration_not_cleared``  a required GTD is missing or not cleared
      ``vet_certificate_missing``  no valid veterinary certificate

    An empty declaration set is a blocker, not a pass. A CI with no customs
    paperwork at all has not been cleared; treating "nothing to check" as
    "everything is fine" is how goods leave without a GTD.
    """
    rows = list(declarations or [])
    if required_only:
        rows = [d for d in rows if d.get("required_for_departure")]

    blockers = []
    if not rows:
        blockers.append({"code": "no_required_declaration", "gtd_number": None})
    else:
        for d in rows:
            if not is_cleared(d):
                blockers.append({
                    "code": "declaration_not_cleared",
                    "gtd_number": d.get("gtd_number"),
                })

    if not vet_valid:
        blockers.append({"code": "vet_certificate_missing", "gtd_number": None})

    return blockers


def may_depart(declarations, *, vet_valid: bool, override: bool = False,
               override_reason: str = "") -> dict:
    """Decide the gate. Returns ``{"allowed", "blockers", "via_override"}``.

    An override without a reason is not an override. Letting a blank one
    through would turn the audit trail into a checkbox nobody has to justify.
    """
    blockers = departure_blockers(declarations, vet_valid=vet_valid)
    if not blockers:
        return {"allowed": True, "blockers": [], "via_override": False}

    if override and str(override_reason or "").strip():
        return {"allowed": True, "blockers": blockers, "via_override": True}

    return {"allowed": False, "blockers": blockers, "via_override": False}


def gates_this_transition(previous_status, new_status) -> bool:
    """True when a status change is the one the gate guards.

    Only the forward move out of PENDING is gated. A backward correction, a
    cancellation, or any later step is somebody else's rule — this function
    must not quietly widen its own scope.
    """
    return (str(previous_status or ""), str(new_status or "")) == GATED_TRANSITION
