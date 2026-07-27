"""Kassa Telegram Mini App (WebApp) backend (WP-K7).

Turns the "ℹ️ Mening jadvalim" button into a full Telegram Mini App served at
/kassa (see stabler.www.kassa). Two halves:

  (a) verify_init_data() — pure, frappe-free HMAC verification of Telegram's
      WebApp initData (see "Validating data received via the Mini App":
      https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
      This IS the auth boundary for a money-adjacent endpoint, so it is
      unit-tested in isolation (stabler.tests.test_kassa_miniapp) and never
      touches frappe.

  (b) kassa_summary() — the allow_guest + rate-limited endpoint the Mini App
      page's XHR calls. Resolves initData to an enabled Stabler Kassir by
      telegram_user_id, then runs every read IMPERSONATED as that kassir's own
      Frappe user (mirrors stabler.integrations.kassa.bot's impersonation
      pattern), so results reflect exactly what the kassir may see. Fails
      closed: an unconfigured bot token or a bad/expired/missing signature
      rejects the request outright — the endpoint never partially trusts the
      client. Token and initData are never logged.

The `frappe` import below is wrapped in try/except so this module — like
stabler.integrations.kassa.bot and stabler.integrations.uzex.telegram — stays
importable under plain ``python3 -m unittest`` with no bench/site on
PYTHONPATH; only the pure helpers (verify_init_data, _row_op_label) are
exercised that way. Every real deployment has frappe installed (it's a Frappe
app), so the except branch never fires there and kassa_summary is decorated
exactly as if `@frappe.whitelist(allow_guest=True)` / `@rate_limit(...)` had
been written directly above it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl
from urllib.request import Request, urlopen

try:
	import frappe
	from frappe import _
	from frappe.rate_limiter import rate_limit
except ImportError:  # pragma: no cover — plain-unittest import path, no bench/site
	frappe = None
	_ = lambda s: s  # noqa: E731 — trivial passthrough mirroring frappe's own `_`
	rate_limit = None

_API = "https://api.telegram.org"
_TIMEOUT = 20
_ROW_CAP = 200
_DEFAULT_LOOKBACK_DAYS = 30


# --------------------------------------------------------------------------- #
# (a) Pure, frappe-free — the auth boundary. Unit-tested in isolation so a
# refactor can never silently weaken the exact HMAC recipe.
# --------------------------------------------------------------------------- #
def verify_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict | None:
	"""Validate Telegram WebApp initData; return the parsed `user` dict
	(merged with `auth_date`) on success, else None. Fails closed on: an
	empty/falsy bot_token, a missing/mismatched hash, a missing/unparsable
	`user`, or an auth_date older than `max_age_seconds` (replay guard)."""
	if not init_data or not bot_token:
		return None

	pairs = dict(parse_qsl(init_data, keep_blank_values=True))
	received_hash = pairs.pop("hash", None)
	if not received_hash:
		return None

	data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
	secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
	computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
	if not hmac.compare_digest(computed_hash, received_hash):
		return None

	auth_date_raw = pairs.get("auth_date")
	if not auth_date_raw:
		return None
	try:
		auth_date = int(auth_date_raw)
	except (TypeError, ValueError):
		return None
	if time.time() - auth_date > max_age_seconds:
		return None

	user_raw = pairs.get("user")
	if not user_raw:
		return None
	try:
		user = json.loads(user_raw)
	except (TypeError, ValueError):
		return None
	if not isinstance(user, dict):
		return None

	return {**user, "auth_date": auth_date}


def _row_op_label(voucher_type: str | None, remarks: str | None) -> str:
	"""'Kassa Som → PK | ijara' -> 'Journal Entry — ijara'; a remark with no
	'|' separator (or none at all / the ERPNext 'No Remarks' placeholder)
	collapses to the bare voucher_type."""
	vtype = (voucher_type or "").strip()
	text = (remarks or "").strip()
	if not text or text.lower() == "no remarks":
		return vtype
	if "|" in text:
		text = text.split("|", 1)[1].strip()
	if not text:
		return vtype
	return f"{vtype} — {text}"


# --------------------------------------------------------------------------- #
# (b) Endpoint internals — every function below runs only in a real Frappe
# process (impersonated as the resolved kassir), never under plain unittest.
# --------------------------------------------------------------------------- #
def _resolve_kassir(telegram_user_id: str):
	import frappe

	if not telegram_user_id:
		return None
	name = frappe.db.get_value("Stabler Kassir", {"telegram_user_id": telegram_user_id, "enabled": 1}, "name")
	if not name:
		return None
	return frappe.get_doc("Stabler Kassir", name)


def _resolve_date_range(from_date: str | None, to_date: str | None) -> tuple[str, str]:
	from frappe.utils import add_days, getdate, today

	to_d = getdate(to_date) if to_date else getdate(today())
	from_d = getdate(from_date) if from_date else add_days(to_d, -_DEFAULT_LOOKBACK_DAYS)
	if to_d < from_d:
		to_d = from_d
	return str(from_d), str(to_d)


def _kassir_label(kassir) -> str:
	import frappe

	full_name = frappe.db.get_value("User", kassir.user, "full_name") if kassir.user else None
	return full_name or kassir.user or kassir.name


def _format_row_date(value) -> str:
	from frappe.utils import formatdate

	if not value:
		return ""
	try:
		return formatdate(value, "dd.mm.yyyy")
	except Exception:  # a bad date must never blow up the statement
		return str(value)


def _build_cards(company: str, accounts: list[str], to_date: str, base_currency: str) -> list[dict]:
	"""Balances grouped by currency (only currencies the kassir actually
	holds), UZS first — feeds the two mockup cards (plus any extra currency)."""
	import frappe

	from stabler.api import money

	totals: dict[str, float] = {}
	for account in accounts:
		currency = frappe.db.get_value("Account", account, "account_currency") or base_currency
		bal = money.account_balance(company, account, as_of=to_date)
		balance_acc = bal.get("balance_acc")
		if balance_acc is None:
			balance_acc = bal.get("balance_base", 0)
		totals[currency] = totals.get(currency, 0.0) + float(balance_acc or 0)

	cards: list[dict] = []
	if "UZS" in totals:
		cards.append({"currency": "UZS", "balance": totals.pop("UZS")})
	for currency, balance in totals.items():
		cards.append({"currency": currency, "balance": balance})
	return cards


def _build_rows(company: str, accounts: list[str], from_date: str, to_date: str) -> list[dict]:
	"""Statement rows across all of the kassir's accounts, sorted date asc,
	capped at the most recent _ROW_CAP."""
	import frappe

	from stabler.api import money

	# account_transactions returns BASE-currency GL amounts (debit/credit/balance),
	# so every statement row is denominated in the company base currency — this is
	# why the mockup labels the columns "Summa UZS / Qoldiq UZS". A USD sub-kassa
	# op therefore shows its base-UZS equivalent here (the account_label names the
	# sub-kassa); the per-currency USD balance lives in the cards, not the rows.
	base_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	all_rows: list[dict] = []
	for account in accounts:
		info = (
			frappe.db.get_value("Account", account, ["account_name", "account_currency"], as_dict=True) or {}
		)
		label = info.get("account_name") or account
		txns = money.account_transactions(company, account, from_date=from_date, to_date=to_date, limit=500)
		for entry in txns.get("entries") or []:
			debit = float(entry.get("debit") or 0)
			credit = float(entry.get("credit") or 0)
			posting_date = entry.get("posting_date")
			all_rows.append(
				{
					"_sort_date": str(posting_date),
					"date": _format_row_date(posting_date),
					"op": _row_op_label(entry.get("voucher_type"), entry.get("remarks")),
					"amount": debit - credit,
					"currency": base_currency,  # rows are base-currency (see note above)
					"account_label": label,
					"running": float(entry.get("balance") or 0),
				}
			)

	all_rows.sort(key=lambda r: r["_sort_date"])
	if len(all_rows) > _ROW_CAP:
		all_rows = all_rows[-_ROW_CAP:]
	for row in all_rows:
		row.pop("_sort_date", None)
	return all_rows


def _build_summary(kassir, from_date: str, to_date: str) -> dict:
	import frappe

	company = kassir.company
	base_currency = frappe.db.get_value("Company", company, "default_currency") or "UZS"
	accounts = [row.account for row in (kassir.accounts or []) if row.account]

	return {
		"kassir": _kassir_label(kassir),
		"company": company,
		"base_currency": base_currency,
		"from_date": from_date,
		"to_date": to_date,
		"cards": _build_cards(company, accounts, to_date, base_currency),
		"rows": _build_rows(company, accounts, from_date, to_date),
	}


def _kassa_summary(init_data: str, from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Telegram Mini App data endpoint for 'Mening kassa jadvalim' (WP-K7).

	FAIL-CLOSED auth: the only credential is Telegram's initData HMAC
	(verify_init_data), resolved to an enabled Stabler Kassir by
	telegram_user_id. Never logs init_data or the bot token."""
	import frappe

	token = getattr(frappe.conf, "kassa_telegram_token", None)
	if not token:
		frappe.throw(_("Kassa Telegram integration is not configured"), frappe.PermissionError)

	user = verify_init_data(init_data, token)
	if not user:
		# Never log init_data/token — only that a rejection happened.
		frappe.log_error(
			title="Kassa miniapp: rejected (invalid initData)",
			message="init_data signature verification failed or expired",
		)
		frappe.throw(_("Invalid Telegram signature"), frappe.PermissionError)

	telegram_user_id = str(user.get("id") or "").strip()
	kassir = _resolve_kassir(telegram_user_id)
	if not kassir:
		frappe.throw(_("Ruxsat yo'q"), frappe.PermissionError)

	resolved_from, resolved_to = _resolve_date_range(from_date, to_date)

	# IMPERSONATE: every read below runs as the kassir's own Frappe user, so
	# permissions behave exactly as they would through the bot/SPA.
	original_user = frappe.session.user
	frappe.set_user(kassir.user)
	try:
		return _build_summary(kassir, resolved_from, resolved_to)
	finally:
		frappe.set_user(original_user)


if frappe is not None:
	kassa_summary = frappe.whitelist(allow_guest=True)(rate_limit(limit=120, seconds=60)(_kassa_summary))
else:  # pragma: no cover — plain-unittest import path only; real deploys always have frappe
	kassa_summary = _kassa_summary


# --------------------------------------------------------------------------- #
# Bot wiring — mini app URL + one-time chat-menu-button setup.
# --------------------------------------------------------------------------- #
def mini_app_url() -> str:
	"""Site URL of the Mini App page. Used by bot.py's keyboard-serialization
	step (BTN_STATEMENT -> web_app button) and by setup_menu_button()."""
	from frappe.utils import get_url

	return f"{get_url()}/kassa"


def _post(url: str, payload: dict):
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


def setup_menu_button() -> dict:
	"""One-time setup: point the bot's chat menu button at the Kassa Mini App
	so it's always reachable from the chat menu, even before any message.

	Run once (or again after the site URL changes) via:
	  bench --site <site> execute stabler.integrations.kassa.miniapp.setup_menu_button

	Fail-closed: returns {"ok": False, "error": ...} instead of raising when
	the token is missing — a misconfigured site must never trace out a token."""
	import frappe

	token = getattr(frappe.conf, "kassa_telegram_token", None)
	if not token:
		return {"ok": False, "error": "kassa_telegram_token not configured"}
	payload = {
		"menu_button": {
			"type": "web_app",
			"text": "Kassa",
			"web_app": {"url": mini_app_url()},
		}
	}
	return _post(f"{_API}/bot{token}/setChatMenuButton", payload)
