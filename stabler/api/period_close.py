"""Period-close enforcement for Stabler.

Prevents posting or editing documents into a closed accounting period.
All rule logic lives in the frappe-free ``stabler.api._period_close`` module;
this wrapper owns Frappe I/O, config reads, and role checks.

Feature is **opt-in** and OFF by default.  Enable via Stabler Settings:
  * ``enable_period_close`` (Check, default 0)  — master on/off.
  * ``period_close_date`` (Date, default blank)  — inclusive boundary.
  * ``period_close_override_roles`` (Small Text, default blank) — comma or
    newline-separated list of ERPNext role names whose holders may post into
    a closed period without an error (e.g. "Accounts Manager,System Manager").

Hook entry point
----------------
``enforce_on_validate(doc, method)`` is wired in hooks.py under ``doc_events``
for every financial doctype (see ## WIRING NOTE in the feature report).  It
runs both on validate (Save in Draft) and before_submit.  The hook exits
silently when:
  * the feature is disabled (``enable_period_close == 0``),
  * ``period_close_date`` is blank / None, or
  * the document has no ``posting_date`` field.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate

from stabler.api._period_close import assert_posting_allowed

_SETTINGS = "Stabler Settings"

# Roles that are always treated as admins for period-close purposes.
# They can set / clear the close date and are implicitly override-capable.
_ADMIN_ROLES = ("System Manager", "Stabler Admin")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_admin() -> None:
	"""Raise PermissionError unless the current user holds an admin role."""
	if not any(r in frappe.get_roles() for r in _ADMIN_ROLES):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _settings_exist() -> bool:
	return bool(frappe.db.exists("DocType", _SETTINGS))


def _read_config() -> dict:
	"""Return period-close config from Stabler Settings.

	Safe to call even when the doctype does not exist yet (returns disabled).
	"""
	if not _settings_exist():
		return {"enabled": False, "close_date": None, "override_roles": []}

	enabled = bool(
		int(frappe.db.get_single_value(_SETTINGS, "enable_period_close") or 0)
	)
	close_date = frappe.db.get_single_value(_SETTINGS, "period_close_date") or None
	raw_roles = (
		frappe.db.get_single_value(_SETTINGS, "period_close_override_roles") or ""
	)
	# Support both comma and newline as delimiters; strip whitespace.
	override_roles = [
		r.strip()
		for r in raw_roles.replace("\n", ",").split(",")
		if r.strip()
	]
	return {
		"enabled": enabled,
		"close_date": close_date,
		"override_roles": override_roles,
	}


def _user_has_override(override_roles: list[str]) -> bool:
	"""True if the current user holds any of the configured override roles.

	Admins are implicitly granted override so they are never locked out.
	"""
	if not override_roles:
		return False
	user_roles = set(frappe.get_roles())
	# Admins are always allowed regardless of the override_roles list.
	if user_roles & set(_ADMIN_ROLES):
		return True
	return bool(user_roles & set(override_roles))


# ---------------------------------------------------------------------------
# Public whitelisted endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_period_status() -> dict:
	"""Return the current period-close status visible to all authenticated users.

	Response shape::

	    {
	        "enabled": true,
	        "close_date": "2025-03-31",
	        "is_closed": true,
	        "has_override": false,
	        "today": "2025-04-10"
	    }
	"""
	cfg = _read_config()
	from stabler.api._period_close import is_closed
	today = frappe.utils.today()
	return {
		"enabled": cfg["enabled"],
		"close_date": cfg["close_date"],
		"is_closed": cfg["enabled"] and is_closed(today, cfg["close_date"]),
		"has_override": _user_has_override(cfg["override_roles"]),
		"today": today,
	}


@frappe.whitelist()
def set_close_date(date: str | None = None) -> dict:
	"""Set (or clear) the period-close date.  Admin-only.

	Parameters
	----------
	date : str | None
	    ISO-8601 date string ``"YYYY-MM-DD"`` to set, or ``""`` / ``None``
	    to clear (re-open the period).

	Returns
	-------
	dict
	    ``{"close_date": "<date or null>", "enabled": <bool>}``
	"""
	_require_admin()

	if not _settings_exist():
		frappe.throw(
			_("Stabler Settings doctype does not exist. Run migrations first."),
			frappe.ValidationError,
		)

	# Validate the incoming date string (or accept blank = clear).
	clean_date: str | None = None
	if date:
		try:
			# getdate raises on invalid input
			parsed = getdate(date)
			clean_date = parsed.isoformat()
		except Exception:
			frappe.throw(
				_("Invalid date: {0}. Expected YYYY-MM-DD.").format(date),
				frappe.ValidationError,
			)

	frappe.db.set_single_value(_SETTINGS, "period_close_date", clean_date or "")
	frappe.db.commit()

	return {
		"close_date": clean_date,
		"enabled": bool(
			int(frappe.db.get_single_value(_SETTINGS, "enable_period_close") or 0)
		),
	}


# ---------------------------------------------------------------------------
# Hook: wired via hooks.py doc_events
# ---------------------------------------------------------------------------

def enforce_on_validate(doc, method=None) -> None:
	"""Doc-event hook — block saves/submits into a closed period.

	Designed to be registered under ``doc_events`` in ``hooks.py`` for the
	key financial doctypes.  See ## WIRING NOTE in the feature report.

	The hook is a silent no-op when:
	  * ``enable_period_close`` is falsy (feature off).
	  * ``period_close_date`` is blank (not yet configured).
	  * The document has no ``posting_date`` attribute.
	  * The current user holds an override role or is an admin.

	When posting IS blocked, ``frappe.throw`` is called with a translated
	human-readable message so both the SPA and the Desk surface it properly.
	"""
	cfg = _read_config()

	if not cfg["enabled"]:
		return

	if not cfg["close_date"]:
		return

	posting_date = getattr(doc, "posting_date", None)
	if not posting_date:
		return

	has_override = _user_has_override(cfg["override_roles"])

	try:
		assert_posting_allowed(
			posting_date,
			cfg["close_date"],
			has_override=has_override,
		)
	except ValueError as exc:
		frappe.throw(_(str(exc)), frappe.ValidationError)
