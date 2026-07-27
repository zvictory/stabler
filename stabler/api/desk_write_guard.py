"""Restrict writes to Stabler-owned documents to the Stabler app.

Registered as before_validate / before_update_after_submit / before_cancel /
on_trash doc-events in hooks.py. Blocks any create/edit/submit/cancel/delete
that does NOT originate from a stabler.api.* call, so these docs are mutable
only via the Stabler SPA.

Why per-doctype and not per-URL: the Frappe Desk is a single-page app — every
/desk/... path resolves to the same template and all in-app navigation happens
client-side via pushState, so a before_request path allowlist would only gate
the first page load. The doc-event layer is the only place every write channel
(Desk savedocs, frappe.client.*, REST /api/resource, /api/v2/document) must
pass through.

Two lists, because "can the Desk write this?" has two different answers:
  - _STABLER_ONLY_ALWAYS — the orchestration lives in the Stabler API layer,
    not in doc_events, so a Desk save silently skips it. Locked everywhere.
  - _STABLER_ONLY_WHEN_DESK_OPEN — locked only on sites that opened the Desk
    (Stabler Settings.allow_desk_access). Those tenants get the purchasing and
    manufacturing forms in the Desk; everything else stays in Stabler. Sites
    with the flag off keep exactly the old scope.

Exempt (allowed through):
  - System Manager / Administrator.
  - Headless contexts with no HTTP request (background jobs, scheduler,
    console, bench migrate, tests).

UX/safety gate, not a security boundary — same philosophy as middleware/desk_gate.py.
Bench/console can still bypass this for ops emergencies.
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.stabler.doctype.stabler_settings.stabler_settings import desk_access_enabled

# Matches the admin set in middleware/desk_gate.py and api/organization.py.
_ADMIN_ROLES = ("System Manager", "Administrator")

# Sales Order / Sales Invoice carry the stock-reservation chain, and that chain is
# orchestrated in stabler/api/sales.py (the API layer), not in doc_events — a Desk
# save passes every validation and still leaves the reservation stranded. Locked on
# every site, flag or no flag.
_STABLER_ONLY_ALWAYS = (
	"Sales Order",
	"Sales Invoice",
)

# Locked in addition once a site opens the Desk. Kept out of _STABLER_ONLY_ALWAYS so
# the six tenants with the flag off see zero behaviour change (their kassa/telegram
# bots write some of these over REST).
_STABLER_ONLY_WHEN_DESK_OPEN = (
	"Delivery Note",
	"Payment Entry",
	"Journal Entry",
	"Stock Reconciliation",
	"Bank Transaction",
	"Customer",
	"Supplier",
)


def _is_admin() -> bool:
	user = frappe.session.user if frappe.session else None
	if not user:
		return False
	if user == "Administrator":
		return True
	return any(r in frappe.get_roles(user) for r in _ADMIN_ROLES)


def _from_stabler_or_headless() -> bool:
	"""Return True when the call is safe to allow (Stabler SPA or no HTTP request).

	The Stabler SPA's only write channel is POST /api/method/stabler.api.*
	(see public/js/api/client.js). Every other channel (Desk saveDoc, generic
	REST /api/resource/..., Frappe's form API) lacks the "stabler." marker.
	"""
	request = getattr(frappe.local, "request", None)
	if request is None:
		# Background job, scheduler, console, migrate, tests — all safe.
		return True
	cmd = (frappe.local.form_dict or {}).get("cmd") or ""
	path = request.path or ""
	return cmd.startswith("stabler.") or "/api/method/stabler." in path


def _locked_doctypes() -> tuple[str, ...]:
	if desk_access_enabled():
		return _STABLER_ONLY_ALWAYS + _STABLER_ONLY_WHEN_DESK_OPEN
	return _STABLER_ONLY_ALWAYS


def assert_write_via_stabler(doc, method=None) -> None:
	"""Doc-event hook: raise PermissionError unless caller is Stabler or an admin."""
	# Cheapest first: this one never touches the DB, and it is the path almost
	# every write takes, so the settings read below stays off the hot path.
	if _from_stabler_or_headless():
		return
	if _is_admin():
		return
	if doc.doctype not in _locked_doctypes():
		return
	frappe.throw(
		_("{0} can only be created or changed through the Stabler app.").format(_(doc.doctype)),
		frappe.PermissionError,
	)
