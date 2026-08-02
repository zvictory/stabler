"""Organization (Company) API for Stabler."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from stabler.stabler.doctype.stabler_settings.stabler_settings import (
	_default_enable_row,
	get_company_module_row,
	module_map_for,
)


@frappe.whitelist(allow_guest=True)
def stabler_login(usr: str, pwd: str, remember: int = 1):
	"""Authenticate user and initialize session for Stabler SPA."""
	if not usr or not pwd:
		frappe.throw(_("Username/Email and Password are required."))

	frappe.local.form_dict["usr"] = usr
	frappe.local.form_dict["pwd"] = pwd

	try:
		login_manager = frappe.auth.LoginManager()
		login_manager.authenticate(user=usr, pwd=pwd)
		login_manager.post_login()
	except Exception:
		frappe.clear_messages()
		frappe.throw(_("Invalid username or password. Please check your credentials."))

	if not cint(remember):
		# Frappe always sets sid with max_age (CookieManager.init_cookies), so a
		# login normally survives ~10 days. Re-setting it without max_age turns it
		# into a browser-session cookie: closing the browser forgets the login.
		frappe.local.cookie_manager.set_cookie("sid", frappe.session.sid, httponly=True)

	user_info = (
		frappe.db.get_value("User", frappe.session.user, ["full_name", "email", "user_image", "language"], as_dict=True)
		if frappe.session.user and frappe.session.user != "Guest"
		else None
	) or {}
	company = frappe.db.get_value("Company", {"is_group": 0}, "name")

	return {
		"message": "Logged In",
		"user": {
			"id": frappe.session.user,
			"name": user_info.get("full_name") or frappe.session.user,
			"email": user_info.get("email") or "",
			"user_image": user_info.get("user_image") or "",
			"language": user_info.get("language") or "en",
		},
		"company": company,
		"redirect_to": "/stabler#/dashboard",
	}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def stabler_logout() -> dict:
	"""Logout the current user session for Stabler SPA gracefully."""
	try:
		if hasattr(frappe.local, "login_manager") and frappe.local.login_manager:
			frappe.local.login_manager.logout()
		elif hasattr(frappe, "auth") and hasattr(frappe.auth, "LoginManager"):
			frappe.auth.LoginManager().logout()
	except Exception:
		pass
	if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
		frappe.db.commit()
	return {"message": "Logged Out"}


_MODULE_FIELDS = {
	"money": "enable_money",
	"sales": "enable_sales",
	"purchasing": "enable_purchasing",
	"inventory": "enable_inventory",
	"manufacturing": "enable_manufacturing",
	"hr": "enable_hr",
	"crm": "enable_crm",
	"finance": "enable_finance",
	"pos": "enable_pos",
	"sfa": "enable_sfa",
	"field_service": "enable_field_service",
	"quality": "enable_quality",
	"assets": "enable_assets",
	"projects": "enable_projects",
	"tender": "enable_tender",
}


def _available_modules_for(company: str) -> dict[str, bool]:
	"""Return a boolean map of all 15 modules for a company.

	Checks Stabler Settings first; falls back to site defaults when unconfigured.
	"""
	if not company or not frappe.db.exists("Company", company):
		return {m: True for m in _MODULE_FIELDS}

	row = get_company_module_row(company)
	if row:
		return {mod: bool(row.get(field, True)) for mod, field in _MODULE_FIELDS.items()}

	# Fall back to site-wide module map
	site_map = module_map_for(company)
	return {m: site_map.get(m, True) for m in _MODULE_FIELDS}


def _user_role_list() -> set[str]:
	"""Get set of roles for current session user."""
	return set(frappe.get_roles(frappe.session.user))


def _has_company_access(company: str) -> bool:
	"""Check if current user is permitted for the given company."""
	user = frappe.session.user
	if user == "Administrator" or "System Manager" in _user_role_list():
		return True
	permitted = frappe.get_list(
		"User Permission",
		filters={"user": user, "allow": "Company"},
		pluck="for_value",
		ignore_permissions=True,
	)
	if not permitted:
		return True  # No company restrictions set
	return company in permitted


@frappe.whitelist()
def active_companies() -> list[dict]:
	"""List companies accessible by the current user."""
	all_comps = frappe.get_all(
		"Company",
		filters={"is_group": 0},
		fields=["name", "company_name", "default_currency"],
		order_by="name asc",
	)
	user = frappe.session.user
	if user == "Administrator" or "System Manager" in _user_role_list():
		return all_comps

	permitted = set(
		frappe.get_list(
			"User Permission",
			filters={"user": user, "allow": "Company"},
			pluck="for_value",
			ignore_permissions=True,
		)
	)
	if not permitted:
		return all_comps

	return [c for c in all_comps if c["name"] in permitted]


@frappe.whitelist()
def boot(company: str | None = None) -> dict:
	"""Return application bootstrap data for the active company & session user."""
	user = frappe.session.user
	user_info = (
		frappe.db.get_value("User", user, ["full_name", "email", "user_image", "language"], as_dict=True)
		if user and user != "Guest"
		else None
	) or {}

	companies = active_companies()
	comp_names = [c["name"] for c in companies]

	if not company or company not in comp_names:
		company = comp_names[0] if comp_names else ""

	modules = _available_modules_for(company) if company else {m: True for m in _MODULE_FIELDS}

	currency = frappe.get_cached_value("Company", company, "default_currency") if company else "USD"

	# Determine tender view permissions
	roles = _user_role_list()
	tender_views = []
	if "System Manager" in roles or "Sales Manager" in roles:
		tender_views.extend(["director", "sourcing", "sales"])
	elif "Sales User" in roles:
		tender_views.append("sales")
	elif "Purchase User" in roles or "Stock User" in roles:
		tender_views.append("sourcing")
	else:
		tender_views.append("sales")

	return {
		"user": {
			"id": user,
			"name": user_info.get("full_name") or user,
			"email": user_info.get("email") or "",
			"user_image": user_info.get("user_image") or "",
			"language": user_info.get("language") or "en",
			"roles": list(roles),
		},
		"company": company,
		"companies": companies,
		"currency": currency or "USD",
		"modules": modules,
		"tender_views": list(set(tender_views)),
	}


@frappe.whitelist()
def switch_company(company: str) -> dict:
	"""Switch active company context for current user."""
	if not company or not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist.").format(company))

	if not _has_company_access(company):
		frappe.throw(_("Not permitted to access company {0}.").format(company), frappe.PermissionError)

	return boot(company=company)
