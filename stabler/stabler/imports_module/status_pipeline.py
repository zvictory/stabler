"""Shared forward-only status pipeline guard for imports operational docs.

Commercial Invoice / Import Container / Import Truck are non-submittable
operational documents (critique M5): their lifecycle is enforced as a one-way
status pipeline instead of a submit/cancel docstatus flow. This module holds the
single generic transition guard they all share, so the rule set lives in one
place and each controller only supplies its own `_ALLOWED_TRANSITIONS` map.

`assert_transition(doctype, old, new, transitions, doc)` enforces:

1. Forward move — any target listed in ``transitions[old]`` is allowed.
2. Backward correction — a single-step move that reverses exactly one nominal
   forward edge (``old in transitions[new]``) is allowed ONLY for a privileged
   role (Imports Manager / System Manager) AND only when
   ``doc.status_correction_reason`` is filled in. This is the fat-finger escape
   hatch; it never lets you un-cancel (Cancelled is excluded on both ends).
3. Bypass — the guard no-ops entirely during ETL
   (``frappe.flags.in_msaerp_migration``) or when the ``imports`` module is
   disabled for the document's company (critique M6 — 22-tenant blast radius).
"""

import frappe

_CORRECTION_ROLES = ("Imports Manager", "System Manager")


def _imports_active(company) -> bool:
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	return bool(module_map_for(company).get("imports"))


def _is_backward_correction(old, new, transitions) -> bool:
	"""True when old->new reverses exactly one nominal forward edge.

	``new -> old`` must be a real forward edge in the map. Cancelled is excluded
	on both ends so a cancelled doc can never be walked back into an active
	status via the correction path.
	"""
	if old == "Cancelled" or new == "Cancelled":
		return False
	return old in transitions.get(new, set())


def assert_transition(doctype, old, new, transitions, doc) -> None:
	if frappe.flags.in_msaerp_migration:
		return
	if not _imports_active(getattr(doc, "company", None)):
		return
	if not old or old == new:
		return
	# 1. Forward transition per the map.
	if new in transitions.get(old, set()):
		return
	# 2. Single-step backward correction (privileged + reason required).
	if _is_backward_correction(old, new, transitions):
		if not set(frappe.get_roles()).intersection(_CORRECTION_ROLES):
			frappe.throw(
				frappe._("Only an Imports Manager can correct the {0} status backwards.").format(
					frappe._(doctype)
				)
			)
		if not (getattr(doc, "status_correction_reason", None) or "").strip():
			frappe.throw(
				frappe._("A status correction reason is required to move {0} back from {1} to {2}.").format(
					frappe._(doctype), old, new
				)
			)
		return
	frappe.throw(frappe._("Cannot change {0} status from {1} to {2}.").format(frappe._(doctype), old, new))
