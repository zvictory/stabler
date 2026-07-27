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
from frappe.utils import cint, flt

from stabler.stabler.customer_hierarchy import (
	ERR_HAS_CHILDREN,
	ERR_PARENT_HAS_PARENT,
	ERR_SELF,
	check_parent_link,
	credit_limit_decision,
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


# ---------------------------------------------------------------------------
# Parent-chain credit limit (plan §2 K2). Wired in hooks.py as a Sales Invoice
# `validate` hook. The credit limit lives on the chain ROOT (the parent, or the
# customer itself when it is a parent) and is checked against the whole chain's
# outstanding receivable plus this invoice — never per-child.
#
# NOTE: ERPNext's own per-customer credit-limit check is intentionally left
# DISABLED for these chained customers (their limit rows are cleared, or their
# "bypass" flag set). This hook is the single source of truth for the group
# limit; running both would double-count. See docs/plans §2 K2.
# ---------------------------------------------------------------------------


def check_sales_invoice_credit_limit(doc, method=None):
	"""Throw when a Sales Invoice would push its customer chain past the root's
	credit limit. Deliberately cheap and a hard no-op on the common paths.

	Bypass: users with the Accounts Manager or System Manager role are allowed
	through (a warning is logged), matching the finance-override convention used
	elsewhere in the app."""
	# --- fast no-op guards (ordered cheapest-first) -----------------------
	if not frappe.db.get_single_value("Stabler Settings", "enable_parent_credit_check"):
		return
	if not frappe.db.has_column("Customer", "custom_parent_customer"):
		return
	customer = getattr(doc, "customer", None)
	company = getattr(doc, "company", None)
	if not customer or not company:
		return
	if cint(getattr(doc, "is_return", 0)):
		return  # credit notes reduce exposure — never blocked

	parent = frappe.db.get_value("Customer", customer, "custom_parent_customer")
	root = parent or customer
	chain = [root, *frappe.db.get_all(
		"Customer", filters={"custom_parent_customer": root, "disabled": 0}, pluck="name"
	)]
	# Standalone customer (no parent and no children of its own) → not a chain.
	if not parent and len(chain) == 1:
		return

	# Root's group credit limit from ERPNext's native per-company child table.
	if not frappe.db.exists("DocType", "Customer Credit Limit"):
		return
	limit = frappe.db.get_value(
		"Customer Credit Limit", {"parent": root, "company": company}, "credit_limit"
	)
	if not flt(limit):
		return  # 0 / absent → unlimited

	# Chain outstanding in BASE currency from the GL (same signed source the
	# rollup uses), excluding this invoice's own voucher so an amend/re-validate
	# never double-counts. New base_grand_total is then added on top.
	params: dict = {"company": company, "self": doc.name or ""}
	placeholders = []
	for i, name in enumerate(chain):
		key = f"c{i}"
		params[key] = name
		placeholders.append(f"%({key})s")
	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(debit - credit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND party_type = 'Customer'
		  AND is_cancelled = 0
		  AND voucher_no != %(self)s
		  AND party IN ({", ".join(placeholders)})
		""",
		params,
	)
	chain_outstanding = flt(row[0][0]) if row else 0.0
	new_amount = flt(getattr(doc, "base_grand_total", 0)) or flt(getattr(doc, "grand_total", 0))

	decision = credit_limit_decision(limit, chain_outstanding, new_amount)
	if not decision.exceeded:
		return

	roles = set(frappe.get_roles())
	root_name = frappe.db.get_value("Customer", root, "customer_name") or root
	if {"Accounts Manager", "System Manager"} & roles:
		frappe.logger("stabler").warning(
			"Parent-chain credit limit bypassed by %s for chain root %s: "
			"projected %.2f > limit %.2f"
			% (frappe.session.user, root, decision.projected, decision.limit)
		)
		return
	frappe.throw(
		_(
			"This sale would bring {0}'s group balance to {1}, over its credit limit of {2}. "
			"Ask an Accounts Manager to approve or increase the limit."
		).format(root_name, f"{decision.projected:,.2f}", f"{decision.limit:,.2f}")
	)


@frappe.whitelist()
def get_parent_credit_limit_status(customer: str, company: str | None = None) -> dict:
	"""Return the credit limit status of the customer's parent chain.

	Gated by Customer read permission (IDOR guard).
	"""
	if not frappe.has_permission("Customer", "read", doc=customer):
		frappe.throw(frappe._("Not permitted to read Customer: {0}").format(customer), frappe.PermissionError)

	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.get_all("Company", pluck="name", limit=1)[0]

	parent = frappe.db.get_value("Customer", customer, "custom_parent_customer")
	root = parent or customer
	root_name = frappe.db.get_value("Customer", root, "customer_name") or root

	# Get the chain (active, non-disabled children)
	chain = [root]
	if frappe.db.has_column("Customer", "custom_parent_customer"):
		chain.extend(frappe.db.get_all(
			"Customer", filters={"custom_parent_customer": root, "disabled": 0}, pluck="name"
		))

	limit = 0.0
	if frappe.db.exists("DocType", "Customer Credit Limit"):
		limit = flt(frappe.db.get_value(
			"Customer Credit Limit", {"parent": root, "company": company}, "credit_limit"
		))

	chain_outstanding = 0.0
	if chain:
		placeholders = [f"%({f'c{i}'})s" for i in range(len(chain))]
		params = {"company": company}
		for i, name in enumerate(chain):
			params[f"c{i}"] = name

		row = frappe.db.sql(
			f"""
			SELECT COALESCE(SUM(debit - credit), 0)
			FROM `tabGL Entry`
			WHERE company = %(company)s
			  AND party_type = 'Customer'
			  AND is_cancelled = 0
			  AND party IN ({", ".join(placeholders)})
			""",
			params,
		)
		chain_outstanding = flt(row[0][0]) if row else 0.0

	remaining = limit - chain_outstanding if limit else 0.0
	exceeded = bool(limit and chain_outstanding > limit)

	return {
		"root_customer": root,
		"root_customer_name": root_name,
		"company": company,
		"credit_limit": limit,
		"chain_outstanding": chain_outstanding,
		"remaining_limit": remaining,
		"exceeded": exceeded,
	}

