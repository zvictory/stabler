"""Smart free-text entry parser for KassaBot v2 (shadow mode) — Frappe-free.

Turns a kassir's Uzbek free-text ("100mln aldim Aliyevdan ijara uchun",
"100d berdim", "500d ni somga aylantirdim 12900 kurs") into a structured
shadow-entry intent: op + amount + currency + counterparty + purpose + rate.

Design principles (mirrors _flow.py):
- Pure + unit-testable; no frappe import. Reuses _flow.parse_amount for the
  numeric/word-number core.
- Context-Aware Extraction: In Kirim/Chiqim mode, if the user types an amount
  along with a remaining name/reason (e.g. "650d ismoil"), automatically infers
  the counterparty/purpose without requiring "-dan"/"-uchun" suffixes. The amount
  is the divider: what stands to its left is who/what, to its right is the note,
  and BOTH keep every word they were typed with — a note is a sentence, and the
  ledger renders this field rather than raw_text.
- NEVER guesses on ambiguity. When a required slot is missing or unclear, it
  returns exactly ONE targeted Uzbek question (`question`) — the bot asks that
  instead of the old kasa/miktar step chain.
- Always preserves the raw text (caller stores raw_text alongside parsed_json).

Currency shorthand: s/som/so'm -> UZS, d/dollar/$ -> USD, e/euro/€ -> EUR.
Multipliers: k/ming -> 1e3, m/mln -> 1e6, mlrd -> 1e9.
Uzbek ships in two scripts and the kassirs mix them, so every vocabulary here —
currency, kassa, operation keywords, the dan/uchun/ga/kurs suffixes and the
single-letter shorthands (179100с, 100д) — is listed in Latin AND Cyrillic.
"Dollar aldim" (buying foreign) -> konversiya; source kassa asked if ambiguous.
"""

from __future__ import annotations

import re

from ._flow import _normalize_apostrophes, parse_amount

# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #
_CCY_WORDS = [
	("USD", ("dollar", "dollor", "usd", "доллар", "долл")),
	("EUR", ("euro", "yevro", "eur", "евро", "еуро")),
	("UZS", ("so'm", "som", "sum", "uzs", "сўм", "сум", "сом")),
]
_CCY_SYMBOL = {"$": "USD", "€": "EUR"}
_CCY_LETTER = {"d": "USD", "e": "EUR", "s": "UZS", "д": "USD", "е": "EUR", "с": "UZS"}
_CCY_LETTER_RE = "".join(_CCY_LETTER)

_MULT = {
	"k": 1_000,
	"ming": 1_000,
	"минг": 1_000,
	"m": 1_000_000,
	"mln": 1_000_000,
	"million": 1_000_000,
	"milion": 1_000_000,
	"млн": 1_000_000,
	"mlrd": 1_000_000_000,
	"milliard": 1_000_000_000,
	"млрд": 1_000_000_000,
}
_MULT_RE = "|".join(sorted((re.escape(k) for k in _MULT), key=len, reverse=True))

# --------------------------------------------------------------------------- #
# Intent keywords
# --------------------------------------------------------------------------- #
_KONV = (
	"konvert",
	"konversiya",
	"almashtir",
	"ayirboshla",
	"valyuta",
	"aylantir",
	"aylashtir",
	"ayr",
	"конверт",
	"конверсия",
	"алмаштир",
	"айирбошла",
	"валюта",
	"айлантир",
	"айлаштир",
)
_CHIQIM = (
	"chiqdi",
	"chiqim",
	"berdim",
	"berdik",
	"to'ladim",
	"tuladim",
	"to'lov",
	"tulov",
	"masraf",
	"xarajat",
	"sarfladim",
	"sarf",
	"chiqdi",
	"чиқди",
	"чикди",
	"чиқим",
	"чиким",
	"бердим",
	"бердик",
	"тўладим",
	"туладим",
	"тўлов",
	"тулов",
	"масраф",
	"харажат",
	"сарфладим",
	"сарф",
)
_K2K = (
	"o'tkaz",
	"otkaz",
	"ko'chir",
	"kochir",
	"kassaga",
	"kassadan",
	"ўтказ",
	"утказ",
	"кўчир",
	"кучир",
	"кассага",
	"кассадан",
)
_KIRIM = (
	"kirdi",
	"kirim",
	"keldi",
	"tushdi",
	"qabul",
	"olindi",
	"kirdik",
	"кирди",
	"кирим",
	"кирдик",
	"келди",
	"тушди",
	"қабул",
	"кабул",
	"олинди",
)
_BUY = ("oldim", "aldim", "sotib", "sotvoldim", "sotib oldim", "олдим", "алдим", "сотиб", "сотволдим")

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
	m = re.search(rf"\d\s*([{_CCY_LETTER_RE}])\b", t) or re.search(rf"\b([{_CCY_LETTER_RE}])\b", t)
	if m:
		return _CCY_LETTER[m.group(1)]
	return None


def _strip_currency(t: str) -> str:
	for sym in _CCY_SYMBOL:
		t = t.replace(sym, " ")
	for _ccy, words in _CCY_WORDS:
		for w in words:
			t = re.sub(rf"\b{re.escape(w)}\b", " ", t, flags=re.IGNORECASE)
	t = re.sub(rf"\b[{_CCY_LETTER_RE}]\b", " ", t, flags=re.IGNORECASE)
	return t


# Letters that may carry a name, a note word or a currency/kassa suffix — Latin
# and Cyrillic alike, because the kassirs write Uzbek in both scripts.
_WORD_CHARS = "a-zA-Zʼ'Ѐ-ӿ"

# Uzbek case suffixes the parser keys on, in both scripts.
_DAN = "(?:dan|дан)"
_GA = "(?:ga|га)"
_UCHUN = "(?:uchun|учун)"
_KURS = "(?:kurs|курс)"

_DIGIT_AMT_RE = re.compile(rf"(\d[\d\s.,]*?)\s*({_MULT_RE})?(?=\s|$|[{_WORD_CHARS}])", re.IGNORECASE)


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
	m = re.search(rf"(\d[\d\s.,]*)\s*{_KURS}\b", t) or re.search(rf"\b{_KURS}\s*(\d[\d\s.,]*)", t)
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
	second is the exchange rate."""
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


_CP_STOP = {
	"uchun",
	"ga",
	"dan",
	"kurs",
	"som",
	"dollar",
	"euro",
	"pul",
	"berdim",
	"oldim",
	"aldim",
	"kirim",
	"chiqim",
	"va",
	"и",
	"yana",
	"учун",
	"га",
	"дан",
	"курс",
	"сўм",
	"сум",
	"доллар",
	"евро",
	"пул",
	"бердим",
	"олдим",
	"алдим",
	"кирим",
	"чиқим",
	"ва",
	"яна",
}


def _is_noise(core: str) -> bool:
	"""A token that can be neither a name nor part of a note: too short, a stop
	word, an operation keyword, or the name of a kassa."""
	low = core.lower()
	return (
		len(core) < 3
		or low in _CP_STOP
		or low in _KONV
		or low in _CHIQIM
		or low in _KIRIM
		or detect_kassa(low) is not None
	)


def _phrase(segment: str) -> str | None:
	"""Trim noise off BOTH ENDS of a segment and hand back what the kassir wrote
	in between, verbatim.

	Edge-only on purpose: filtering token by token would silently delete short
	words from the middle of a sentence, turning "чой ва нон" into "чой нон".
	"""
	toks = [(tok, re.sub(rf"[^{_WORD_CHARS}]", "", tok)) for tok in segment.split()]
	while toks and _is_noise(toks[0][1]):
		toks.pop(0)
	while toks and _is_noise(toks[-1][1]):
		toks.pop()
	return " ".join(tok for tok, _ in toks).strip(" -–—:,") or None


def _as_name(phrase: str | None) -> str | None:
	"""Capitalise a name typed all-lowercase ("ismoil" -> "Ismoil"); leave the
	kassir's own capitalisation alone ("Бек Офис")."""
	if not phrase:
		return None
	return phrase[0].upper() + phrase[1:] if phrase.islower() else phrase


def _fields(text: str, op: str | None) -> tuple[str | None, str | None]:
	"""(counterparty, purpose) from one free-text message.

	Explicit suffixes win: "<name>dan" names the payer, "<what> uchun" / "<what>ga"
	names the reason. Otherwise the amount splits the message — what the kassir
	typed to the LEFT of it is who/what, what they typed to the RIGHT is the note.

	Both keep every word. A note is a sentence ("Чой ичгани нарса олиб келинди"),
	and the shadow ledger renders THIS field, not raw_text — so cutting it at the
	first space destroys the only structured record of what the money was for.
	"""
	s = _normalize_apostrophes(text or "")  # 1:1 char swap — spans stay valid
	t = _norm(s)

	cp = None
	m = re.search(rf"\b([{_WORD_CHARS}]{{3,}})\s*{_DAN}\b", t)
	if m:
		cand = m.group(1)
		if cand not in _CP_STOP and cand not in _KONV and cand not in _CHIQIM and detect_kassa(cand) is None:
			cp = cand.capitalize()

	# The suffix rules run on the amount-free text: in "100mln ijara uchun" the
	# capture would otherwise start inside the number and yield "mln ijara". The
	# amount becomes a NEWLINE, not a space — the multi-word 'uchun' class matches
	# spaces, so a blank would let it reach back across the amount and swallow the
	# payee too ("Hojaga 350 ming s ijara haqi uchun" -> "Hojaga ijara haqi").
	bare = _DIGIT_AMT_RE.sub("\n", _strip_currency(s))
	purpose = None
	m = re.search(rf"\b([{_WORD_CHARS} ]{{3,}}?)\s*{_UCHUN}\b", bare, re.IGNORECASE)
	if m:
		purpose = _phrase(m.group(1))
	if purpose is None:
		m = re.search(rf"\b([{_WORD_CHARS}]{{4,}}){_GA}\b", bare, re.IGNORECASE)
		stem = m.group(1) if m else None
		# "картага"/"kartaga" is a destination kassa, not a reason — the same
		# guard the 'dan' rule already carries.
		if stem and stem.lower() not in _CP_STOP and stem.lower() not in _KONV and detect_kassa(stem) is None:
			purpose = stem

	spans = [
		m.span()
		for m in _DIGIT_AMT_RE.finditer(s)
		if re.search(r"\d", m.group(1) or "")
		and not re.match(rf"[{_WORD_CHARS}]", s[m.start() - 1] if m.start() else " ")
	]
	head = _phrase(s[: spans[0][0]]) if spans else None
	tail = _phrase(s[spans[-1][1] :]) if spans else _phrase(s)

	if op == "kirim":
		if cp is None:
			cp = _as_name(head or tail)
	elif op == "chiqim":
		if purpose is None:
			purpose = tail or head
		if cp is None and head and tail:
			cp = _as_name(head)

	return cp, purpose


def extract_counterparty(text: str, op: str | None) -> str | None:
	"""Kimdan — the name before 'dan'/'дан', else (Kirim/Chiqim) the words the
	kassir typed on the amount's left."""
	return _fields(text, op)[0]


def extract_purpose(text: str, op: str | None = None) -> str | None:
	"""Izoh — the words before 'uchun'/'учун', the stem before 'ga'/'га', else
	(Chiqim/Kirim) the words the kassir typed on the amount's right."""
	return _fields(text, op)[1]


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
_Q = {
	"op": "Bu kirim, chiqim, konvertatsiya yoki kassalararomi?",
	"amount": "Qancha? (masalan: 100mln, 100d, 100ming s)",
	"currency": "Qaysi kassa? \U0001f7e6 Som / \U0001f7e7 PK / \U0001f7e9 USD",
	"konv_source": "Qaysi kassadan? \U0001f7e6 Som / \U0001f7e7 PK",
	"kirim_from": "Kimdan oldingiz?",
	"chiqim_to": "Kimga / nima uchun?",
}


def parse_entry(text: str, ctx: dict | None = None) -> dict:
	"""Parse a kassir free-text message into a structured shadow-entry intent."""
	raw = text or ""
	currency = detect_currency(raw)
	amount = extract_amount(raw)
	op = detect_op(raw, currency)
	res = {
		"op": op,
		"amount": amount,
		"currency": currency,
		"counterparty": extract_counterparty(raw, op),
		"purpose": extract_purpose(raw, op),
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
		if currency is None:
			return need("currency")
		if currency in ("USD", "EUR") and not res["counterparty"] and not (ctx or {}).get("konv_source"):
			return need("konv_source")
	else:
		if currency is None:
			currency = "UZS"
			res["currency"] = "UZS"
		if op == "kirim" and not res["counterparty"]:
			return need("kirim_from")
		if op == "chiqim" and not res["counterparty"] and not res["purpose"]:
			return need("chiqim_to")

	res["ready"] = True
	return res


KASSA_CCY = {"nakit": "UZS", "pk": "UZS", "usd": "USD"}
_KASSA_WORDS = {
	"nakit": (
		"naqd",
		"naxt",
		"nakit",
		"som",
		"so'm",
		"sum",
		"kesh",
		"cash",
		"нақд",
		"нақт",
		"накит",
		"сўм",
		"сум",
		"сом",
		"кеш",
	),
	"pk": ("karta", "kartaga", "plastik", "plastic", "pk", "карта", "картага", "пластик", "пк"),
	"usd": ("dollar", "dollor", "usd", "valyuta", "доллар", "валюта"),
}
_KASSA_LETTER = {"s": "nakit", "p": "pk", "d": "usd", "с": "nakit", "п": "pk", "д": "usd"}
_KASSA_LETTER_RE = "".join(_KASSA_LETTER)
_SEG_SPLIT = re.compile(r"\s*,\s*|\s+va\s+|\s+ва\s+|\s+и\s+|[\n;]+", re.IGNORECASE)


def detect_kassa(text: str) -> str | None:
	"""Which of the 3 kassas a segment names: nakit / pk / usd (or None)."""
	t = _norm(text)
	for kid, words in _KASSA_WORDS.items():
		for w in words:
			if re.search(rf"\b{re.escape(w)}\b", t):
				return kid
	m = re.search(rf"\d\s*([{_KASSA_LETTER_RE}])\b", t) or re.search(rf"\b([{_KASSA_LETTER_RE}])\b", t)
	if m:
		return _KASSA_LETTER[m.group(1)]
	return None


_KASSA_DIR_WORDS = [(w, k) for k, ws in _KASSA_WORDS.items() for w in ws] + [
	(lt, k) for lt, k in _KASSA_LETTER.items()
]


def detect_transfer_dirs(text: str):
	"""(from_kassa, to_kassa) from directional text."""
	t = _norm(text)
	frm = to = None
	for w, k in _KASSA_DIR_WORDS:
		if frm is None and re.search(rf"\b{re.escape(w)}{_DAN}\b", t):
			frm = k
		if to is None and re.search(rf"\b{re.escape(w)}\s*{_GA}\b", t):
			to = k
	return frm, to


def parse_legs(text: str) -> list[dict]:
	"""Split a message into amount+kassa legs."""
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
	"""Bot entry point."""
	raw = text or ""
	if not op:
		op = detect_op(raw, detect_currency(raw))
	res = {
		"op": op,
		"counterparty": extract_counterparty(raw, op),
		"purpose": extract_purpose(raw, op),
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
				leg["kassa"] = "nakit"
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
		res["from"] = frm
		res["to"] = to
		res["amount"] = extract_amount(raw)
		return res

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
