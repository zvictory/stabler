"""Block /app and /desk for users without the System Manager role.

Mounted via `before_request` in hooks.py. Runs in `init_request` (see
apps/frappe/frappe/app.py:208), before route dispatch.

Behavior:
  - Guest users: not handled here. Frappe's own auth flow will redirect
    them to /login when they hit a desk page.
  - Authenticated user with System Manager / Administrator: pass through.
  - Any site with Stabler Settings.allow_desk_access on: everyone passes
    through — that tenant wants the raw Desk next to Stabler.
  - Anyone else: bounced to the SPA with a 302.

Why a werkzeug abort and not frappe.Redirect: handle_exception() has no
branch for frappe.Redirect, so raising it from a before_request hook
renders an error page with a 301 status and no Location header. But
application() (app.py:145) hands any *werkzeug* HTTPException straight to
e.get_response(), and abort(<Response>) raises exactly that with the
response attached — so this produces a real 302 with a Location header.
"""

import frappe
from werkzeug.exceptions import abort
from werkzeug.utils import redirect

from stabler.stabler.doctype.stabler_settings.stabler_settings import desk_access_enabled

GATED_PREFIXES = ("/app", "/desk")
STABLER_HOME = "/stabler"


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

	# Per-site opt-out. The DB read sits here, after _is_gated and the role
	# check, so it only costs a query on actual /app|/desk hits — not on every
	# request that passes through before_request.
	if desk_access_enabled():
		return

	# 302, not 301: the browser must not cache this permanently — the day this
	# user is granted System Manager, /app has to open again immediately.
	abort(redirect(STABLER_HOME, 302))


def _is_gated(path: str) -> bool:
	for prefix in GATED_PREFIXES:
		if path == prefix or path.startswith(prefix + "/"):
			return True
	return False
