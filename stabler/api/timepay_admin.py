"""Whitelisted endpoints for managing the Stabler TimePay Credential singleton.

Only HR Manager / System Manager can read or write credentials.
Tokens are stored as Frappe Password fields (encrypted at rest) and are
NEVER returned to the client — the UI shows only whether they are set and
when they expire.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

_DOCTYPE = "Stabler Timepay Credential"


def _guard() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)
	if not frappe.has_permission(_DOCTYPE, "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _guard_write() -> None:
	_guard()
	if not frappe.has_permission(_DOCTYPE, "write"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def get_timepay_credential() -> dict:
	_guard()
	if not frappe.db.exists("DocType", _DOCTYPE):
		return {
			"enabled": 0,
			"api_base": "",
			"origin": "",
			"has_access_token": False,
			"access_expires_at": None,
			"has_refresh_token": False,
			"refresh_expires_at": None,
		}
	doc = frappe.get_single(_DOCTYPE)
	access = doc.get_password("access_token") or ""
	refresh = doc.get_password("refresh_token") or ""
	return {
		"enabled": int(doc.enabled or 0),
		"api_base": doc.api_base or "",
		"origin": doc.origin or "",
		"has_access_token": bool(access),
		"access_expires_at": doc.access_expires_at or None,
		"has_refresh_token": bool(refresh),
		"refresh_expires_at": doc.refresh_expires_at or None,
	}


@frappe.whitelist()
def save_timepay_credential(payload) -> dict:
	_guard_write()
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw(_("Invalid payload."))
	if not isinstance(payload, dict):
		frappe.throw(_("payload must be a JSON object."))

	doc = frappe.get_single(_DOCTYPE)
	doc.enabled = 1 if payload.get("enabled") else 0
	if payload.get("api_base") is not None:
		doc.api_base = (payload["api_base"] or "").rstrip("/")
	if payload.get("origin") is not None:
		doc.origin = (payload["origin"] or "").rstrip("/")
	if payload.get("access_token", "").strip():
		doc.access_token = payload["access_token"].strip()
		doc.access_expires_at = 0
	if payload.get("refresh_token", "").strip():
		doc.refresh_token = payload["refresh_token"].strip()
		doc.refresh_expires_at = 0
	doc.save(ignore_permissions=True)
	return {"ok": True}
