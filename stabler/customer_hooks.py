"""Customer doc_events — single-level parent/child hierarchy validation.

Wired in hooks.py as Customer.validate. Enforces the plan §2 K2 rules on the
`custom_parent_customer` link. This is a shared-bench app module, so it must be a
safe no-op on tenants where the Custom Field was never created: we read the value
with getattr(...) (absent field → None → early return) and never touch the
`custom_parent_customer` column unless a parent was actually set on this doc
(which is only possible when the field exists).
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.stabler.customer_hierarchy import (
	ERR_HAS_CHILDREN,
	ERR_PARENT_HAS_PARENT,
	ERR_SELF,
	check_parent_link,
)

_MESSAGES = {
	ERR_SELF: lambda: _("A customer cannot be its own parent."),
	ERR_PARENT_HAS_PARENT: lambda: _(
		"The selected parent already belongs to another parent. "
		"Only one level of hierarchy is allowed."
	),
	ERR_HAS_CHILDREN: lambda: _(
		"This customer already has child locations, so it cannot become a child itself."
	),
}


def validate_hierarchy(doc, method=None):
	"""Reject invalid parent links. No-op when the field is absent/empty."""
	parent = getattr(doc, "custom_parent_customer", None)
	if not parent:
		return

	if not frappe.db.exists("Customer", parent):
		frappe.throw(_("The selected parent customer does not exist."))

	# Reaching here means the field exists (the doc carried a value), so reading
	# custom_parent_customer on the parent row is safe.
	parent_has_own_parent = bool(
		frappe.db.get_value("Customer", parent, "custom_parent_customer")
	)
	customer_has_children = bool(
		doc.name and frappe.db.exists("Customer", {"custom_parent_customer": doc.name})
	)

	code = check_parent_link(
		doc.name,
		parent,
		parent_has_own_parent=parent_has_own_parent,
		customer_has_children=customer_has_children,
	)
	if code:
		frappe.throw(_MESSAGES[code]())
