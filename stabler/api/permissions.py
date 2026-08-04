"""Record-level permission hooks for Stabler.

Covers:
  • Company isolation (transactional doctypes with a ``company`` field).
  • Owner / territory scoping for company-agnostic masters (Customer, Supplier)
    — Gap #46.

Registered in ``hooks.py`` as ``permission_query_conditions`` (list / report /
get_list queries) and ``has_permission`` (single-doc access). Because these are
framework hooks, **both the REST API and the Desk inherit them**.

Safe-by-default throughout: restriction applies ONLY when a non-empty allow-list
is present and the user is not an admin (System Manager / Stabler Admin).

## WIRING NOTE
---------------------------------------------------------------------------
Add the following to hooks.py **under the existing permission_query_conditions
and has_permission blocks** to activate Gap #46 (Customer / Supplier scoping):

    permission_query_conditions = {
        ...existing entries...,
        "Customer":  "stabler.api.permissions.customer_query",
        "Supplier":  "stabler.api.permissions.supplier_query",
    }

    has_permission = {
        ...existing entries...,
        "Customer":  "stabler.api.permissions.master_has_permission",
        "Supplier":  "stabler.api.permissions.master_has_permission",
    }

Add the following **Stabler Settings** fields (Check type, default 0):
    restrict_masters_to_owner     — when enabled, users without an explicit
                                    allowed_owners list see only their own
                                    Customers/Suppliers.
    restrict_masters_to_territory — when enabled, the territory filter applies.

Add the following **Stabler Settings** field (Table MultiSelect or Small Text):
    cost_visible_roles            — comma-separated role names that may see
                                    valuation_rate, last_purchase_rate, margins,
                                    etc. (used by Gap #45 field masking).

For Gap #45 (cost/margin field masking) the recommended ERPNext approach is to
set ``perm_level: 1`` on each cost field in the Item / Item Price doctypes, and
then **remove level-1 read permission** from all roles except those in
``cost_visible_roles``. That way ERPNext itself omits the columns from REST
responses without any extra Python. The ``mask_fields`` helper in
``stabler.api._perm_rules`` (and the thin ``apply_cost_mask`` wrapper below)
are available as a fallback for custom endpoints that bypass standard permission
levels.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import frappe
from frappe.utils import get_datetime

from stabler.api._perm_rules import (
	is_company_allowed,
	master_allowed,
	needs_company_restriction,
	needs_owner_restriction,
	needs_territory_restriction,
)
from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies

# Transactional doctypes with a `company` field that we scope.
SCOPED_DOCTYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
	"Sales Order",
	"Purchase Order",
	"Delivery Note",
	"Purchase Receipt",
	"Stock Entry",
	"Stock Reconciliation",
	"Bank Transaction",
	"CRM Activity",
	"CRM Stage Event",
)


def _allowed_for(user: str | None):
	"""Allowed companies for `user`, or None when unrestricted (admin / no list)."""
	user = user or frappe.session.user
	if not user or user in ("Administrator", "Guest"):
		return None
	if any(r in frappe.get_roles(user) for r in _ADMIN_ROLES):
		return None
	allowed = _user_allowed_companies(user)
	return allowed or None  # empty list ⇒ unrestricted


def _company_condition(user: str | None, doctype: str) -> str:
	"""SQL WHERE fragment limiting `doctype` rows to the user's companies.

	Returns "" when unrestricted. Values are escaped via frappe.db.escape (the
	sanctioned way to build a permission_query_conditions fragment).
	"""
	allowed = _allowed_for(user)
	if not needs_company_restriction(allowed):
		return ""
	escaped = ", ".join(frappe.db.escape(c) for c in allowed)
	table = f"`tab{doctype}`"
	# Allow rows whose company is in the list, or that have no company set.
	return f"({table}.company in ({escaped}) or {table}.company is null or {table}.company = '')"


def company_has_permission(doc, ptype=None, user=None):
	"""has_permission hook: deny a single doc whose company is out of scope.

	Returns True to allow, False to deny. Never None — Frappe treats None as
	falsy and would block permission even for admin users.
	"""
	allowed = _allowed_for(user)
	if not needs_company_restriction(allowed):
		return True
	if doc is None:
		return True
	company = getattr(doc, "company", None) if doc is not None else None
	if not company:
		return True
	return is_company_allowed(company, allowed)


# --- permission_query_conditions wrappers (Frappe calls these with `user`) --- #
def sales_invoice_query(user=None):
	return _company_condition(user, "Sales Invoice")


def purchase_invoice_query(user=None):
	return _company_condition(user, "Purchase Invoice")


def payment_entry_query(user=None):
	return _company_condition(user, "Payment Entry")


def journal_entry_query(user=None):
	return _company_condition(user, "Journal Entry")


def sales_order_query(user=None):
	return _company_condition(user, "Sales Order")


def purchase_order_query(user=None):
	return _company_condition(user, "Purchase Order")


def delivery_note_query(user=None):
	return _company_condition(user, "Delivery Note")


def purchase_receipt_query(user=None):
	return _company_condition(user, "Purchase Receipt")


def stock_entry_query(user=None):
	return _company_condition(user, "Stock Entry")


def stock_reconciliation_query(user=None):
	return _company_condition(user, "Stock Reconciliation")


def bank_transaction_query(user=None):
	return _company_condition(user, "Bank Transaction")


def crm_activity_query(user=None):
	return _company_condition(user, "CRM Activity")


def crm_stage_event_query(user=None):
	return _company_condition(user, "CRM Stage Event")


def tender_master_query(user=None):
	return _company_condition(user, "Tender Master")


def tender_sourcing_decision_query(user=None):
	return _company_condition(user, "Tender Sourcing Decision")


# ---------------------------------------------------------------------------
# Gap #46 — owner / territory scoping for masters (Customer, Supplier)
# ---------------------------------------------------------------------------


def _is_admin(user: str) -> bool:
	"""True for Administrator / Guest special accounts and Stabler admin roles."""
	if not user or user in ("Administrator", "Guest"):
		return True
	return any(r in frappe.get_roles(user) for r in _ADMIN_ROLES)


def _master_allowed_owners(user: str):
	"""Return the owner restriction list for *user*, or None when unrestricted.

	Reads the ``Stabler User Allowed Owner`` child table (parent = User,
	parentfield = ``allowed_owners``).  Empty result → no restriction.
	"""
	try:
		rows = frappe.get_all(
			"Stabler User Allowed Owner",
			filters={"parent": user, "parenttype": "User", "parentfield": "allowed_owners"},
			fields=["owner_email"],
		)
		owners = sorted({r.owner_email for r in rows if r.owner_email})
		return owners if owners else None
	except Exception:
		return None


def _master_allowed_territories(user: str):
	"""Return the territory restriction list for *user*, or None when unrestricted.

	Reads the ``Stabler User Allowed Territory`` child table (parent = User,
	parentfield = ``allowed_territories``).  Empty result → no restriction.
	"""
	try:
		rows = frappe.get_all(
			"Stabler User Allowed Territory",
			filters={"parent": user, "parenttype": "User", "parentfield": "allowed_territories"},
			fields=["territory"],
		)
		territories = sorted({r.territory for r in rows if r.territory})
		return territories if territories else None
	except Exception:
		return None


def _master_condition(user: str | None, doctype: str) -> str:
	"""SQL WHERE fragment for owner + territory restrictions on a master doctype.

	Returns "" when the user is unrestricted on both axes.  SQL values are
	escaped via ``frappe.db.escape`` (the sanctioned pattern).
	"""
	user = user or frappe.session.user
	if _is_admin(user):
		return ""

	allowed_owners = _master_allowed_owners(user)
	allowed_territories = _master_allowed_territories(user)

	if not needs_owner_restriction(allowed_owners) and not needs_territory_restriction(allowed_territories):
		return ""

	table = f"`tab{doctype}`"
	clauses: list[str] = []

	if needs_owner_restriction(allowed_owners):
		escaped = ", ".join(frappe.db.escape(o) for o in allowed_owners)
		# Blank owner rows are never hidden.
		clauses.append(f"({table}.owner in ({escaped}) or {table}.owner is null or {table}.owner = '')")

	if needs_territory_restriction(allowed_territories):
		escaped = ", ".join(frappe.db.escape(t) for t in allowed_territories)
		# Blank territory rows are never hidden.
		clauses.append(
			f"({table}.territory in ({escaped}) or {table}.territory is null or {table}.territory = '')"
		)

	return " and ".join(clauses)


def master_has_permission(doc, ptype=None, user=None):
	"""has_permission hook for Customer and Supplier.

	Returns True to allow, False to deny. Never None.
	"""
	user = user or frappe.session.user
	if _is_admin(user):
		return True

	if doc is None:
		return True

	allowed_owners = _master_allowed_owners(user)
	allowed_territories = _master_allowed_territories(user)

	if not needs_owner_restriction(allowed_owners) and not needs_territory_restriction(allowed_territories):
		return True

	if isinstance(doc, str):
		owner = None
		territory = None
		for dt in ("Customer", "Supplier"):
			if frappe.db.exists(dt, doc):
				vals = frappe.db.get_value(dt, doc, ["owner", "territory"], as_dict=True)
				if vals:
					owner = vals.get("owner")
					territory = vals.get("territory")
				break
	else:
		owner = getattr(doc, "owner", None)
		territory = getattr(doc, "territory", None)

	return master_allowed(owner, territory, allowed_owners, allowed_territories)


def customer_query(user=None):
	"""permission_query_conditions for Customer."""
	return _master_condition(user, "Customer")


def supplier_query(user=None):
	"""permission_query_conditions for Supplier."""
	return _master_condition(user, "Supplier")


# ---------------------------------------------------------------------------
# Gap #45 — cost / margin field masking (thin wrapper for custom endpoints)
# ---------------------------------------------------------------------------

from stabler.api._perm_rules import COST_FIELDS, mask_fields


def _user_has_cost_visibility(user: str | None, cost_visible_roles) -> bool:
	"""True when *user* holds at least one role from *cost_visible_roles*.

	Parameters
	----------
	user:
		Frappe user email; defaults to ``frappe.session.user``.
	cost_visible_roles:
		Iterable of role names that grant cost visibility (read from
		Stabler Settings ``cost_visible_roles`` field in the caller).
		Admins always have visibility.
	"""
	user = user or frappe.session.user
	if _is_admin(user):
		return True
	if not cost_visible_roles:
		# No roles configured → nobody can see cost (safe-by-default).
		return False
	user_roles = set(frappe.get_roles(user))
	return bool(user_roles & set(cost_visible_roles))


# Roles that always see landed-cost / dual-pricing figures (migration plan §6),
# on top of whatever is configured in Stabler Settings ``cost_visible_roles``.
_DEFAULT_COST_ROLES = ("Imports Manager", "Director")


def cost_visible_roles() -> list[str]:
	"""The role names granted cost visibility (Stabler Settings comma list + defaults).

	Single source of truth shared by the imports SPA API (``stabler.api.imports``)
	and the SPA boot payload (``stabler.api.organization.boot``) so the frontend's
	``cost_visible`` flag and the backend masking gate can never drift apart.
	"""
	raw = frappe.db.get_single_value("Stabler Settings", "cost_visible_roles") or ""
	roles = [r.strip() for r in raw.replace("\n", ",").split(",") if r.strip()]
	for default_role in _DEFAULT_COST_ROLES:
		if default_role not in roles:
			roles.append(default_role)
	return roles


def cost_visible_for(user: str | None = None) -> bool:
	"""True when *user* (default: the session user) may see landed-cost figures."""
	return _user_has_cost_visibility(user or frappe.session.user, cost_visible_roles())


def apply_cost_mask(payload, user=None, cost_visible_roles=None):
	"""Strip cost/margin fields from *payload* for users lacking visibility.

	Intended for custom list / detail endpoints that bypass standard Frappe
	perm-level filtering.  Pass the ``cost_visible_roles`` iterable from
	``frappe.get_single("Stabler Settings").cost_visible_roles`` (or a cached
	equivalent).

	Parameters
	----------
	payload:
		A ``dict`` or ``list[dict]`` — modified in-place, also returned.
	user:
		Frappe user; defaults to session user.
	cost_visible_roles:
		Iterable of role names; ``None`` or empty → everyone masked.

	Returns
	-------
	The (possibly mutated) payload.
	"""
	visible = _user_has_cost_visibility(user, cost_visible_roles or [])
	return mask_fields(payload, visible)


# ---------------------------------------------------------------------------
# Custom DocPerm shadowing (incident 2026-08-03 / 2026-08-04)
# ---------------------------------------------------------------------------
#
# Frappe semantics: as soon as ANY row exists in `tabCustom DocPerm` for a
# doctype, that doctype's ENTIRE standard `tabDocPerm` set is ignored.
# ``frappe.permissions.add_permission()`` handles this correctly — it calls
# ``setup_custom_perms()``, which copies the full standard set first. Ad-hoc
# scripts that INSERT rows directly skip that step and silently strip every
# standard role of its permissions.
#
# That is what happened on mikas (2026-08-03, tender roles) and anjan
# (2026-08-04, "Dokon POS" role): a single row per doctype shadowed the whole
# standard set, so ordinary users lost `read` on Customer / Item and `report`
# on GL Entry.
#
# The helpers below detect and repair that state. They only ever ADD missing
# rows — never delete or downgrade — so a deliberate restriction can never be
# widened by accident.

# Row identity / metadata columns — everything else on the two tables is a
# permission flag we want to copy verbatim.
_PERM_META_COLUMNS = {
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"docstatus",
	"idx",
	"parent",
	"parenttype",
	"parentfield",
	"role",
	"permlevel",
	"_user_tags",
	"_comments",
	"_assign",
	"_liked_by",
}


def _perm_flag_columns() -> list[str]:
	"""Permission flag columns common to DocPerm and Custom DocPerm.

	Derived from meta rather than hardcoded so a Frappe upgrade that adds or
	drops a flag cannot break the repair with an unknown-column SQL error.
	"""
	shared = set(frappe.get_meta("DocPerm").get_valid_columns()) & set(
		frappe.get_meta("Custom DocPerm").get_valid_columns()
	)
	return sorted(shared - _PERM_META_COLUMNS)


def _standard_docperms(doctype: str) -> list[dict]:
	"""App-shipped permission rows for *doctype*, ``permlevel`` included."""
	cols = ", ".join(f"`{c}`" for c in ["role", "permlevel"] + _perm_flag_columns())
	return frappe.db.sql(
		f"SELECT {cols} FROM `tabDocPerm` WHERE parent = %s ORDER BY permlevel, role",  # noqa: S608
		(doctype,),
		as_dict=True,
	)


def _custom_docperm_keys(doctype: str) -> set:
	"""``(role, permlevel)`` pairs already present in Custom DocPerm."""
	rows = frappe.db.sql(
		"SELECT role, permlevel FROM `tabCustom DocPerm` WHERE parent = %s",
		(doctype,),
		as_dict=True,
	)
	return {(r.role, int(r.permlevel or 0)) for r in rows}


def _custom_docperm_doctypes() -> list[str]:
	"""Every doctype that currently has at least one Custom DocPerm row."""
	return frappe.db.sql_list("SELECT DISTINCT parent FROM `tabCustom DocPerm` ORDER BY parent")


def detect_shadowed_doctypes() -> list[dict]:
	"""Doctypes whose Custom DocPerm set shadows read/report from standard roles.

	Pure read — never writes. Single source of truth shared by the repair patch,
	the nightly drift scan and the regression test.

	Returns one entry per affected doctype::

	    {"doctype": "GL Entry",
	     "missing": [{"role": "Auditor", "permlevel": 0, "read": 1, "report": 1}]}
	"""
	findings = []
	for doctype in _custom_docperm_doctypes():
		custom_keys = _custom_docperm_keys(doctype)
		missing = [
			{
				"role": p.role,
				"permlevel": int(p.permlevel or 0),
				"read": p.get("read"),
				"report": p.get("report"),
			}
			for p in _standard_docperms(doctype)
			if (p.get("read") or p.get("report"))
			and (p.role, int(p.permlevel or 0)) not in custom_keys
		]
		if missing:
			findings.append({"doctype": doctype, "missing": missing})
	return findings


def repair_shadowed_docperms(doctypes=None, only_created_after=None) -> dict:
	"""Re-insert the standard permission rows a Custom DocPerm set is shadowing.

	Only ever ADDS the missing ``(role, permlevel)`` rows, copied verbatim from
	``tabDocPerm``. Existing Custom DocPerm rows are never modified or deleted,
	so this call cannot widen a deliberate restriction. Idempotent.

	Parameters
	----------
	doctypes:
		Restrict to these doctypes; ``None`` → every doctype carrying Custom
		DocPerm rows.
	only_created_after:
		When set, a doctype is repaired only if **every** one of its existing
		Custom DocPerm rows was created at/after this timestamp — i.e. its custom
		set is entirely a product of the incident window. Older, deliberate
		restrictions are skipped untouched.

	Returns
	-------
	``{"repaired": {doctype: rows_added}, "skipped": [doctype, ...]}``
	"""
	logger = frappe.logger("stabler.permissions")
	flag_columns = _perm_flag_columns()
	repaired: dict[str, int] = {}
	skipped: list[str] = []

	for doctype in doctypes or _custom_docperm_doctypes():
		if only_created_after:
			oldest = frappe.db.sql(
				"SELECT MIN(creation) FROM `tabCustom DocPerm` WHERE parent = %s",
				(doctype,),
			)[0][0]
			if not oldest or get_datetime(oldest) < get_datetime(only_created_after):
				skipped.append(doctype)
				continue

		custom_keys = _custom_docperm_keys(doctype)
		added = 0
		for p in _standard_docperms(doctype):
			permlevel = int(p.permlevel or 0)
			if (p.role, permlevel) in custom_keys:
				continue
			row = {
				"doctype": "Custom DocPerm",
				"parent": doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": p.role,
				"permlevel": permlevel,
			}
			row.update({c: p.get(c) for c in flag_columns})
			frappe.get_doc(row).insert(ignore_permissions=True)
			custom_keys.add((p.role, permlevel))
			added += 1
			logger.info(
				f"restored Custom DocPerm: {doctype} / {p.role} / permlevel {permlevel}"
			)
		if added:
			repaired[doctype] = added

	return {"repaired": repaired, "skipped": skipped}


def _require_permission_admin() -> None:
	"""Guard for permission-introspection endpoints.

	Deliberately NOT ``_is_admin`` — that helper returns True for ``Guest``
	(it is written for record scoping, where Guest never reaches it).
	"""
	user = frappe.session.user
	if user == "Administrator":
		return
	if any(r in frappe.get_roles(user) for r in _ADMIN_ROLES):
		return
	frappe.throw(frappe._("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def docperm_shadow_report():
	"""Admin-only, read-only permission-drift report.

	Replaces the former ``sync_custom_docperm_for_masters`` endpoint, which was
	whitelisted with no authorization at all and mutated the permission tables.
	Repair now happens only via the migrate patch / scheduled task.
	"""
	_require_permission_admin()
	return {"findings": detect_shadowed_doctypes()}
