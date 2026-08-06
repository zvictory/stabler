"""Valuation guard tests, seeded with the two real poisoning incidents.

Every scenario below is a transcription of production data, not an invention:

  * ACC-PINV-2026-01802-1 / R099 — base_rate 20 000 USD on a row whose siblings
    on the same bill were 1.65 USD (12 121x).
  * ACC-SINV-2026-01514 / S187 — incoming_rate 1300 (UZS) where base_rate was
    0.11 (USD); the ratio is the document's own exchange rate.
  * ACC-SINV-2026-01420 / S187 — the control: same day, same item, same
    1300 / 0.11, incoming_rate 0, never poisoned. It must stay legal.

The tests assert WHY each guard exists (a mistyped amount, a currency mix-up,
a cost explosion at the shop floor, a queue nobody watches), so they fail if
the business rule is weakened — not merely if the code is refactored.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from stabler.api import valuation_guard as vg


class _Row:
	def __init__(self, **kwargs):
		for key, val in kwargs.items():
			setattr(self, key, val)


class _Doc:
	def __init__(self, company="Test Company", items=None, **kwargs):
		self.company = company
		self.name = "TEST-DOC-0001"
		self.items = items or []
		for key, val in kwargs.items():
			setattr(self, key, val)

	def get(self, fieldname):
		return getattr(self, fieldname, None)


def _defaults(fieldname, default):
	"""Stand-in for Stabler Settings returning the shipped doctype defaults."""
	return default


class TestPurchaseInvoiceRateGuard(unittest.TestCase):
	"""Shield 1 — the door incident 1 came through."""

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._trailing_avg_base_rate", return_value=1.65)
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_amount_typed_into_rate_field_is_blocked(self, _gate, _set, _avg, mock_throw):
		# ACC-PINV-2026-01802-1: the same item priced 1.65 twice and 20 000 once.
		# The evidence is on the page itself — no purchase history needed.
		doc = _Doc(
			items=[
				_Row(item_code="R099", base_rate=1.65),
				_Row(item_code="R099", base_rate=1.65),
				_Row(item_code="R099", base_rate=20000.0),
			]
		)
		vg.check_purchase_invoice_rates(doc)

		self.assertTrue(mock_throw.called, "a 12 121x rate on a vendor bill must not be postable")
		msg = mock_throw.call_args[0][0]
		self.assertIn("12121", msg, "the message must quantify the error the buyer has to recognise")
		self.assertIn("R099", msg)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._trailing_avg_base_rate", return_value=None)
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_first_purchase_of_an_item_is_never_blocked(self, _gate, _set, _avg, mock_throw):
		# No history means no baseline. Blocking here would stop buyers from ever
		# introducing a new item — the guard must stay silent, not guess.
		doc = _Doc(items=[_Row(item_code="BRAND-NEW", base_rate=20000.0)])
		vg.check_purchase_invoice_rates(doc)
		self.assertFalse(mock_throw.called)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._trailing_avg_base_rate", return_value=1.65)
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_price_rising_below_the_multiple_stays_legal(self, _gate, _set, _avg, mock_throw):
		# A genuine 10x supplier price jump is a business event, not a typo.
		doc = _Doc(items=[_Row(item_code="R099", base_rate=16.5)])
		vg.check_purchase_invoice_rates(doc)
		self.assertFalse(mock_throw.called)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._trailing_avg_base_rate", return_value=1.65)
	@patch("stabler.api.valuation_guard._setting")
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_threshold_comes_from_settings_not_from_code(self, _gate, mock_setting, _avg, mock_throw):
		# Tenants tune their own tolerance. If 50 were hardcoded, raising the
		# setting could not let the same document through — and this test would fail.
		mock_setting.side_effect = lambda field, default: (
			20000.0 if field == "valuation_guard_purchase_rate_multiple" else default
		)
		doc = _Doc(items=[_Row(item_code="R099", base_rate=1.65), _Row(item_code="R099", base_rate=20000.0)])
		vg.check_purchase_invoice_rates(doc)
		self.assertFalse(mock_throw.called)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=False)
	def test_company_without_the_module_is_untouched(self, _gate, mock_throw):
		# Multi-tenant leakage check: code ships to all 7 sites, behaviour must not.
		doc = _Doc(items=[_Row(item_code="R099", base_rate=1.65), _Row(item_code="R099", base_rate=20000.0)])
		vg.check_purchase_invoice_rates(doc)
		self.assertFalse(mock_throw.called)


class TestIncomingRateCurrencyGuard(unittest.TestCase):
	"""Shield 2 — the door incident 2 came through."""

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_transaction_currency_in_incoming_rate_is_blocked(self, _gate, _set, mock_throw):
		# ACC-SINV-2026-01514: incoming_rate 1300 UZS in a USD-denominated field.
		doc = _Doc(
			conversion_rate=11818.18,
			is_return=1,
			items=[_Row(item_code="S187", incoming_rate=1300.0, base_rate=0.11, rate=1300.0)],
		)
		vg.check_incoming_rate_currency(doc)

		self.assertTrue(mock_throw.called, "1300 USD/unit for an item worth 0.11 must not be postable")
		msg = mock_throw.call_args[0][0]
		self.assertIn("11818", msg)
		self.assertIn(
			"exchange rate",
			msg.lower(),
			"when the ratio IS the exchange rate the message must name the cause, not just flag a number",
		)
		self.assertIn("0.11", msg, "the message must state the value that belongs in the field")

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_control_invoice_with_zero_incoming_rate_stays_legal(self, _gate, _set, mock_throw):
		# ACC-SINV-2026-01420 — identical to the poisoned one except incoming_rate 0,
		# which means "let ERPNext value it". That is the correct way to file a return.
		doc = _Doc(
			conversion_rate=11818.18,
			is_return=1,
			items=[_Row(item_code="S187", incoming_rate=0.0, base_rate=0.11, rate=1300.0)],
		)
		vg.check_incoming_rate_currency(doc)
		self.assertFalse(mock_throw.called)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_deliberate_incoming_rate_close_to_cost_stays_legal(self, _gate, _set, mock_throw):
		# Stating the true cost of a returned unit is a legitimate use of the field.
		doc = _Doc(
			conversion_rate=11818.18,
			items=[_Row(item_code="S187", incoming_rate=0.13, base_rate=0.11, rate=1300.0)],
		)
		vg.check_incoming_rate_currency(doc)
		self.assertFalse(mock_throw.called)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=False)
	def test_company_without_the_module_is_untouched(self, _gate, mock_throw):
		doc = _Doc(
			conversion_rate=11818.18,
			items=[_Row(item_code="S187", incoming_rate=1300.0, base_rate=0.11)],
		)
		vg.check_incoming_rate_currency(doc)
		self.assertFalse(mock_throw.called)


class TestStockEntryValuationGuard(unittest.TestCase):
	"""Shield 3 — where incident 1 propagated into the production chain."""

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._bin_valuation_rate", return_value=1.65)
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_poisoned_valuation_cannot_reach_the_shop_floor(self, _gate, _set, _bin, mock_throw):
		# The five stock entries that carried $3 032 535 of phantom cost all
		# consumed a bin still valued at 1.65. This is the cut point.
		se = _Doc(
			items=[_Row(item_code="R099", s_warehouse="Stores - TC", valuation_rate=20000.0, basic_rate=0.0)]
		)
		vg.assert_stock_entry_valuation_sane(se)

		self.assertTrue(mock_throw.called)
		self.assertIn("R099", mock_throw.call_args[0][0])

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._bin_valuation_rate", return_value=0.0)
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_unvalued_bin_is_skipped_not_blocked(self, _gate, _set, _bin, mock_throw):
		# A bin worth 0 is the first-run case that allow_zero_valuation_rate exists
		# for (tests/test_manufacturing_kiosk.py). Blocking here would stop the
		# shift; the guard has no baseline and must abstain.
		se = _Doc(
			items=[_Row(item_code="NEW-FG", t_warehouse="FG - TC", valuation_rate=500.0, basic_rate=0.0)]
		)
		vg.assert_stock_entry_valuation_sane(se)
		self.assertFalse(mock_throw.called)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard._bin_valuation_rate", return_value=1.65)
	@patch("stabler.api.valuation_guard._setting", side_effect=_defaults)
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=True)
	def test_normal_production_entry_passes(self, _gate, _set, _bin, mock_throw):
		se = _Doc(
			items=[_Row(item_code="R099", s_warehouse="Stores - TC", valuation_rate=1.8, basic_rate=0.0)]
		)
		vg.assert_stock_entry_valuation_sane(se)
		self.assertFalse(mock_throw.called)

	@patch("stabler.api.valuation_guard.frappe.throw")
	@patch("stabler.api.valuation_guard.guard_enabled", return_value=False)
	def test_company_without_the_module_is_untouched(self, _gate, mock_throw):
		se = _Doc(
			items=[_Row(item_code="R099", s_warehouse="Stores - TC", valuation_rate=20000.0, basic_rate=0.0)]
		)
		vg.assert_stock_entry_valuation_sane(se)
		self.assertFalse(mock_throw.called)


class TestRepostQueueAlert(unittest.TestCase):
	"""Shield 4 — the silence that let both incidents live for weeks."""

	def _status(self, **kwargs):
		base = {"queued": 0, "errors": [], "in_progress": [], "oldest_queued": ""}
		base.update(kwargs)
		return base

	def _run(self, status, announce):
		from stabler.tasks import repost_queue_alert as rqa

		with (
			patch.object(rqa, "_any_company_guarded", return_value=True),
			patch.object(rqa, "_setting", side_effect=lambda field, default: default),
			patch.object(rqa, "_announce", announce),
			# Pin "now" so the age assertions are about the rule, not the calendar.
			patch.object(rqa, "today", return_value="2026-08-06"),
			patch("stabler.api.repost_monitor.repost_status", return_value=status),
		):
			rqa.check_repost_queue()

	def test_backlog_raises_the_alarm(self):
		announce = MagicMock()
		self._run(self._status(queued=150), announce)
		self.assertTrue(announce.called, "a backed-up queue means valuation corrections are not landing")

	def test_a_single_failed_repost_raises_the_alarm(self):
		# One failed repost is enough: it blocks every repost queued behind it.
		announce = MagicMock()
		self._run(self._status(queued=2, errors=[{"name": "RIV-0001"}]), announce)
		self.assertTrue(announce.called)

	def test_a_stale_queued_repost_raises_the_alarm(self):
		announce = MagicMock()
		self._run(self._status(queued=3, oldest_queued="2026-01-01"), announce)
		self.assertTrue(announce.called)

	def test_healthy_queue_stays_quiet(self):
		# An alarm that fires every night is an alarm nobody reads.
		announce = MagicMock()
		self._run(self._status(queued=3, oldest_queued="2026-08-05"), announce)
		self.assertFalse(announce.called)

	def test_site_without_the_module_is_never_alarmed(self):
		from stabler.tasks import repost_queue_alert as rqa

		announce = MagicMock()
		with (
			patch.object(rqa, "_any_company_guarded", return_value=False),
			patch.object(rqa, "_announce", announce),
		):
			rqa.check_repost_queue()
		self.assertFalse(announce.called)
