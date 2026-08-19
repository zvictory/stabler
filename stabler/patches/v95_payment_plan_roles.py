"""Create the two Payment Plan Frappe Roles.

The payment calendar has exactly two levels of authority, and they are roles
rather than a name check because Zafar asked for it that way (2026-08-19,
"yetki rol olsun"): a ``Payment Plan User`` keeps their own plan, and a
``Payment Plan Manager`` reads across everyone's and sees the totals. The API
resolves the difference from the session's roles; nothing in the SPA decides it.

Same shape as v87_remittance_roles and v84_vehicle_finance_roles: each Role is
inserted only if missing, and Role is a core doctype that always exists, so this
patch needs no table probe. Role creation is deliberately NOT gated on the
Payment Plan Entry table existing — the DocPerm rows naming these roles ship
inside the app's own doctype JSON, so any site with the app has them, and gating
would leave DocPerms pointing at a Role that was never created. The cost of not
gating is two inert Role records on a tenant that never turns the module on.

``desk_access = 0``: these are a capability layer for the SPA. A role created
without it hands its holder the Frappe Desk, which the SPA exists to replace.

Idempotent: the loop skips roles that already exist, so a replayed migrate
touches nothing.
"""

import frappe

_ROLES = (
	"Payment Plan User",
	"Payment Plan Manager",
)


def execute():
	for role in _ROLES:
		if frappe.db.exists("Role", role):
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 0  # SPA-only; no Frappe Desk access
		doc.insert(ignore_permissions=True)
