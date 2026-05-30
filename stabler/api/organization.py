"""Organization (Company) API for Stabler."""

from __future__ import annotations

import frappe
from frappe import _

from stabler.stabler.doctype.stabler_settings.stabler_settings import (
	get_company_module_row,
	module_map_for,
)


_MODULE_FIELDS = {
	"money": "enable_money",
	"sales": "enable_sales",
	"purchasing": "enable_purchasing",
	"inventory": "enable_inventory",
	"manufacturing": "enable_manufacturing",
	"hr": "enable_hr",
	"stock_reservation": "enable_stock_reservation",
	"compliance": "enable_compliance",
	"field_sales": "enable_field_sales",
	"marketing": "enable_marketing",
}

# Maps each SPA module key to the Frappe roles that grant access to it.
# Admins (System Manager / Stabler Admin) always see all modules and bypass this map.
# Any module key absent from this map is admin-only (least-privilege default).
_MODULE_ROLES: dict[str, list[str]] = {
	"money": ["Accounts User", "Accounts Manager"],
	"sales": ["Sales User", "Sales Manager"],
	"purchasing": ["Purchase User", "Purchase Manager"],
	"inventory": ["Stock User", "Stock Manager"],
	"stock_reservation": ["Stock User", "Stock Manager"],
	"manufacturing": ["Manufacturing User", "Manufacturing Manager"],
	"hr": ["HR User", "HR Manager"],
	"field_sales": ["Sales User", "Sales Manager"],
	"marketing": ["Sales Manager"],
	"compliance": ["Accounts Manager"],
}

_ADMIN_ROLES = ("System Manager", "Stabler Admin")


def _require_admin() -> None:
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _user_allowed_companies(user: str) -> list[str]:
	"""Read the custom Table MultiSelect on User. Empty list = all companies."""
	if not user or user == "Guest":
		return []
	try:
		rows = frappe.get_all(
			"Stabler User Company",
			filters={"parent": user, "parenttype": "User", "parentfield": "allowed_companies"},
			fields=["company"],
		)
		return sorted({r.company for r in rows if r.company})
	except Exception:
		return []


@frappe.whitelist()
def list_companies():
	"""All companies the current user can read (filtered by Allowed Companies if set)."""
	rows = frappe.get_all(
		"Company",
		fields=["name", "abbr", "default_currency", "country"],
		order_by="name asc",
	)
	allowed = _user_allowed_companies(frappe.session.user)
	if allowed:
		rows = [r for r in rows if r["name"] in allowed]
	return rows


@frappe.whitelist()
def boot():
	"""Initial payload for the SPA: user, roles, allowed companies, module flags."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Login required"), frappe.PermissionError)

	roles = frappe.get_roles(user)
	companies = list_companies()
	default_company = frappe.defaults.get_user_default("Company", user) or (
		companies[0]["name"] if companies else None
	)
	# Validate default sits within allowed list.
	if default_company and not any(c["name"] == default_company for c in companies):
		default_company = companies[0]["name"] if companies else None

	user_doc = None
	try:
		user_doc = frappe.get_doc("User", user)
	except Exception:
		pass

	# Derive per-user allowed modules from assigned roles.
	# Admins see all modules; everyone else sees only modules their roles grant.
	is_admin = any(r in roles for r in _ADMIN_ROLES)
	allowed_modules = (
		list(_MODULE_ROLES.keys())
		if is_admin
		else [mod for mod, allow in _MODULE_ROLES.items() if any(r in roles for r in allow)]
	)

	return {
		"user": {
			"id": user,
			"name": (user_doc and (user_doc.full_name or user_doc.first_name)) or user,
			"image": (user_doc and user_doc.user_image) or "",
			"language": (user_doc and user_doc.language) or frappe.local.lang or "en",
		},
		"roles": roles,
		"companies": companies,
		"default_company": default_company,
		"allowed_companies": _user_allowed_companies(user),
		"modules": module_map_for(default_company) if default_company else {},
		"allowed_modules": allowed_modules,
	}


@frappe.whitelist()
def switch_company(company: str):
	"""Persist the user's preferred default company on their User doc."""
	if not company:
		frappe.throw(_("Company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))

	user = frappe.session.user
	if user == "Guest":
		return {"ok": False, "reason": "guest"}

	allowed = _user_allowed_companies(user)
	if allowed and company not in allowed:
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)

	frappe.defaults.set_user_default("company", company, user)
	return {
		"ok": True,
		"company": company,
		"modules": module_map_for(company),
	}


@frappe.whitelist()
def get_company_modules(company: str):
	"""Module bool map for the given company."""
	if not company:
		return {}
	# Read-only: any logged-in user with access to the company can fetch.
	allowed = _user_allowed_companies(frappe.session.user)
	if allowed and company not in allowed and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return module_map_for(company)


@frappe.whitelist()
def update_company_modules(
	company: str,
	money=None,
	sales=None,
	purchasing=None,
	inventory=None,
	manufacturing=None,
	hr=None,
	stock_reservation=None,
	compliance=None,
	field_sales=None,
	marketing=None,
):
	"""Admin-only: toggle per-module flags for a company. Pass 0/1 to update; omit to leave."""
	_require_admin()
	if not company:
		frappe.throw(_("Company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))

	settings = frappe.get_single("Stabler Settings")
	row = None
	for r in settings.company_modules or []:
		if r.company == company:
			row = r
			break
	if not row:
		row = settings.append(
			"company_modules",
			{
				"company": company,
				"enable_money": 1,
				"enable_sales": 1,
				"enable_purchasing": 1,
				"enable_inventory": 1,
				"enable_manufacturing": 1,
				"enable_hr": 1,
				"enable_stock_reservation": 1,
				"enable_compliance": 1,
				"enable_field_sales": 1,
				"enable_marketing": 1,
			},
		)

	updates = {
		"enable_money": money,
		"enable_sales": sales,
		"enable_purchasing": purchasing,
		"enable_inventory": inventory,
		"enable_manufacturing": manufacturing,
		"enable_hr": hr,
		"enable_stock_reservation": stock_reservation,
		"enable_compliance": compliance,
		"enable_field_sales": field_sales,
		"enable_marketing": marketing,
	}
	for field, val in updates.items():
		if val is None or val == "":
			continue
		setattr(row, field, 1 if str(val) in ("1", "true", "True") else 0)

	settings.save(ignore_permissions=True)
	frappe.db.commit()
	return module_map_for(company)


@frappe.whitelist()
def set_user_allowed_companies(user: str, companies):
	"""Admin-only: replace the user's Allowed Companies multi-select."""
	_require_admin()
	if not user or not frappe.db.exists("User", user):
		frappe.throw(_("User not found"))

	if isinstance(companies, str):
		companies = frappe.parse_json(companies) or []
	companies = [c for c in (companies or []) if c]

	user_doc = frappe.get_doc("User", user)
	user_doc.set("allowed_companies", [])
	for c in companies:
		if frappe.db.exists("Company", c):
			user_doc.append("allowed_companies", {"company": c})
	user_doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "allowed_companies": companies}


_SUPPORTED_LANGUAGES = {"en", "ru", "uz", "uzc"}


@frappe.whitelist()
def update_language(language: str):
	"""Persist the user's preferred UI language on their User doc."""
	if language not in _SUPPORTED_LANGUAGES:
		frappe.throw(_("Unsupported language: {0}").format(language))
	user = frappe.session.user
	if user == "Guest":
		return {"ok": False, "reason": "guest"}
	frappe.db.set_value("User", user, "language", language)
	return {"ok": True, "language": language}
