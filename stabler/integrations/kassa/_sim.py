"""Local terminal simulator for the shadow KassaBot — NO frappe, NO Telegram.

Runs the REAL shadow modules (shadow_flow + shadow_store + _smart) so you can
"chat" with the bot logic in your terminal and watch the standalone SQLite
balances update. Proves the whole flow works locally, independent of prod / the
kassa_shadow_mode flag / a Telegram webhook.

    cd /Users/zafar/frappe-bench-local/apps/stabler
    PYTHONPATH=$PWD python3 -m stabler.integrations.kassa._sim

Interactive: type the same things a kassir would ("⚙️ Ochilish", "🟢 Kirim",
"Mijozdan 2 mln naqd, 3 mln karta va 500 dollar", "✅ Tasdiqlash"…). You can
type plain "kirim / chiqim / konv / k2k / ochilish / ok / bekor" as shortcuts.
Pipe a script too:  printf 'ochilish\\n402 mln naqd, 3 mln karta, 400 dollar\\nok\\nkirim\\nMijozdan 2 mln naqd\\nAli\\nok\\n' | PYTHONPATH=$PWD python3 -m stabler.integrations.kassa._sim
"""

from __future__ import annotations

import sys
import tempfile

from . import shadow_flow as sf
from . import shadow_store as ss

COMPANY = "mikas"
DATE = "2026-07-19"

# friendly shortcuts -> the exact button labels the flow expects
_ALIAS = {
	"kirim": sf.BTN_KIRIM,
	"chiqim": sf.BTN_CHIQIM,
	"konv": sf.BTN_KONV,
	"konversiya": sf.BTN_KONV,
	"k2k": sf.BTN_K2K,
	"kassalararo": sf.BTN_K2K,
	"ochilish": sf.BTN_OPENING,
	"opening": sf.BTN_OPENING,
	"ok": sf.BTN_CONFIRM,
	"ha": sf.BTN_CONFIRM,
	"tasdiq": sf.BTN_CONFIRM,
	"bekor": sf.BTN_CANCEL,
	"yoq": sf.BTN_CANCEL,
	"cancel": sf.BTN_CANCEL,
	"som": sf.BTN_SOM,
	"pk": sf.BTN_PK,
	"usd": sf.BTN_USD,
}


def _print_bot(reply, keyboard):
	print("\n╔═ BOT " + "═" * 40)
	for line in (reply or "").split("\n"):
		print("║ " + line)
	if keyboard:
		rows = " | ".join("[" + "] [".join(r) + "]" for r in keyboard)
		print("║ tugmalar: " + rows)
	print("╚" + "═" * 45)


def main():
	path = tempfile.mktemp(suffix=".sqlite")
	state = {"step": "menu"}

	def balances():
		return ss.balances(path, COMPANY, DATE)

	def apply(action):
		if not action:
			return None
		if action.get("type") == "record":
			ss.add_entry(
				path,
				company=COMPANY,
				kassir="sim",
				op=action["op"],
				deltas=action["deltas"],
				counterparty=action.get("counterparty"),
				purpose=action.get("purpose"),
				rate=action.get("rate"),
				raw_text=action.get("raw_text"),
				parsed=action.get("parsed"),
				date=DATE,
			)
			return "✅ Saqlandi. Qoldiq: " + sf.format_balance(balances())
		if action.get("type") == "set_opening":
			for o in action.get("openings") or []:
				ss.set_opening(path, COMPANY, DATE, o["kassa"], o["amount"])
			return "✅ Ochilish saqlandi. Qoldiq: " + sf.format_balance(balances())
		return None

	# opening menu
	reply, kb, state, _ = sf.handle({"step": "menu"}, "", {"balances": balances()})
	_print_bot(reply, kb)
	print(
		"\n(yozing — «kirim/chiqim/konv/k2k/ochilish», «ok», «bekor», «som/pk/usd», yoki to'liq gap. Chiqish: Ctrl-D)"
	)

	for raw in sys.stdin:
		line = raw.rstrip("\n")
		text = _ALIAS.get(line.strip().lower(), line)
		print("\n▶ siz: " + line)
		reply, kb, state, action = sf.handle(state, text, {"balances": balances()})
		follow = apply(action)
		if follow:
			reply = follow + "\n\nAmalni tanlang:"
			kb = sf.MENU_KEYBOARD
		_print_bot(reply, kb)


if __name__ == "__main__":
	main()
