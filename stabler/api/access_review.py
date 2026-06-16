"""Access review & segregation-of-duties API for Stabler.

Answers the question a System Manager (and an auditor) could not previously ask
without spelunking the Frappe Desk: *who can do what, and who holds a toxic
combination of duties?*

The policy and evaluation are pure (``stabler.api._sod_rules``); this module
just supplies the users + roles and shapes the response for the Access Review
admin page. It is read-only except for the role-change check used to warn at
assignment time.
"""
from __future__ import annotations

import frappe
from frappe import _

from stabler.api._sod_rules import (
	CAPABILITIES,
	SOD_CONFLICTS,
	capabilities_for,
	evaluate_user,
	scan_users,
	would_conflict,
)

_SETTINGS = "Stabler Settings"


def _require_admin() -> None:
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _enforce_sod() -> bool:
	if not frappe.db.exists("DocType", _SETTINGS):
		return False
	return bool(int(frappe.db.get_single_value(_SETTINGS, "enforce_sod") or 0))


def _real_users() -> list[dict]:
	"""Enabled, human users with their roles (excludes system/website users)."""
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["not in", ("Administrator", "Guest")]},
		fields=["name", "full_name"],
		limit=0,
	)
	if not users:
		return []
	names = [u.name for u in users]
	has_role = frappe.get_all(
		"Has Role",
		filters={"parent": ["in", names], "parenttype": "User"},
		fields=["parent", "role"],
		limit=0,
	)
	roles_by_user: dict[str, list[str]] = {}
	for r in has_role:
		roles_by_user.setdefault(r.parent, []).append(r.role)
	return [
		{"user": u.name, "full_name": u.full_name or u.name, "roles": roles_by_user.get(u.name, [])}
		for u in users
	]


@frappe.whitelist()
def sod_matrix() -> dict:
	"""The SoD policy itself — so the UI can show what is being checked."""
	_require_admin()
	return {
		"conflicts": [
			{
				"id": c["id"],
				"label": c["label"],
				"severity": c["severity"],
				"group_a": c["group_a"]["label"],
				"group_b": c["group_b"]["label"],
				"rationale": c["rationale"],
				"mitigation": c.get("mitigation", ""),
			}
			for c in SOD_CONFLICTS
		],
		"enforce": _enforce_sod(),
	}


@frappe.whitelist()
def sod_scan() -> dict:
	"""Scan all real users for segregation-of-duties violations."""
	_require_admin()
	result = scan_users(_real_users())
	result["enforce"] = _enforce_sod()
	return result


@frappe.whitelist()
def access_review() -> dict:
	"""Users-by-sensitive-capability grid, with each user's violation count."""
	_require_admin()
	users = _real_users()
	cap_keys = list(CAPABILITIES.keys())
	rows = []
	for u in users:
		caps = capabilities_for(u["roles"])
		violations = evaluate_user(u["roles"])
		rows.append(
			{
				"user": u["user"],
				"full_name": u["full_name"],
				"roles": sorted(u["roles"]),
				"capabilities": caps,
				"violation_count": len(violations),
				"max_severity": _max_severity(violations),
			}
		)
	rows.sort(key=lambda r: (-r["violation_count"], r["user"]))
	return {
		"capabilities": [{"key": k, "label": v["label"]} for k, v in CAPABILITIES.items()],
		"cap_keys": cap_keys,
		"users": rows,
	}


def _max_severity(violations) -> str | None:
	order = {"critical": 3, "high": 2, "medium": 1, "info": 0}
	best = None
	best_rank = -1
	for v in violations:
		rank = order.get(v["severity"], 0)
		if rank > best_rank:
			best, best_rank = v["severity"], rank
	return best


@frappe.whitelist()
def check_role_change(user: str, roles) -> dict:
	"""Preview SoD conflicts a proposed role set would introduce for a user.

	Returns {warnings:[...], enforce:bool}. The admin UI calls this before
	saving so the reviewer sees the consequence of an assignment.
	"""
	_require_admin()
	if isinstance(roles, str):
		roles = frappe.parse_json(roles) or []
	roles = [r for r in (roles or []) if r]
	new_conflicts = evaluate_user(roles)
	return {
		"warnings": new_conflicts,
		"enforce": _enforce_sod(),
		"count": len(new_conflicts),
	}


def assert_role_change_allowed(user: str, target_roles: list[str]) -> list[dict]:
	"""Server-side guard used by admin.update_user.

	Always returns the list of SoD violations the target role set carries. When
	``enforce_sod`` is on, a *new* critical/high violation is blocked outright;
	otherwise the violations are returned for the caller to surface as warnings.
	"""
	target = [r for r in (target_roles or []) if r]
	violations = evaluate_user(target)
	if not violations:
		return []
	if _enforce_sod():
		existing = frappe.get_all(
			"Has Role", filters={"parent": user, "parenttype": "User"}, fields=["role"], limit=0
		)
		existing_roles = [r.role for r in existing]
		# Only block violations that are genuinely new for this user.
		before = {c["id"] for c in evaluate_user(existing_roles)}
		blocking = [
			v for v in violations if v["id"] not in before and v["severity"] in ("critical", "high")
		]
		if blocking:
			labels = ", ".join(v["label"] for v in blocking)
			frappe.throw(
				_("Segregation of duties: this role combination is not allowed ({0}). Disable 'Enforce SoD' to override.").format(labels),
				title=_("Role change blocked"),
			)
	return violations
