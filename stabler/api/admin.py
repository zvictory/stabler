"""Admin API for Stabler — user & role management.

All methods require System Manager unless explicitly noted.
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.api.organization import MODULE_KEYS

# Role bundles applied by `apply_role_template`. Replaces a user's full role set.
ROLE_TEMPLATES: dict[str, list[str]] = {
	"sales-rep": ["Sales User", "Sales Manager"],
	"accountant": ["Accounts User", "Accounts Manager"],
	"warehouse": ["Stock User", "Stock Manager"],
	"owner": ["System Manager"],
}

# Roles we don't surface in the Stabler admin UI (Frappe internals / desk-only).
_HIDDEN_ROLES = {
	"Guest",
	"All",
	"Administrator",
	"Desk User",
	"Website Manager",
	"Website User",
	"Blogger",
	"Newsletter Manager",
	"Translator",
}


def _require_admin() -> None:
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _user_roles(name: str) -> list[str]:
	rows = frappe.get_all("Has Role", filters={"parent": name}, fields=["role"])
	return sorted({r.role for r in rows if r.role})


def _user_allowed_companies(name: str) -> list[str]:
	"""Read the Stabler User Company multi-select on User. Empty = all companies."""
	try:
		rows = frappe.get_all(
			"Stabler User Company",
			filters={"parent": name, "parenttype": "User", "parentfield": "allowed_companies"},
			fields=["company"],
		)
		return sorted({r.company for r in rows if r.company})
	except Exception:
		return []


def _user_allowed_modules(name: str) -> list[str]:
	"""Read the Stabler User Module table on User. Empty = derive from roles."""
	try:
		rows = frappe.get_all(
			"Stabler User Module",
			filters={"parent": name, "parenttype": "User", "parentfield": "allowed_modules"},
			fields=["module"],
		)
		return sorted({r.module for r in rows if r.module in MODULE_KEYS})
	except Exception:
		return []


@frappe.whitelist()
def list_users(search: str | None = None, role: str | None = None, enabled=None, limit: int = 50):
	_require_admin()
	filters: dict = {}
	if enabled is not None and enabled != "":
		filters["enabled"] = 1 if str(enabled) in ("1", "true", "True") else 0
	if search:
		filters["full_name"] = ["like", f"%{search}%"]

	if role:
		# Filter by role via Has Role child table.
		has_rows = frappe.get_all("Has Role", filters={"role": role}, fields=["parent"])
		names = list({r.parent for r in has_rows})
		if not names:
			return []
		filters["name"] = ["in", names]

	users = frappe.get_all(
		"User",
		filters=filters,
		fields=["name", "email", "full_name", "enabled", "last_login", "user_image"],
		order_by="full_name asc",
		limit=int(limit) if limit else 50,
	)
	for u in users:
		u["roles"] = _user_roles(u["name"])
	return users


@frappe.whitelist()
def get_user(name: str):
	_require_admin()
	if not frappe.db.exists("User", name):
		frappe.throw(_("User not found"))
	doc = frappe.get_doc("User", name)
	return {
		"name": doc.name,
		"email": doc.email,
		"full_name": doc.full_name,
		"first_name": doc.first_name,
		"last_name": doc.last_name,
		"enabled": int(doc.enabled or 0),
		"last_login": doc.last_login,
		"language": doc.language,
		"user_image": doc.user_image,
		"roles": _user_roles(doc.name),
		"allowed_companies": _user_allowed_companies(doc.name),
		"allowed_modules": _user_allowed_modules(doc.name),
	}


@frappe.whitelist()
def update_user(name: str, full_name: str | None = None, enabled=None, roles=None, allowed_modules=None):
	_require_admin()
	if not frappe.db.exists("User", name):
		frappe.throw(_("User not found"))

	doc = frappe.get_doc("User", name)

	if full_name is not None:
		doc.full_name = full_name
	if enabled is not None and enabled != "":
		doc.enabled = 1 if str(enabled) in ("1", "true", "True") else 0

	doc.save(ignore_permissions=True)

	sod_warnings: list = []
	if roles is not None:
		# `roles` may arrive as JSON string from form-encoded request.
		if isinstance(roles, str):
			roles = frappe.parse_json(roles) or []
		target_roles = [r for r in roles if r]
		# Segregation-of-duties check. Returns the violations the target set
		# carries; when 'Enforce SoD' is on it throws on a new critical/high
		# conflict before any role rows are written.
		from stabler.api.access_review import assert_role_change_allowed

		sod_warnings = assert_role_change_allowed(name, target_roles)
		_replace_user_roles(name, target_roles)

	if allowed_modules is not None:
		# `allowed_modules` may arrive as JSON string from form-encoded request.
		if isinstance(allowed_modules, str):
			allowed_modules = frappe.parse_json(allowed_modules) or []
		# Validate: only accept canonical module keys.
		allowed_modules = [m for m in (allowed_modules or []) if m in MODULE_KEYS]
		user_doc = frappe.get_doc("User", name)
		user_doc.set("allowed_modules", [])
		for m in allowed_modules:
			user_doc.append("allowed_modules", {"module": m})
		user_doc.save(ignore_permissions=True)

	frappe.db.commit()
	result = get_user(name)
	if isinstance(result, dict):
		result["sod_warnings"] = sod_warnings
	return result


def _replace_user_roles(user: str, target_roles: list[str]) -> None:
	"""Sync user's `Has Role` rows to exactly `target_roles`."""
	current = set(_user_roles(user))
	target = set(target_roles)

	to_add = target - current
	to_remove = current - target

	for role in to_remove:
		frappe.db.delete("Has Role", {"parent": user, "role": role})

	for role in to_add:
		# Skip unknown roles to avoid silent failures, but don't crash.
		if not frappe.db.exists("Role", role):
			continue
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": user,
				"parenttype": "User",
				"parentfield": "roles",
				"role": role,
			}
		).insert(ignore_permissions=True)


@frappe.whitelist()
def invite_user(email: str, full_name: str, template: str | None = None):
	_require_admin()
	if not email or "@" not in email:
		frappe.throw(_("A valid email is required"))
	if frappe.db.exists("User", email):
		frappe.throw(_("User already exists"))

	first, _sep, last = (full_name or "").partition(" ")
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first or email.split("@")[0],
			"last_name": last,
			"full_name": full_name or email,
			"enabled": 0,
			"send_welcome_email": 0,
			"user_type": "System User",
		}
	)
	user.insert(ignore_permissions=True)

	if template and template in ROLE_TEMPLATES:
		_replace_user_roles(user.name, ROLE_TEMPLATES[template])

	# Trigger the reset-password / magic-link email so the invitee can set credentials.
	try:
		from frappe.utils.password import update_password

		# Generate reset key + email via core helper.
		user.reset_password(send_email=True)
	except Exception as e:
		frappe.log_error(f"invite_user reset email failed for {email}: {e}")

	frappe.db.commit()
	return get_user(user.name)


@frappe.whitelist()
def reset_password(name: str):
	"""Send password-reset link. Self-service allowed; otherwise admin-only."""
	if frappe.session.user != name:
		_require_admin()
	if not frappe.db.exists("User", name):
		frappe.throw(_("User not found"))
	doc = frappe.get_doc("User", name)
	doc.reset_password(send_email=True)
	return {"ok": True}


@frappe.whitelist()
def list_roles(stabler_only: int | str = 1):
	_require_admin()
	rows = frappe.get_all(
		"Role",
		fields=["name", "desk_access", "restrict_to_domain", "disabled"],
		order_by="name asc",
	)
	rows = [r for r in rows if not r.get("disabled")]
	if str(stabler_only) in ("1", "true", "True"):
		rows = [r for r in rows if r["name"] not in _HIDDEN_ROLES]

	# Permission counts: Custom DocPerm + DocPerm.
	for r in rows:
		try:
			custom = frappe.db.count("Custom DocPerm", {"role": r["name"]})
			std = frappe.db.count("DocPerm", {"role": r["name"]})
			r["permission_count"] = (custom or 0) + (std or 0)
		except Exception:
			r["permission_count"] = 0
	return rows


@frappe.whitelist()
def get_role(name: str):
	_require_admin()
	if not frappe.db.exists("Role", name):
		frappe.throw(_("Role not found"))
	role = frappe.get_doc("Role", name)

	perms: list[dict] = []
	for src in ("Custom DocPerm", "DocPerm"):
		try:
			rows = frappe.get_all(
				src,
				filters={"role": name},
				fields=[
					"parent",
					"permlevel",
					"`read`",
					"`write`",
					"`create`",
					"`delete`",
					"submit",
					"cancel",
					"amend",
				],
			)
		except Exception:
			rows = []
		for p in rows:
			p["source"] = src
			perms.append(p)

	# Group by module via parent DocType.
	doctype_names = list({p["parent"] for p in perms if p.get("parent")})
	dt_module = {}
	if doctype_names:
		try:
			dt_rows = frappe.get_all(
				"DocType",
				filters={"name": ["in", doctype_names]},
				fields=["name", "module"],
			)
			dt_module = {r["name"]: r.get("module") or "Other" for r in dt_rows}
		except Exception:
			dt_module = {}

	grouped: dict[str, list[dict]] = {}
	for p in perms:
		mod = dt_module.get(p.get("parent"), "Other")
		grouped.setdefault(mod, []).append(p)

	return {
		"name": role.name,
		"desk_access": int(role.desk_access or 0),
		"restrict_to_domain": role.restrict_to_domain,
		"permissions_by_module": grouped,
		"permission_count": len(perms),
	}


@frappe.whitelist()
def apply_role_template(user: str, template: str):
	_require_admin()
	if template not in ROLE_TEMPLATES:
		frappe.throw(_("Unknown role template: {0}").format(template))
	if not frappe.db.exists("User", user):
		frappe.throw(_("User not found"))
	_replace_user_roles(user, ROLE_TEMPLATES[template])
	frappe.db.commit()
	return get_user(user)


@frappe.whitelist()
def list_role_templates():
	"""Public-ish: any logged-in admin user can see templates."""
	_require_admin()
	return [{"key": k, "label": k.replace("-", " ").title(), "roles": v} for k, v in ROLE_TEMPLATES.items()]


# --- Posting / back-dating window -------------------------------------------
# Surfaces ERPNext's native back-dating freezes so Finance can manage them from
# the SPA instead of the Desk. These are the settings behind "can't create/edit
# transactions older than N days".

def _read_posting_window() -> dict:
	stk = frappe.get_single("Stock Settings")
	acc = frappe.get_single("Accounts Settings")
	return {
		# Stock: rolling N-day freeze on stock-affecting transactions.
		"stock_frozen_upto_days": int(stk.get("stock_frozen_upto_days") or 0),
		"stock_frozen_upto": str(stk.get("stock_frozen_upto") or "") or None,
		"stock_backdated_role": stk.get("role_allowed_to_create_edit_back_dated_transactions") or None,
		# Accounts: fixed freeze date + override role.
		"acc_frozen_upto": str(acc.get("acc_frozen_upto") or "") or None,
		"frozen_accounts_modifier": acc.get("frozen_accounts_modifier") or None,
		# Exchange-rate staleness (affects back-dated multi-currency docs).
		"allow_stale": int(acc.get("allow_stale") or 0),
		"stale_days": int(acc.get("stale_days") or 0),
	}


@frappe.whitelist()
def get_posting_window_settings() -> dict:
	"""Read the ERPNext back-dating freeze settings (Stock + Accounts). Admin only."""
	_require_admin()
	return _read_posting_window()


@frappe.whitelist()
def set_posting_window_settings(payload=None) -> dict:
	"""Update the back-dating freeze settings. Admin only.

	Accepts any subset of: stock_frozen_upto_days, stock_frozen_upto,
	stock_backdated_role, acc_frozen_upto, frozen_accounts_modifier, allow_stale,
	stale_days. Validates numbers and that any role actually exists.
	"""
	_require_admin()
	if isinstance(payload, str):
		try:
			payload = frappe.parse_json(payload)
		except Exception:
			frappe.throw(_("Invalid payload — expected JSON object."))
	if not isinstance(payload, dict):
		frappe.throw(_("payload must be a JSON object."))

	stk = frappe.get_single("Stock Settings")
	acc = frappe.get_single("Accounts Settings")

	if "stock_frozen_upto_days" in payload:
		days = frappe.utils.cint(payload.get("stock_frozen_upto_days"))
		if days < 0:
			frappe.throw(_("Frozen days cannot be negative."))
		stk.stock_frozen_upto_days = days
	if "stock_frozen_upto" in payload:
		stk.stock_frozen_upto = frappe.utils.getdate(payload["stock_frozen_upto"]) if payload["stock_frozen_upto"] else None
	if "stock_backdated_role" in payload:
		role = payload["stock_backdated_role"] or None
		if role and not frappe.db.exists("Role", role):
			frappe.throw(_("Unknown role: {0}").format(role))
		stk.role_allowed_to_create_edit_back_dated_transactions = role

	if "acc_frozen_upto" in payload:
		acc.acc_frozen_upto = frappe.utils.getdate(payload["acc_frozen_upto"]) if payload["acc_frozen_upto"] else None
	if "frozen_accounts_modifier" in payload:
		role = payload["frozen_accounts_modifier"] or None
		if role and not frappe.db.exists("Role", role):
			frappe.throw(_("Unknown role: {0}").format(role))
		acc.frozen_accounts_modifier = role
	if "allow_stale" in payload:
		acc.allow_stale = 1 if frappe.utils.cint(payload["allow_stale"]) else 0
	if "stale_days" in payload:
		sd = frappe.utils.cint(payload.get("stale_days"))
		if sd < 0:
			frappe.throw(_("Stale days cannot be negative."))
		acc.stale_days = sd

	stk.save(ignore_permissions=True)
	acc.save(ignore_permissions=True)
	frappe.db.commit()
	return _read_posting_window()


@frappe.whitelist()
def get_attendance_lock_setting() -> dict:
	"""Read the attendance edit-lock window (days). Admin only."""
	_require_admin()
	try:
		days = frappe.db.get_single_value("Stabler Settings", "attendance_edit_lock_days")
	except Exception:
		days = None
	return {"attendance_edit_lock_days": int(days or 0)}


@frappe.whitelist()
def set_attendance_lock_setting(days=0) -> dict:
	"""Set the attendance edit-lock window (days). 0 disables the hard lock."""
	_require_admin()
	n = frappe.utils.cint(days)
	if n < 0:
		frappe.throw(_("Days cannot be negative."))
	if n > 3650:
		frappe.throw(_("Days is unreasonably large."))
	settings = frappe.get_single("Stabler Settings")
	settings.attendance_edit_lock_days = n
	settings.save(ignore_permissions=True)
	frappe.db.commit()
	return {"attendance_edit_lock_days": n}
