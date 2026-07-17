"""Kassa Telegram bot glue (WP-K3).

THIN layer over stabler.api.money — no accounting logic lives here. This
module wires the pure state machine in ``_flow.py`` to:

  * Telegram's sendMessage API (urllib POST, mirrors
    stabler.integrations.uzex.telegram's style/config-key pattern).
  * frappe.cache() for per-chat conversation state (900s TTL).
  * IN-PROCESS calls into stabler.api.money for every accounting action, run
    under an IMPERSONATED session (frappe.set_user(kassir.user)) so
    permissions / maker-checker approvals / back-dating freezes all apply
    exactly as if the kassir had used the SPA themselves.

Config (site_config.json): ``kassa_telegram_token`` (bot token) +
``kassa_telegram_secret`` (webhook X-Telegram-Bot-Api-Secret-Token). The
token/secret are never logged. See webhook.py for the inbound side.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from stabler.integrations.kassa import _flow

_API = "https://api.telegram.org"
_TIMEOUT = 20

_STATE_PREFIX = "stabler_kassa_state:"
_STATE_TTL = 900  # seconds

_NO_ACCESS_TEXT = "Ruxsat yo'q. Administratorga murojaat qiling."
_STATEMENT_LOOKBACK = 5


# --------------------------------------------------------------------------- #
# Telegram transport (mirrors stabler.integrations.uzex.telegram._post)
# --------------------------------------------------------------------------- #
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


def _keyboard_markup(keyboard: list[list[str]] | None) -> dict | None:
	"""None -> omit reply_markup entirely so Telegram keeps showing whatever
	keyboard the client already has (free-text entry steps: amount/memo/date).
	"""
	if keyboard is None:
		return None
	return {
		"keyboard": [[{"text": label} for label in row] for row in keyboard],
		"resize_keyboard": True,
		"one_time_keyboard": False,
	}


def _send_message(chat_id, text: str, keyboard: list[list[str]] | None = None) -> bool:
	import frappe

	token = getattr(frappe.conf, "kassa_telegram_token", None)
	if not token or not text:
		return False
	payload: dict = {"chat_id": chat_id, "text": text}
	markup = _keyboard_markup(keyboard)
	if markup is not None:
		payload["reply_markup"] = markup
	_post(f"{_API}/bot{token}/sendMessage", payload)
	return True


# --------------------------------------------------------------------------- #
# Conversation state (frappe.cache(), JSON-serialized, 15 min TTL)
# --------------------------------------------------------------------------- #
def _state_key(chat_id) -> str:
	return f"{_STATE_PREFIX}{chat_id}"


def _load_state(chat_id) -> dict:
	import frappe

	raw = frappe.cache().get_value(_state_key(chat_id))
	if not raw:
		return {"step": _flow.STEP_MAIN, "kassa": None, "posting_date": None}
	try:
		state = json.loads(raw)
	except (TypeError, ValueError):
		return {"step": _flow.STEP_MAIN, "kassa": None, "posting_date": None}
	if not isinstance(state, dict):
		return {"step": _flow.STEP_MAIN, "kassa": None, "posting_date": None}
	return state


def _save_state(chat_id, state: dict) -> None:
	import frappe

	frappe.cache().set_value(_state_key(chat_id), json.dumps(state), expires_in_sec=_STATE_TTL)


# --------------------------------------------------------------------------- #
# ctx assembly — thin reads over stabler.api.money + organization module map
# --------------------------------------------------------------------------- #
def _tender_enabled(company: str) -> bool:
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	try:
		return bool(module_map_for(company).get("tender"))
	except Exception:  # noqa: BLE001 — a misconfigured company must never crash the bot
		return False


def build_ctx(kassir) -> dict:
	"""Assemble the Frappe-free ``ctx`` dict _flow.handle() needs, scoped to
	this kassir's company and allowed accounts. Called under the kassir's
	impersonated session (see handle_update) so company-scope / permission
	checks inside stabler.api.money behave exactly as they would in the SPA.
	"""
	import frappe

	from stabler.api import money

	company = kassir.company
	base_currency = frappe.db.get_value("Company", company, "default_currency") or "UZS"

	# Group this kassir's leaf accounts by their parent account's account_name
	# — that parent grouping IS the "kassa" the MAIN step picks between.
	kassas: dict[str, list[dict]] = {}
	for row in kassir.accounts or []:
		acc = row.account
		info = frappe.db.get_value(
			"Account", acc, ["account_name", "account_currency", "parent_account"], as_dict=True
		)
		if not info:
			continue
		parent_label = None
		if info.parent_account:
			parent_label = frappe.db.get_value("Account", info.parent_account, "account_name")
		parent_label = parent_label or "Kassa"
		kassas.setdefault(parent_label, []).append(
			{
				"account": acc,
				"label": info.account_name or acc,
				"currency": info.account_currency or base_currency,
			}
		)

	categories = [
		{"account": r["name"], "label": r["account_name"] or r["name"]}
		for r in (money.expense_accounts(company) or [])[:30]
	]

	deals: list[dict] = []
	if frappe.db.has_column("Journal Entry", "custom_crm_deal") and _tender_enabled(company):
		rows = frappe.get_all(
			"CRM Deal",
			filters={"company": company, "status": ["not in", ["Won", "Lost"]]},
			fields=["name", "organization", "lead_name"],
			order_by="modified desc",
			limit_page_length=8,
		)
		deals = [
			{"name": r.name, "label": r.organization or r.lead_name or r.name} for r in rows
		]

	targets = [
		{
			"account": r["name"],
			"label": r["account_name"] or r["name"],
			"currency": r["account_currency"] or base_currency,
		}
		for r in (money.bank_cash_accounts(company) or [])
	]

	return {
		"kassas": kassas,
		"categories": categories,
		"deals": deals,
		"targets": targets,
		"base_currency": base_currency,
	}


# --------------------------------------------------------------------------- #
# Action execution — thin pass-through into stabler.api.money
# --------------------------------------------------------------------------- #
def execute_action(action: dict, state: dict, kassir, ctx: dict) -> dict:
	"""Map a completed flow action onto the EXISTING money.py endpoints.

	`state` (not the flow's post-reset new_state) supplies posting_date, since
	the flow already resets it to None (one-shot back-date) in its returned
	new_state — the caller must pass the state as it was BEFORE handle()
	advanced it.
	"""
	import frappe
	from frappe.utils import today

	from stabler.api import money

	company = kassir.company
	posting_date = state.get("posting_date") or today()
	action_type = action.get("type")

	if action_type == "transfer":
		return money.submit_transfer_entry(
			company=company,
			posting_date=posting_date,
			from_account=action["from"],
			to_account=action["to"],
			from_amount=action["from_amount"],
			to_amount=action.get("to_amount"),
			memo=action.get("memo"),
			submit=1,
		)

	if action_type == "expense":
		base_currency = frappe.db.get_value("Company", company, "default_currency") or "UZS"
		leaf_currency = (
			frappe.db.get_value("Account", action["payment_from"], "account_currency") or base_currency
		)
		exchange_rate = None
		if leaf_currency != base_currency:
			# Mirror Expenses.vue exactly: it fetches base->leaf via
			# get_exchange_rate_for_currencies(base_currency, pay_currency), then
			# submits the INVERSE (leaf->base) — submit_expense_entry's
			# `exchange_rate` param is payment-from -> base, not base -> payment-from.
			base_to_leaf = money.get_exchange_rate_for_currencies(
				base_currency, leaf_currency, posting_date
			)
			exchange_rate = (1 / base_to_leaf) if base_to_leaf else None
		lines = [
			{"account": action["category"], "amount": action["amount"], "memo": action.get("memo")}
		]
		return money.submit_expense_entry(
			company=company,
			posting_date=posting_date,
			payment_from=action["payment_from"],
			lines=lines,
			exchange_rate=exchange_rate,
			submit=1,
			entry_kind="Expense",
			deal=action.get("deal"),
		)

	raise ValueError(f"Unknown kassa action type: {action_type}")


def _format_result_text(result: dict) -> str:
	name = result.get("name")
	if result.get("pending_approval"):
		return f"⏳ Tasdiqqa yuborildi: {name}"
	return f"✅ Yozildi: {name} (holat: {result.get('docstatus')})"


def _build_statement_text(kassir, state: dict, ctx: dict) -> str:
	"""'Mening jadvalim' — balance + last N transactions per leaf of the
	currently-selected kassa. Read-only, so no impersonation-sensitive writes."""
	from stabler.api import money

	kassa = state.get("kassa")
	leaves = ctx.get("kassas", {}).get(kassa, [])
	if not leaves:
		return "Kassa tanlanmagan."

	parts = [f"\U0001F4CB {kassa} — jadval"]
	for leaf in leaves:
		bal = money.account_balance(kassir.company, leaf["account"])
		balance_acc = bal.get("balance_acc")
		if balance_acc is None:
			balance_acc = bal.get("balance_base", 0)
		parts.append(
			f"\n{leaf['label']} ({leaf['currency']}): "
			f"{_flow.format_amount(balance_acc, leaf['currency'])}"
		)
		txns = money.account_transactions(kassir.company, leaf["account"], limit=50)
		recent = (txns.get("entries") or [])[-_STATEMENT_LOOKBACK:]
		if not recent:
			parts.append("  (harakatlar yo'q)")
			continue
		for row in recent:
			net = float(row.get("debit") or 0) - float(row.get("credit") or 0)
			parts.append(
				f"  {row.get('posting_date')} {row.get('voucher_type')} {row.get('voucher_no')}: "
				f"{_flow.format_amount(net, leaf['currency'])}"
			)
	return "\n".join(parts)


def _append_backdate_warning(reply: str, iso_date: str) -> str:
	"""Informational-only nudge from money.get_backdating_status() — the real
	enforcement gate is ERPNext's own frozen-accounts/frozen-stock check on
	insert()/submit(), which fires regardless of what this bot shows."""
	from stabler.api import money

	try:
		status = money.get_backdating_status()
	except Exception:  # noqa: BLE001 — a status-check failure must never block the flow
		return reply
	if not status.get("active"):
		return reply
	earliest = status.get("acc_earliest_date") or status.get("stock_earliest_date")
	if earliest and iso_date < earliest:
		reply = (
			f"{reply}\n\n⚠️ Diqqat: {earliest} sanasidan oldingi amallar "
			"tizim tomonidan rad etilishi mumkin."
		)
	return reply


# --------------------------------------------------------------------------- #
# Update entrypoint (called by webhook.py)
# --------------------------------------------------------------------------- #
def _resolve_kassir(telegram_user_id: str):
	import frappe

	name = frappe.db.get_value(
		"Stabler Kassir", {"telegram_user_id": telegram_user_id, "enabled": 1}, "name"
	)
	if not name:
		return None
	return frappe.get_doc("Stabler Kassir", name)


def handle_update(update: dict) -> None:
	"""Process one Telegram Update. Only private-chat text messages are
	handled; everything else (group chats, edited messages, callback
	queries, non-text content) is silently ignored."""
	import frappe

	message = (update or {}).get("message")
	if not isinstance(message, dict):
		return
	chat = message.get("chat") or {}
	if chat.get("type") != "private":
		return
	chat_id = chat.get("id")
	from_user = message.get("from") or {}
	telegram_user_id = str(from_user.get("id") or "").strip()
	text = message.get("text")
	if chat_id is None or not telegram_user_id or text is None:
		return

	kassir = _resolve_kassir(telegram_user_id)
	if not kassir:
		_send_message(chat_id, _NO_ACCESS_TEXT)
		return

	# IMPERSONATION: every stabler.api.money call below runs as the kassir's
	# own Frappe user, so permissions / maker-checker approvals / back-dating
	# freezes all apply exactly as they would through the SPA.
	original_user = frappe.session.user
	reply = keyboard = new_state = follow_up = None
	frappe.set_user(kassir.user)
	try:
		old_state = _load_state(chat_id)
		ctx = build_ctx(kassir)
		reply, keyboard, new_state, action = _flow.handle(old_state, text, ctx)

		if (
			old_state.get("step") == _flow.STEP_BACKDATE
			and new_state.get("posting_date")
			and new_state.get("posting_date") != old_state.get("posting_date")
		):
			reply = _append_backdate_warning(reply, new_state["posting_date"])

		if action:
			if action.get("type") == "statement":
				follow_up = _build_statement_text(kassir, old_state, ctx)
			else:
				try:
					result = execute_action(action, old_state, kassir, ctx)
					follow_up = _format_result_text(result)
				except Exception as e:  # noqa: BLE001 — surfaced to the kassir, not swallowed
					frappe.log_error(
						title="Kassa bot: action failed",
						message=f"kassir={kassir.name} action_type={action.get('type')} error={e}",
					)
					follow_up = f"❌ Xatolik: {e}"

		_save_state(chat_id, new_state)
	finally:
		frappe.set_user(original_user)

	if reply:
		_send_message(chat_id, reply, keyboard)
	if follow_up:
		_send_message(chat_id, follow_up, keyboard)
