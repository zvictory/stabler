"""Pure Proforma Invoice status-transition rules (WP-I2, Frappe-free).

The supersede flow: a Proforma Invoice (PI) that is still DRAFT or CONFIRMED can
be superseded by a Commercial Invoice, moving it to SUPERSEDED_BY_CI. An already
superseded or cancelled PI cannot be superseded again (idempotent / safe).

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
