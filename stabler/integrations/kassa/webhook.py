"""Kassa Telegram bot — inbound webhook (WP-K3).

Telegram POSTs every Update here (text messages from kassirs). We verify the
``X-Telegram-Bot-Api-Secret-Token`` header against
``frappe.conf.kassa_telegram_secret`` (fail-closed: unset OR mismatched
secret rejects everyone — mirrors stabler.integrations.uzex.webhook), then
hand the update to stabler.integrations.kassa.bot.handle_update, which does
all the actual conversation / accounting work under the resolved kassir's
impersonated session.

Register the webhook with Telegram:
  setWebhook url=…/api/method/stabler.integrations.kassa.webhook.telegram_webhook
             secret_token=<kassa_telegram_secret>
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from stabler.integrations.kassa import bot
from stabler.integrations.uzex.telegram import verify_secret

_GENERIC_ERROR_TEXT = "Xatolik yuz berdi"


def _reply_generic_error(update: dict) -> None:
	"""Best-effort — never let the error-reporting path itself raise."""
	try:
		message = (update or {}).get("message") or {}
		chat_id = (message.get("chat") or {}).get("id")
		if chat_id is not None:
			bot._send_message(chat_id, _GENERIC_ERROR_TEXT)
	except Exception:  # this IS the error handler; it must not itself throw
		pass


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=120, seconds=60)
def telegram_webhook() -> dict:
	"""Handle one Telegram Update for the kassa bot."""
	# Fail-closed: reject when the secret is unset OR the header does not match.
	# An allow_guest endpoint with no configured secret must NOT accept anonymous
	# POSTs that would post Journal Entries via an impersonated session.
	secret = getattr(frappe.conf, "kassa_telegram_secret", None)
	sent = frappe.get_request_header("X-Telegram-Bot-Api-Secret-Token")
	if not verify_secret(secret, sent):
		# Never log the secret/header values themselves.
		frappe.log_error(
			title="Kassa telegram webhook: rejected (bad/absent secret)",
			message=f"configured={bool(secret)} header_present={bool(sent)}",
		)
		frappe.throw(_("Invalid webhook secret"), frappe.PermissionError)

	try:
		update = frappe.request.get_json(force=True, silent=True) or {}
	except Exception:  # a malformed body is simply ignored
		update = {}

	try:
		bot.handle_update(update)
	except Exception as e:  # never let one bad update retry-storm Telegram
		frappe.log_error(
			title="Kassa telegram webhook: update processing failed",
			message=f"error={e}",
		)
		_reply_generic_error(update)

	# Always 200 {"ok": True} — Telegram retries aggressively on non-2xx / timeouts,
	# and a retry storm from a single bad update would repeat the same failure.
	return {"ok": True}
