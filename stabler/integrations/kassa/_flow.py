"""Kassa Telegram bot — pure reply-keyboard state machine (WP-K3).

NO frappe import here — this module is fully unit-testable under plain
unittest (mirrors the style of stabler.integrations.uzex.telegram's
Frappe-free builders). All accounting/DB access lives in bot.py, which calls
IN-PROCESS into stabler.api.money; this module only decides what to say and
what to ask next.

State shape (plain dict, JSON-serializable):
    {
        "step": str,
        "kassa": str | None,               # chosen top-level kassa label
        "posting_date": str | None,        # ISO yyyy-mm-dd; None == today
        ...per-operation scratch keys (cleared on MENU re-entry)...
    }

``ctx`` (built by bot.py.build_ctx, Frappe-free once assembled):
    {
        "kassas": {kassa_label: [{"account","label","currency"}, ...]},
        "categories": [{"account","label"}, ...],
        "deals": [{"name","label"}, ...],           # [] when tender is off
        "targets": [{"account","label","currency"}, ...],
        "base_currency": "UZS",
    }

``handle(state, text, ctx)`` returns ``(reply_text, keyboard, new_state, action)``.
``keyboard`` is a list of button-label rows, or ``None`` to leave whatever
keyboard is already showing untouched (free-text entry steps).
``action`` is ``None`` unless a completed operation must be executed by the
caller — see the docstring of each action shape below.
"""

from __future__ import annotations

import re
from datetime import date

# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
STEP_MAIN = "main"
STEP_MENU = "menu"

STEP_KIRIM_SUBKASSA = "kirim_subkassa"
STEP_KIRIM_SOURCE = "kirim_source"
STEP_KIRIM_AMOUNT = "kirim_amount"
STEP_KIRIM_MEMO = "kirim_memo"
STEP_KIRIM_CONFIRM = "kirim_confirm"

STEP_CHIQIM_SUBKASSA = "chiqim_subkassa"
STEP_CHIQIM_CATEGORY = "chiqim_category"
STEP_CHIQIM_CATEGORY_FILTER = "chiqim_category_filter"
STEP_CHIQIM_CATEGORY_PICK = "chiqim_category_pick"
STEP_CHIQIM_DEAL = "chiqim_deal"
STEP_CHIQIM_AMOUNT = "chiqim_amount"
STEP_CHIQIM_MEMO = "chiqim_memo"
STEP_CHIQIM_CONFIRM = "chiqim_confirm"

STEP_KONV_TARGET = "konv_target"
STEP_KONV_SOURCE = "konv_source"
STEP_KONV_RECEIVED = "konv_received"
STEP_KONV_GIVEN = "konv_given"
STEP_KONV_CONFIRM = "konv_confirm"

STEP_K2K_SOURCE = "k2k_source"
STEP_K2K_TARGET = "k2k_target"
STEP_K2K_AMOUNT = "k2k_amount"
STEP_K2K_CONFIRM = "k2k_confirm"

STEP_BACKDATE = "backdate"

# --------------------------------------------------------------------------- #
# Fixed labels (Uzbek latin, exactly as drawn in the Whimsical flow)
# --------------------------------------------------------------------------- #
BTN_KIRIM = "\U0001F7E2 Kirim"
BTN_CHIQIM = "\U0001F534 Chiqim"
BTN_KONV = "\U0001F504 Konvertatsiya"
BTN_K2K = "\U0001F4B1 Kassadan kassaga"
BTN_BACKDATE = "\U0001F4DD Qolib ketgan amal"
BTN_STATEMENT = "ℹ️ Mening jadvalim"
BTN_CANCEL = "❌ Bekor qilish"
BTN_CONFIRM = "✅ Tasdiqlash"
BTN_OTHER = "Boshqa…"
BTN_SKIP_DEAL = "O'tkazib yuborish"

MENU_KEYBOARD = [
	[BTN_KIRIM, BTN_CHIQIM],
	[BTN_KONV, BTN_K2K],
	[BTN_BACKDATE, BTN_STATEMENT],
	[BTN_CANCEL],
]

CONFIRM_KEYBOARD = [[BTN_CONFIRM], [BTN_CANCEL]]

_CATEGORY_PAGE = 10
_DEAL_PAGE = 8

_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
_NBSP = "\xa0"


# --------------------------------------------------------------------------- #
# Pure helpers (exported, unit-tested)
# --------------------------------------------------------------------------- #
def parse_amount(text: str | None) -> float | None:
	"""'2 000 000' -> 2000000.0 / '1 250,50' -> 1250.5 / garbage or <=0 -> None."""
	if text is None:
		return None
	raw = str(text).strip().replace(_NBSP, " ")
	if not raw:
		return None
	# Thousands separator is whitespace in this bot's UX — strip all of it.
	cleaned = re.sub(r"\s+", "", raw)
	if "," in cleaned and "." in cleaned:
		# Ambiguous (both separators present) — reject rather than guess.
		return None
	if "," in cleaned:
		cleaned = cleaned.replace(",", ".")
	try:
		value = float(cleaned)
	except ValueError:
		return None
	if value <= 0:
		return None
	return value


def parse_date_ddmmyyyy(text: str | None) -> str | None:
	"""'05.07.2026' -> '2026-07-05'; invalid/garbage -> None."""
	if not text:
		return None
	m = _DATE_RE.match(text.strip())
	if not m:
		return None
	dd, mm, yyyy = m.groups()
	try:
		d = date(int(yyyy), int(mm), int(dd))
	except ValueError:
		return None
	return d.isoformat()


def format_amount(amount: float, currency: str) -> str:
	"""2000000, 'UZS' -> '2 000 000 UZS'; 1250.5, 'USD' -> '1 250.5 USD'."""
	amt = float(amount)
	if amt == int(amt):
		int_part = f"{int(amt):,}".replace(",", " ")
		return f"{int_part} {currency}".strip()
	whole = f"{amt:,.2f}"
	int_part, frac_part = whole.split(".")
	int_part = int_part.replace(",", " ")
	frac_part = frac_part.rstrip("0") or "0"
	return f"{int_part}.{frac_part} {currency}".strip()


def _fmt_date_human(iso: str | None) -> str:
	if not iso:
		return "bugun"
	try:
		y, m, d = iso.split("-")
	except ValueError:
		return iso
	return f"{d}.{m}.{y}"


# --------------------------------------------------------------------------- #
# ctx lookups
# --------------------------------------------------------------------------- #
def _kassa_labels(ctx: dict) -> list[str]:
	return list((ctx or {}).get("kassas", {}).keys())


def _leaves_for_kassa(ctx: dict, kassa_label: str | None) -> list[dict]:
	return (ctx or {}).get("kassas", {}).get(kassa_label, []) or []


def _find_by_label(rows: list[dict], label: str, key: str = "label") -> dict | None:
	for row in rows or []:
		if row.get(key) == label:
			return row
	return None


def _targets_same_currency(ctx: dict, currency: str, exclude_account: str) -> list[dict]:
	return [
		t
		for t in (ctx or {}).get("targets", []) or []
		if t.get("currency") == currency and t.get("account") != exclude_account
	]


def _rows(labels: list[str]) -> list[list[str]]:
	return [[label] for label in labels]


def _menu_state(kassa: str | None, posting_date: str | None) -> dict:
	return {"step": STEP_MENU, "kassa": kassa, "posting_date": posting_date}


def _menu_text(state: dict) -> str:
	return (
		f"Kassa: {state.get('kassa')}\n"
		f"Sana: {_fmt_date_human(state.get('posting_date'))}\n\n"
		"Amalni tanlang:"
	)


# --------------------------------------------------------------------------- #
# Confirm-text builders
# --------------------------------------------------------------------------- #
def _kirim_confirm_text(state: dict) -> str:
	leaf = state["sub_kassa"]
	src = state["src"]
	lines = [
		"\U0001F7E2 Kirim",
		f"Kassa: {leaf['label']} ({leaf['currency']})",
		f"Manba: {src['label']}",
		f"Summa: {format_amount(state['amount'], leaf['currency'])}",
		f"Izoh: {state.get('memo') or '-'}",
		f"Sana: {_fmt_date_human(state.get('posting_date'))}",
		"",
		"Tasdiqlaysizmi?",
	]
	return "\n".join(lines)


def _chiqim_confirm_text(state: dict, ctx: dict) -> str:
	leaf = state["sub_kassa"]
	cat = _find_by_label(ctx.get("categories", []), state["category"], key="account") or {}
	cat_label = cat.get("label", state["category"])
	deal_label = None
	if state.get("deal"):
		deal = _find_by_label(ctx.get("deals", []) or [], state["deal"], key="name")
		deal_label = deal.get("label") if deal else state["deal"]
	lines = [
		"\U0001F534 Chiqim",
		f"Kassa: {leaf['label']} ({leaf['currency']})",
		f"Kategoriya: {cat_label}",
	]
	if deal_label:
		lines.append(f"Tender: {deal_label}")
	lines.append(f"Summa: {format_amount(state['amount'], leaf['currency'])}")
	lines.append(f"Izoh: {state.get('memo') or '-'}")
	lines.append(f"Sana: {_fmt_date_human(state.get('posting_date'))}")
	lines.append("")
	lines.append("Tasdiqlaysizmi?")
	return "\n".join(lines)


def _konv_confirm_text(state: dict) -> str:
	tgt, src = state["tgt"], state["src"]
	lines = [
		"\U0001F504 Konvertatsiya",
		f"Oldingiz: {format_amount(state['received'], tgt['currency'])} ({tgt['label']})",
		f"Berdingiz: {format_amount(state['given'], src['currency'])} ({src['label']})",
		f"Sana: {_fmt_date_human(state.get('posting_date'))}",
		"",
		"Tasdiqlaysizmi?",
	]
	return "\n".join(lines)


def _k2k_confirm_text(state: dict) -> str:
	src, tgt = state["src"], state["tgt"]
	lines = [
		"\U0001F4B1 Kassadan kassaga",
		f"Manba: {src['label']}",
		f"Manzil: {tgt['label']}",
		f"Summa: {format_amount(state['amount'], src['currency'])}",
		f"Sana: {_fmt_date_human(state.get('posting_date'))}",
		"",
		"Tasdiqlaysizmi?",
	]
	return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Step handlers — each returns (reply, keyboard, new_state, action)
# --------------------------------------------------------------------------- #
def _cancel(state: dict, ctx: dict):
	new_state = {"step": STEP_MAIN, "kassa": None, "posting_date": state.get("posting_date")}
	return ("Bekor qilindi.", _rows(_kassa_labels(ctx)), new_state, None)


def _handle_main(state: dict, text: str, ctx: dict):
	labels = _kassa_labels(ctx)
	if text in labels:
		new_state = _menu_state(text, state.get("posting_date"))
		return (_menu_text(new_state), MENU_KEYBOARD, new_state, None)
	return ("Kassani tanlang:", _rows(labels), state, None)


def _handle_menu(state: dict, text: str, ctx: dict):
	kassa = state.get("kassa")
	if text == BTN_KIRIM:
		leaves = _leaves_for_kassa(ctx, kassa)
		new_state = {**state, "step": STEP_KIRIM_SUBKASSA}
		return ("Qaysi kassaga kirim qilasiz?", _rows([l["label"] for l in leaves]), new_state, None)
	if text == BTN_CHIQIM:
		leaves = _leaves_for_kassa(ctx, kassa)
		new_state = {**state, "step": STEP_CHIQIM_SUBKASSA}
		return ("Qaysi kassadan chiqim qilasiz?", _rows([l["label"] for l in leaves]), new_state, None)
	if text == BTN_KONV:
		leaves = _leaves_for_kassa(ctx, kassa)
		new_state = {**state, "step": STEP_KONV_TARGET}
		return ("Nima oldingiz?", _rows([l["label"] for l in leaves]), new_state, None)
	if text == BTN_K2K:
		leaves = _leaves_for_kassa(ctx, kassa)
		new_state = {**state, "step": STEP_K2K_SOURCE}
		return ("Qaysi kassadan?", _rows([l["label"] for l in leaves]), new_state, None)
	if text == BTN_BACKDATE:
		new_state = {**state, "step": STEP_BACKDATE}
		return ("Sana (kk.oo.yyyy):", None, new_state, None)
	if text == BTN_STATEMENT:
		return ("\U0001F4CB Jadval tayyorlanmoqda...", MENU_KEYBOARD, dict(state), {"type": "statement"})
	return ("Iltimos, menyudan tanlang.", MENU_KEYBOARD, state, None)


# --- Kirim ------------------------------------------------------------------ #
def _handle_kirim_subkassa(state: dict, text: str, ctx: dict):
	leaves = _leaves_for_kassa(ctx, state.get("kassa"))
	leaf = _find_by_label(leaves, text)
	if not leaf:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([l["label"] for l in leaves]), state, None)
	sources = _targets_same_currency(ctx, leaf["currency"], leaf["account"])
	new_state = {**state, "step": STEP_KIRIM_SOURCE, "sub_kassa": leaf}
	return ("Qaysi hisobdan kirim keladi?", _rows([s["label"] for s in sources]), new_state, None)


def _handle_kirim_source(state: dict, text: str, ctx: dict):
	leaf = state["sub_kassa"]
	sources = _targets_same_currency(ctx, leaf["currency"], leaf["account"])
	src = _find_by_label(sources, text)
	if not src:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([s["label"] for s in sources]), state, None)
	new_state = {**state, "step": STEP_KIRIM_AMOUNT, "src": src}
	return ("Summani kiriting:", None, new_state, None)


def _handle_kirim_amount(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	new_state = {**state, "step": STEP_KIRIM_MEMO, "amount": amt}
	return ("Izoh (yoki '-' o'tkazib yuborish uchun):", None, new_state, None)


def _handle_kirim_memo(state: dict, text: str, ctx: dict):
	memo = None if text.strip() == "-" else (text.strip() or None)
	new_state = {**state, "step": STEP_KIRIM_CONFIRM, "memo": memo}
	return (_kirim_confirm_text(new_state), CONFIRM_KEYBOARD, new_state, None)


def _handle_kirim_confirm(state: dict, text: str, ctx: dict):
	if text != BTN_CONFIRM:
		return (_kirim_confirm_text(state), CONFIRM_KEYBOARD, state, None)
	action = {
		"type": "transfer",
		"from": state["src"]["account"],
		"to": state["sub_kassa"]["account"],
		"from_amount": state["amount"],
		"memo": state.get("memo"),
	}
	new_state = _menu_state(state.get("kassa"), None)
	return ("⏳ Amal bajarilmoqda...", MENU_KEYBOARD, new_state, action)


# --- Chiqim ------------------------------------------------------------------ #
def _handle_chiqim_subkassa(state: dict, text: str, ctx: dict):
	leaves = _leaves_for_kassa(ctx, state.get("kassa"))
	leaf = _find_by_label(leaves, text)
	if not leaf:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([l["label"] for l in leaves]), state, None)
	new_state = {**state, "step": STEP_CHIQIM_SUBKASSA, "sub_kassa": leaf}
	return _category_prompt(new_state, ctx)


def _category_prompt(state: dict, ctx: dict):
	categories = (ctx.get("categories") or [])[:_CATEGORY_PAGE]
	keyboard = _rows([c["label"] for c in categories]) + [[BTN_OTHER]]
	new_state = {**state, "step": STEP_CHIQIM_CATEGORY}
	return ("Kategoriyani tanlang:", keyboard, new_state, None)


def _handle_chiqim_category(state: dict, text: str, ctx: dict):
	categories = (ctx.get("categories") or [])[:_CATEGORY_PAGE]
	if text == BTN_OTHER:
		new_state = {**state, "step": STEP_CHIQIM_CATEGORY_FILTER}
		return ("Hisob nomining bir qismini yozing:", None, new_state, None)
	cat = _find_by_label(categories, text)
	if not cat:
		keyboard = _rows([c["label"] for c in categories]) + [[BTN_OTHER]]
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", keyboard, state, None)
	new_state = {**state, "category": cat["account"]}
	return _after_category_chosen(new_state, ctx)


def _handle_chiqim_category_filter(state: dict, text: str, ctx: dict):
	needle = (text or "").strip().lower()
	filtered = (
		[c for c in (ctx.get("categories") or []) if needle in c["label"].lower()][:_CATEGORY_PAGE]
		if needle
		else []
	)
	if not filtered:
		return ("Topilmadi. Qayta urinib ko'ring:", None, state, None)
	new_state = {**state, "step": STEP_CHIQIM_CATEGORY_PICK, "_filtered_categories": filtered}
	return ("Tanlang:", _rows([c["label"] for c in filtered]), new_state, None)


def _handle_chiqim_category_pick(state: dict, text: str, ctx: dict):
	filtered = state.get("_filtered_categories", [])
	cat = _find_by_label(filtered, text)
	if not cat:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([c["label"] for c in filtered]), state, None)
	new_state = {k: v for k, v in state.items() if k != "_filtered_categories"}
	new_state["category"] = cat["account"]
	return _after_category_chosen(new_state, ctx)


def _after_category_chosen(state: dict, ctx: dict):
	deals = ctx.get("deals") or []
	if deals:
		new_state = {**state, "step": STEP_CHIQIM_DEAL}
		keyboard = _rows([d["label"] for d in deals]) + [[BTN_SKIP_DEAL]]
		return ("Tenderni tanlang (ixtiyoriy):", keyboard, new_state, None)
	leaf = state["sub_kassa"]
	new_state = {**state, "step": STEP_CHIQIM_AMOUNT}
	return (f"Summani kiriting ({leaf['currency']}):", None, new_state, None)


def _handle_chiqim_deal(state: dict, text: str, ctx: dict):
	deals = ctx.get("deals") or []
	if text == BTN_SKIP_DEAL:
		new_state = {**state, "deal": None}
	else:
		deal = _find_by_label(deals, text)
		if not deal:
			keyboard = _rows([d["label"] for d in deals]) + [[BTN_SKIP_DEAL]]
			return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", keyboard, state, None)
		new_state = {**state, "deal": deal["name"]}
	leaf = new_state["sub_kassa"]
	new_state["step"] = STEP_CHIQIM_AMOUNT
	return (f"Summani kiriting ({leaf['currency']}):", None, new_state, None)


def _handle_chiqim_amount(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	new_state = {**state, "step": STEP_CHIQIM_MEMO, "amount": amt}
	return ("Izoh (yoki '-' o'tkazib yuborish uchun):", None, new_state, None)


def _handle_chiqim_memo(state: dict, text: str, ctx: dict):
	memo = None if text.strip() == "-" else (text.strip() or None)
	new_state = {**state, "step": STEP_CHIQIM_CONFIRM, "memo": memo}
	return (_chiqim_confirm_text(new_state, ctx), CONFIRM_KEYBOARD, new_state, None)


def _handle_chiqim_confirm(state: dict, text: str, ctx: dict):
	if text != BTN_CONFIRM:
		return (_chiqim_confirm_text(state, ctx), CONFIRM_KEYBOARD, state, None)
	action = {
		"type": "expense",
		"payment_from": state["sub_kassa"]["account"],
		"category": state["category"],
		"amount": state["amount"],
		"deal": state.get("deal"),
		"memo": state.get("memo"),
	}
	new_state = _menu_state(state.get("kassa"), None)
	return ("⏳ Amal bajarilmoqda...", MENU_KEYBOARD, new_state, action)


# --- Konvertatsiya ------------------------------------------------------------ #
def _handle_konv_target(state: dict, text: str, ctx: dict):
	leaves = _leaves_for_kassa(ctx, state.get("kassa"))
	tgt = _find_by_label(leaves, text)
	if not tgt:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([l["label"] for l in leaves]), state, None)
	candidates = [
		l for l in leaves if l["account"] != tgt["account"] and l["currency"] != tgt["currency"]
	]
	new_state = {**state, "step": STEP_KONV_SOURCE, "tgt": tgt}
	return ("Nimani berdingiz?", _rows([c["label"] for c in candidates]), new_state, None)


def _handle_konv_source(state: dict, text: str, ctx: dict):
	leaves = _leaves_for_kassa(ctx, state.get("kassa"))
	tgt = state["tgt"]
	candidates = [
		l for l in leaves if l["account"] != tgt["account"] and l["currency"] != tgt["currency"]
	]
	src = _find_by_label(candidates, text)
	if not src:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([c["label"] for c in candidates]), state, None)
	new_state = {**state, "step": STEP_KONV_RECEIVED, "src": src}
	return ("Qancha oldingiz?", None, new_state, None)


def _handle_konv_received(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	new_state = {**state, "step": STEP_KONV_GIVEN, "received": amt}
	return ("Qancha berdingiz?", None, new_state, None)


def _handle_konv_given(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	new_state = {**state, "step": STEP_KONV_CONFIRM, "given": amt}
	return (_konv_confirm_text(new_state), CONFIRM_KEYBOARD, new_state, None)


def _handle_konv_confirm(state: dict, text: str, ctx: dict):
	if text != BTN_CONFIRM:
		return (_konv_confirm_text(state), CONFIRM_KEYBOARD, state, None)
	action = {
		"type": "transfer",
		"from": state["src"]["account"],
		"to": state["tgt"]["account"],
		"from_amount": state["given"],
		"to_amount": state["received"],
	}
	new_state = _menu_state(state.get("kassa"), None)
	return ("⏳ Amal bajarilmoqda...", MENU_KEYBOARD, new_state, action)


# --- Kassadan kassaga ---------------------------------------------------------- #
def _handle_k2k_source(state: dict, text: str, ctx: dict):
	leaves = _leaves_for_kassa(ctx, state.get("kassa"))
	src = _find_by_label(leaves, text)
	if not src:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([l["label"] for l in leaves]), state, None)
	targets = _targets_same_currency(ctx, src["currency"], src["account"])
	new_state = {**state, "step": STEP_K2K_TARGET, "src": src}
	return ("Qaysi kassaga?", _rows([t["label"] for t in targets]), new_state, None)


def _handle_k2k_target(state: dict, text: str, ctx: dict):
	src = state["src"]
	targets = _targets_same_currency(ctx, src["currency"], src["account"])
	tgt = _find_by_label(targets, text)
	if not tgt:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([t["label"] for t in targets]), state, None)
	new_state = {**state, "step": STEP_K2K_AMOUNT, "tgt": tgt}
	return ("Summani kiriting:", None, new_state, None)


def _handle_k2k_amount(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	new_state = {**state, "step": STEP_K2K_CONFIRM, "amount": amt}
	return (_k2k_confirm_text(new_state), CONFIRM_KEYBOARD, new_state, None)


def _handle_k2k_confirm(state: dict, text: str, ctx: dict):
	if text != BTN_CONFIRM:
		return (_k2k_confirm_text(state), CONFIRM_KEYBOARD, state, None)
	action = {
		"type": "transfer",
		"from": state["src"]["account"],
		"to": state["tgt"]["account"],
		"from_amount": state["amount"],
	}
	new_state = _menu_state(state.get("kassa"), None)
	return ("⏳ Amal bajarilmoqda...", MENU_KEYBOARD, new_state, action)


# --- Backdate ------------------------------------------------------------------ #
def _handle_backdate(state: dict, text: str, ctx: dict):
	iso = parse_date_ddmmyyyy(text)
	if not iso:
		return ("Noto'g'ri format. Masalan: 05.07.2026", None, state, None)
	new_state = _menu_state(state.get("kassa"), iso)
	reply = (
		f"Endi barcha amallar {_fmt_date_human(iso)} sanasida yoziladi "
		"(bitta amaldan keyin bugungi sanaga qaytadi).\n\n" + _menu_text(new_state)
	)
	return (reply, MENU_KEYBOARD, new_state, None)


# --------------------------------------------------------------------------- #
# Dispatch table
# --------------------------------------------------------------------------- #
_STEP_HANDLERS = {
	STEP_MAIN: _handle_main,
	STEP_MENU: _handle_menu,
	STEP_KIRIM_SUBKASSA: _handle_kirim_subkassa,
	STEP_KIRIM_SOURCE: _handle_kirim_source,
	STEP_KIRIM_AMOUNT: _handle_kirim_amount,
	STEP_KIRIM_MEMO: _handle_kirim_memo,
	STEP_KIRIM_CONFIRM: _handle_kirim_confirm,
	STEP_CHIQIM_SUBKASSA: _handle_chiqim_subkassa,
	STEP_CHIQIM_CATEGORY: _handle_chiqim_category,
	STEP_CHIQIM_CATEGORY_FILTER: _handle_chiqim_category_filter,
	STEP_CHIQIM_CATEGORY_PICK: _handle_chiqim_category_pick,
	STEP_CHIQIM_DEAL: _handle_chiqim_deal,
	STEP_CHIQIM_AMOUNT: _handle_chiqim_amount,
	STEP_CHIQIM_MEMO: _handle_chiqim_memo,
	STEP_CHIQIM_CONFIRM: _handle_chiqim_confirm,
	STEP_KONV_TARGET: _handle_konv_target,
	STEP_KONV_SOURCE: _handle_konv_source,
	STEP_KONV_RECEIVED: _handle_konv_received,
	STEP_KONV_GIVEN: _handle_konv_given,
	STEP_KONV_CONFIRM: _handle_konv_confirm,
	STEP_K2K_SOURCE: _handle_k2k_source,
	STEP_K2K_TARGET: _handle_k2k_target,
	STEP_K2K_AMOUNT: _handle_k2k_amount,
	STEP_K2K_CONFIRM: _handle_k2k_confirm,
	STEP_BACKDATE: _handle_backdate,
}


def handle(state: dict | None, text: str | None, ctx: dict):
	"""Advance the state machine by one user message.

	Returns ``(reply_text, keyboard, new_state, action)``. ``action`` is a dict
	the caller (bot.py) must execute via IN-PROCESS money.py calls when a flow
	completes; None otherwise. See module docstring for the ctx shape and each
	action's field layout (transfer / expense / statement).
	"""
	state = dict(state or {})
	state.setdefault("step", STEP_MAIN)
	state.setdefault("kassa", None)
	state.setdefault("posting_date", None)
	text = (text or "").strip()

	if text == BTN_CANCEL:
		return _cancel(state, ctx)

	handler = _STEP_HANDLERS.get(state["step"], _handle_main)
	return handler(state, text, ctx)
