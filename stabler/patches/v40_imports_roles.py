"""Create the imports-module Frappe Roles.

Adds two desk-less roles used purely as the SPA access layer for the new
imports module: Imports User, Imports Manager. "Stabler Declarant" and
"Stabler Logist" are reused from v38_tender_view_roles — not re-created here.

Idempotent: each Role is inserted only if missing. Pre-sync safe (Role is a
core doctype that always exists), but listed under [post_model_sync] to sit
alongside the other imports-module patches (v41).
"""

import frappe

_ROLES = ("Imports User", "Imports Manager")


def execute():
	for role in _ROLES:
		if frappe.db.exists("Role", role):
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 0  # SPA-only; no Frappe Desk access
		doc.insert(ignore_permissions=True)
