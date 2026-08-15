"""Create the Vehicle Finance Center Frappe Roles.

Seven desk-less roles used purely as the SPA capability layer for the Vehicle
Finance Center (module key `installment`, engine `Agreement V1`): Viewer,
Contract Clerk, Collector, Payables Clerk, Reviewer, Cashier, Manager.

Idempotent: each Role is inserted only if missing. Pre-sync and post-sync safe
(Role is a core doctype that always exists).
"""

import frappe

_ROLES = (
	"Vehicle Finance Viewer",
	"Vehicle Finance Contract Clerk",
	"Vehicle Finance Collector",
	"Vehicle Finance Payables Clerk",
	"Vehicle Finance Reviewer",
	"Vehicle Finance Cashier",
	"Vehicle Finance Manager",
)


def execute():
	for role in _ROLES:
		if frappe.db.exists("Role", role):
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 0  # SPA-only; no Frappe Desk access
		doc.insert(ignore_permissions=True)
