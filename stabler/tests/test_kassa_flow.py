"""Unit tests for stabler.integrations.kassa._flow (WP-K3, Frappe-free).

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_flow -v
"""

from __future__ import annotations

import unittest

from stabler.integrations.kassa._flow import (
	BTN_CANCEL,
	BTN_CHIQIM,
	BTN_CONFIRM,
	BTN_K2K,
	BTN_KIRIM,
	BTN_KONV,
	BTN_OTHER,
	BTN_SKIP_DEAL,
	MENU_KEYBOARD,
	STEP_MAIN,
	STEP_MENU,
	format_amount,
	handle,
	parse_amount,
	parse_date_ddmmyyyy,
)

CTX = {
	"kassas": {
		"Kassa 1": [
			{"account": "Kassa Naqd UZS - M", "label": "Naqd UZS", "currency": "UZS"},
			{"account": "Kassa Naqd USD - M", "label": "Naqd USD", "currency": "USD"},
		]
	},
	"categories": [
		{"account": f"Expense {i} - M", "label": f"Xarajat {i}"} for i in range(1, 4)
	],
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
}

CTX_NO_DEALS = {**CTX, "deals": []}


def _init_state():
	return {"step": STEP_MAIN, "kassa": None, "posting_date": None}


def _pick_kassa(ctx=CTX):
	state = _init_state()
	reply, kb, state, action = handle(state, "Kassa 1", ctx)
	return state


class TestParseAmount(unittest.TestCase):
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


class TestMainAndMenu(unittest.TestCase):
	def test_pick_kassa_enters_menu(self):
		state = _init_state()
		reply, kb, state, action = handle(state, "Kassa 1", CTX)
		self.assertEqual(state["step"], STEP_MENU)
		self.assertEqual(state["kassa"], "Kassa 1")
		self.assertEqual(kb, MENU_KEYBOARD)
		self.assertIsNone(action)

	def test_unknown_kassa_reprompts(self):
		state = _init_state()
		reply, kb, new_state, action = handle(state, "garbage", CTX)
		self.assertEqual(new_state, state)
		self.assertIsNone(action)

	def test_unknown_menu_text_reprompts_unchanged(self):
		state = _pick_kassa()
		reply, kb, new_state, action = handle(state, "???", CTX)
		self.assertEqual(new_state, state)
		self.assertEqual(kb, MENU_KEYBOARD)
		self.assertIsNone(action)


class TestCancel(unittest.TestCase):
	def test_cancel_from_mid_flow_resets_to_main(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		reply, kb, state, action = handle(state, BTN_CANCEL, CTX)
		self.assertEqual(state["step"], STEP_MAIN)
		self.assertIsNone(state["kassa"])
		self.assertIsNone(action)

	def test_cancel_preserves_posting_date(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001F4DD Qolib ketgan amal", CTX)
		_, _, state, _ = handle(state, "05.07.2026", CTX)
		self.assertEqual(state["posting_date"], "2026-07-05")
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, action = handle(state, BTN_CANCEL, CTX)
		self.assertEqual(state["step"], STEP_MAIN)
		self.assertEqual(state["posting_date"], "2026-07-05")


class TestBackdate(unittest.TestCase):
	def test_sets_date_and_returns_to_menu(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001F4DD Qolib ketgan amal", CTX)
		reply, kb, state, action = handle(state, "05.07.2026", CTX)
		self.assertEqual(state["step"], STEP_MENU)
		self.assertEqual(state["posting_date"], "2026-07-05")
		self.assertIsNone(action)

	def test_invalid_date_reprompts(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001F4DD Qolib ketgan amal", CTX)
		reply, kb, new_state, action = handle(state, "not-a-date", CTX)
		self.assertEqual(new_state, state)

	def test_date_resets_after_one_completed_op(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, "\U0001F4DD Qolib ketgan amal", CTX)
		_, _, state, _ = handle(state, "05.07.2026", CTX)
		self.assertEqual(state["posting_date"], "2026-07-05")

		# Complete a Kirim operation end to end.
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Bank UZS", CTX)
		_, _, state, _ = handle(state, "10000", CTX)
		_, _, state, _ = handle(state, "-", CTX)
		reply, kb, state, action = handle(state, BTN_CONFIRM, CTX)

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
		_, _, state, _ = handle(state, "-", CTX)
		_, _, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertIsNone(action["memo"])

	def test_invalid_amount_reprompts(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_KIRIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Bank UZS", CTX)
		reply, kb, new_state, action = handle(state, "not a number", CTX)
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
		reply, kb, state, action = handle(state, "Xarajat 1", CTX_NO_DEALS)
		# Should skip straight to amount, not the deal step.
		self.assertIn("Summani kiriting", reply)
		_, _, state, _ = handle(state, "20000", CTX_NO_DEALS)
		_, _, state, _ = handle(state, "-", CTX_NO_DEALS)
		_, _, state, action = handle(state, BTN_CONFIRM, CTX_NO_DEALS)
		self.assertIsNone(action["deal"])

	def test_skip_deal_button(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, "Xarajat 1", CTX)
		_, _, state, _ = handle(state, BTN_SKIP_DEAL, CTX)
		_, _, state, _ = handle(state, "10000", CTX)
		_, _, state, _ = handle(state, "-", CTX)
		_, _, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertIsNone(action["deal"])

	def test_other_category_filter(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, BTN_OTHER, CTX)
		reply, kb, state, action = handle(state, "3", CTX)
		self.assertIn(["Xarajat 3"], kb)
		reply, kb, state, action = handle(state, "Xarajat 3", CTX)
		# CTX has deals configured, so it should now prompt for the deal, not amount.
		self.assertIn("Tender", reply)

	def test_other_category_filter_no_match(self):
		state = _pick_kassa()
		_, _, state, _ = handle(state, BTN_CHIQIM, CTX)
		_, _, state, _ = handle(state, "Naqd UZS", CTX)
		_, _, state, _ = handle(state, BTN_OTHER, CTX)
		reply, kb, new_state, action = handle(state, "zzz-no-match", CTX)
		self.assertIn("Topilmadi", reply)


class TestKonvertatsiyaFlow(unittest.TestCase):
	def test_happy_path(self):
		state = _pick_kassa()
		reply, kb, state, action = handle(state, BTN_KONV, CTX)
		self.assertEqual(reply, "Nima oldingiz?")

		reply, kb, state, action = handle(state, "Naqd USD", CTX)
		labels = [row[0] for row in kb]
		self.assertIn("Naqd UZS", labels)
		self.assertNotIn("Naqd USD", labels)

		reply, kb, state, action = handle(state, "Naqd UZS", CTX)
		self.assertEqual(reply, "Qancha oldingiz?")

		reply, kb, state, action = handle(state, "100", CTX)
		self.assertEqual(reply, "Qancha berdingiz?")

		reply, kb, state, action = handle(state, "1250000", CTX)
		self.assertIn("100 USD", reply)
		self.assertIn("1 250 000 UZS", reply)

		reply, kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Kassa Naqd UZS - M",
				"to": "Kassa Naqd USD - M",
				"from_amount": 1250000.0,
				"to_amount": 100.0,
			},
		)


class TestKassadanKassagaFlow(unittest.TestCase):
	def test_happy_path(self):
		state = _pick_kassa()
		reply, kb, state, action = handle(state, BTN_K2K, CTX)
		self.assertEqual(reply, "Qaysi kassadan?")

		reply, kb, state, action = handle(state, "Naqd UZS", CTX)
		labels = [row[0] for row in kb]
		self.assertIn("Bank UZS", labels)
		self.assertNotIn("Naqd UZS", labels)
		self.assertNotIn("Naqd USD", labels)

		reply, kb, state, action = handle(state, "Bank UZS", CTX)
		reply, kb, state, action = handle(state, "300000", CTX)
		self.assertIn("300 000 UZS", reply)

		reply, kb, state, action = handle(state, BTN_CONFIRM, CTX)
		self.assertEqual(
			action,
			{
				"type": "transfer",
				"from": "Kassa Naqd UZS - M",
				"to": "Bank UZS - M",
				"from_amount": 300000.0,
			},
		)


class TestStatement(unittest.TestCase):
	def test_statement_action_returns_to_menu_unchanged(self):
		state = _pick_kassa()
		reply, kb, new_state, action = handle(state, "ℹ️ Mening jadvalim", CTX)
		self.assertEqual(action, {"type": "statement"})
		self.assertEqual(new_state["step"], STEP_MENU)
		self.assertEqual(new_state["kassa"], state["kassa"])
		self.assertEqual(new_state["posting_date"], state["posting_date"])


if __name__ == "__main__":
	unittest.main()
