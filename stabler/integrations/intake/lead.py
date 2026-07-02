"""Multi-channel lead intake (F2).

A single guest-callable endpoint that turns an inbound enquiry — from a Telegram
bot, a public web form, a procurement portal, or a direct entry — into a CRM
Lead, stamping the channel and raw message.

Security:
  * Token-gated. The caller must send the shared secret set in
    ``site_config.json`` as ``intake_token``. Compared in constant time.
  * Rate-limited per the Frappe rate limiter (defence against spam/abuse).
  * No authenticated session is required (allow_guest) — the token IS the auth.

The Telegram bot is an external sidecar (its own process) that POSTs here; it is
not part of this app. The web form (see the intake page) posts here too.
"""

from __future__ import annotations

import hmac

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

_CHANNELS = {"Telegram", "Web", "Portal", "Direct"}
_DEDUP_WINDOW_MIN = 10  # collapse accidental double-submits within this window


def _check_token(token: str) -> bool:
	secret = getattr(frappe.conf, "intake_token", None)
	if not secret:
		frappe.local.response.http_status_code = 503
		return False
	if not token or not hmac.compare_digest(str(token), str(secret)):
		frappe.local.response.http_status_code = 401
		return False
	return True


def _recent_duplicate(phone: str, email: str) -> str | None:
	"""Return a recently-created Lead name for the same phone/email, if any."""
	if not (phone or email):
		return None
	from frappe.utils import add_to_date, now_datetime

	since = add_to_date(now_datetime(), minutes=-_DEDUP_WINDOW_MIN)
	or_filters = {}
	if phone:
		or_filters["mobile_no"] = phone
	if email:
		or_filters["email"] = email
	rows = frappe.get_all(
		"CRM Lead",
		filters={"creation": [">=", since]},
		or_filters=or_filters,
		fields=["name"],
		limit=1,
	)
	return rows[0]["name"] if rows else None


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=60, seconds=60)
def intake_lead(
	token: str = "",
	channel: str = "Web",
	name: str = "",
	phone: str = "",
	email: str = "",
	organization: str = "",
	message: str = "",
	tender_no: str = "",
) -> dict:
	"""Create a CRM Lead from an inbound enquiry. Returns {ok, lead, duplicate}."""
	# Prefer the token from the X-Intake-Token header so it stays out of access
	# logs / referer / browser history; fall back to the body param for older
	# callers (Telegram sidecar, existing web form).
	header_token = frappe.get_request_header("X-Intake-Token") or ""
	if not _check_token(header_token or token):
		return {"ok": False, "reason": "unauthorized"}

	channel = channel if channel in _CHANNELS else "Web"
	name = (name or "").strip()
	phone = (phone or "").strip()
	email = (email or "").strip()
	if not (name or phone):
		frappe.local.response.http_status_code = 400
		return {"ok": False, "reason": "name or phone is required"}

	dup = _recent_duplicate(phone, email)
	if dup:
		return {"ok": True, "lead": dup, "duplicate": True}

	doc = frappe.new_doc("CRM Lead")
	doc.lead_name = name or phone
	if phone:
		doc.mobile_no = phone
	if email:
		doc.email = email
	if organization:
		doc.organization = organization
	# Stamp the channel onto the queryable custom fields (added by v29).
	if frappe.db.has_column("CRM Lead", "custom_intake_channel"):
		doc.custom_intake_channel = channel
		doc.custom_intake_message = (message or "")[:2000]
		doc.custom_intake_tender_no = (tender_no or "").strip()
	doc.insert(ignore_permissions=True)

	# Always keep a human-readable trail, even if custom fields are absent.
	trail = _("Intake via {0}.").format(channel)
	if tender_no:
		trail += " " + _("Tender: {0}.").format(tender_no)
	if message:
		trail += "\n" + message
	doc.add_comment("Comment", trail)
	frappe.db.commit()

	return {"ok": True, "lead": doc.name, "duplicate": False}


@frappe.whitelist()
def intake_log(limit: int = 100) -> dict:
	"""Recent intake leads with channel + message — for the admin intake log."""
	from stabler.api.crm import _require_crm

	_require_crm()
	has_ch = frappe.db.has_column("CRM Lead", "custom_intake_channel")
	fields = ["name", "lead_name", "mobile_no", "email", "organization", "source", "status", "creation"]
	if has_ch:
		fields += ["custom_intake_channel", "custom_intake_message", "custom_intake_tender_no"]
	rows = frappe.get_all(
		"CRM Lead",
		filters={"custom_intake_channel": ["is", "set"]} if has_ch else {},
		fields=fields,
		order_by="creation desc",
		limit_page_length=min(int(limit or 100), 500),
	)
	return {"rows": rows, "channels": sorted(_CHANNELS)}
