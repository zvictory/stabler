"""Pure conversational core for the shadow KassaBot (WP-S4b) — Frappe-free.

Op-first flow: kassir picks the operation (Kirim / Chiqim / Konvertatsiya /
Kassalararo), then free-texts. The smart parser (_smart.parse_message) fills the
amount(s)+kassa(s)+slots; one missing slot => ONE question. On confirm this
module hands the caller a `record` action with signed per-kassa DELTAS, which the
bot writes to the standalone shadow store (shadow.record). NEVER touches GL.

`handle(state, text, ctx)` -> (reply_text, keyboard_rows|None, new_state, action)
`action` is None until confirmed; then:
  {"type":"record", "op","counterparty","purpose","rate","raw_text","parsed",
   "deltas":[{"kassa","delta"}, ...]}
`ctx` may carry {"balances": {"nakit":..,"pk":..,"usd":..}} for the header.
"""

from __future__ import annotations

from ._smart import extract_amount, parse_legs, parse_message

# --------------------------------------------------------------------------- #
KLABEL = {"nakit": "\U0001F7E6 Nakit", "pk": "\U0001F7E7 PK", "usd": "\U0001F7E9 USD"}
KSUF = {"nakit": "s", "pk": "p", "usd": "d"}

BTN_KIRIM = "\U0001F7E2 Kirim"
BTN_CHIQIM = "\U0001F534 Chiqim"
BTN_KONV = "\U0001F504 Konvertatsiya"
BTN_K2K = "\U0001F4B1 Kassalararo"
BTN_CONFIRM = "✅ Tasdiqlash"
BTN_CANCEL = "❌ Bekor"
BTN_OPENING = "⚙️ Ochilish"
BTN_UNDO = "↩️ Oxirgi amalni bekor"
BTN_SOM = "\U0001F7E6 Som"
BTN_PK = "\U0001F7E7 PK"
BTN_USD = "\U0001F7E9 USD"

_OP_BTN = {BTN_KIRIM: "kirim", BTN_CHIQIM: "chiqim", BTN_KONV: "konversiya", BTN_K2K: "kassalararo"}
_OPLABEL = {"kirim": "Kirim", "chiqim": "Chiqim", "konversiya": "Konvertatsiya", "kassalararo": "Kassalararo"}
_KASSA_BTN = {BTN_SOM: "nakit", BTN_PK: "pk", BTN_USD: "usd"}
_PH = {
    "kirim": "Masalan: «Mijozdan 2 mln naqd, 3 mln karta va 500 dollar» yoki «Alidan 600 ming»",
    "chiqim": "Masalan: «100ming s ijaraga» yoki «100d Aliyevga»",
    "konversiya": "Masalan: «500 dollar oldim 12900 kurs»",
    "kassalararo": "Masalan: «2 mln naqddan pk ga»",
}
MENU_KEYBOARD = [[BTN_KIRIM, BTN_CHIQIM], [BTN_KONV, BTN_K2K], [BTN_OPENING, BTN_UNDO]]


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def fmt_amount(v, kassa=None):
    """Always 2 decimals (decimals shown for every kassa)."""
    return f"{float(v or 0):,.2f}".replace(",", " ")


def format_balance(balances):
    """Inline: '🟦 402 250 000.00 s · 🟧 3 000 000.00 p · 🟩 400.00 d'."""
    b = balances or {}
    parts = []
    for k in ("nakit", "pk", "usd"):
        emoji = KLABEL[k].split()[0]
        parts.append(f"{emoji} {fmt_amount(b.get(k, 0))} {KSUF[k]}")
    return " · ".join(parts)


def format_balance_lines(balances):
    """One kassa per line (for the menu header)."""
    b = balances or {}
    lines = []
    for k in ("nakit", "pk", "usd"):
        emoji = KLABEL[k].split()[0]
        lines.append(f"{emoji} {fmt_amount(b.get(k, 0))} {KSUF[k]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Money math — signed per-kassa deltas from a resolved parse
# --------------------------------------------------------------------------- #
def compute_deltas(p):
    op = p.get("op")
    if op in ("kirim", "chiqim"):
        sign = 1 if op == "kirim" else -1
        return [{"kassa": l["kassa"], "delta": sign * float(l["amount"])} for l in p.get("legs", [])]
    if op == "konversiya":
        a = float(p["amount"]); r = float(p["rate"])
        if p.get("dir", "buy") == "buy":
            return [{"kassa": p["source"], "delta": -a * r}, {"kassa": "usd", "delta": a}]
        return [{"kassa": "usd", "delta": -a}, {"kassa": p["target"], "delta": a * r}]
    if op == "kassalararo":
        a = float(p["amount"])
        return [{"kassa": p["from"], "delta": -a}, {"kassa": p["to"], "delta": a}]
    return []


def confirm_text(p):
    op = p.get("op")
    lines = []
    if op in ("kirim", "chiqim"):
        sign = "+" if op == "kirim" else "−"
        lines.append(_OPLABEL[op] + ":")
        for l in p.get("legs", []):
            emoji = KLABEL[l["kassa"]].split()[0]
            lines.append(f"{emoji} {sign}{fmt_amount(l['amount'])} {KSUF[l['kassa']]}")
        if p.get("counterparty"):
            lines.append(("Kimdan: " if op == "kirim" else "Kimga: ") + p["counterparty"])
        if p.get("purpose"):
            lines.append("Izoh: " + p["purpose"])
    elif op == "konversiya":
        if p.get("dir", "buy") == "buy":
            lines.append(f"{KLABEL[p['source']]} → \U0001F7E9 USD")
        else:
            lines.append(f"\U0001F7E9 USD → {KLABEL[p['target']]}")
        lines.append(f"{fmt_amount(p['amount'], 'usd')} $ · kurs {fmt_amount(p['rate'], 'nakit')}")
    elif op == "kassalararo":
        lines.append(f"{KLABEL[p['from']]} → {KLABEL[p['to']]}")
        lines.append(f"{fmt_amount(p['amount'], p['from'])} {KSUF[p['from']]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Readiness re-check after a manual slot answer
# --------------------------------------------------------------------------- #
_Q = {
    "amount": "Qancha?",
    "kirim_from": "Kimdan oldingiz?",
    "chiqim_to": "Kimga / nima uchun?",
    "konv_source": "Qaysi kassadan?",
    "konv_target": "Qaysi kassaga?",
    "rate": "Kurs qancha?",
    "k2k_from": "Qaysi kassadan?",
    "k2k_to": "Qaysi kassaga?",
}


def _check(p):
    op = p.get("op")
    if op in ("kirim", "chiqim"):
        if not p.get("legs"):
            return "amount"
        if op == "kirim" and not p.get("counterparty"):
            return "kirim_from"
        if op == "chiqim" and not p.get("counterparty") and not p.get("purpose"):
            return "chiqim_to"
        return None
    if op == "konversiya":
        if p.get("amount") is None:
            return "amount"
        if p.get("dir", "buy") == "buy" and not p.get("source"):
            return "konv_source"
        if p.get("dir") == "sell" and not p.get("target"):
            return "konv_target"
        if p.get("rate") is None:
            return "rate"
        return None
    if op == "kassalararo":
        if p.get("amount") is None:
            return "amount"
        if not p.get("from"):
            return "k2k_from"
        if not p.get("to"):
            return "k2k_to"
        return None
    return None


def _slot_keyboard(slot, p):
    if slot in ("konv_source", "k2k_from"):
        return [[BTN_SOM, BTN_PK, BTN_USD]] if slot == "k2k_from" else [[BTN_SOM, BTN_PK]]
    if slot in ("konv_target", "k2k_to"):
        opts = [BTN_SOM, BTN_PK, BTN_USD]
        frm = p.get("from")
        if slot == "k2k_to" and frm:
            opts = [b for b in opts if _KASSA_BTN[b] != frm]
        return [opts]
    return None  # free-text answer


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
def _opening_confirm_text(openings):
    kmap = {o["kassa"]: o["amount"] for o in openings}
    lines = ["Ochilish balansi:"]
    for k in ("nakit", "pk", "usd"):
        if k in kmap:
            lines.append(f"  {KLABEL[k]}: {fmt_amount(kmap[k], k)} {KSUF[k]}")
    lines += ["", "Tasdiqlaysizmi?"]
    return "\n".join(lines)


def _menu(ctx):
    hdr = "Qoldiq:\n" + format_balance_lines((ctx or {}).get("balances"))
    return hdr + "\n\nAmalni tanlang:", MENU_KEYBOARD


def handle(state, text, ctx=None):
    state = dict(state or {})
    step = state.get("step") or "menu"
    t = (text or "").strip()

    if t == BTN_CANCEL:
        reply, kb = _menu(ctx)
        return reply, kb, {"step": "menu"}, None

    if step == "menu":
        if t in _OP_BTN:
            op = _OP_BTN[t]
            return (f"{_OPLABEL[op]} ✍️", [[BTN_CANCEL]], {"step": "await_text", "op": op}, None)
        if t == BTN_OPENING:
            return ("Ochilish balansini yozing (masalan: «402 mln naqd, 3 mln karta, 400 dollar»):",
                    [[BTN_CANCEL]], {"step": "await_opening"}, None)
        if t == BTN_UNDO:
            reply, kb = _menu(ctx)
            return reply, kb, {"step": "menu"}, {"type": "undo_last"}
        reply, kb = _menu(ctx)
        return reply, kb, {"step": "menu"}, None

    if step == "await_opening":
        legs = parse_legs(t)
        if not legs:
            return ("Tushunmadim. Masalan: «402 mln naqd, 3 mln karta, 400 dollar»",
                    [[BTN_CANCEL]], {"step": "await_opening"}, None)
        openings = [{"kassa": l.get("kassa") or "nakit", "amount": float(l["amount"])} for l in legs]
        return (_opening_confirm_text(openings), [[BTN_CONFIRM], [BTN_CANCEL]],
                {"step": "confirm_opening", "openings": openings}, None)

    if step == "confirm_opening":
        if t == BTN_CONFIRM:
            action = {"type": "set_opening", "openings": state.get("openings") or []}
            reply, kb = _menu(ctx)
            return reply, kb, {"step": "menu"}, action
        reply, kb = _menu(ctx)
        return reply, kb, {"step": "menu"}, None

    if step == "await_text":
        op = state.get("op")
        p = parse_message(t, op=op)
        last_cp = (ctx or {}).get("last_cp")
        if op == "kirim" and not p.get("counterparty") and last_cp and "yana" in t.lower():
            p["counterparty"] = last_cp
        return _after_parse(p, ctx)

    if step == "await_slot":
        p = dict(state.get("p") or {})
        slot = state.get("slot")
        _fill(p, slot, t)
        return _after_parse(p, ctx)

    if step == "confirm":
        p = dict(state.get("p") or {})
        if t == BTN_CONFIRM:
            action = {
                "type": "record", "op": p.get("op"), "counterparty": p.get("counterparty"),
                "purpose": p.get("purpose"), "rate": p.get("rate"), "raw_text": p.get("raw_text"),
                "parsed": p, "deltas": compute_deltas(p),
            }
            reply, kb = _menu(ctx)
            return reply, kb, {"step": "menu"}, action
        reply, kb = _menu(ctx)
        return reply, kb, {"step": "menu"}, None

    reply, kb = _menu(ctx)
    return reply, kb, {"step": "menu"}, None


def _preview(p, ctx):
    """Append the projected new balance + a negative-balance warning."""
    bals = dict((ctx or {}).get("balances") or {})
    deltas = compute_deltas(p)
    if not deltas:
        return ""
    for d in deltas:
        bals[d["kassa"]] = bals.get(d["kassa"], 0) + d["delta"]
    out = ["", "Yangi qoldiq: " + format_balance(bals)]
    neg = [k for k in ("nakit", "pk", "usd") if bals.get(k, 0) < 0]
    if neg:
        out.append("⚠️ Manfiy bo'ladi: " + ", ".join(KLABEL[k] for k in neg))
    return "\n".join(out)


def _after_parse(p, ctx):
    slot = _check(p)
    if slot is None:
        return (confirm_text(p) + _preview(p, ctx) + "\n\nShundaymi?",
                [[BTN_CONFIRM], [BTN_CANCEL]], {"step": "confirm", "p": p}, None)
    kb = _slot_keyboard(slot, p)
    if kb is None and slot == "kirim_from":
        last_cp = (ctx or {}).get("last_cp")
        if last_cp:
            kb = [[last_cp]]
    if kb is not None:
        kb = kb + [[BTN_CANCEL]]
    return _Q[slot], kb, {"step": "await_slot", "op": p.get("op"), "slot": slot, "p": p}, None


def _fill(p, slot, answer):
    a = (answer or "").strip()
    if slot == "kirim_from":
        p["counterparty"] = a
    elif slot == "chiqim_to":
        p["purpose"] = a
    elif slot in ("konv_source", "k2k_from"):
        p["source" if slot == "konv_source" else "from"] = _KASSA_BTN.get(a) or a.lower()
    elif slot in ("konv_target", "k2k_to"):
        p["target" if slot == "konv_target" else "to"] = _KASSA_BTN.get(a) or a.lower()
    elif slot == "rate":
        p["rate"] = extract_amount(a)
    elif slot == "amount":
        amt = extract_amount(a)
        if amt is not None and p.get("op") in ("kirim", "chiqim") and not p.get("legs"):
            p["legs"] = [{"kassa": "nakit", "currency": "UZS", "amount": amt}]
        else:
            p["amount"] = amt
