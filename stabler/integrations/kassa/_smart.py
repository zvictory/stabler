"""Smart free-text entry parser for KassaBot v2 (shadow mode) — Frappe-free.

Turns a kassir's Uzbek free-text ("100mln aldim Aliyevdan ijara uchun",
"100d berdim", "500d ni somga aylantirdim 12900 kurs") into a structured
shadow-entry intent: op + amount + currency + counterparty + purpose + rate.

Design principles (mirrors _flow.py):
- Pure + unit-testable; no frappe import. Reuses _flow.parse_amount for the
  numeric/word-number core.
- NEVER guesses on ambiguity. When a required slot is missing or unclear, it
  returns exactly ONE targeted Uzbek question (`question`) — the bot asks that
  instead of the old kasa/miktar step chain.
- Always preserves the raw text (caller stores raw_text alongside parsed_json).

Currency shorthand: s/som/so'm -> UZS, d/dollar/$ -> USD, e/euro/€ -> EUR.
Multipliers: k/ming -> 1e3, m/mln -> 1e6, mlrd -> 1e9 (+ Cyrillic).
"Dollar aldim" (buying foreign) -> konversiya; source kassa asked if ambiguous.
"""

from __future__ import annotations

import re

from ._flow import _normalize_apostrophes, parse_amount

# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #
_CCY_WORDS = [
    ("USD", ("dollar", "dollor", "usd")),
    ("EUR", ("euro", "yevro", "eur")),
    ("UZS", ("so'm", "som", "sum", "uzs")),
]
_CCY_SYMBOL = {"$": "USD", "€": "EUR"}
_CCY_LETTER = {"d": "USD", "e": "EUR", "s": "UZS"}

_MULT = {
    "k": 1_000, "ming": 1_000, "минг": 1_000,
    "m": 1_000_000, "mln": 1_000_000, "million": 1_000_000, "milion": 1_000_000, "млн": 1_000_000,
    "mlrd": 1_000_000_000, "milliard": 1_000_000_000, "млрд": 1_000_000_000,
}
_MULT_RE = "|".join(sorted((re.escape(k) for k in _MULT), key=len, reverse=True))

# --------------------------------------------------------------------------- #
# Intent keywords
# --------------------------------------------------------------------------- #
_KONV = ("konvert", "konversiya", "almashtir", "ayirboshla", "valyuta", "aylantir", "aylashtir", "ayr")
_CHIQIM = ("chiqdi", "chiqim", "berdim", "berdik", "to'ladim", "tuladim", "to'lov", "tulov",
           "masraf", "xarajat", "sarfladim", "sarf", "chiqdi")
_K2K = ("o'tkaz", "otkaz", "ko'chir", "kochir", "kassaga", "kassadan")
_KIRIM = ("kirdi", "kirim", "keldi", "tushdi", "qabul", "olindi", "kirdik")
_BUY = ("oldim", "aldim", "sotib", "sotvoldim", "sotib oldim")

_OPS = ("kirim", "chiqim", "konversiya", "kassalararo")


def _norm(text: str) -> str:
    return _normalize_apostrophes((text or "").lower()).strip()


def detect_currency(text: str) -> str | None:
    """Detect a currency from free text. None when absent."""
    t = _norm(text)
    for sym, ccy in _CCY_SYMBOL.items():
        if sym in t:
            return ccy
    for ccy, words in _CCY_WORDS:
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", t):
                return ccy
    # single-letter suffix: attached to the number (100d, 500e) or standalone
    # after a multiplier (100ming s)
    m = re.search(r"\d\s*([dse])\b", t) or re.search(r"\b([dse])\b", t)
    if m:
        return _CCY_LETTER[m.group(1)]
    return None


def _strip_currency(t: str) -> str:
    for sym in _CCY_SYMBOL:
        t = t.replace(sym, " ")
    for _ccy, words in _CCY_WORDS:
        for w in words:
            t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
    t = re.sub(r"\b[dse]\b", " ", t)
    return t


_DIGIT_AMT_RE = re.compile(
    rf"(\d[\d\s.,]*?)\s*({_MULT_RE})?(?=\s|$|[a-zʼ'])", re.IGNORECASE
)


def extract_amount(text: str) -> float | None:
    """Amount from free text. Digit-led ('100mln', '1,5 mln') via regex;
    pure word-number messages ('besh yuz ming') via _flow.parse_amount."""
    t = _strip_currency(_norm(text))
    m = _DIGIT_AMT_RE.search(t)
    if m and re.search(r"\d", m.group(1) or ""):
        num_raw = re.sub(r"\s+", "", m.group(1))
        if "," in num_raw and "." in num_raw:
            return None
        num_raw = num_raw.replace(",", ".")
        try:
            num = float(num_raw)
        except ValueError:
            return None
        if num <= 0:
            return None
        mult = _MULT.get((m.group(2) or "").lower(), 1)
        return num * mult
    # no digits -> try a pure word-number (missing-slot answers like "besh yuz ming")
    return parse_amount(t.strip())


def detect_op(text: str, currency: str | None = None) -> str | None:
    """kirim / chiqim / konversiya / kassalararo — priority-ordered, never guesses."""
    t = _norm(text)

    def has(words):
        return any(re.search(rf"\b{re.escape(w)}", t) for w in words)

    if has(_KONV):
        return "konversiya"
    if has(_K2K):
        return "kassalararo"
    if has(_CHIQIM):
        return "chiqim"
    # buying a foreign currency == conversion (UZS/PK -> USD/EUR)
    if currency in ("USD", "EUR") and has(_BUY):
        return "konversiya"
    if has(_KIRIM) or has(_BUY):
        return "kirim"
    return None


def extract_rate(text: str) -> float | None:
    """'12900 kurs' / 'kurs 12900' -> 12900.0."""
    t = _norm(text)
    m = re.search(r"(\d[\d\s.,]*)\s*kurs\b", t) or re.search(r"\bkurs\s*(\d[\d\s.,]*)", t)
    if not m:
        return None
    raw = re.sub(r"\s+", "", m.group(1)).replace(",", ".")
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def parse_konv_amount_rate(text: str):
    """For the button-driven conversion flow: the kassir picked a direction, then
    types '100 12600' / '100$ 12600' / '500 11990' — first number is the amount,
    second is the exchange rate. Multipliers (mln/ming) apply to the amount;
    currency symbols/letters are ignored. Returns (amount, rate); either may be
    None when the message doesn't carry it yet."""
    t = _strip_currency(_norm(text or ""))
    vals: list[float] = []
    for num, mult in _DIGIT_AMT_RE.findall(t):
        if not re.search(r"\d", num or ""):
            continue
        raw = re.sub(r"\s+", "", num).replace(",", ".")
        if "," in num and "." in num:
            continue
        try:
            f = float(raw)
        except ValueError:
            continue
        if f <= 0:
            continue
        vals.append(f * _MULT.get((mult or "").lower(), 1))
    amount = vals[0] if vals else None
    rate = vals[1] if len(vals) >= 2 else None
    return amount, rate


_CP_STOP = {"uchun", "ga", "dan", "kurs", "som", "dollar", "euro", "pul", "berdim", "oldim", "aldim"}


def extract_counterparty(text: str, op: str | None) -> str | None:
    """Kimdan — the name token before 'dan' (from), attached OR space-separated
    ('Aliyevdan' and 'Aliyev dan' both yield 'Aliyev'). '…ga' (to/for) is treated
    as purpose, and kassa words (naqd/karta/dollar…) are never taken as a name."""
    t = _norm(text)
    m = re.search(r"\b([a-zA-Zʼ'Ѐ-ӿ]{3,})\s*dan\b", t)
    if m:
        cand = m.group(1)
        if (cand not in _CP_STOP and cand not in _KONV and cand not in _CHIQIM
                and detect_kassa(cand) is None):
            return cand.capitalize()
    return None


def extract_purpose(text: str) -> str | None:
    """Izoh — the word(s) before 'uchun', or after 'ga' when it's a purpose."""
    t = _norm(text)
    m = re.search(r"\b([a-zA-Zʼ'Ѐ-ӿ ]{3,}?)\s*uchun\b", t)
    if m:
        cand = m.group(1).strip().split()[-1]
        if cand not in _CP_STOP:
            return cand
    # "...ijaraga", "...transportga" -> purpose is the stem before 'ga'
    m2 = re.search(r"\b([a-zA-Zʼ'Ѐ-ӿ]{4,})ga\b", t)
    if m2:
        stem = m2.group(1)
        if stem not in _CP_STOP and stem not in _KONV:
            return stem
    return None


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
_Q = {
    "op": "Bu kirim, chiqim, konvertatsiya yoki kassalararomi?",
    "amount": "Qancha? (masalan: 100mln, 100d, 100ming s)",
    "currency": "Qaysi kassa? \U0001F7E6 Som / \U0001F7E7 PK / \U0001F7E9 USD",
    "konv_source": "Qaysi kassadan? \U0001F7E6 Som / \U0001F7E7 PK",
    "kirim_from": "Kimdan oldingiz?",
    "chiqim_to": "Kimga / nima uchun?",
}


def parse_entry(text: str, ctx: dict | None = None) -> dict:
    """Parse a kassir free-text message into a structured shadow-entry intent.

    Returns a dict with op/amount/currency/counterparty/purpose/rate/raw_text and,
    when something required is missing/ambiguous, a single Uzbek `question` plus
    the `missing` slot name. `ready` is True only when nothing needs asking.
    """
    raw = text or ""
    currency = detect_currency(raw)
    amount = extract_amount(raw)
    op = detect_op(raw, currency)
    res = {
        "op": op,
        "amount": amount,
        "currency": currency,
        "counterparty": extract_counterparty(raw, op),
        "purpose": extract_purpose(raw),
        "rate": extract_rate(raw),
        "raw_text": raw,
        "missing": None,
        "question": None,
        "ready": False,
    }

    def need(slot):
        res["missing"] = slot
        res["question"] = _Q[slot]
        return res

    if not op:
        return need("op")
    if amount is None:
        return need("amount")
    if op == "konversiya":
        # Conversion needs a currency; buying foreign (USD/EUR) also needs the
        # source kassa (Som/PK). Cross-currency two-leg details (given/received,
        # rate) are refined by the bot's conversion sub-flow afterwards.
        if currency is None:
            return need("currency")
        if currency in ("USD", "EUR") and not res["counterparty"] and not (ctx or {}).get("konv_source"):
            return need("konv_source")
    else:
        # No explicit currency on a kirim/chiqim/transfer -> default to UZS
        # (som is base; foreign is written with d/dollar). Don't ask.
        if currency is None:
            currency = "UZS"
            res["currency"] = "UZS"
        if op == "kirim" and not res["counterparty"]:
            return need("kirim_from")
        if op == "chiqim" and not res["counterparty"] and not res["purpose"]:
            return need("chiqim_to")

    res["ready"] = True
    return res


# --------------------------------------------------------------------------- #
# Kassa channels + multi-leg parsing (WP-S3b)
# "Mijozdan 2 mln naqd, 3 mln karta va 500 dollar oldim" -> 3 legs, 1 kirim.
# Kassa keywords: naqd/som->Nakit(UZS), karta/plastik/pk->PK(UZS), dollar->USD.
# Letter suffixes for balances/legs: s->Nakit, p->PK, d->USD.
# --------------------------------------------------------------------------- #
KASSA_CCY = {"nakit": "UZS", "pk": "UZS", "usd": "USD"}
_KASSA_WORDS = {
    "nakit": ("naqd", "naxt", "nakit", "som", "so'm", "sum", "kesh", "cash"),
    "pk": ("karta", "kartaga", "plastik", "plastic", "pk"),
    "usd": ("dollar", "dollor", "usd", "valyuta"),
}
_KASSA_LETTER = {"s": "nakit", "p": "pk", "d": "usd"}
_SEG_SPLIT = re.compile(r"\s*,\s*|\s+va\s+|\s+и\s+|[\n;]+", re.IGNORECASE)


def detect_kassa(text: str) -> str | None:
    """Which of the 3 kassas a segment names: nakit / pk / usd (or None)."""
    t = _norm(text)
    for kid, words in _KASSA_WORDS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", t):
                return kid
    m = re.search(r"\d\s*([spd])\b", t) or re.search(r"\b([spd])\b", t)
    if m:
        return _KASSA_LETTER[m.group(1)]
    return None


_KASSA_DIR_WORDS = (
    [(w, k) for k, ws in _KASSA_WORDS.items() for w in ws]
    + [(lt, k) for lt, k in _KASSA_LETTER.items()]
)


def detect_transfer_dirs(text: str):
    """(from_kassa, to_kassa) from directional text: '…dan' = from, '…ga' = to.
    'naqddan pk ga' -> ('nakit','pk'); 'somdan dollarga' -> ('nakit','usd')."""
    t = _norm(text)
    frm = to = None
    for w, k in _KASSA_DIR_WORDS:
        if frm is None and re.search(rf"\b{re.escape(w)}dan\b", t):
            frm = k
        if to is None and re.search(rf"\b{re.escape(w)}\s*ga\b", t):
            to = k
    return frm, to


def parse_legs(text: str) -> list[dict]:
    """Split a message into amount+kassa legs. One kirim/chiqim can move money
    into several kassas at once ("2 mln naqd, 3 mln karta va 500 dollar")."""
    legs = []
    for seg in _SEG_SPLIT.split(text or ""):
        amt = extract_amount(seg)
        if amt is None:
            continue
        kid = detect_kassa(seg)
        ccy = KASSA_CCY[kid] if kid else detect_currency(seg)
        legs.append({"amount": amt, "kassa": kid, "currency": ccy})
    return legs


def parse_message(text: str, op: str | None = None, ctx: dict | None = None) -> dict:
    """Bot entry point. `op` is the button the kassir picked first (kirim/chiqim/
    konversiya/kassalararo); the free text fills amount(s) + kassa(s) + slots.
    kirim/chiqim support MULTIPLE legs; konv/kassalararo delegate to parse_entry."""
    raw = text or ""
    if not op:
        op = detect_op(raw, detect_currency(raw))
    res = {
        "op": op,
        "counterparty": extract_counterparty(raw, op),
        "purpose": extract_purpose(raw),
        "rate": extract_rate(raw),
        "legs": [],
        "raw_text": raw,
        "missing": None,
        "question": None,
        "ready": False,
    }

    def need(slot):
        res["missing"] = slot
        res["question"] = _Q[slot]
        return res

    if not op:
        return need("op")

    if op in ("kirim", "chiqim"):
        legs = parse_legs(raw)
        if not legs:
            return need("amount")
        for leg in legs:
            if leg["kassa"] is None:
                leg["kassa"] = "nakit"       # default: UZS cash unless PK/USD named
                leg["currency"] = "UZS"
            elif leg["currency"] is None:
                leg["currency"] = KASSA_CCY[leg["kassa"]]
        res["legs"] = legs
        if op == "kirim" and not res["counterparty"]:
            return need("kirim_from")
        if op == "chiqim" and not res["counterparty"] and not res["purpose"]:
            return need("chiqim_to")
        res["ready"] = True
        return res

    frm, to = detect_transfer_dirs(raw)

    if op == "kassalararo":
        # "1mln naqddan pk ga" -> from nakit, to pk, no questions asked.
        res["from"] = frm
        res["to"] = to
        res["amount"] = extract_amount(raw)
        return res

    # konversiya — single (USD) amount; pre-fill direction/source from the text.
    r = parse_entry(raw, ctx)
    r["op"] = "konversiya"
    if to == "usd":
        r["dir"] = "buy"
        if frm and frm != "usd" and not r.get("source"):
            r["source"] = frm
    elif frm == "usd":
        r["dir"] = "sell"
        if to and to != "usd" and not r.get("target"):
            r["target"] = to
    if r.get("amount") is not None:
        r["legs"] = [{"amount": r["amount"], "kassa": "usd", "currency": r.get("currency")}]
    return r
