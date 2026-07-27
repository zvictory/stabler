"""Unit tests for stabler.integrations.kassa.shadow_flow (WP-S4b, Frappe-free)."""

from __future__ import annotations

import unittest

from stabler.integrations.kassa import shadow_flow as sf
from stabler.integrations.kassa.shadow_flow import (
    BTN_CHIQIM,
    BTN_CONFIRM,
    BTN_KIRIM,
    BTN_KONV,
    BTN_KONV_NAQD_KARTA,
    BTN_KONV_NAQD_USD,
    BTN_KONV_USD_KARTA,
    BTN_PK,
    BTN_SOM,
    BTN_UNDO,
    compute_deltas,
    format_balance,
    handle,
)

CTX = {"balances": {"nakit": 402_250_000, "pk": 3_000_000, "usd": 400}}


class TestFormat(unittest.TestCase):
    def test_balance_spd(self):
        s = format_balance(CTX["balances"])
        self.assertIn("402 250 000.00 s", s)
        self.assertIn("3 000 000.00 p", s)
        self.assertIn("400.00 d", s)


class TestDeltas(unittest.TestCase):
    def test_kirim_multi(self):
        p = {"op": "kirim", "legs": [
            {"kassa": "nakit", "amount": 2_000_000}, {"kassa": "pk", "amount": 3_000_000},
            {"kassa": "usd", "amount": 500}]}
        self.assertEqual(compute_deltas(p), [
            {"kassa": "nakit", "delta": 2_000_000.0},
            {"kassa": "pk", "delta": 3_000_000.0},
            {"kassa": "usd", "delta": 500.0}])

    def test_chiqim_negative(self):
        p = {"op": "chiqim", "legs": [{"kassa": "nakit", "amount": 100_000}]}
        self.assertEqual(compute_deltas(p), [{"kassa": "nakit", "delta": -100_000.0}])

    def test_konv_buy(self):
        p = {"op": "konversiya", "dir": "buy", "source": "nakit", "amount": 500, "rate": 12900}
        self.assertEqual(compute_deltas(p), [
            {"kassa": "nakit", "delta": -6_450_000.0}, {"kassa": "usd", "delta": 500.0}])

    def test_k2k(self):
        p = {"op": "kassalararo", "from": "nakit", "to": "pk", "amount": 2_000_000}
        self.assertEqual(compute_deltas(p), [
            {"kassa": "nakit", "delta": -2_000_000.0}, {"kassa": "pk", "delta": 2_000_000.0}])


class TestFlowKirim(unittest.TestCase):
    def test_full_happy_path(self):
        # menu -> pick Kirim
        reply, _kb, st, act = handle({}, BTN_KIRIM, CTX)
        self.assertEqual(st["step"], "await_text")
        self.assertEqual(st["op"], "kirim")
        # free text (multi-leg, has counterparty) -> confirm
        reply, _kb, st, act = handle(st, "Mijozdan 2 mln naqd, 3 mln karta va 500 dollar oldim", CTX)
        self.assertEqual(st["step"], "confirm")
        self.assertIn("Kirim:", reply)
        self.assertIn("+2 000 000.00 s", reply)
        self.assertIn("Shundaymi?", reply)
        self.assertIsNone(act)
        # confirm -> record action
        reply, _kb, st, act = handle(st, BTN_CONFIRM, CTX)
        self.assertIsNotNone(act)
        self.assertEqual(act["type"], "record")
        self.assertEqual(act["counterparty"], "Mijoz")
        self.assertEqual(act["deltas"], [
            {"kassa": "nakit", "delta": 2_000_000.0},
            {"kassa": "pk", "delta": 3_000_000.0},
            {"kassa": "usd", "delta": 500.0}])
        self.assertEqual(st["step"], "menu")

    def test_missing_counterparty_asks_once(self):
        _, _, st, _ = handle({}, BTN_KIRIM, CTX)
        reply, _kb, st, act = handle(st, "600 ming naqd", CTX)
        self.assertEqual(st["step"], "await_slot")
        self.assertEqual(st["slot"], "kirim_from")
        self.assertIn("Kimdan", reply)
        # answer the single question -> confirm
        reply, _kb, st, act = handle(st, "Ali", CTX)
        self.assertEqual(st["step"], "confirm")
        reply, _kb, st, act = handle(st, BTN_CONFIRM, CTX)
        self.assertEqual(act["counterparty"], "Ali")
        self.assertEqual(act["deltas"], [{"kassa": "nakit", "delta": 600_000.0}])


class TestFlowKonv(unittest.TestCase):
    def test_buy_usd_button_dir_then_amount_rate(self):
        # Konvertatsiya -> direction buttons
        _reply, kb, st, act = handle({}, BTN_KONV, CTX)
        self.assertEqual(st["step"], "await_konv_dir")
        self.assertIn(BTN_KONV_NAQD_USD, [b for row in kb for b in row])
        # pick Naqd -> Dollar (buy from cash), then just amount + rate
        _reply, kb, st, act = handle(st, BTN_KONV_NAQD_USD, CTX)
        self.assertEqual(st["step"], "await_konv_amt")
        _reply, kb, st, act = handle(st, "500 12900", CTX)
        self.assertEqual(st["step"], "confirm")
        _reply, kb, st, act = handle(st, BTN_CONFIRM, CTX)
        self.assertEqual(act["deltas"], [
            {"kassa": "nakit", "delta": -6_450_000.0}, {"kassa": "usd", "delta": 500.0}])

    def test_same_currency_transfer_via_konv(self):
        # Naqd → Karta is a same-currency move: ask amount only (no rate), booked
        # as a kassalararo transfer.
        _, _, st, _ = handle({}, BTN_KONV, CTX)
        _, _, st, _ = handle(st, BTN_KONV_NAQD_KARTA, CTX)
        self.assertEqual(st["step"], "await_konv_amt")
        _reply, _kb, st, act = handle(st, "2 mln", CTX)
        self.assertEqual(st["step"], "confirm")
        _reply, _kb, st, act = handle(st, BTN_CONFIRM, CTX)
        self.assertEqual(act["deltas"], [
            {"kassa": "nakit", "delta": -2_000_000.0}, {"kassa": "pk", "delta": 2_000_000.0}])

    def test_sell_usd_to_card_with_dollar_sign(self):
        _, _, st, _ = handle({}, BTN_KONV, CTX)
        _, _, st, _ = handle(st, BTN_KONV_USD_KARTA, CTX)  # Dollar -> Karta (sell)
        self.assertEqual(st["step"], "await_konv_amt")
        _reply, _kb, st, act = handle(st, "100$ 12600", CTX)
        self.assertEqual(st["step"], "confirm")
        _reply, _kb, st, act = handle(st, BTN_CONFIRM, CTX)
        self.assertEqual(act["deltas"], [
            {"kassa": "usd", "delta": -100.0}, {"kassa": "pk", "delta": 1_260_000.0}])


class TestQuickPack(unittest.TestCase):
    def test_confirm_has_no_yangi_qoldiq(self):
        # 'Yangi qoldiq' projection was removed from the confirm screen.
        _, _, st, _ = handle({}, BTN_KIRIM, CTX)
        reply, _kb, st, _act = handle(st, "Mijozdan 2 mln naqd", CTX)
        self.assertEqual(st["step"], "confirm")
        self.assertNotIn("Yangi qoldiq", reply)
        self.assertIn("Shundaymi?", reply)

    def test_negative_warning(self):
        ctx = {"balances": {"nakit": 100_000, "pk": 0, "usd": 0}}
        _, _, st, _ = handle({}, BTN_CHIQIM, ctx)
        reply, _kb, st, _act = handle(st, "5 mln naqd ijaraga", ctx)
        self.assertEqual(st["step"], "confirm")
        self.assertIn("Manfiy", reply)

    def test_yana_reuses_last_cp(self):
        ctx = {"balances": {}, "last_cp": "Ali"}
        _, _, st, _ = handle({}, BTN_KIRIM, ctx)
        _reply, _kb, st, act = handle(st, "yana 200 ming naqd", ctx)
        self.assertEqual(st["step"], "confirm")
        _reply, _kb, st, act = handle(st, BTN_CONFIRM, ctx)
        self.assertEqual(act["counterparty"], "Ali")

    def test_last_cp_chip_offered(self):
        ctx = {"balances": {}, "last_cp": "Ali"}
        _, _, st, _ = handle({}, BTN_KIRIM, ctx)
        _reply, kb, st, _act = handle(st, "200 ming naqd", ctx)
        self.assertEqual(st["slot"], "kirim_from")
        self.assertIn("Ali", [b for row in kb for b in row])

    def test_undo_action(self):
        _reply, _kb, _st, act = handle({"step": "menu"}, BTN_UNDO, CTX)
        self.assertEqual(act, {"type": "undo_last"})


class TestOpening(unittest.TestCase):
    def test_opening_flow(self):
        from stabler.integrations.kassa.shadow_flow import BTN_OPENING
        _, _, st, _ = handle({"step": "menu"}, BTN_OPENING, CTX)
        self.assertEqual(st["step"], "await_opening")
        _reply, _kb, st, act = handle(st, "402 mln naqd, 3 mln karta, 400 dollar", CTX)
        self.assertEqual(st["step"], "confirm_opening")
        self.assertIsNone(act)
        _reply, _kb, st, act = handle(st, BTN_CONFIRM, CTX)
        self.assertEqual(act["type"], "set_opening")
        self.assertEqual(act["openings"], [
            {"kassa": "nakit", "amount": 402_000_000.0},
            {"kassa": "pk", "amount": 3_000_000.0},
            {"kassa": "usd", "amount": 400.0}])
        self.assertEqual(st["step"], "menu")


if __name__ == "__main__":
    unittest.main()
