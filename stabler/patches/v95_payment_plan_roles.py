"""Create the two Payment Plan Frappe Roles — and make them desk-less, which insert-if-missing does not.

The payment calendar has exactly two levels of authority, and they are roles
rather than a name check because Zafar asked for it that way (2026-08-19,
"yetki rol olsun"): a ``Payment Plan User`` keeps their own plan, and a
``Payment Plan Manager`` reads across everyone's and sees the totals. The API
resolves the difference from the session's roles; nothing in the SPA decides it.

**Why this patch does more than v84 and v87 did.** Those two insert a Role only
when it is missing, and every role they create still reads ``desk_access = 1``
on a migrated site. Measured on genesis-test.local, 2026-08-19: ``Payment Plan
Manager`` was created at 20:26:23.753 and this patch's Patch Log row is stamped
20:26:24.033 — 280 ms later. The role was not created here at all. Frappe's
model sync creates any Role named by a doctype's ``permissions`` rows, and every
patch from v81 on sits under ``[post_model_sync]``, so the sync always wins and
the patch always takes the skip branch. ``desk_access = 0`` on the insert path
is therefore dead code on every site that ever ran a migrate.

So the flag is asserted, not merely passed at insert. It is written through the
document API rather than ``db.set_value`` because Frappe re-evaluates the user
type of everyone holding the role when the flag changes, and that re-evaluation
is the point of the flag — these roles exist to grant a capability inside the
SPA, never the Frappe Desk the SPA replaces. At patch time nobody holds either
role, so the re-evaluation is a no-op; it stops being one only if this ever runs
again after the roles are assigned, which is exactly when it should not be
skipped.

Deliberately not touched: the remittance (v87) and vehicle finance (v84) roles
carry the same stale ``desk_access = 1``. Repairing them would flip the user
type of everyone holding them, on seven tenants, in a patch nobody asked for.
That is Zafar's call, not this patch's.

Idempotent: an already-desk-less role is left alone, so a replayed migrate
writes nothing.
"""

import frappe

_ROLES = (
	"Payment Plan User",
	"Payment Plan Manager",
)


def execute():
	for role in _ROLES:
		_ensure_spa_only_role(role)


def _ensure_spa_only_role(role: str) -> None:
	"""Create the role if missing; either way leave it without Desk access."""
	if not frappe.db.exists("Role", role):
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 0  # SPA-only; no Frappe Desk access
		doc.insert(ignore_permissions=True)
		return

	if frappe.db.get_value("Role", role, "desk_access"):
		doc = frappe.get_doc("Role", role)
		doc.desk_access = 0
		doc.save(ignore_permissions=True)
