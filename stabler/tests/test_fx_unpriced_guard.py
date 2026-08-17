"""A balance may not be revalued at a rate nobody published.

The failure this guards against is silent by construction. ERPNext's
`get_exchange_rate` returns 0.0 when no Currency Exchange row exists
(erpnext/setup/utils.py:145-154), Exchange Rate Revaluation multiplies the
balance by it (exchange_rate_revaluation.py:264-266), and the row's entire book
value comes out as an FX loss with no exception raised anywhere on the path.
USDT is the live instance: `tasks/cbu_rate_refresh.py` has no USDT source, ADR-006
makes a USDT desk an ordinary Cash leaf, and ADR-009 makes revaluation the only
place remittance FX margin is ever recognised — so the fabricated loss lands
straight on profit.

Three layers are asserted, because two of them can be true while the guard does
nothing:

  * the rule (`find_unpriced_positions`) — pure, no Frappe;
  * the wiring (`hooks.py`) — a guard nobody registered is not a guard, and this
    is the assertion that fails if the doc_events entry is ever dropped;
  * the behaviour (`assert_positions_priced`) — it must actually raise, and the
    message must name the currency an operator has to go and price.

Bench-free by design: `make check` does not run the bench set, so a test needing
one would not gate a push. What is NOT proved here is the ERPNext side — that a
real Exchange Rate Revaluation on a real ledger routes through this hook. That
needs a bench.
"""

from __future__ import annotations

import importlib
import types
import unittest
from decimal import Decimal

from stabler.api._fx_revaluation import find_unpriced_positions
from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.fx_revaluation"

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


def _position(**overrides) -> dict:
	position = {
		"account": "Cash - USDT - M",
		"currency": "USDT",
		"balance": 50_000,
		"rate": 12_600,
	}
	position.update(overrides)
	return position


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


class UnpricedPositionRuleTest(unittest.TestCase):
	"""What counts as "would be written off", stated once, without Frappe."""

	def test_money_with_no_rate_is_unpriced(self):
		found = find_unpriced_positions([_position(rate=0)])
		self.assertEqual(len(found), 1)
		self.assertEqual(found[0]["currency"], "USDT")
		self.assertEqual(found[0]["balance"], Decimal("50000"))

	def test_money_with_a_rate_is_left_alone(self):
		self.assertEqual(find_unpriced_positions([_position()]), [])

	def test_drained_account_at_zero_rate_is_not_flagged(self):
		"""The false positive that would make the guard unusable.

		ERPNext deliberately writes rate 0 for zero-balance rows
		(exchange_rate_revaluation.py:286-300). Flagging those would block every
		close on accounts that hold nothing, and the guard would be switched off.
		"""
		self.assertEqual(find_unpriced_positions([_position(balance=0, rate=0)]), [])

	def test_foreign_currency_liability_is_flagged_too(self):
		"""A negative balance is a debt: zeroing it fabricates a gain."""
		found = find_unpriced_positions([_position(balance=-50_000, rate=0)])
		self.assertEqual(len(found), 1)
		self.assertEqual(found[0]["balance"], Decimal("-50000"))

	def test_negative_rate_is_unpriced(self):
		self.assertEqual(len(find_unpriced_positions([_position(rate=-1)])), 1)

	def test_missing_and_garbage_rates_are_unpriced(self):
		"""`get_exchange_rate` returns 0.0, but a None/"" field must not pass."""
		for bad in (None, "", "n/a"):
			with self.subTest(rate=bad):
				self.assertEqual(len(find_unpriced_positions([_position(rate=bad)])), 1)

	def test_only_the_unpriced_rows_come_back(self):
		found = find_unpriced_positions(
			[
				_position(account="Cash - USD - M", currency="USD"),
				_position(account="Cash - USDT - M", rate=0),
				_position(account="Cash - EUR - M", currency="EUR", balance=0, rate=0),
			]
		)
		self.assertEqual([p["account"] for p in found], ["Cash - USDT - M"])

	def test_nothing_to_revalue_is_not_an_error(self):
		self.assertEqual(find_unpriced_positions([]), [])
		self.assertEqual(find_unpriced_positions(None), [])


# ---------------------------------------------------------------------------
# The wiring
# ---------------------------------------------------------------------------


class GuardIsRegisteredTest(unittest.TestCase):
	"""An unregistered guard is indistinguishable from no guard at all."""

	def test_hooks_run_the_guard_on_exchange_rate_revaluation_validate(self):
		hooks = importlib.import_module("stabler.hooks")
		events = hooks.doc_events.get("Exchange Rate Revaluation") or {}
		self.assertIn(
			"stabler.api.fx_revaluation.assert_positions_priced",
			events.get("validate") or [],
			"the guard must run on validate — that is the one event that fires on "
			"both save and submit, for Desk documents as well as our own endpoint",
		)


# ---------------------------------------------------------------------------
# The behaviour
# ---------------------------------------------------------------------------


def _load():
	_SANDBOX.evict(
		_MODULE,
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.approvals",
	)

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.db = types.SimpleNamespace()
	frappe.session = types.SimpleNamespace(user="accountant@example.com")
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn
	frappe.get_cached_value = lambda _dt, _name, _field: "UZS"
	frappe.has_permission = lambda *_a, **_k: True
	frappe.PermissionError = PermissionError
	frappe.ValidationError = _Thrown

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value, precision=None: float(value or 0)
	utils.getdate = lambda value=None: value
	utils.today = lambda: "2026-08-31"
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_a, **_k: None
	common._require_company = lambda company: company
	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: None

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
		}
	)
	return importlib.import_module(_MODULE)


def _doc(rows: list[dict]) -> dict:
	"""An Exchange Rate Revaluation as the hook sees it — company, date, rows."""
	return {
		"company": "Mikas",
		"posting_date": "2026-08-31",
		"accounts": rows,
	}


def _row(**overrides) -> dict:
	row = {
		"account": "Cash - USDT - M",
		"account_currency": "USDT",
		"balance_in_account_currency": 50_000,
		"new_exchange_rate": 12_600,
		"zero_balance": 0,
	}
	row.update(overrides)
	return row


class GuardRefusesTest(unittest.TestCase):
	"""The document must not save. Naming the currency is part of the fix."""

	@classmethod
	def setUpClass(cls):
		cls.api = _load()

	def test_usdt_balance_with_no_rate_is_refused(self):
		with self.assertRaises(_Thrown) as caught:
			self.api.assert_positions_priced(_doc([_row(new_exchange_rate=0)]))
		message = str(caught.exception)
		self.assertIn("USDT", message)
		self.assertIn("Cash - USDT - M", message)
		self.assertIn("2026-08-31", message)
		self.assertIn("UZS", message)  # the base currency the row must be priced in

	def test_one_unpriced_row_refuses_the_whole_document(self):
		"""Not "skip that row": the rest of the revaluation is fine, but posting
		it while a real balance goes unvalued is exactly the half-close that
		hides the problem until the accounts are signed."""
		with self.assertRaises(_Thrown):
			self.api.assert_positions_priced(
				_doc(
					[
						_row(account="Cash - USD - M", account_currency="USD"),
						_row(new_exchange_rate=0),
					]
				)
			)

	def test_fully_priced_document_passes(self):
		self.assertIsNone(self.api.assert_positions_priced(_doc([_row()])))

	def test_drained_usdt_drawer_passes(self):
		"""ERPNext's own zero_balance row carries rate 0 legitimately."""
		self.assertIsNone(
			self.api.assert_positions_priced(
				_doc([_row(balance_in_account_currency=0, new_exchange_rate=0, zero_balance=1)])
			)
		)

	def test_document_without_rows_passes(self):
		self.assertIsNone(self.api.assert_positions_priced(_doc([])))

	def test_hook_accepts_the_method_argument_frappe_passes(self):
		"""doc_events handlers are called as fn(doc, method); a signature that
		takes only `doc` raises TypeError inside validate and would look like an
		unrelated bug."""
		self.assertIsNone(self.api.assert_positions_priced(_doc([_row()]), "validate"))


if __name__ == "__main__":
	unittest.main()
