"""Block /app and /desk for users without the System Manager role.

Mounted via `before_request` in hooks.py. Runs in `init_request` (see
apps/frappe/frappe/app.py:208), before route dispatch.

Behavior:
  - Guest users: not handled here. Frappe's own auth flow will redirect
    them to /login when they hit a desk page.
  - Authenticated user with System Manager / Administrator: pass through.
  - Anyone else: raise frappe.PermissionError, which the top-level
    exception handler (app.py:386) renders as a 403 Not Permitted page.

Why PermissionError and not Redirect: handle_exception() doesn't special-
case frappe.Redirect, so raising it from a before_request hook would
render an error page with a 301 status and no Location header.
"""

import frappe

GATED_PREFIXES = ("/app", "/desk")


def gate_desk():
	request = getattr(frappe.local, "request", None)
	if request is None:
		return

	path = request.path or ""
	if not _is_gated(path):
		return

	user = frappe.session.user if frappe.session else "Guest"
	if user == "Guest":
		return

	roles = frappe.get_roles(user)
	if "System Manager" in roles or "Administrator" in roles:
		return

	raise frappe.PermissionError("Desk access is restricted. Use /stabler instead.")


def _is_gated(path: str) -> bool:
	for prefix in GATED_PREFIXES:
		if path == prefix or path.startswith(prefix + "/"):
			return True
	return False
