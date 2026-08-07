"""Pure Proforma Invoice status-transition rules (WP-I2, Frappe-free).

The supersede flow: a Proforma Invoice (PI) that is still DRAFT or CONFIRMED can
be superseded by a Commercial Invoice, moving it to SUPERSEDED_BY_CI. An already
superseded or cancelled PI cannot be superseded again (idempotent / safe).

The link is 1:1 but the shipping is not: one PI is routinely split over several
containers, and each container is its own CI. The link therefore names the FIRST
CI and stays there; every later container ships against the PI's remaining
balance without re-superseding it (``accepts_another_ci``).

Kept Frappe-free so the transition logic unit-tests without a bench; the Frappe
layer (api.imports.link_proforma_to_ci) applies the bidirectional link + save.
"""

from __future__ import annotations

DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
SUPERSEDED = "SUPERSEDED_BY_CI"
CANCELLED = "CANCELLED"

_SUPERSEDABLE = frozenset({DRAFT, CONFIRMED})


def can_supersede(pi_status: str | None) -> bool:
	"""True only when a PI in this status may be superseded by a CI."""
	return (pi_status or "").strip() in _SUPERSEDABLE


def is_already_linked(pi_status: str | None, pi_commercial_invoice: str | None, target_ci: str) -> bool:
	"""True when the PI is already superseded by exactly ``target_ci`` (re-link no-op)."""
	return (pi_status or "").strip() == SUPERSEDED and (pi_commercial_invoice or "") == (target_ci or "")


def accepts_another_ci(pi_status: str | None, has_open_balance: bool) -> bool:
	"""True when an already-superseded PI may still feed a further CI.

	The second container of a PI is a normal shipment, not a second supersession:
	the PI keeps pointing at the first CI and the new one simply consumes part of
	the remaining balance. Only an open balance earns the pass — a PI whose boxes
	are all shipped, and a CANCELLED one, must still be reported to the user.
	"""
	return (pi_status or "").strip() == SUPERSEDED and bool(has_open_balance)


# ---------------------------------------------------------------------------
# Import PI Group membership (WP — group ↔ PI assignment, Frappe-free)
#
# A PI Group is a thin grouping of Proforma Invoices, optionally restricted to
# one supplier (``pi_vendor``). A PI is "eligible" for assignment to a group
# when it is either already a member of that group (so a re-submit of the same
# selection is a no-op) or currently unlinked from any group AND — if the
# group restricts by vendor — its supplier matches that vendor. A PI already
# linked to a *different* group is never eligible (a PI belongs to <=1 group).
# ---------------------------------------------------------------------------


def is_group_eligible(
	pi_group: str | None,
	pi_supplier: str | None,
	group_name: str,
	group_vendor: str | None,
) -> bool:
	"""True when a PI (given its current group + supplier) may be assigned to
	``group_name``, optionally restricted to ``group_vendor``."""
	if (pi_group or None) == (group_name or None):
		return True
	if pi_group:
		return False
	if group_vendor and (pi_supplier or None) != (group_vendor or None):
		return False
	return True


def validate_assignment(pi_rows: list[dict], group_name: str, group_vendor: str | None) -> list[str]:
	"""Server-side re-validation of a bulk assign_pis_to_group request.

	``pi_rows`` are dicts with at least ``name``, ``supplier``, ``import_pi_group``
	(the PIs' *current* DB state). Returns the names of any row that is NOT
	eligible for assignment to ``group_name`` under ``group_vendor`` — an empty
	list means every requested PI may be linked."""
	bad = []
	for row in pi_rows or []:
		row = row or {}
		if not is_group_eligible(row.get("import_pi_group"), row.get("supplier"), group_name, group_vendor):
			bad.append(row.get("name"))
	return bad
