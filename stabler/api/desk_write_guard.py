"""Restrict Sales Order / Sales Invoice writes to the Stabler app.

Registered as before_validate / before_cancel / on_trash doc-events for SO & SI
in hooks.py. Blocks any create/edit/submit/cancel/delete that does NOT originate
from a stabler.api.* call, so these docs are mutable only via the Stabler SPA.

Exempt (allowed through):
  - System Manager / Administrator.
  - Sites with Stabler Settings.allow_desk_access on — a tenant that opens the
    Desk to everyone opts out of this lock too.
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


def assert_write_via_stabler(doc, method=None) -> None:
	"""Doc-event hook: raise PermissionError unless caller is Stabler or an admin."""
	if _is_admin():
		return
	if desk_access_enabled():
		return
	if _from_stabler_or_headless():
		return
	frappe.throw(
		_("Sales Orders and Sales Invoices can only be created or changed through the Stabler app."),
		frappe.PermissionError,
	)
