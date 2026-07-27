"""Unit tests for stabler.integrations.kassa._flow (WP-K3 + WP-K6 smart-bot, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_flow -v
"""

from __future__ import annotations

import unittest
from typing import ClassVar

from stabler.integrations.kassa._flow import (
	BTN_CANCEL,
	BTN_CHIQIM,
	BTN_CONFIRM,
	BTN_K2K,
	BTN_KIRIM,
	BTN_KONV,
	BTN_KONV_MANUAL,
	BTN_OTHER,
	BTN_SKIP_DEAL,
	MENU_KEYBOARD,
	STEP_MAIN,
	STEP_MENU,
	_konv_cbu_accept_label,
	_konv_direction_keyboard,
	_konv_direction_label,
	_konv_direction_pairs,
	format_amount,
	handle,
	parse_amount,
	parse_date_ddmmyyyy,
	parse_quick_transfer,
)
from stabler.integrations.kassa.bot import _direction_emoji, _truncate_remark

CTX = {
	"kassas": {
		"Kassa 1": [
			{"account": "Kassa Naqd UZS - M", "label": "Naqd UZS", "currency": "UZS"},
			{"account": "Kassa Naqd USD - M", "label": "Naqd USD", "currency": "USD"},
			{"account": "PK Naqd UZS - M", "label": "PK", "currency": "UZS"},
		]
	},
	"categories": [{"account": f"Expense {i} - M", "label": f"Xarajat {i}"} for i in range(1, 4)],
	"deals": [
		{"name": "CRM-DEAL-0001", "label": "Tender A"},
		{"name": "CRM-DEAL-0002", "label": "Tender B"},
	],
	"targets": [
		{"account": "Bank UZS - M", "label": "Bank UZS", "currency": "UZS"},
		{"account": "Bank USD - M", "label": "Bank USD", "currency": "USD"},
		{"account": "Kassa Naqd UZS - M", "label": "Naqd UZS", "currency": "UZS"},
		{"account": "Kassa Naqd USD - M", "label": "Naqd USD", "currency": "USD"},
	],
	"base_currency": "UZS",
	"aliases": {
		"som": "Kassa Naqd UZS - M",
		"naqd uzs": "Kassa Naqd UZS - M",
		"pk": "PK Naqd UZS - M",
		"usd": "Kassa Naqd USD - M",
		"dollar": "Kassa Naqd USD - M",
		"valyuta": "Kassa Naqd USD - M",
		"naqd usd": "Kassa Naqd USD - M",
	},
}

CTX_NO_DEALS = {**CTX, "deals": []}

CTX_WITH_CBU = {**CTX, "cbu": {"rate": 12950.0, "date": "17.07"}}

# Mikas-style single-kassa tenant: every same-currency company cash account is
# itself a leaf of "Kassa 1" -> Kassadan-kassaga has no OTHER kassa to target.
CTX_SINGLE_KASSA = {
	**CTX,
	"targets": [
		{"account": "Kassa Naqd UZS - M", "label": "Naqd UZS", "currency": "UZS"},
		{"account": "Kassa Naqd USD - M", "label": "Naqd USD", "currency": "USD"},
	],
}


def _init_state():
	return {"step": STEP_MAIN, "kassa": None, "posting_date": None}


def _pick_kassa(ctx=CTX):
	state = _init_state()
	_reply, _kb, state, _action = handle(state, "Kassa 1", ctx)
	return state


class TestParseAmount(unittest.TestCase):
	# --- existing numeric formats (unchanged behaviour) --- #
	def test_thousands_spaces(self):
		self.assertEqual(parse_amount("2 000 000"), 2000000.0)

	def test_comma_decimal(self):
		self.assertEqual(parse_amount("1 250,50"), 1250.5)

	def test_plain_int(self):
		self.assertEqual(parse_amount("500"), 500.0)

	def test_rejects_zero(self):
		self.assertIsNone(parse_amount("0"))

	def test_rejects_negative(self):
		self.assertIsNone(parse_amount("-5"))

	def test_rejects_garbage(self):
		self.assertIsNone(parse_amount("abc"))

	def test_rejects_none_and_empty(self):
		self.assertIsNone(parse_amount(None))
		self.assertIsNone(parse_amount(""))
		self.assertIsNone(parse_amount("   "))

	def test_rejects_ambiguous_separators(self):
		self.assertIsNone(parse_amount("1.234,56"))

	# --- suffix shorthand (WP-K6) --- #
	def test_suffix_k(self):
		self.assertEqual(parse_amount("100k"), 100000.0)

	def test_suffix_m_dot_decimal(self):
		self.assertEqual(parse_amount("1.5m"), 1500000.0)

	def test_suffix_m_comma_decimal(self):
		self.assertEqual(parse_amount("1,5m"), 1500000.0)

	def test_suffix_mln_latin(self):
		self.assertEqual(parse_amount("2 mln"), 2000000.0)

	def test_suffix_mln_cyrillic(self):
		self.assertEqual(parse_amount("2млн"), 2000000.0)

	def test_suffix_ming_latin(self):
		self.assertEqual(parse_amount("500 ming"), 500000.0)

	def test_suffix_ming_cyrillic(self):
		self.assertEqual(parse_amount("500минг"), 500000.0)

	def test_suffix_bin_turkish(self):
		self.assertEqual(parse_amount("3 bin"), 3000.0)

	# --- Uzbek/Turkish word-number grammar (WP-K6) --- #
	def test_word_yuz_ming(self):
		self.assertEqual(parse_amount("yuz ming"), 100000.0)

	def test_word_besh_yuz_ming(self):
		self.assertEqual(parse_amount("besh yuz ming"), 500000.0)

	def test_word_million_composition(self):
		self.assertEqual(parse_amount("ikki million uch yuz ming"), 2300000.0)

	def test_word_bir_yarim_million(self):
		self.assertEqual(parse_amount("bir yarim million"), 1500000.0)

	def test_word_yarim_million_alone(self):
		self.assertEqual(parse_amount("yarim million"), 500000.0)

	def test_word_turkish_yuz_bin(self):
		self.assertEqual(parse_amount("yüz bin"), 100000.0)

	def test_word_ascii_fallback_spelling(self):
		self.assertEqual(parse_amount("toqqiz yuz ming"), 900000.0)

	def test_word_single_digit(self):
		self.assertEqual(parse_amount("besh"), 5.0)

	def test_word_garbage_rejected(self):
		self.assertIsNone(parse_amount("salom dunyo"))

	def test_word_mixed_with_unknown_token_rejected(self):
		self.assertIsNone(parse_amount("besh yuz million nimadir"))

	def test_word_yarim_without_unit_rejected(self):
		self.assertIsNone(parse_amount("yarim"))


class TestParseDate(unittest.TestCase):
	def test_valid(self):
		self.assertEqual(parse_date_ddmmyyyy("05.07.2026"), "2026-07-05")

	def test_invalid_format(self):
		self.assertIsNone(parse_date_ddmmyyyy("2026-07-05"))
		self.assertIsNone(parse_date_ddmmyyyy("5.7.2026"))
		self.assertIsNone(parse_date_ddmmyyyy(""))
		self.assertIsNone(parse_date_ddmmyyyy(None))

	def test_invalid_calendar_date(self):
		self.assertIsNone(parse_date_ddmmyyyy("31.02.2026"))
		self.assertIsNone(parse_date_ddmmyyyy("00.01.2026"))


class TestFormatAmount(unittest.TestCase):
	def test_whole_number(self):
		self.assertEqual(format_amount(2000000, "UZS"), "2 000 000 UZS")

	def test_fraction(self):
		self.assertEqual(format_amount(1250.5, "USD"), "1 250.5 USD")

	def test_small_whole(self):
		self.assertEqual(format_amount(500, "UZS"), "500 UZS")


class TestParseQuickTransfer(unittest.TestCase):
	def test_attached_suffixes_no_izoh(self):
		result = parse_quick_transfer("somdan pkga 500 ming", CTX)
		self.assertEqual(
			result,
			{
				"from": "Kassa Naqd UZS - M",
				"to": "PK Naqd UZS - M",
				"amount": 500000.0,
				"izoh": None,
			},
		)

	def test_detached_suffixes_with_izoh(self):
		result = parse_quick_transfer("som dan pk ga 500 ming ijara uchun", CTX)
		self.assertEqual(
			result,
			{
				"from": "Kassa Naqd UZS - M",
				"to": "PK Naqd UZS - M",
				"amount": 500000.0,
				"izoh": "ijara",
			},
		)

	def test_izoh_after_comma(self):
		result = parse_quick_transfer("somdan pkga 100000, kira haqi", CTX)
		self.assertEqual(result["amount"], 100000.0)
		self.assertEqual(result["izoh"], "kira haqi")

	def test_numeric_amount(self):
		result = parse_quick_transfer("pkdan somga 2 000 000", CTX)
		self.assertEqual(
			result,
			{
				"from": "PK Naqd UZS - M",
				"to": "Kassa Naqd UZS - M",
				"amount": 2000000.0,
				"izoh": None,
			},
		)

	def test_unknown_alias_returns_none(self):
		self.assertIsNone(parse_quick_transfer("noaliasdan somga 100000", CTX))

	def test_cross_currency_out_of_scope(self):
		self.assertIsNone(parse_quick_transfer("usd dan somga 100 konvertatsiya", CTX))

	def test_no_amount_returns_none(self):
		self.assertIsNone(parse_quick_transfer("somdan pkga", CTX))

	def test_no_aliases_in_ctx_returns_none(self):
		self.assertIsNone(parse_quick_transfer("somdan pkga 500 ming", {}))

	def test_unrelated_text_returns_none(self):
		self.assertIsNone(parse_quick_transfer(BTN_KIRIM, CTX))

	def test_empty_text_returns_none(self):
		self.assertIsNone(parse_quick_transfer("", CTX))
		self.assertIsNone(parse_quick_transfer(None, CTX))


class TestMainAndMenu(unittest.TestCase):
	def test_pick_kassa_enters_menu(self):
		state = _init_state()
		_reply, kb, state, action = handle(state, "Kassa 1", CTX)
		self.assertEqual(state["step"], STEP_MENU)
		self.assertEqual(state["kassa"], "Kassa 1")
		self.assertEqual(kb, MENU_KEYBOARD)
		self.assertIsNone(action)

	def test_unknown_kassa_reprompts(self):
		state = _init_state()
		_reply, _kb, new_state, action = handle(state, "garbage", CTX)
		self.assertEqual(new_state, state)
		self.assertIsNone(action)

	def test_unknown_menu_text_reprompts_unchanged(self):
		state = _pick_kassa()
		_reply, kb, new_state, action = handle(state, "???", CTX)
		self.assertEqual(new_state, state)
		self.assertEqual(kb, MENU_KEYBOARD)
		self.assertIsNone(action)

	def test_quick_transfer_at_main_jumps_to_memo_prompt(self):
		state = _init_state()
		reply, _kb, new_state, action = handle(state, "somdan pkga 500 ming", CTX)
		self.assertIsNone(action)
		self.assertEqual(new_state["step"], "k2k_memo")
		self.assertEqual(new_state["amount"], 500000.0)
		self.assertEqual(new_state["src"]["account"], "Kassa Naqd UZS - M")
		self.assertEqual(new_state["tgt"]["account"], "PK Naqd UZS - M")
		self.assertIn("500 000 UZS", reply)

	def test_quick_transfer_with_izoh_jumps_straight_to_confirm(self):
		state = _pick_kassa()
		reply, _kb, new_state, action = handle(state, "somdan pkga 500 ming ijara uchun", CTX)
		self.assertIsNone(action)
		self.assertEqual(new_state["step"], "k2k_confirm")
		self.assertEqual(new_state["memo"], "ijara")
		self.assertIn("500 000 UZS", reply)
		self.assertIn("Tasdiqlaysizmi?", reply)

	def test_quick_transfer_completes_with_confirm_button(self):
		state = _pick_kassa()
		_reply, _kb, state, action = handle(state, "somdan pkga 500 ming ijara uchun", CTX)
		_reply, _kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Kassa Naqd UZS - M",
				"to": "PK Naqd UZS - M",
				"from_amount": 500000.0,
				"memo": "ijara",
			},
		)


class TestCancel(unittest.TestCase):
	def test_cancel_from_mid_flow_resets_to_main(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_reply, _kb, state, action = handle(state, BTN_CANCEL, CTX)
		self.assertEqual(state["step"], STEP_MAIN)
		self.assertIsNone(state["kassa"])
		self.assertIsNone(action)

	def test_cancel_preserves_posting_date(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001f4dd Qolib ketgan amal", CTX)
		_, _, state, _ = handle(state, "05.07.2026", CTX)
		self.assertEqual(state["posting_date"], "2026-07-05")
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _action = handle(state, BTN_CANCEL, CTX)
		self.assertEqual(state["step"], STEP_MAIN)
		self.assertEqual(state["posting_date"], "2026-07-05")


class TestBackdate(unittest.TestCase):
	def test_sets_date_and_returns_to_menu(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001f4dd Qolib ketgan amal", CTX)
		_reply, _kb, state, action = handle(state, "05.07.2026", CTX)
		self.assertEqual(state["step"], STEP_MENU)
		self.assertEqual(state["posting_date"], "2026-07-05")
		self.assertIsNone(action)

	def test_invalid_date_reprompts(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001f4dd Qolib ketgan amal", CTX)
		_reply, _kb, new_state, _action = handle(state, "not-a-date", CTX)
		self.assertEqual(new_state, state)

	def test_date_resets_after_one_completed_op(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001f4dd Qolib ketgan amal", CTX)
		_, _, state, _ = handle(state, "05.07.2026", CTX)
		self.assertEqual(state["posting_date"], "2026-07-05")

		# Complete a Kirim operation end to end.
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Bank UZS", CTX)
		_, _, state, _ = handle(state, "10000", CTX)
		_, _, state, _ = handle(state, "-", CTX)
		_reply, _kb, state, action = handle(state, BTN_CONFIRM, CTX)

		self.assertIsNotNone(action)
		self.assertEqual(state["step"], STEP_MENU)
		self.assertIsNone(state["posting_date"])


class TestKirimFlow(unittest.TestCase):
	def test_happy_path(self):
		state = _pick_kassa()
		reply, kb, state, action = handle(state, BTN_KIRIM, CTX)
		self.assertIn("Naqd UZS", [row[0] for row in kb])

		reply, kb, state, action = handle(state, "Naqd UZS", CTX)
		# Sources must be same-currency and exclude the sub-kassa itself.
		labels = [row[0] for row in kb]
		self.assertIn("Bank UZS", labels)
		self.assertNotIn("Naqd UZS", labels)
		self.assertNotIn("Bank USD", labels)

		reply, kb, state, action = handle(state, "Bank UZS", CTX)
		reply, kb, state, action = handle(state, "2 000 000", CTX)
		self.assertEqual(state["amount"], 2000000.0)
		self.assertIn("2 000 000 UZS", reply)  # amount echo (WP-K6 #1)

		reply, kb, state, action = handle(state, "test izoh", CTX)
		self.assertIn("2 000 000 UZS", reply)
		self.assertIn("Naqd UZS", reply)
		self.assertIn("Bank UZS", reply)

		reply, kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Bank UZS - M",
				"to": "Kassa Naqd UZS - M",
				"from_amount": 2000000.0,
				"memo": "test izoh",
			},
		)
		self.assertEqual(state["step"], STEP_MENU)

	def test_memo_dash_skips(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Bank UZS", CTX)
		_, _, state, _ = handle(state, "5000", CTX)
		_, _, state, action = handle(state, "-", CTX)
		self.assertEqual(state["step"], "kirim_confirm")
		_, _, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertIsNone(action["memo"])

	def test_smart_amount_accepted_via_word_grammar(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Bank UZS", CTX)
		reply, _kb, state, _action = handle(state, "besh yuz ming", CTX)
		self.assertEqual(state["amount"], 500000.0)
		self.assertIn("500 000 UZS", reply)

	def test_invalid_amount_reprompts(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Bank UZS", CTX)
		_reply, _kb, new_state, action = handle(state, "not a number", CTX)
		self.assertEqual(new_state, state)
		self.assertIsNone(action)


class TestChiqimFlow(unittest.TestCase):
	def test_happy_path_with_deal(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		reply, kb, state, action = handle(state, "Naqd UZS", CTX)
		labels = [row[0] for row in kb]
		self.assertIn("Xarajat 1", labels)
		self.assertIn(BTN_OTHER, labels)

		reply, kb, state, action = handle(state, "Xarajat 2", CTX)
		labels = [row[0] for row in kb]
		self.assertIn("Tender A", labels)
		self.assertIn(BTN_SKIP_DEAL, labels)

		reply, kb, state, action = handle(state, "Tender A", CTX)
		reply, kb, state, action = handle(state, "150000", CTX)
		self.assertIn("150 000 UZS", reply)  # amount echo (WP-K6 #1)
		reply, kb, state, action = handle(state, "gazeta", CTX)
		self.assertIn("Xarajat 2", reply)
		self.assertIn("Tender A", reply)
		self.assertIn("150 000 UZS", reply)

		reply, kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "expense",
				"payment_from": "Kassa Naqd UZS - M",
				"category": "Expense 2 - M",
				"amount": 150000.0,
				"deal": "CRM-DEAL-0001",
				"memo": "gazeta",
			},
		)

	def test_happy_path_without_deal_when_no_deals_available(self):
		state = _pick_kassa(CTX_NO_DEALS)
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX_NO_DEALS)
		_, _, state, _ = handle(state, "Naqd UZS", CTX_NO_DEALS)
		reply, _kb, state, action = handle(state, "Xarajat 1", CTX_NO_DEALS)
		# Should skip straight to amount, not the deal step.
		self.assertIn("Summani kiriting", reply)
		_, _, state, _ = handle(state, "20000", CTX_NO_DEALS)
		_, _, state, action = handle(state, "Bozor-xarid", CTX_NO_DEALS)
		self.assertEqual(state["step"], "chiqim_confirm")
		_, _, state, action = handle(state, BTN_CONFIRM, CTX_NO_DEALS)
		self.assertIsNone(action["deal"])
		self.assertEqual(action["memo"], "Bozor-xarid")

	def test_skip_deal_button(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Xarajat 1", CTX)
		_, _, state, _ = handle(state, BTN_SKIP_DEAL, CTX)
		_, _, state, _ = handle(state, "10000", CTX)
		_, _, state, _ = handle(state, "market uchun", CTX)
		_, _, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertIsNone(action["deal"])
		self.assertEqual(action["memo"], "market uchun")

	def test_other_category_filter(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, BTN_OTHER, CTX)
		reply, kb, state, _action = handle(state, "3", CTX)
		self.assertIn(["Xarajat 3"], kb)
		reply, kb, state, _action = handle(state, "Xarajat 3", CTX)
		# CTX has deals configured, so it should now prompt for the deal, not amount.
		self.assertIn("Tender", reply)

	def test_other_category_filter_no_match(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, BTN_OTHER, CTX)
		reply, _kb, _new_state, _action = handle(state, "zzz-no-match", CTX)
		self.assertIn("Topilmadi", reply)

	# --- mandatory izoh (WP-K6 #3) --- #
	def test_dash_rejected_for_izoh(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Xarajat 1", CTX)
		_, _, state, _ = handle(state, BTN_SKIP_DEAL, CTX)
		_, _, state, _ = handle(state, "10000", CTX)
		reply, _kb, new_state, action = handle(state, "-", CTX)
		self.assertEqual(new_state["step"], "chiqim_memo")
		self.assertIn("majburiy", reply)
		self.assertIsNone(action)

	def test_empty_string_rejected_for_izoh(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Xarajat 1", CTX)
		_, _, state, _ = handle(state, BTN_SKIP_DEAL, CTX)
		_, _, state, _ = handle(state, "10000", CTX)
		_reply, _kb, new_state, action = handle(state, "   ", CTX)
		self.assertEqual(new_state["step"], "chiqim_memo")
		self.assertIsNone(action)

	def test_izoh_boshqa_button_opens_free_text(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Xarajat 1", CTX)
		_, _, state, _ = handle(state, BTN_SKIP_DEAL, CTX)
		_, _, state, _ = handle(state, "10000", CTX)
		reply, _kb, state, _action = handle(state, BTN_OTHER, CTX)
		self.assertTrue(state.get("_memo_await_free"))
		reply, _kb, state, _action = handle(state, "elektr energiyasi", CTX)
		self.assertEqual(state["step"], "chiqim_confirm")
		self.assertIn("elektr energiyasi", reply)


class TestKonvDirectionPairs(unittest.TestCase):
	"""WP-K9: Konvertatsiya as one-tap direction-pair buttons (screen A)."""

	def test_pair_count_and_labels(self):
		leaves = CTX["kassas"]["Kassa 1"]
		pairs = _konv_direction_pairs(leaves)
		self.assertEqual(len(pairs), len(leaves) * (len(leaves) - 1))
		labels = {_konv_direction_label(s, t) for s, t in pairs}
		self.assertIn("Naqd UZS → Naqd USD", labels)
		self.assertIn("Naqd USD → Naqd UZS", labels)
		self.assertIn("Naqd UZS → PK", labels)  # same-currency pair included
		self.assertIn("PK → Naqd UZS", labels)
		for src, tgt in pairs:
			self.assertNotEqual(src["account"], tgt["account"])

	def test_keyboard_two_per_row(self):
		leaves = CTX["kassas"]["Kassa 1"]
		kb = _konv_direction_keyboard(leaves)
		self.assertEqual(sum(len(row) for row in kb), 6)
		for row in kb:
			self.assertLessEqual(len(row), 2)


class TestKonvertatsiyaFlow(unittest.TestCase):
	def test_entering_konv_shows_direction_keyboard(self):
		state = _pick_kassa()
		reply, kb, state, action = handle(state, BTN_KONV, CTX)
		self.assertEqual(reply, "Yo'nalishni tanlang:")
		self.assertEqual(state["step"], "konv_direction")
		labels = [label for row in kb for label in row]
		self.assertIn("Naqd USD → Naqd UZS", labels)
		self.assertIsNone(action)

	def test_invalid_direction_reprompts(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KONV, CTX)
		_reply, _kb, new_state, action = handle(state, "garbage", CTX)
		self.assertEqual(new_state, state)
		self.assertIsNone(action)

	def test_happy_path_cross_currency_asks_both_amounts(self):
		"""No ctx['cbu'] rate -> falls back to asking both amounts manually,
		given (source) first, then received (target). Direction picked in a
		single tap: 'Naqd USD → Naqd UZS' means USD given, UZS received."""
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KONV, CTX)

		reply, _kb, state, action = handle(state, "Naqd USD → Naqd UZS", CTX)
		self.assertEqual(reply, "Qancha berdingiz? (USD)")

		reply, _kb, state, action = handle(state, "100", CTX)
		self.assertIn("100 USD", reply)
		self.assertIn("Qancha oldingiz? (UZS)", reply)

		reply, _kb, state, action = handle(state, "1250000", CTX)
		self.assertIn("1 250 000 UZS", reply)
		self.assertIn("majburiy", reply)

		reply, _kb, state, action = handle(state, "valyuta almashtirish", CTX)
		self.assertIn("100 USD", reply)
		self.assertIn("1 250 000 UZS", reply)
		self.assertIn("Kurs:", reply)

		reply, _kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Kassa Naqd USD - M",
				"to": "Kassa Naqd UZS - M",
				"from_amount": 100.0,
				"to_amount": 1250000.0,
				"memo": "valyuta almashtirish",
			},
		)

	def test_happy_path_same_currency_skips_received_and_cbu(self):
		"""UZS<->PK (same currency) — no CBU offer, no 'received' step, given
		== received, confirm has no Kurs line."""
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KONV, CTX)

		reply, _kb, state, action = handle(state, "Naqd UZS → PK", CTX)
		self.assertEqual(reply, "Qancha o'tkazasiz? (UZS)")

		reply, _kb, state, action = handle(state, "500000", CTX)
		self.assertIn("500 000 UZS", reply)
		self.assertIn("majburiy", reply)
		self.assertEqual(state["step"], "konv_memo")
		self.assertEqual(state["given"], 500000.0)
		self.assertEqual(state["received"], 500000.0)

		reply, _kb, state, action = handle(state, "ichki ko'chirish", CTX)
		self.assertEqual(state["step"], "konv_confirm")
		self.assertIn("Manba: Naqd UZS", reply)
		self.assertIn("Manzil: PK", reply)
		self.assertIn("Summa: 500 000 UZS", reply)
		self.assertNotIn("Kurs:", reply)
		self.assertNotIn("Berdingiz:", reply)
		self.assertNotIn("Oldingiz:", reply)

		reply, _kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Kassa Naqd UZS - M",
				"to": "PK Naqd UZS - M",
				"from_amount": 500000.0,
				"memo": "ichki ko'chirish",
			},
		)
		self.assertNotIn("to_amount", action)

	def test_izoh_dash_rejected(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KONV, CTX)
		_, _, state, _ = handle(state, "Naqd USD → Naqd UZS", CTX)
		_, _, state, _ = handle(state, "100", CTX)
		_, _, state, _ = handle(state, "1250000", CTX)
		_reply, _kb, new_state, action = handle(state, "-", CTX)
		self.assertEqual(new_state["step"], "konv_memo")
		self.assertIsNone(action)

	def test_cbu_assist_accept_computed(self):
		state = _pick_kassa(CTX_WITH_CBU)
		_, _, state, _ = handle(state, BTN_KONV, CTX_WITH_CBU)
		reply, kb, state, action = handle(state, "Naqd USD → Naqd UZS", CTX_WITH_CBU)
		self.assertEqual(reply, "Qancha berdingiz? (USD)")

		reply, kb, state, action = handle(state, "100", CTX_WITH_CBU)
		self.assertEqual(state["step"], "konv_cbu_choice")
		accept_label = _konv_cbu_accept_label(1295000.0, "UZS")
		self.assertIn(accept_label, [row[0] for row in kb])
		self.assertIn(BTN_KONV_MANUAL, [row[0] for row in kb])
		self.assertIn("100 USD", reply)

		reply, kb, state, action = handle(state, accept_label, CTX_WITH_CBU)
		self.assertEqual(state["received"], 1295000.0)
		self.assertEqual(state["step"], "konv_memo")

		reply, kb, state, action = handle(state, "CBU kursida", CTX_WITH_CBU)
		self.assertEqual(state["step"], "konv_confirm")

		reply, kb, state, action = handle(state, BTN_CONFIRM, CTX_WITH_CBU)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Kassa Naqd USD - M",
				"to": "Kassa Naqd UZS - M",
				"from_amount": 100.0,
				"to_amount": 1295000.0,
				"memo": "CBU kursida",
			},
		)

	def test_cbu_assist_manual_override(self):
		state = _pick_kassa(CTX_WITH_CBU)
		_, _, state, _ = handle(state, BTN_KONV, CTX_WITH_CBU)
		_, _, state, _ = handle(state, "Naqd USD → Naqd UZS", CTX_WITH_CBU)
		reply, _kb, state, _action = handle(state, "100", CTX_WITH_CBU)
		self.assertEqual(state["step"], "konv_cbu_choice")

		reply, _kb, state, _action = handle(state, BTN_KONV_MANUAL, CTX_WITH_CBU)
		self.assertEqual(state["step"], "konv_received")
		self.assertIn("Qancha oldingiz?", reply)

		reply, _kb, state, _action = handle(state, "1300000", CTX_WITH_CBU)
		self.assertEqual(state["received"], 1300000.0)
		self.assertEqual(state["step"], "konv_memo")

	def test_cbu_not_offered_for_non_usd_uzs_pair(self):
		"""CBU assist only applies to a USD<->UZS pair — any other pair falls
		back to the manual both-amounts flow even when ctx['cbu'] has a rate."""
		ctx = {
			**CTX_WITH_CBU,
			"kassas": {
				"Kassa 1": [
					{"account": "Kassa Naqd EUR - M", "label": "Naqd EUR", "currency": "EUR"},
					{"account": "Kassa Naqd UZS - M", "label": "Naqd UZS", "currency": "UZS"},
				]
			},
		}
		state = _pick_kassa(ctx)
		_, _, state, _ = handle(state, BTN_KONV, ctx)
		reply, _kb, state, _action = handle(state, "Naqd EUR → Naqd UZS", ctx)
		self.assertEqual(reply, "Qancha berdingiz? (EUR)")
		reply, _kb, state, _action = handle(state, "100", ctx)
		self.assertEqual(state["step"], "konv_received")


class TestKassadanKassagaFlow(unittest.TestCase):
	def test_happy_path(self):
		state = _pick_kassa()
		reply, kb, state, action = handle(state, BTN_K2K, CTX)
		self.assertEqual(reply, "Qaysi hisobdan yuborasiz?")

		reply, kb, state, action = handle(state, "Naqd UZS", CTX)
		labels = [row[0] for row in kb]
		self.assertIn("Bank UZS", labels)
		self.assertNotIn("Naqd UZS", labels)
		self.assertNotIn("Naqd USD", labels)
		self.assertIn("Yuboruvchi: Kassa 1 / UZS", reply)
		self.assertIn("Qaysi kassaga o'tkazasiz?", reply)

		reply, kb, state, action = handle(state, "Bank UZS", CTX)
		reply, kb, state, action = handle(state, "300000", CTX)
		self.assertIn("300 000 UZS", reply)
		self.assertIn("majburiy", reply)

		reply, kb, state, action = handle(state, "ijara haqi", CTX)
		self.assertIn("300 000 UZS", reply)
		self.assertIn("Tasdiqlaysizmi?", reply)

		reply, kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Kassa Naqd UZS - M",
				"to": "Bank UZS - M",
				"from_amount": 300000.0,
				"memo": "ijara haqi",
			},
		)

	def test_izoh_dash_rejected(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_K2K, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Bank UZS", CTX)
		_, _, state, _ = handle(state, "300000", CTX)
		_reply, _kb, new_state, action = handle(state, "-", CTX)
		self.assertEqual(new_state["step"], "k2k_memo")
		self.assertIsNone(action)

	def test_izoh_suggestion_keyboard_includes_recent_and_presets(self):
		ctx = {**CTX, "recent_memos": ["Ijara to'lovi", "Yoqilg'i"]}
		state = _pick_kassa(ctx)
		_, _, state, _ = handle(state, BTN_K2K, ctx)
		_, _, state, _ = handle(state, "Naqd UZS", ctx)
		_, _, state, _ = handle(state, "Bank UZS", ctx)
		_reply, kb, state, _action = handle(state, "300000", ctx)
		flat = [label for row in kb for label in row]
		self.assertIn("Ijara to'lovi", flat)
		self.assertIn("Yoqilg'i", flat)
		self.assertIn("Ijara", flat)
		self.assertIn("Boshqa…", flat)


class TestKassadanKassagaSeparation(unittest.TestCase):
	"""WP-K9: K2K now targets only OTHER kassas — same-kassa, same-currency
	moves belong to Konvertatsiya (screen B separation)."""

	def test_target_list_excludes_current_kassas_own_leaves(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_K2K, CTX)
		_reply, kb, state, _action = handle(state, "Naqd UZS", CTX)
		labels = [row[0] for row in kb]
		self.assertIn("Bank UZS", labels)
		self.assertNotIn("Naqd UZS", labels)
		self.assertNotIn("Naqd USD", labels)
		self.assertNotIn("PK", labels)

	def test_empty_target_list_returns_to_menu_with_message(self):
		"""Mikas-style single-kassa tenant: every same-currency cash account
		IS a leaf of the only kassa -> no OTHER kassa to send to."""
		state = _pick_kassa(CTX_SINGLE_KASSA)
		_, _, state, _ = handle(state, BTN_K2K, CTX_SINGLE_KASSA)
		reply, kb, new_state, action = handle(state, "Naqd UZS", CTX_SINGLE_KASSA)
		self.assertIn("Boshqa kassa yo'q", reply)
		self.assertEqual(new_state["step"], STEP_MENU)
		self.assertEqual(new_state["kassa"], "Kassa 1")
		self.assertEqual(kb, MENU_KEYBOARD)
		self.assertIsNone(action)


class TestQoldiqHeaders(unittest.TestCase):
	"""WP-K9: Konvertatsiya-direction and K2K-source entry prompts, plus the
	K2K 'Yuboruvchi' prompt, surface a Qoldiq balance header when ctx has it."""

	_CTX_WITH_BALANCES: ClassVar[dict] = {
		**CTX,
		"balances_by_kassa": {
			"Kassa 1": "Naqd UZS: 50 000.00 UZS · Naqd USD: 500.00 USD",
		},
		"balances_by_leaf": {
			"Kassa Naqd UZS - M": "50 000.00 UZS",
		},
	}

	def test_konv_direction_prompt_includes_qoldiq(self):
		state = _pick_kassa(self._CTX_WITH_BALANCES)
		reply, _kb, state, _action = handle(state, BTN_KONV, self._CTX_WITH_BALANCES)
		self.assertTrue(reply.startswith("Qoldiq: "))
		self.assertIn("Naqd UZS: 50 000.00 UZS", reply)
		self.assertIn("Yo'nalishni tanlang:", reply)

	def test_k2k_source_prompt_includes_qoldiq(self):
		state = _pick_kassa(self._CTX_WITH_BALANCES)
		reply, _kb, state, _action = handle(state, BTN_K2K, self._CTX_WITH_BALANCES)
		self.assertTrue(reply.startswith("Qoldiq: "))
		self.assertIn("Qaysi hisobdan yuborasiz?", reply)

	def test_k2k_target_prompt_includes_leaf_balance(self):
		state = _pick_kassa(self._CTX_WITH_BALANCES)
		_, _, state, _ = handle(state, BTN_K2K, self._CTX_WITH_BALANCES)
		reply, _kb, state, _action = handle(state, "Naqd UZS", self._CTX_WITH_BALANCES)
		self.assertIn("Yuboruvchi: Kassa 1 / UZS", reply)
		self.assertIn("Qoldiq: 50 000.00 UZS", reply)

	def test_no_balances_omits_header(self):
		state = _pick_kassa(CTX)
		reply, _kb, state, _action = handle(state, BTN_KONV, CTX)
		self.assertEqual(reply, "Yo'nalishni tanlang:")
		state = _pick_kassa(CTX)
		reply, _kb, state, _action = handle(state, BTN_K2K, CTX)
		self.assertEqual(reply, "Qaysi hisobdan yuborasiz?")


class TestStatement(unittest.TestCase):
	def test_statement_action_returns_to_menu_unchanged(self):
		state = _pick_kassa()
		_reply, _kb, new_state, action = handle(state, "ℹ️ Mening jadvalim", CTX)
		self.assertEqual(action, {"type": "statement"})
		self.assertEqual(new_state["step"], STEP_MENU)
		self.assertEqual(new_state["kassa"], state["kassa"])
		self.assertEqual(new_state["posting_date"], state["posting_date"])


class TestMenuHeaderBalances(unittest.TestCase):
	def test_menu_header_includes_balances_and_cbu_line(self):
		ctx = {
			**CTX,
			"cbu": {"rate": 12950.0, "date": "17.07"},
			"balances_by_kassa": {
				"Kassa 1": "\U0001f4b1 1 USD = 12 950 UZS (CBU 17.07)\nNaqd UZS: 26 991 567 UZS · Naqd USD: 5 244 USD"
			},
		}
		state = _init_state()
		reply, _kb, state, _action = handle(state, "Kassa 1", ctx)
		self.assertIn("CBU 17.07", reply)
		self.assertIn("26 991 567 UZS", reply)

	def test_menu_header_unaffected_when_no_extra(self):
		state = _init_state()
		reply, _kb, state, _action = handle(state, "Kassa 1", CTX)
		self.assertEqual(reply, "Kassa: Kassa 1\nSana: bugun\n\nAmalni tanlang:")


# --------------------------------------------------------------------------- #
# bot.py pure helpers (no frappe import required at module scope — WP-K6 #5)
# --------------------------------------------------------------------------- #
class TestStatementRemarkTruncation(unittest.TestCase):
	def test_none_and_blank_omitted(self):
		self.assertIsNone(_truncate_remark(None))
		self.assertIsNone(_truncate_remark(""))
		self.assertIsNone(_truncate_remark("   "))

	def test_no_remarks_placeholder_omitted(self):
		self.assertIsNone(_truncate_remark("No Remarks"))
		self.assertIsNone(_truncate_remark("no remarks"))

	def test_short_remark_passthrough(self):
		self.assertEqual(_truncate_remark("ijara haqi"), "ijara haqi")

	def test_long_remark_truncated_to_60(self):
		long_remark = "x" * 100
		result = _truncate_remark(long_remark)
		self.assertEqual(len(result), 60)
		self.assertTrue(result.endswith("…"))

	def test_direction_emoji(self):
		self.assertEqual(_direction_emoji(100, 0), "⬆")
		self.assertEqual(_direction_emoji(0, 100), "⬇")


class TestTypedEcho(unittest.TestCase):
	"""WP-K8: confirm screen echoes the RAW typed amount ('Yozganingiz: …')
	only when it differs from the plain formatted number, so a word/shorthand
	misparse is visible before Tasdiqlash."""

	def test_word_amount_echoed(self):
		from stabler.integrations.kassa._flow import _typed_echo

		self.assertEqual(_typed_echo("400ming", 400000, "UZS"), "Yozganingiz: 400ming")
		self.assertEqual(_typed_echo("besh yuz ming", 500000, "UZS"), "Yozganingiz: besh yuz ming")

	def test_plain_digits_not_echoed(self):
		from stabler.integrations.kassa._flow import _typed_echo

		self.assertIsNone(_typed_echo("400 000", 400000, "UZS"))
		self.assertIsNone(_typed_echo("400000", 400000, "UZS"))
		self.assertIsNone(_typed_echo("", 400000, "UZS"))
		self.assertIsNone(_typed_echo(None, 400000, "UZS"))


if __name__ == "__main__":
	unittest.main()
