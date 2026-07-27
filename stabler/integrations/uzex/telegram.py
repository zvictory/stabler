"""Telegram new-lot notifications for UZEX (WP-307).

Outbound only: when the poller creates a NEW lot Deal, push a card to the sales
Telegram channel with a go/no-go inline keyboard. Because the poller upserts by
the UNIQUE custom_uzex_lot_no, "created" fires exactly once per lot — so one lot
produces one message, no duplicates on re-runs.

Config (site_config.json): ``uzex_telegram_token`` (bot token) +
``uzex_telegram_chat_id`` (channel/chat). Absent → silent no-op, so sites without
Telegram are unaffected. The token is never logged.

The pure text/keyboard/callback builders are Frappe-free and unit-tested; the
network POST mirrors the didox/uzex urllib style (Telegram's API is always HTTPS).
"""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# NOTE: `frappe` is imported lazily inside the network helpers so the pure
# text/keyboard/callback builders above stay import-safe under plain unittest.

_API = "https://api.telegram.org"
_TIMEOUT = 20


def build_new_lot_text(norm: dict) -> str:
	"""HTML-formatted (escaped) message body for a new lot."""
	def esc(v) -> str:
		return html.escape(str(v))

	parts = ["\U0001F195 <b>Yangi UZEX loti</b>"]
	if norm.get("name"):
		parts.append(esc(norm["name"]))
	parts.append(f"№ <code>{esc(norm.get('lot_no') or '-')}</code>")
	if norm.get("customer_org"):
		parts.append("\U0001F464 " + esc(norm["customer_org"]))
	if norm.get("start_price") is not None:
		price = f"{norm['start_price']:,.0f}".replace(",", " ")
		parts.append(("\U0001F4B0 " + price + " " + esc(norm.get("currency") or "")).strip())
	if norm.get("deadline"):
		parts.append("⏰ " + esc(norm["deadline"]))
	return "\n".join(parts)


def build_keyboard(norm: dict, deal_name: str | None) -> dict | None:
	"""Inline keyboard: open-on-UZEX URL + go/no-go callbacks."""
	rows: list[list[dict]] = []
	lot_id = norm.get("lot_id")
	if lot_id:
		rows.append([{"text": "\U0001F517 UZEX", "url": f"https://etender.uzex.uz/lot/{lot_id}"}])
	if deal_name:
		rows.append(
			[
				{"text": "✅ Boramiz", "callback_data": f"uzex_go:{deal_name}"},
				{"text": "❌ Yo'q", "callback_data": f"uzex_nogo:{deal_name}"},
			]
		)
	return {"inline_keyboard": rows} if rows else None


def verify_secret(configured, sent) -> bool:
	"""True only when a secret IS configured AND ``sent`` matches it (constant time).

	Fail-closed: an unset/blank ``configured`` secret rejects everyone — an
	``allow_guest`` webhook with no secret must NOT accept anonymous writes.
	"""
	if not configured or not sent:
		return False
	import hmac

	return hmac.compare_digest(str(configured), str(sent))


def parse_callback(data: str | None) -> tuple[str | None, str | None]:
	"""('go'|'no-go', deal_name) from a callback_data string, else (None, None)."""
	if not data or ":" not in data:
		return (None, None)
	prefix, deal = data.split(":", 1)
	if prefix == "uzex_go":
		return ("go", deal)
	if prefix == "uzex_nogo":
		return ("no-go", deal)
	return (None, None)


def _post(url: str, payload: dict) -> Any:
	import frappe

	body = json.dumps(payload).encode("utf-8")
	req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
	try:
		with urlopen(req, timeout=_TIMEOUT) as resp:
			return json.loads(resp.read().decode("utf-8"))
	except HTTPError as e:
		raise frappe.ValidationError(f"Telegram HTTP {e.code}: {e.reason}") from e
	except URLError as e:
		raise frappe.ValidationError(f"Telegram unreachable: {e.reason}") from e


def send_new_lot(norm: dict, deal_name: str | None) -> bool:
	"""Push a new-lot card. Returns False (no-op) when Telegram is not configured."""
	import frappe

	token = getattr(frappe.conf, "uzex_telegram_token", None)
	chat_id = getattr(frappe.conf, "uzex_telegram_chat_id", None)
	if not token or not chat_id:
		return False
	payload = {
		"chat_id": chat_id,
		"text": build_new_lot_text(norm),
		"parse_mode": "HTML",
		"disable_web_page_preview": True,
	}
	keyboard = build_keyboard(norm, deal_name)
	if keyboard:
		payload["reply_markup"] = keyboard
	_post(f"{_API}/bot{token}/sendMessage", payload)
	return True


def answer_callback(callback_query_id: str, text: str = "") -> None:
	"""Stop the button spinner in the Telegram client (best-effort)."""
	import frappe

	token = getattr(frappe.conf, "uzex_telegram_token", None)
	if not token or not callback_query_id:
		return
	try:
		_post(
			f"{_API}/bot{token}/answerCallbackQuery",
			{"callback_query_id": callback_query_id, "text": text},
		)
	except Exception:  # answering is cosmetic
		pass
