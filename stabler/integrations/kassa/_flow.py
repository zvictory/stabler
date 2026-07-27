"""Kassa Telegram bot — pure reply-keyboard state machine (WP-K3, smart-bot WP-K6).

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
        "aliases": {alias_lower: account_name, ...}, # WP-K6 quick-transfer
        "recent_memos": [str, ...],                  # WP-K6 izoh suggestions
        "cbu": {"rate": float | None, "date": "dd.mm"},  # WP-K6 konv assist
        "balances_by_kassa": {kassa_label: str | None}, # WP-K6 menu header
        "balances_by_leaf": {account: str | None},      # WP-K9 per-leaf Qoldiq line
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

STEP_KONV_DIRECTION = "konv_direction"
STEP_KONV_GIVEN = "konv_given"
STEP_KONV_CBU_CHOICE = "konv_cbu_choice"
STEP_KONV_RECEIVED = "konv_received"
STEP_KONV_MEMO = "konv_memo"
STEP_KONV_CONFIRM = "konv_confirm"

STEP_K2K_SOURCE = "k2k_source"
STEP_K2K_TARGET = "k2k_target"
STEP_K2K_AMOUNT = "k2k_amount"
STEP_K2K_MEMO = "k2k_memo"
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
BTN_KONV_MANUAL = "✏️ Boshqa summa"
BTN_KONV_CBU_PREFIX = "✅ CBU bo'yicha: "

MENU_KEYBOARD = [
	[BTN_KIRIM, BTN_CHIQIM],
	[BTN_KONV, BTN_K2K],
	[BTN_BACKDATE, BTN_STATEMENT],
	[BTN_CANCEL],
]

CONFIRM_KEYBOARD = [[BTN_CONFIRM], [BTN_CANCEL]]

_CATEGORY_PAGE = 10
_DEAL_PAGE = 8

_MEMO_PRESETS = ["Ijara", "Transport", "Bozor-xarid", BTN_OTHER]

_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
_NBSP = "\xa0"


# --------------------------------------------------------------------------- #
# Smart amount parser (WP-K6) — numeric formats, suffix shorthand, word-number
# grammar (Uzbek + Turkish). Never guesses: any ambiguity/garbage -> None.
# --------------------------------------------------------------------------- #
_NUMERIC_RE = re.compile(r"^[\d\s.,]+$")


def _parse_numeric(raw: str) -> float | None:
	"""'2 000 000' -> 2000000.0 / '1 250,50' -> 1250.5. Only digits/space/./,."""
	if not _NUMERIC_RE.match(raw):
		return None
	cleaned = re.sub(r"\s+", "", raw)
	if not cleaned:
		return None
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


def _to_float(num_str: str) -> float | None:
	s = num_str.strip()
	if "," in s and "." in s:
		return None
	s = s.replace(",", ".")
	try:
		return float(s)
	except ValueError:
		return None


# (pattern, multiplier) — every pattern is fully anchored (^...$) so order
# doesn't matter for correctness (e.g. "500ming" can never match the bare
# "...m$" pattern because the $ anchor requires the string to end right there).
_SUFFIX_MULTIPLIERS = [
	(re.compile(r"^(\d+(?:[.,]\d+)?)\s*k$", re.IGNORECASE), 1_000),
	(re.compile(r"^(\d+(?:[.,]\d+)?)\s*m$", re.IGNORECASE), 1_000_000),
	(re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:mln|млн)$", re.IGNORECASE), 1_000_000),
	(re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:ming|минг)$", re.IGNORECASE), 1_000),
	(re.compile(r"^(\d+(?:[.,]\d+)?)\s*bin$", re.IGNORECASE), 1_000),
]


def _parse_suffix_shorthand(raw: str) -> float | None:
	"""'100k'->100000 / '1.5m'/'1,5m'->1500000 / '2 mln'/'2млн'->2000000 /
	'500 ming'/'500минг'->500000 / '3 bin' (tr)->3000."""
	candidate = raw.strip()
	if not candidate:
		return None
	for pattern, mult in _SUFFIX_MULTIPLIERS:
		m = pattern.match(candidate)
		if not m:
			continue
		num = _to_float(m.group(1))
		if num is None or num <= 0:
			return None
		return num * mult
	return None


_APOSTROPHES = "’‘ʻʼ`"


def _normalize_apostrophes(s: str) -> str:
	for ch in _APOSTROPHES:
		s = s.replace(ch, "'")
	return s


# Uzbek (latin, with ASCII-fallback spellings) + Turkish digit/tens words.
# Values that coincide across languages (e.g. "on" = 10 in both) share one key.
_DIGIT_WORDS = {
	"bir": 1,
	"ikki": 2,
	"uch": 3,
	"üç": 3,
	"to'rt": 4,
	"tort": 4,
	"dört": 4,
	"besh": 5,
	"olti": 6,
	"altı": 6,
	"yetti": 7,
	"yedi": 7,
	"sakkiz": 8,
	"sekiz": 8,
	"to'qqiz": 9,
	"toqqiz": 9,
	"dokuz": 9,
}
_TENS_WORDS = {
	"o'n": 10,
	"on": 10,
	"yigirma": 20,
	"yirmi": 20,
	"o'ttiz": 30,
	"ottiz": 30,
	"otuz": 30,
	"qirq": 40,
	"kırk": 40,
	"ellik": 50,
	"elli": 50,
	"oltmish": 60,
	"altmış": 60,
	"yetmish": 70,
	"yetmiş": 70,
	"sakson": 80,
	"seksen": 80,
	"to'qson": 90,
	"toqson": 90,
	"doksan": 90,
}
_HUNDRED_WORDS = {"yuz", "yüz"}
_UNIT_WORDS = {
	"ming": 1_000,
	"bin": 1_000,
	"million": 1_000_000,
	"mln": 1_000_000,
	"milyon": 1_000_000,
}


def _parse_word_number(raw: str) -> float | None:
	"""Compositional Uzbek/Turkish number-word grammar.

	'yuz ming'=100000, 'besh yuz ming'=500000,
	'ikki million uch yuz ming'=2300000, 'bir yarim million'=1500000
	(X yarim UNIT = (X+0.5)*UNIT), 'yarim million'=500000 (yarim UNIT = 0.5*UNIT).
	Any unrecognized token aborts the whole parse -> None (never guesses).
	"""
	text = _normalize_apostrophes(raw.strip().lower())
	if not text:
		return None
	tokens = text.split()
	if not tokens:
		return None
	total = 0.0
	current = 0.0
	seen = False
	i = 0
	n = len(tokens)
	while i < n:
		tok = tokens[i]
		if tok == "yarim":
			if i + 1 >= n or tokens[i + 1] not in _UNIT_WORDS:
				return None
			mult = _UNIT_WORDS[tokens[i + 1]]
			half_value = (current + 0.5) if current else 0.5
			total += half_value * mult
			current = 0.0
			seen = True
			i += 2
			continue
		if tok in _DIGIT_WORDS:
			current += _DIGIT_WORDS[tok]
			seen = True
			i += 1
			continue
		if tok in _TENS_WORDS:
			current += _TENS_WORDS[tok]
			seen = True
			i += 1
			continue
		if tok in _HUNDRED_WORDS:
			current = (current or 1) * 100
			seen = True
			i += 1
			continue
		if tok in _UNIT_WORDS:
			total += (current or 1) * _UNIT_WORDS[tok]
			current = 0.0
			seen = True
			i += 1
			continue
		return None
	total += current
	if not seen or total <= 0:
		return None
	return total


def parse_amount(text: str | None) -> float | None:
	"""'2 000 000' -> 2000000.0 / '1 250,50' -> 1250.5 / '100k' -> 100000.0 /
	'besh yuz ming' -> 500000.0 / garbage, ambiguous or <=0 -> None. Never guesses."""
	if text is None:
		return None
	raw = str(text).strip().replace(_NBSP, " ")
	if not raw:
		return None
	numeric = _parse_numeric(raw)
	if numeric is not None:
		return numeric
	suffix = _parse_suffix_shorthand(raw)
	if suffix is not None:
		return suffix
	return _parse_word_number(raw)


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


def _echo_amount(amount: float, currency: str) -> str:
	"""Confirmation echo shown right after the bot accepts a typed amount, so
	the kassir sees what was understood before confirming — money path never
	silently guesses."""
	return f"≈ {format_amount(amount, currency)}"


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


def _targets_other_kassas_same_currency(ctx: dict, kassa: str | None, currency: str) -> list[dict]:
	"""Kassadan-kassaga (WP-K9) targets: same-currency company cash accounts
	that are NOT a leaf of the CURRENT kassa — i.e. only OTHER kassas. Own-
	kassa, same-currency moves belong to Konvertatsiya, not this flow."""
	own_accounts = {l.get("account") for l in _leaves_for_kassa(ctx, kassa)}
	return [
		t
		for t in (ctx or {}).get("targets", []) or []
		if t.get("currency") == currency and t.get("account") not in own_accounts
	]


def _qoldiq_header(ctx: dict, kassa: str | None) -> str | None:
	"""Reuse ctx['balances_by_kassa'][kassa] as a 'Qoldiq: ...' header line for
	the Konvertatsiya-direction and Kassadan-kassaga entry prompts (WP-K9)."""
	extra = ((ctx or {}).get("balances_by_kassa") or {}).get(kassa)
	if not extra:
		return None
	if extra.lstrip().lower().startswith("qoldiq"):
		return extra
	return f"Qoldiq: {extra}"


def _leaf_balance_line(ctx: dict, leaf: dict) -> str | None:
	"""Per-leaf 'Qoldiq: ...' line for the K2K 'Yuboruvchi' prompt (WP-K9).
	ctx['balances_by_leaf'] is optional — omitted entirely when bot.py hasn't
	populated it, never a new lookup from this Frappe-free module."""
	bal = ((ctx or {}).get("balances_by_leaf") or {}).get((leaf or {}).get("account"))
	if not bal:
		return None
	return f"Qoldiq: {bal}"


def _rows(labels: list[str]) -> list[list[str]]:
	return [[label] for label in labels]


def _chunk(items: list, size: int) -> list[list]:
	return [items[i : i + size] for i in range(0, len(items), size)]


def _menu_state(kassa: str | None, posting_date: str | None) -> dict:
	return {"step": STEP_MENU, "kassa": kassa, "posting_date": posting_date}


def _menu_text(state: dict, ctx: dict | None = None) -> str:
	lines = [
		f"Kassa: {state.get('kassa')}",
		f"Sana: {_fmt_date_human(state.get('posting_date'))}",
	]
	extra = ((ctx or {}).get("balances_by_kassa") or {}).get(state.get("kassa"))
	if extra:
		lines.append(extra)
	lines.append("")
	lines.append("Amalni tanlang:")
	return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Mandatory-izoh helper (WP-K6): shared by Chiqim / Kassadan-kassaga /
# Konvertatsiya, which now all REQUIRE a non-empty, non-"-" izoh. Kirim keeps
# its own optional "-"-skips handler, untouched.
# --------------------------------------------------------------------------- #
def _izoh_keyboard(ctx: dict | None) -> list[list[str]]:
	recent = [m for m in ((ctx or {}).get("recent_memos") or []) if m][:6]
	rows = _chunk(recent, 2)
	rows.append(list(_MEMO_PRESETS))
	return rows


def _mandatory_memo_step(state: dict, text: str, ctx: dict, confirm_builder):
	"""Shared body for izoh steps that REQUIRE a non-empty, non-'-' memo.

	``confirm_builder(new_state_with_memo, ctx)`` must return the same
	``(reply, keyboard, new_state, action)`` tuple shape as any step handler.
	"""
	if state.get("_memo_await_free"):
		stripped = (text or "").strip()
		if not stripped or stripped == "-":
			return ("Izoh bo'sh bo'lishi mumkin emas. Yozing:", None, state, None)
		new_state = {k: v for k, v in state.items() if k != "_memo_await_free"}
		new_state["memo"] = stripped
		return confirm_builder(new_state, ctx)
	if text == BTN_OTHER:
		new_state = {**state, "_memo_await_free": True}
		return ("Izohni yozing:", None, new_state, None)
	stripped = (text or "").strip()
	if not stripped or stripped == "-":
		return ("Izoh majburiy. Tanlang yoki yozing:", _izoh_keyboard(ctx), state, None)
	new_state = {**state, "memo": stripped}
	return confirm_builder(new_state, ctx)


# --------------------------------------------------------------------------- #
# One-message quick transfer (WP-K6): "somdan pkga 500 ming [izoh]" — same-
# currency kassa-to-kassa shortcut recognized at MAIN/MENU. Cross-currency and
# unrecognized text -> None (falls through to normal menu handling).
# --------------------------------------------------------------------------- #
def _all_known_leaves(ctx: dict) -> list[dict]:
	leaves: list[dict] = []
	for group in ((ctx or {}).get("kassas") or {}).values():
		leaves.extend(group)
	leaves.extend((ctx or {}).get("targets") or [])
	return leaves


def _leaf_by_account(ctx: dict, account: str) -> dict | None:
	for leaf in _all_known_leaves(ctx):
		if leaf.get("account") == account:
			return leaf
	return None


def _kassa_for_account(ctx: dict, account: str) -> str | None:
	for kassa_label, leaves in ((ctx or {}).get("kassas") or {}).items():
		for leaf in leaves:
			if leaf.get("account") == account:
				return kassa_label
	return None


def _extract_izoh(rest: str) -> str | None:
	rest = (rest or "").strip()
	if not rest:
		return None
	rest = rest.lstrip(",").strip()
	if not rest or rest == "uchun":
		return None
	if rest.endswith(" uchun"):
		rest = rest[: -len(" uchun")].strip()
	return rest or None


_QT_MAX_AMOUNT_TOKENS = 5


def _finish_quick_transfer(from_acc: str, to_acc: str, tail: str, ctx: dict) -> dict | None:
	tokens = tail.split()
	if not tokens:
		return None
	max_len = min(_QT_MAX_AMOUNT_TOKENS, len(tokens))
	for length in range(max_len, 0, -1):
		candidate = " ".join(tokens[:length])
		amt = parse_amount(candidate)
		if amt is None:
			continue
		from_leaf = _leaf_by_account(ctx, from_acc)
		to_leaf = _leaf_by_account(ctx, to_acc)
		if from_leaf and to_leaf and from_leaf.get("currency") != to_leaf.get("currency"):
			return None  # cross-currency — out of scope for this shortcut
		izoh = _extract_izoh(" ".join(tokens[length:]))
		return {"from": from_acc, "to": to_acc, "amount": amt, "izoh": izoh}
	return None


def parse_quick_transfer(text: str | None, ctx: dict) -> dict | None:
	"""'somdan pkga 500 ming ijara uchun' -> {"from","to","amount","izoh"}.

	``ctx["aliases"]`` is {alias_lower: account_name}, built by bot.py from
	leaf labels. Matches "X dan Y ga" with -dan/-ga attached or separate.
	Same-currency only; cross-currency or unrecognized text -> None."""
	if not text:
		return None
	aliases = (ctx or {}).get("aliases") or {}
	if not aliases:
		return None
	lowered = text.strip().lower()
	if not lowered:
		return None
	alias_keys = sorted(aliases.keys(), key=len, reverse=True)
	for from_alias in alias_keys:
		remainder = None
		for dan_variant in (from_alias + "dan", from_alias + " dan"):
			if lowered.startswith(dan_variant):
				remainder = lowered[len(dan_variant) :].lstrip()
				break
		if remainder is None:
			continue
		for to_alias in alias_keys:
			if to_alias == from_alias or aliases[to_alias] == aliases[from_alias]:
				continue
			for ga_variant in (to_alias + "ga", to_alias + " ga"):
				if remainder.startswith(ga_variant):
					tail = remainder[len(ga_variant) :].strip()
					result = _finish_quick_transfer(aliases[from_alias], aliases[to_alias], tail, ctx)
					if result:
						return result
	return None


def _try_quick_transfer(state: dict, text: str, ctx: dict):
	"""Wired into MAIN/MENU, before keyword matching. On a recognized
	same-currency quick-transfer, jump straight to the Kassadan-kassaga
	confirm step (or the mandatory-izoh prompt if none was typed)."""
	qt = parse_quick_transfer(text, ctx)
	if not qt:
		return None
	src = _leaf_by_account(ctx, qt["from"])
	tgt = _leaf_by_account(ctx, qt["to"])
	if not src or not tgt or src["account"] == tgt["account"]:
		return None
	kassa = state.get("kassa") or _kassa_for_account(ctx, src["account"])
	if not kassa:
		labels = _kassa_labels(ctx)
		kassa = labels[0] if labels else None
	base_state = {
		**state,
		"kassa": kassa,
		"step": STEP_K2K_TARGET,
		"src": src,
		"tgt": tgt,
		"amount": qt["amount"],
	}
	if qt.get("izoh"):
		base_state["memo"] = qt["izoh"]
		base_state["step"] = STEP_K2K_CONFIRM
		return (_k2k_confirm_text(base_state), CONFIRM_KEYBOARD, base_state, None)
	base_state["step"] = STEP_K2K_MEMO
	reply = f"{_echo_amount(qt['amount'], src['currency'])}\n\nIzoh (majburiy):"
	return (reply, _izoh_keyboard(ctx), base_state, None)


# --------------------------------------------------------------------------- #
# Confirm-text builders
# --------------------------------------------------------------------------- #
def _typed_echo(raw, amount, currency) -> str | None:
	"""'Yozganingiz: <raw>' line — shown only when the kassir typed something
	other than the plain formatted number (word/shorthand like "400ming",
	"besh yuz ming"), so a misparse is visible right before Tasdiqlash. Returns
	None when the raw text already equals the formatted amount (no noise)."""
	raw = (raw or "").strip()
	if not raw:
		return None
	# Normalize both to digits-only; if identical, the raw adds nothing.
	digits_raw = "".join(ch for ch in raw if ch.isdigit())
	digits_fmt = "".join(ch for ch in format_amount(amount, currency) if ch.isdigit())
	if digits_raw and digits_raw == digits_fmt:
		return None
	return f"Yozganingiz: {raw}"


def _kirim_confirm_text(state: dict) -> str:
	leaf = state["sub_kassa"]
	src = state["src"]
	lines = [
		"\U0001F7E2 Kirim",
		f"Kassa: {leaf['label']} ({leaf['currency']})",
		f"Manba: {src['label']}",
		f"Summa: {format_amount(state['amount'], leaf['currency'])}",
	]
	_te = _typed_echo(state.get("amount_raw"), state["amount"], leaf["currency"])
	if _te:
		lines.append(_te)
	lines += [
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
	_te = _typed_echo(state.get("amount_raw"), state["amount"], leaf["currency"])
	if _te:
		lines.append(_te)
	lines.append(f"Izoh: {state.get('memo') or '-'}")
	lines.append(f"Sana: {_fmt_date_human(state.get('posting_date'))}")
	lines.append("")
	lines.append("Tasdiqlaysizmi?")
	return "\n".join(lines)


def _konv_confirm_text(state: dict) -> str:
	tgt, src = state["tgt"], state["src"]
	given, received = state["given"], state["received"]
	if src["currency"] == tgt["currency"]:
		# Same-currency move — no Kurs line, single Summa (given == received).
		lines = [
			BTN_KONV,
			f"Manba: {src['label']}",
			f"Manzil: {tgt['label']}",
			f"Summa: {format_amount(given, src['currency'])}",
		]
		_tg = _typed_echo(state.get("given_raw"), given, src["currency"])
		if _tg:
			lines.append(_tg)
		lines += [
			f"Izoh: {state.get('memo') or '-'}",
			f"Sana: {_fmt_date_human(state.get('posting_date'))}",
			"",
			"Tasdiqlaysizmi?",
		]
		return "\n".join(lines)
	rate = (received / given) if given else 0.0
	lines = [
		BTN_KONV,
		f"Berdingiz: {format_amount(given, src['currency'])} ({src['label']})",
		f"Oldingiz: {format_amount(received, tgt['currency'])} ({tgt['label']})",
		f"Kurs: 1 {src['currency']} = {format_amount(rate, tgt['currency'])}",
	]
	_tg = _typed_echo(state.get("given_raw"), given, src["currency"])
	if _tg:
		lines.append(f"Berdingiz — {_tg.lower()}")
	_tr = _typed_echo(state.get("received_raw"), received, tgt["currency"])
	if _tr:
		lines.append(f"Oldingiz — {_tr.lower()}")
	lines += [
		f"Izoh: {state.get('memo') or '-'}",
		f"Sana: {_fmt_date_human(state.get('posting_date'))}",
		"",
		"Tasdiqlaysizmi?",
	]
	return "\n".join(lines)


def _k2k_confirm_text(state: dict) -> str:
	src, tgt = state["src"], state["tgt"]
	lines = [
		BTN_K2K,
		f"Manba: {src['label']}",
		f"Manzil: {tgt['label']}",
		f"Summa: {format_amount(state['amount'], src['currency'])}",
	]
	_te = _typed_echo(state.get("amount_raw"), state["amount"], src["currency"])
	if _te:
		lines.append(_te)
	lines += [
		f"Izoh: {state.get('memo') or '-'}",
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
	qt = _try_quick_transfer(state, text, ctx)
	if qt:
		return qt
	labels = _kassa_labels(ctx)
	if text in labels:
		new_state = _menu_state(text, state.get("posting_date"))
		return (_menu_text(new_state, ctx), MENU_KEYBOARD, new_state, None)
	return ("Kassani tanlang:", _rows(labels), state, None)


def _handle_menu(state: dict, text: str, ctx: dict):
	qt = _try_quick_transfer(state, text, ctx)
	if qt:
		return qt
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
		new_state = {**state, "step": STEP_KONV_DIRECTION}
		return (_konv_direction_text(ctx, kassa), _konv_direction_keyboard(leaves), new_state, None)
	if text == BTN_K2K:
		leaves = _leaves_for_kassa(ctx, kassa)
		new_state = {**state, "step": STEP_K2K_SOURCE}
		return (_k2k_source_text(ctx, kassa), _rows([l["label"] for l in leaves]), new_state, None)
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
	leaf = state["sub_kassa"]
	new_state = {**state, "step": STEP_KIRIM_MEMO, "amount": amt, "amount_raw": text.strip()}
	reply = f"{_echo_amount(amt, leaf['currency'])}\n\nIzoh (yoki '-' o'tkazib yuborish uchun):"
	return (reply, None, new_state, None)


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
	keyboard = [*_rows([c["label"] for c in categories]), [BTN_OTHER]]
	new_state = {**state, "step": STEP_CHIQIM_CATEGORY}
	return ("Kategoriyani tanlang:", keyboard, new_state, None)


def _handle_chiqim_category(state: dict, text: str, ctx: dict):
	categories = (ctx.get("categories") or [])[:_CATEGORY_PAGE]
	if text == BTN_OTHER:
		new_state = {**state, "step": STEP_CHIQIM_CATEGORY_FILTER}
		return ("Hisob nomining bir qismini yozing:", None, new_state, None)
	cat = _find_by_label(categories, text)
	if not cat:
		keyboard = [*_rows([c["label"] for c in categories]), [BTN_OTHER]]
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
		keyboard = [*_rows([d["label"] for d in deals]), [BTN_SKIP_DEAL]]
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
			keyboard = [*_rows([d["label"] for d in deals]), [BTN_SKIP_DEAL]]
			return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", keyboard, state, None)
		new_state = {**state, "deal": deal["name"]}
	leaf = new_state["sub_kassa"]
	new_state["step"] = STEP_CHIQIM_AMOUNT
	return (f"Summani kiriting ({leaf['currency']}):", None, new_state, None)


def _handle_chiqim_amount(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	leaf = state["sub_kassa"]
	new_state = {**state, "step": STEP_CHIQIM_MEMO, "amount": amt, "amount_raw": text.strip()}
	reply = f"{_echo_amount(amt, leaf['currency'])}\n\nIzoh (majburiy):"
	return (reply, _izoh_keyboard(ctx), new_state, None)


def _handle_chiqim_memo(state: dict, text: str, ctx: dict):
	def _confirm(new_state: dict, ctx: dict):
		new_state = {**new_state, "step": STEP_CHIQIM_CONFIRM}
		return (_chiqim_confirm_text(new_state, ctx), CONFIRM_KEYBOARD, new_state, None)

	return _mandatory_memo_step(state, text, ctx, _confirm)


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
_ARROW = "→"


def _konv_direction_pairs(leaves: list[dict]) -> list[tuple[dict, dict]]:
	"""Every ordered pair of DISTINCT leaves (by account) of a kassa —
	INCLUDING same-currency pairs (e.g. UZS<->PK). n leaves -> n*(n-1) pairs."""
	pairs: list[tuple[dict, dict]] = []
	for src in leaves:
		for tgt in leaves:
			if src["account"] == tgt["account"]:
				continue
			pairs.append((src, tgt))
	return pairs


def _konv_direction_label(src: dict, tgt: dict) -> str:
	return f"{src['label']} {_ARROW} {tgt['label']}"


def _konv_direction_keyboard(leaves: list[dict]) -> list[list[str]]:
	labels = [_konv_direction_label(src, tgt) for src, tgt in _konv_direction_pairs(leaves)]
	return _chunk(labels, 2)


def _konv_direction_text(ctx: dict, kassa: str | None) -> str:
	header = _qoldiq_header(ctx, kassa)
	if header:
		return f"{header}\n\nYo'nalishni tanlang:"
	return "Yo'nalishni tanlang:"


def _handle_konv_direction(state: dict, text: str, ctx: dict):
	leaves = _leaves_for_kassa(ctx, state.get("kassa"))
	pairs = _konv_direction_pairs(leaves)
	match = None
	for src, tgt in pairs:
		if _konv_direction_label(src, tgt) == text:
			match = (src, tgt)
			break
	if not match:
		return (
			"Noto'g'ri tanlov. Ro'yxatdan tanlang:",
			_konv_direction_keyboard(leaves),
			state,
			None,
		)
	src, tgt = match
	new_state = {**state, "step": STEP_KONV_GIVEN, "src": src, "tgt": tgt}
	if src["currency"] == tgt["currency"]:
		reply = f"Qancha o'tkazasiz? ({src['currency']})"
	else:
		reply = f"Qancha berdingiz? ({src['currency']})"
	return (reply, None, new_state, None)


def _konv_cbu_accept_label(computed: float, currency: str) -> str:
	return f"{BTN_KONV_CBU_PREFIX}{format_amount(computed, currency)}"


def _handle_konv_given(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	src, tgt = state["src"], state["tgt"]
	echo = _echo_amount(amt, src["currency"])
	if src["currency"] == tgt["currency"]:
		# Same-currency Konvertatsiya = a straight own-channel move. No CBU
		# assist, no separate "received" ask — given IS received.
		new_state = {
			**state,
			"step": STEP_KONV_MEMO,
			"given": amt,
			"received": amt,
			"given_raw": text.strip(),
		}
		reply = f"{echo}\n\nIzoh (majburiy):"
		return (reply, _izoh_keyboard(ctx), new_state, None)
	cbu = (ctx or {}).get("cbu") or {}
	rate = cbu.get("rate")
	pair_ok = {src["currency"], tgt["currency"]} == {"USD", "UZS"}
	if rate and pair_ok:
		computed = amt * rate if src["currency"] == "USD" else (amt / rate if rate else None)
		if computed and computed > 0:
			new_state = {**state, "step": STEP_KONV_CBU_CHOICE, "given": amt, "given_raw": text.strip(), "_cbu_computed": computed}
			accept_label = _konv_cbu_accept_label(computed, tgt["currency"])
			keyboard = [[accept_label], [BTN_KONV_MANUAL]]
			reply = (
				f"{echo}\n\nCBU kursi: 1 USD = {format_amount(rate, 'UZS')} ({cbu.get('date') or ''})\n\n"
				"Qabul qilingan summani tanlang:"
			)
			return (reply, keyboard, new_state, None)
	new_state = {**state, "step": STEP_KONV_RECEIVED, "given": amt, "given_raw": text.strip()}
	reply = f"{echo}\n\nQancha oldingiz? ({tgt['currency']})"
	return (reply, None, new_state, None)


def _handle_konv_cbu_choice(state: dict, text: str, ctx: dict):
	computed = state.get("_cbu_computed")
	tgt = state["tgt"]
	accept_label = _konv_cbu_accept_label(computed, tgt["currency"]) if computed is not None else None
	if computed is not None and text == accept_label:
		new_state = {k: v for k, v in state.items() if k != "_cbu_computed"}
		new_state["received"] = computed
		new_state["step"] = STEP_KONV_MEMO
		return ("Izoh (majburiy):", _izoh_keyboard(ctx), new_state, None)
	if text == BTN_KONV_MANUAL:
		new_state = {k: v for k, v in state.items() if k != "_cbu_computed"}
		new_state["step"] = STEP_KONV_RECEIVED
		return (f"Qancha oldingiz? ({tgt['currency']})", None, new_state, None)
	keyboard = [[accept_label], [BTN_KONV_MANUAL]] if accept_label else [[BTN_KONV_MANUAL]]
	return ("Tanlang:", keyboard, state, None)


def _handle_konv_received(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	tgt = state["tgt"]
	new_state = {**state, "step": STEP_KONV_MEMO, "received": amt, "received_raw": text.strip()}
	reply = f"{_echo_amount(amt, tgt['currency'])}\n\nIzoh (majburiy):"
	return (reply, _izoh_keyboard(ctx), new_state, None)


def _handle_konv_memo(state: dict, text: str, ctx: dict):
	def _confirm(new_state: dict, ctx: dict):
		new_state = {**new_state, "step": STEP_KONV_CONFIRM}
		return (_konv_confirm_text(new_state), CONFIRM_KEYBOARD, new_state, None)

	return _mandatory_memo_step(state, text, ctx, _confirm)


def _handle_konv_confirm(state: dict, text: str, ctx: dict):
	if text != BTN_CONFIRM:
		return (_konv_confirm_text(state), CONFIRM_KEYBOARD, state, None)
	src, tgt = state["src"], state["tgt"]
	action = {
		"type": "transfer",
		"from": src["account"],
		"to": tgt["account"],
		"from_amount": state["given"],
		"memo": state.get("memo"),
	}
	if src["currency"] != tgt["currency"]:
		# Cross-currency conversion — carry to_amount so bot.py composes the
		# "Konvertatsiya CCY→CCY @rate" memo. Same-currency moves omit it, so
		# the memo reads as a plain transfer, matching Kirim/K2K.
		action["to_amount"] = state["received"]
	new_state = _menu_state(state.get("kassa"), None)
	return ("⏳ Amal bajarilmoqda...", MENU_KEYBOARD, new_state, action)


# --- Kassadan kassaga ---------------------------------------------------------- #
_K2K_NO_OTHER_KASSA_TEXT = (
	"Boshqa kassa yo'q — bu amal faqat boshqa kassaga o'tkazish uchun. "
	"Konvertatsiya orqali hisoblar orasida ko'chiring."
)


def _k2k_source_text(ctx: dict, kassa: str | None) -> str:
	header = _qoldiq_header(ctx, kassa)
	if header:
		return f"{header}\n\nQaysi hisobdan yuborasiz?"
	return "Qaysi hisobdan yuborasiz?"


def _k2k_target_text(kassa: str | None, src: dict, ctx: dict) -> str:
	lines = [f"Yuboruvchi: {kassa} / {src['currency']}"]
	balance_line = _leaf_balance_line(ctx, src)
	if balance_line:
		lines.append(balance_line)
	lines.append("")
	lines.append("Qaysi kassaga o'tkazasiz?")
	return "\n".join(lines)


def _handle_k2k_source(state: dict, text: str, ctx: dict):
	kassa = state.get("kassa")
	leaves = _leaves_for_kassa(ctx, kassa)
	src = _find_by_label(leaves, text)
	if not src:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([l["label"] for l in leaves]), state, None)
	targets = _targets_other_kassas_same_currency(ctx, kassa, src["currency"])
	if not targets:
		# Single-kassa case (e.g. Mikas): K2K is only for moving between
		# DIFFERENT kassas — own-channel moves belong to Konvertatsiya.
		reset_state = _menu_state(kassa, state.get("posting_date"))
		return (_K2K_NO_OTHER_KASSA_TEXT, MENU_KEYBOARD, reset_state, None)
	new_state = {**state, "step": STEP_K2K_TARGET, "src": src}
	return (_k2k_target_text(kassa, src, ctx), _rows([t["label"] for t in targets]), new_state, None)


def _handle_k2k_target(state: dict, text: str, ctx: dict):
	src = state["src"]
	kassa = state.get("kassa")
	targets = _targets_other_kassas_same_currency(ctx, kassa, src["currency"])
	tgt = _find_by_label(targets, text)
	if not tgt:
		return ("Noto'g'ri tanlov. Ro'yxatdan tanlang:", _rows([t["label"] for t in targets]), state, None)
	new_state = {**state, "step": STEP_K2K_AMOUNT, "tgt": tgt}
	return ("Summani kiriting:", None, new_state, None)


def _handle_k2k_amount(state: dict, text: str, ctx: dict):
	amt = parse_amount(text)
	if amt is None:
		return ("Noto'g'ri summa. Qayta kiriting:", None, state, None)
	src = state["src"]
	new_state = {**state, "step": STEP_K2K_MEMO, "amount": amt, "amount_raw": text.strip()}
	reply = f"{_echo_amount(amt, src['currency'])}\n\nIzoh (majburiy):"
	return (reply, _izoh_keyboard(ctx), new_state, None)


def _handle_k2k_memo(state: dict, text: str, ctx: dict):
	def _confirm(new_state: dict, ctx: dict):
		new_state = {**new_state, "step": STEP_K2K_CONFIRM}
		return (_k2k_confirm_text(new_state), CONFIRM_KEYBOARD, new_state, None)

	return _mandatory_memo_step(state, text, ctx, _confirm)


def _handle_k2k_confirm(state: dict, text: str, ctx: dict):
	if text != BTN_CONFIRM:
		return (_k2k_confirm_text(state), CONFIRM_KEYBOARD, state, None)
	action = {
		"type": "transfer",
		"from": state["src"]["account"],
		"to": state["tgt"]["account"],
		"from_amount": state["amount"],
		"memo": state.get("memo"),
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
		"(bitta amaldan keyin bugungi sanaga qaytadi).\n\n" + _menu_text(new_state, ctx)
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
	STEP_KONV_DIRECTION: _handle_konv_direction,
	STEP_KONV_GIVEN: _handle_konv_given,
	STEP_KONV_CBU_CHOICE: _handle_konv_cbu_choice,
	STEP_KONV_RECEIVED: _handle_konv_received,
	STEP_KONV_MEMO: _handle_konv_memo,
	STEP_KONV_CONFIRM: _handle_konv_confirm,
	STEP_K2K_SOURCE: _handle_k2k_source,
	STEP_K2K_TARGET: _handle_k2k_target,
	STEP_K2K_AMOUNT: _handle_k2k_amount,
	STEP_K2K_MEMO: _handle_k2k_memo,
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
