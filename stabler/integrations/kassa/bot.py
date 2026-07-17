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
_REMARK_MAX_LEN = 60
_RECENT_MEMOS_LOOKBACK_DAYS = 90
_RECENT_MEMOS_LIMIT = 6
_BALANCE_LEAVES_LIMIT = 3


# --------------------------------------------------------------------------- #
# Pure helpers (no frappe import needed — unit-testable, WP-K6 statement notes)
# --------------------------------------------------------------------------- #
def _truncate_remark(remark: str | None, max_len: int = _REMARK_MAX_LEN) -> str | None:
	"""Clean + truncate a GL Entry remark for statement display. None/blank/
	the ERPNext default 'No Remarks' placeholder collapse to None (omitted)."""
	if not remark:
		return None
	text = str(remark).strip()
	if not text or text.lower() == "no remarks":
		return None
	if len(text) > max_len:
		text = text[: max_len - 1].rstrip() + "…"
	return text


def _direction_emoji(debit: float, credit: float) -> str:
	"""Kirim (debit-positive, money coming IN) -> up-arrow; chiqim
	(credit, money going OUT) -> down-arrow."""
	return "⬆" if float(debit or 0) > float(credit or 0) else "⬇"


def _strip_memo_prefix(remark: str | None) -> str | None:
	"""Strip a composed "«A» → «B» | izoh" (or "Konvertatsiya CCY→CCY @rate | izoh")
	memo down to the bare izoh, for building the recent-memo suggestion list.
	Remarks without a "|" separator are returned unchanged (already bare)."""
	if not remark:
		return None
	text = str(remark).strip()
	if "|" not in text:
		return text or None
	tail = text.split("|", 1)[1].strip()
	return tail or None


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


def _statement_button_url() -> str | None:
	"""HTTPS site URL for the Mini App, or None when the site isn't served
	over https (local/dev) — Telegram rejects web_app buttons on non-https
	URLs, so BTN_STATEMENT falls back to a plain text button in that case."""
	from stabler.integrations.kassa.miniapp import mini_app_url

	url = mini_app_url()
	return url if url.startswith("https://") else None


def _keyboard_markup(keyboard: list[list[str]] | None) -> dict | None:
	"""None -> omit reply_markup entirely so Telegram keeps showing whatever
	keyboard the client already has (free-text entry steps: amount/memo/date).

	WP-K7: the BTN_STATEMENT ("ℹ️ Mening jadvalim") button is transformed into
	a Telegram web_app KeyboardButton opening the Kassa Mini App, while every
	other button stays a plain text button. Typing the label text manually
	still works as a fallback — _flow.handle() matches it regardless of how
	the tap was delivered (older clients / no web_app support)."""
	if keyboard is None:
		return None
	web_app_url = _statement_button_url()
	rows = []
	for row in keyboard:
		btn_row = []
		for label in row:
			if label == _flow.BTN_STATEMENT and web_app_url:
				btn_row.append({"text": label, "web_app": {"url": web_app_url}})
			else:
				btn_row.append({"text": label})
		rows.append(btn_row)
	return {
		"keyboard": rows,
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


# Known leaf-label shorthands for the one-message quick-transfer parser
# (WP-K6, _flow.parse_quick_transfer): needle (matched by substring, case-
# insensitive) -> alias keys it should register.
_SHORTHAND_RULES = [
	("som", ["som"]),
	("pk", ["pk"]),
	("usd", ["usd", "dollar", "valyuta"]),
]


def _build_aliases(kassas: dict, targets: list) -> dict:
	"""Alias map for _flow.parse_quick_transfer: full leaf label lowered, its
	first word, plus known shorthand overrides matched by substring on the
	label. First writer wins on collisions (kassa leaves before bank/cash
	targets, insertion order)."""
	aliases: dict[str, str] = {}
	seen_accounts: set = set()
	all_leaves: list[dict] = []
	for leaves in (kassas or {}).values():
		all_leaves.extend(leaves)
	all_leaves.extend(targets or [])
	for leaf in all_leaves:
		acc = leaf.get("account")
		if not acc or acc in seen_accounts:
			continue
		seen_accounts.add(acc)
		label = (leaf.get("label") or "").strip()
		if not label:
			continue
		low = label.lower()
		aliases.setdefault(low, acc)
		words = low.split()
		if words:
			aliases.setdefault(words[0], acc)
		for needle, alias_list in _SHORTHAND_RULES:
			if needle in low:
				for alias in alias_list:
					aliases.setdefault(alias, acc)
	return aliases


def _recent_memos(company: str, accounts: list[str]) -> list[str]:
	"""Distinct recent JE memos for this kassir's own accounts, last
	``_RECENT_MEMOS_LOOKBACK_DAYS`` days, stripped of the "«A» → «B» | " (or
	"Konvertatsiya ... | ") composed prefix — feeds the izoh suggestion
	keyboard (WP-K6)."""
	import frappe
	from frappe.utils import add_days, today

	if not accounts:
		return []
	since = add_days(today(), -_RECENT_MEMOS_LOOKBACK_DAYS)
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT je.user_remark, je.posting_date, je.name
		FROM `tabJournal Entry` je
		JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
		WHERE je.company = %(company)s
		  AND je.docstatus = 1
		  AND je.posting_date >= %(since)s
		  AND jea.account IN %(accounts)s
		  AND je.user_remark IS NOT NULL AND je.user_remark != ''
		ORDER BY je.posting_date DESC, je.creation DESC
		LIMIT 50
		""",
		{"company": company, "since": since, "accounts": tuple(accounts)},
		as_dict=True,
	)
	seen: set = set()
	memos: list[str] = []
	for r in rows:
		stripped = _strip_memo_prefix(r.get("user_remark"))
		if not stripped or stripped in seen:
			continue
		seen.add(stripped)
		memos.append(stripped)
		if len(memos) >= _RECENT_MEMOS_LIMIT:
			break
	return memos


def _cbu_ctx(company: str, base_currency: str) -> dict:
	"""CBU-assist rate for Konvertatsiya (WP-K6): 1 USD -> base_currency,
	looked up fresh on every ctx build. None when unavailable — the flow
	always falls back to asking both amounts manually when this is None."""
	from frappe.utils import formatdate, today

	from stabler.api import money

	try:
		rate = money.get_exchange_rate_for_currencies("USD", base_currency, today())
	except Exception:  # noqa: BLE001 — a missing/broken FX rate must never crash the bot
		rate = None
	if not rate:
		return {"rate": None, "date": None}
	return {"rate": float(rate), "date": formatdate(today(), "dd.MM")}


def _cbu_line(cbu: dict, base_currency: str) -> str | None:
	rate = (cbu or {}).get("rate")
	if not rate:
		return None
	date_str = (cbu or {}).get("date") or ""
	return f"\U0001F4B1 1 USD = {_flow.format_amount(rate, base_currency)} (CBU {date_str})"


def _balances_line(company: str, leaves: list[dict]) -> str | None:
	from stabler.api import money

	parts = []
	for leaf in (leaves or [])[:_BALANCE_LEAVES_LIMIT]:
		bal = money.account_balance(company, leaf["account"])
		balance_acc = bal.get("balance_acc")
		if balance_acc is None:
			balance_acc = bal.get("balance_base", 0)
		parts.append(f"{leaf['label']}: {_flow.format_amount(balance_acc, leaf['currency'])}")
	return " · ".join(parts) if parts else None


def build_ctx(kassir, candidate_kassa: str | None = None) -> dict:
	"""Assemble the Frappe-free ``ctx`` dict _flow.handle() needs, scoped to
	this kassir's company and allowed accounts. Called under the kassir's
	impersonated session (see handle_update) so company-scope / permission
	checks inside stabler.api.money behave exactly as they would in the SPA.

	``candidate_kassa`` (usually ``old_state["kassa"] or text``) scopes the
	live-balance lookups (WP-K6 #6) to at most one kassa group (<=3 leaves ->
	<=3 account_balance calls) instead of eagerly pricing every kassa the
	kassir has on every single message.
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

	aliases = _build_aliases(kassas, targets)
	recent_memos = _recent_memos(company, [row.account for row in (kassir.accounts or [])])
	cbu = _cbu_ctx(company, base_currency)

	balances_by_kassa: dict[str, str] = {}
	active_kassa = candidate_kassa if candidate_kassa in kassas else None
	if active_kassa:
		cbu_line = _cbu_line(cbu, base_currency)
		bal_line = _balances_line(company, kassas[active_kassa])
		combined = "\n".join(p for p in (cbu_line, bal_line) if p)
		if combined:
			balances_by_kassa[active_kassa] = combined

	return {
		"kassas": kassas,
		"categories": categories,
		"deals": deals,
		"targets": targets,
		"base_currency": base_currency,
		"aliases": aliases,
		"recent_memos": recent_memos,
		"cbu": cbu,
		"balances_by_kassa": balances_by_kassa,
	}


# --------------------------------------------------------------------------- #
# Action execution — thin pass-through into stabler.api.money
# --------------------------------------------------------------------------- #
def _account_label(account: str) -> str:
	import frappe

	return frappe.db.get_value("Account", account, "account_name") or account


def _compose_transfer_memo(action: dict) -> str | None:
	"""WP-K6 memo composition: same-currency transfers (Kirim / Kassadan-
	kassaga) -> '«FromLabel» → «ToLabel» | izoh'; cross-currency
	(Konvertatsiya, identified by the presence of `to_amount`) ->
	'Konvertatsiya CCY→CCY @rate | izoh'. None when no izoh was given
	(Kirim's izoh is optional)."""
	import frappe

	raw_memo = action.get("memo")
	if not raw_memo:
		return None
	if action.get("to_amount") is not None:
		from_ccy = frappe.db.get_value("Account", action["from"], "account_currency") or ""
		to_ccy = frappe.db.get_value("Account", action["to"], "account_currency") or ""
		from_amt = float(action["from_amount"])
		to_amt = float(action["to_amount"])
		rate = (to_amt / from_amt) if from_amt else 0.0
		return f"Konvertatsiya {from_ccy}→{to_ccy} @{rate:.4f} | {raw_memo}"
	from_label = _account_label(action["from"])
	to_label = _account_label(action["to"])
	return f"«{from_label}» → «{to_label}» | {raw_memo}"


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
			memo=_compose_transfer_memo(action),
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


def _affected_account(action: dict) -> str | None:
	"""Which account's balance to echo back after a successful op (WP-K6 #6)."""
	if action.get("type") == "transfer":
		return action.get("to") or action.get("from")
	if action.get("type") == "expense":
		return action.get("payment_from")
	return None


def _append_new_balance(follow_up: str, company: str, account: str | None) -> str:
	if not account:
		return follow_up
	from stabler.api import money

	try:
		bal = money.account_balance(company, account)
	except Exception:  # noqa: BLE001 — a balance-echo failure must never hide the result text
		return follow_up
	balance_acc = bal.get("balance_acc")
	if balance_acc is None:
		balance_acc = bal.get("balance_base", 0)
	currency = bal.get("account_currency") or bal.get("company_currency") or ""
	return f"{follow_up}\n\nYangi qoldiq: {_flow.format_amount(balance_acc, currency)}"


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
			debit = float(row.get("debit") or 0)
			credit = float(row.get("credit") or 0)
			net = debit - credit
			emoji = _direction_emoji(debit, credit)
			line = (
				f"  {emoji} {row.get('posting_date')} {row.get('voucher_type')} {row.get('voucher_no')}: "
				f"{_flow.format_amount(net, leaf['currency'])}"
			)
			remark = _truncate_remark(row.get("remarks"))
			if remark:
				line += f" — {remark}"
			parts.append(line)
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
		ctx = build_ctx(kassir, candidate_kassa=(old_state.get("kassa") or text))
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
					follow_up = _append_new_balance(follow_up, kassir.company, _affected_account(action))
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
