"""Create the tender role-view Frappe Roles.

Adds three desk-less roles used purely as the SPA access layer for the tender
role windows: Stabler Tender Director, Stabler Declarant, Stabler Logist.
(Sourcing uses the existing Sales User / Sales Manager roles.)

Idempotent: each Role is inserted only if missing. Pre-sync safe (Role is a core
doctype that always exists).
"""

import frappe

_ROLES = ("Stabler Tender Director", "Stabler Declarant", "Stabler Logist")


def execute():
	for role in _ROLES:
		if frappe.db.exists("Role", role):
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 0  # SPA-only; no Frappe Desk access
		doc.insert(ignore_permissions=True)
