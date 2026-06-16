"""Universal search across master and transactional data for the Cmd+K palette."""

from __future__ import annotations

import frappe
from frappe import _


def _like(q: str) -> str:
	return f"%{q}%"


@frappe.whitelist()
def palette_search(query: str, company: str | None = None, limit_per_kind: int = 5):
	query = (query or "").strip()
	if not query:
		return {"customers": [], "suppliers": [], "items": [], "invoices": []}

	limit = max(1, min(int(limit_per_kind), 20))
	like = _like(query)

	# Multi-tenant scoping applies ONLY to the company-bearing result sets
	# (Sales/Purchase Invoice). Customer/Supplier/Item are company-agnostic
	# ERPNext masters with no `company` column — intentionally shared across
	# companies within a site — so they are not filtered here.
	# Validate a passed company against the caller's allowed set; when omitted,
	# restrict a scoped non-admin to their allowed companies rather than
	# returning every tenant's invoices. Admins / unrestricted users (empty
	# allowed list) are unaffected.
	from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies

	is_admin = any(r in frappe.get_roles() for r in _ADMIN_ROLES)
	allowed = [] if is_admin else _user_allowed_companies(frappe.session.user)
	if company and allowed and company not in allowed:
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)

	customers = frappe.db.sql(
		"""
		SELECT name, customer_name AS title, customer_group AS subtitle
		FROM `tabCustomer`
		WHERE disabled = 0
		  AND (customer_name LIKE %(q)s OR name LIKE %(q)s)
		ORDER BY customer_name ASC
		LIMIT %(limit)s
		""",
		{"q": like, "limit": limit},
		as_dict=True,
	)

	suppliers = frappe.db.sql(
		"""
		SELECT name, supplier_name AS title, supplier_group AS subtitle
		FROM `tabSupplier`
		WHERE disabled = 0
		  AND (supplier_name LIKE %(q)s OR name LIKE %(q)s)
		ORDER BY supplier_name ASC
		LIMIT %(limit)s
		""",
		{"q": like, "limit": limit},
		as_dict=True,
	)

	items = frappe.db.sql(
		"""
		SELECT name, item_name AS title, item_group AS subtitle
		FROM `tabItem`
		WHERE disabled = 0
		  AND (item_name LIKE %(q)s OR name LIKE %(q)s OR item_code LIKE %(q)s)
		ORDER BY item_name ASC
		LIMIT %(limit)s
		""",
		{"q": like, "limit": limit},
		as_dict=True,
	)

	invoice_conds = ["(name LIKE %(q)s OR customer LIKE %(q)s OR customer_name LIKE %(q)s)"]
	invoice_params: dict = {"q": like, "limit": limit}
	if company:
		invoice_conds.append("company = %(company)s")
		invoice_params["company"] = company
	elif allowed:
		invoice_conds.append("company IN %(allowed)s")
		invoice_params["allowed"] = tuple(allowed)
	sales_invoices = frappe.db.sql(
		f"""
		SELECT name, name AS title, customer_name AS subtitle,
		       'Sales Invoice' AS doctype, posting_date, grand_total, status
		FROM `tabSales Invoice`
		WHERE docstatus < 2 AND {" AND ".join(invoice_conds)}
		ORDER BY posting_date DESC
		LIMIT %(limit)s
		""",
		invoice_params,
		as_dict=True,
	)

	pi_conds = ["(name LIKE %(q)s OR supplier LIKE %(q)s OR supplier_name LIKE %(q)s)"]
	pi_params: dict = {"q": like, "limit": limit}
	if company:
		pi_conds.append("company = %(company)s")
		pi_params["company"] = company
	elif allowed:
		pi_conds.append("company IN %(allowed)s")
		pi_params["allowed"] = tuple(allowed)
	purchase_invoices = frappe.db.sql(
		f"""
		SELECT name, name AS title, supplier_name AS subtitle,
		       'Purchase Invoice' AS doctype, posting_date, grand_total, status
		FROM `tabPurchase Invoice`
		WHERE docstatus < 2 AND {" AND ".join(pi_conds)}
		ORDER BY posting_date DESC
		LIMIT %(limit)s
		""",
		pi_params,
		as_dict=True,
	)

	return {
		"customers": customers,
		"suppliers": suppliers,
		"items": items,
		"invoices": list(sales_invoices) + list(purchase_invoices),
	}
