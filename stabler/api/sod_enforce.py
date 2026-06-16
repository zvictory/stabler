"""Frappe-facing SoD enforcement guard — thin wrapper over the pure engine.

This module provides ``assert_no_sod_conflict(doc, method)``, suitable for
wiring into ``doc_events`` in hooks.py. It derives the prior-actors map from
the document itself (owner, Version history, linked-doc owners, amendment
chain), calls the pure ``conflicting_actor`` function, and calls
``frappe.throw`` if any rule fires.

The guard is gated by ``Stabler Settings.enable_sod_enforcement`` (Check,
default 0 — off by default). When the flag is off every call is a fast,
unconditional no-op.

Design decisions
----------------
* No duplicate with approvals.py — approvals.py owns the self-approval block
  for its narrow maker-checker flow. This module is the GENERAL guard for
  cross-document, cross-lifecycle SoD enforcement.
* "Prior actors" are collected without a db.sql() scan over full Version
  history for performance; instead we use the lightweight signals that are
  already on the document or cheaply fetchable:
    - doc.owner       → "create" actor
    - doc.submitted_by (custom field, may not exist) or the first Version
      that flipped docstatus to 1 → "submit" actor
    - doc._assign (JSON list of currently-assigned users, used for "approve"
      derivation when a Stabler Approval Request exists)
    - doc.amended_from owner → "create" on the original doc for "amend"
    - linked supplier / PO owner → "create_supplier" / "request" actors
* All database reads are guarded so a missing field or missing linked doc is
  a silent skip, not an exception.
* The guard must be **idempotent** — calling it twice on the same doc state
  must yield the same result.
"""
from __future__ import annotations

import json

import frappe
from frappe import _

from stabler.api._sod_rules import conflicting_actor

_SETTINGS = "Stabler Settings"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _enforcement_enabled() -> bool:
	"""Fast check: is SoD enforcement switched on in Stabler Settings?"""
	if not frappe.db.exists("DocType", _SETTINGS):
		return False
	val = frappe.db.get_single_value(_SETTINGS, "enable_sod_enforcement")
	return bool(int(val or 0))


# ---------------------------------------------------------------------------
# Prior-actors derivation helpers
# ---------------------------------------------------------------------------

def _safe_owner(doctype: str, name: str) -> str | None:
	"""Fetch the owner of any named document; return None on any error."""
	if not doctype or not name:
		return None
	try:
		return frappe.db.get_value(doctype, name, "owner") or None
	except Exception:
		return None


def _submitted_by(doc) -> str | None:
	"""Best-effort: who submitted this document?

	Checks (in order):
	  1. A ``submitted_by`` field if it exists (a Stabler custom field).
	  2. The Version that first flipped docstatus to 1.
	  3. The document owner as fallback when docstatus == 1 and no version found
	     (e.g. programmatic submit without the Stabler audit hook).
	"""
	# 1. Custom field shortcut
	if hasattr(doc, "submitted_by") and doc.submitted_by:
		return doc.submitted_by

	# 2. Version history — find earliest submit Version
	try:
		versions = frappe.get_all(
			"Version",
			filters={"ref_doctype": doc.doctype, "docname": doc.name},
			fields=["owner", "data"],
			order_by="creation asc",
			limit=50,
		)
		for v in versions:
			try:
				data = json.loads(v.data or "{}")
				for row in data.get("changed") or []:
					if len(row) >= 3 and row[0] == "docstatus" and str(row[2]) == "1":
						return v.owner
			except Exception:
				continue
	except Exception:
		pass

	# 3. Fallback
	if getattr(doc, "docstatus", 0) == 1:
		return getattr(doc, "owner", None)
	return None


def _assigned_users(doc) -> list[str]:
	"""Parse doc._assign JSON into a list of user e-mails."""
	raw = getattr(doc, "_assign", None) or "[]"
	try:
		return json.loads(raw) or []
	except Exception:
		return []


def _linked_supplier_owner(doc) -> str | None:
	"""Return the owner of the Supplier linked to this doc, if any."""
	supplier = getattr(doc, "supplier", None)
	if not supplier:
		return None
	return _safe_owner("Supplier", supplier)


def _purchase_order_creator(doc) -> str | None:
	"""Return the owner of the Purchase Order linked to this doc, if any.

	Used when a Purchase Receipt is being received — the PO owner is the
	"create" actor for the po_creator_cannot_receive rule.
	"""
	po = getattr(doc, "purchase_order", None)
	if not po:
		# Purchase Receipts may list POs in the items table; take the first one.
		for item in getattr(doc, "items", []) or []:
			po = getattr(item, "purchase_order", None)
			if po:
				break
	if not po:
		return None
	return _safe_owner("Purchase Order", po)


def _material_request_creator(doc) -> str | None:
	"""Return the owner of the Material Request linked to this doc, if any."""
	mr = getattr(doc, "material_request", None)
	if not mr:
		for item in getattr(doc, "items", []) or []:
			mr = getattr(item, "material_request", None)
			if mr:
				break
	if not mr:
		return None
	return _safe_owner("Material Request", mr)


def _amended_from_owner(doc) -> str | None:
	"""Owner of the document this doc was amended from, if applicable."""
	src = getattr(doc, "amended_from", None)
	if not src:
		return None
	return _safe_owner(doc.doctype, src)


# ---------------------------------------------------------------------------
# Action derivation
# ---------------------------------------------------------------------------

# Map (doctype, method hook name) → the lifecycle action being performed.
# ``method`` is the string Frappe passes as the second arg to doc_events hooks.
_ACTION_MAP: dict[tuple[str, str], str] = {
	# Approval flow
	("Payment Entry",    "before_submit"):  "pay",
	("Journal Entry",    "before_submit"):  "pay",
	("Purchase Invoice", "before_submit"):  "pay",
	("Purchase Order",   "before_submit"):  "approve",
	("Purchase Receipt", "before_submit"):  "receive",
	("Material Request", "before_submit"):  "approve",
	("Sales Invoice",    "before_submit"):  "approve",
	("Expense Claim",    "before_submit"):  "approve",
}
# Universal fallback: any before_submit = "approve" unless overridden above.
_UNIVERSAL_SUBMIT_ACTION = "approve"


def _action_for(doctype: str, method: str) -> str:
	"""Resolve the lifecycle action from the hook method name and doctype."""
	return _ACTION_MAP.get((doctype, method)) or _UNIVERSAL_SUBMIT_ACTION


# ---------------------------------------------------------------------------
# Prior-actors map builder
# ---------------------------------------------------------------------------

def _build_prior_actors(doc, action: str) -> dict[str, list[str]]:
	"""Collect all prior actors for this document into a map keyed by action.

	Only actors that are non-empty strings are included. The result feeds
	directly into ``conflicting_actor()``.
	"""
	def _add(mapping: dict, key: str, user: str | None) -> None:
		if user:
			mapping.setdefault(key, [])
			if user not in mapping[key]:
				mapping[key].append(user)

	prior: dict[str, list[str]] = {}

	# Create actor = document owner.
	_add(prior, "create", getattr(doc, "owner", None))

	# Submit actor.
	_add(prior, "submit", _submitted_by(doc))

	# Assigned users often represent "approve" in lightweight workflows.
	for u in _assigned_users(doc):
		_add(prior, "approve", u)

	# Amendment source — original creator is the "create" actor for amend check.
	_add(prior, "create", _amended_from_owner(doc))

	# Supplier creator — for payment-to-supplier SoD.
	_add(prior, "create_supplier", _linked_supplier_owner(doc))

	# Purchase Order creator — for the receive-goods SoD rule.
	_add(prior, "create", _purchase_order_creator(doc))

	# Material Request originator — "request" action.
	_add(prior, "request", _material_request_creator(doc))

	return prior


# ---------------------------------------------------------------------------
# Public guard
# ---------------------------------------------------------------------------

def assert_no_sod_conflict(doc, method: str) -> None:
	"""Frappe doc_events hook: block conflicting lifecycle actions.

	Wire this to the doctypes you want guarded in hooks.py ``doc_events``.
	Call signature matches what Frappe passes to any before_*/after_* hook.

	When ``enable_sod_enforcement`` is 0 (default) the function returns
	immediately without touching the database.
	"""
	if not _enforcement_enabled():
		return

	actor = frappe.session.user
	if not actor or actor in ("Guest", "Administrator"):
		# Administrator is exempt — break-glass account for emergencies.
		return

	doctype = doc.doctype
	action = _action_for(doctype, method)
	prior = _build_prior_actors(doc, action)

	violations = conflicting_actor(action, doctype, actor, prior)
	if not violations:
		return

	# Report all violations in one throw (most-severe first).
	_SORDER = {"critical": 3, "high": 2, "medium": 1, "info": 0}
	violations.sort(key=lambda v: -_SORDER.get(v["severity"], 0))

	lines = []
	for v in violations:
		lines.append(_("{0} ({1})").format(_(v["message"]), v["rule_id"]))

	frappe.throw(
		_("Separation-of-duties violation — you cannot perform this action:\n{0}").format(
			"\n".join(f"• {l}" for l in lines)
		),
		title=_("SoD Enforcement"),
	)
