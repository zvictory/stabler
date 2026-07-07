"""UZEX Telegram inbound webhook (WP-307): go/no-go button → Deal intake.

Telegram POSTs an Update here when a user taps the go/no-go inline button on a
new-lot card. We verify the ``X-Telegram-Bot-Api-Secret-Token`` header against
``frappe.conf.uzex_telegram_secret`` (set when the webhook is registered), then
fold the decision onto the Deal's ``custom_tender_intake`` JSON (go_no_go).

Setting a value is naturally idempotent — the same tap twice leaves the same
decision. No explicit commit: Frappe commits a successful whitelisted request.

Register the webhook with Telegram:
  setWebhook url=…/api/method/stabler.integrations.uzex.webhook.telegram_webhook
             secret_token=<uzex_telegram_secret>
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from stabler.integrations.uzex import telegram


def _set_go_no_go(deal: str, decision: str) -> None:
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		return
	doc = frappe.get_doc("CRM Deal", deal)
	raw = doc.get("custom_tender_intake")
	try:
		data = json.loads(raw) if raw else {}
	except (TypeError, ValueError):
		data = {}
	if not isinstance(data, dict):
		data = {}
	data["go_no_go"] = decision
	doc.custom_tender_intake = json.dumps(data, ensure_ascii=False)
	doc.save(ignore_permissions=True)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=60, seconds=60)
def telegram_webhook() -> dict:
	"""Handle a Telegram callback_query for a go/no-go decision."""
	# Fail-closed: reject when the secret is unset OR the header does not match.
	# An allow_guest endpoint with no configured secret must NOT accept anonymous
	# POSTs that would write to a Deal via ignore_permissions.
	secret = getattr(frappe.conf, "uzex_telegram_secret", None)
	sent = frappe.get_request_header("X-Telegram-Bot-Api-Secret-Token")
	if not telegram.verify_secret(secret, sent):
		# Never log the secret/header values themselves.
		frappe.log_error(
			title="UZEX telegram webhook: rejected (bad/absent secret)",
			message=f"configured={bool(secret)} header_present={bool(sent)}",
		)
		frappe.throw(_("Invalid webhook secret"), frappe.PermissionError)

	try:
		update = frappe.request.get_json(force=True, silent=True) or {}
	except Exception:  # noqa: BLE001 — a malformed body is simply ignored
		update = {}

	cq = update.get("callback_query") if isinstance(update, dict) else None
	if not isinstance(cq, dict):
		return {"ok": True, "ignored": True}

	decision, deal = telegram.parse_callback(cq.get("data"))
	applied = False
	if decision and deal and frappe.db.exists("CRM Deal", deal):
		_set_go_no_go(deal, decision)
		applied = True

	telegram.answer_callback(cq.get("id"), _("Saved") if applied else "")
	return {"ok": True, "applied": applied}
