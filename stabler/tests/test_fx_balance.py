"""The auto-balancer must not invent a residual out of a float artefact.

`fx_balance.auto_balance_fx_residual` is a `before_validate` doc-event on
**Journal Entry and Payment Entry** (hooks.py) — every save and every submit, in
every module, on all seven tenants. It had no test of any kind. This file is the
first, and it exists because the untested part was wrong.

WHAT WENT WRONG. ERPNext accumulates the two totals WITHOUT rounding the running
sum — only each addend is rounded
(journal_entry.py:948, `self.total_debit = flt(self.total_debit) + flt(d.debit, d.precision("debit"))`)
— and then rounds BOTH SIDES before subtracting them
(journal_entry.py:951). `_balance_journal_entry` subtracted the raw accumulators
instead, with `flt()` and no precision. On a three-leg UZS entry that closes
exactly, the two float sums land ~3e-08 apart, so stabler saw a difference
ERPNext did not, decided it was a rounding residual, and appended an Exchange
Gain/Loss row for it. `set_amounts_in_company_currency` then rounded that row to
zero and `validate_debit_credit_amount` refused the whole document:

    ValidationError: Row 4: Both Debit and Credit values cannot be zero

A balanced journal entry, rejected because of an artefact of float addition. It
is not remittance-specific: any multi-leg entry whose base figures are large
enough for one ulp to exceed nothing at all can hit it, and UZS base figures are
in the hundreds of millions as a matter of course. It was found on 2026-08-18
while trying to register a transfer at a rate that carries cents — the flat
12000,00 the bench fixture uses makes every base value a whole number of base
units, which is why the entire suite was green and had always been.

THE FIXTURE'S ONE LOAD-BEARING DETAIL. `_Journal.set_total_debit_credit` below
accumulates unrounded on purpose, copying journal_entry.py:948. Round the running
sum there — as it would be natural to write it — and the totals come out equal,
the artefact never appears, and this file cannot fail on the bug it was written
for. That line is the test.

Frappe-free: the module is loaded under a fake `frappe` so `make check` gates it.
What is NOT proved here is that ERPNext still refuses the zero row it used to
refuse; that lives on a real ledger, in
`test_remittance_accounting_bench.py::test_a_register_posts_at_a_rate_that_carries_cents`.
"""

from __future__ import annotations

import importlib
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.fx_balance"
_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SANDBOX = ModuleSandbox()

#: The company the fake books against, and the account it books to.
COMPANY = "Mikas"
BASE = "UZS"
GAIN_LOSS = "Exchange Gain/Loss - M"
COST_CENTER = "Main - M"

_COMPANY_VALUES = {
	"default_currency": BASE,
	"exchange_gain_loss_account": GAIN_LOSS,
	"round_off_account": None,
	"round_off_cost_center": COST_CENTER,
	"cost_center": COST_CENTER,
}


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Swallowed(Exception):
	"""Raised by the fake `log_error`, so a swallowed bug fails loudly here.

	`auto_balance_fx_residual` catches `Exception` and files it, deliberately:
	auto-balancing must never break a legitimate save. That is right in
	production and useless in a test, where it would turn any exception into a
	pass. So the fake logger raises instead.
	"""


def _flt(value, precision=None):
	"""frappe.utils.flt, to the extent this module uses it."""
	try:
		number = float(value or 0)
	except (TypeError, ValueError):
		return 0.0
	return round(number, precision) if precision is not None else number


def _load():
	_SANDBOX.evict(_MODULE, "frappe", "frappe.utils")

	frappe = types.ModuleType("frappe")
	frappe._ = lambda text: text
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	frappe.get_cached_value = lambda doctype, name, field: _COMPANY_VALUES.get(field)
	frappe.get_traceback = lambda: "traceback"

	def _log_error(title=None, message=None):
		raise _Swallowed(f"{title}: {message}")

	frappe.log_error = _log_error

	utils = types.ModuleType("frappe.utils")
	utils.flt = _flt
	frappe.utils = utils

	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})
	return importlib.import_module(_MODULE)


class _Row:
	"""One Journal Entry Account row, addressed the way the module addresses it."""

	def __init__(self, **fields):
		self.account = fields.get("account", "Some Account - M")
		self.cost_center = fields.get("cost_center")
		self.user_remark = fields.get("user_remark")
		self.debit = fields.get("debit", 0.0)
		self.credit = fields.get("credit", 0.0)
		self.debit_in_account_currency = fields.get("debit_in_account_currency", 0.0)
		self.credit_in_account_currency = fields.get("credit_in_account_currency", 0.0)

	def precision(self, _fieldname):
		return 2


class _Journal:
	"""A Journal Entry as `before_validate` sees it."""

	doctype = "Journal Entry"

	def __init__(self, rows):
		self.company = COMPANY
		self.accounts = list(rows)
		self.total_debit = 0.0
		self.total_credit = 0.0

	def get(self, fieldname, default=None):
		return getattr(self, fieldname, default)

	def set(self, fieldname, value):
		setattr(self, fieldname, value)

	def append(self, fieldname, row):
		getattr(self, fieldname).append(_Row(**row))

	def precision(self, _fieldname):
		return 2

	def set_total_debit_credit(self):
		"""Copied from erpnext journal_entry.py:942-953, artefact and all.

		The running sum is NOT rounded — only each addend is. That is what makes
		`total_credit` land at 148160262.20999998 for three legs that close
		exactly, and it is the entire reason this file exists. Rounding the
		accumulator here would be tidier and would make the test worthless.
		"""
		self.total_debit = 0.0
		self.total_credit = 0.0
		for row in self.accounts:
			self.total_debit = _flt(self.total_debit) + _flt(row.debit, row.precision("debit"))
			self.total_credit = _flt(self.total_credit) + _flt(row.credit, row.precision("credit"))


def _auto_rows(doc, module) -> list:
	return [row for row in doc.accounts if (row.user_remark or "") == module._JE_MARKER]


class JournalResidualTest(unittest.TestCase):
	"""What counts as a residual worth booking, and what is only float noise."""

	@classmethod
	def setUpClass(cls):
		cls.fx = _load()

	def test_a_float_artefact_is_not_a_residual(self):
		"""The defect, pinned with the figures that produced it.

		A register posting for a 12.000,99 USD transfer into a UZS-base company
		at 12.345,67: cash 148.160.262,21 against an obligation of
		146.693.349,70 and a deferred commission of 1.466.912,51. Those two add
		to the first EXACTLY — in Decimal, and in the arithmetic that built them.
		In float64 they land 2,98e-08 short, which is what ERPNext's unrounded
		accumulator carries and what this module used to call a rounding
		residual. The row it appended rounded straight back to zero and ERPNext
		refused the entry.
		"""
		doc = _Journal(
			[
				_Row(account="Origin Cash - M", debit=148160262.21),
				_Row(account="Deferred Commission - M", credit=1466912.51),
				_Row(account="Receiver Obligation - M", credit=146693349.70),
			]
		)

		self.fx.auto_balance_fx_residual(doc)

		self.assertEqual(
			[],
			_auto_rows(doc, self.fx),
			"a balanced entry was given an Exchange Gain/Loss row for a float artefact; "
			"ERPNext rounds that row to zero and then refuses the whole document",
		)
		self.assertEqual(3, len(doc.accounts))

	def test_the_fixture_really_does_produce_the_artefact(self):
		"""Guards the test above: it only means anything while the sums differ.

		Without this, tidying the figures into round numbers would leave a green
		test that could never fail — and rounding the accumulator in
		`set_total_debit_credit` would do the same while looking like a cleanup.
		"""
		doc = _Journal(
			[
				_Row(debit=148160262.21),
				_Row(credit=1466912.51),
				_Row(credit=146693349.70),
			]
		)
		doc.set_total_debit_credit()

		self.assertNotEqual(
			doc.total_debit,
			doc.total_credit,
			"these legs re-add exactly, so this fixture cannot see the defect",
		)
		self.assertEqual(
			round(doc.total_debit, 2),
			round(doc.total_credit, 2),
			"these legs do not close at all — the fixture is simply wrong",
		)

	def test_a_real_sub_unit_residual_is_still_booked(self):
		"""The behaviour the module exists for, unchanged.

		A difference that survives rounding to the base currency's minor unit is
		a realized exchange gain or loss (IAS 21 §28), not noise, and ERPNext
		would otherwise refuse the submit outright. Fixing the artefact must not
		cost this.
		"""
		doc = _Journal(
			[
				_Row(account="Origin Cash - M", debit=100.00),
				_Row(account="Receiver Obligation - M", credit=99.99),
			]
		)

		self.fx.auto_balance_fx_residual(doc)

		booked = _auto_rows(doc, self.fx)
		self.assertEqual(1, len(booked), "a real 0,01 residual was not booked")
		self.assertEqual(GAIN_LOSS, booked[0].account)
		self.assertAlmostEqual(0.01, booked[0].credit, places=2)

	def test_a_real_imbalance_is_left_for_erpnext_to_refuse(self):
		"""Above the tolerance it is an allocation error, and must stay loud."""
		doc = _Journal(
			[
				_Row(account="Origin Cash - M", debit=1000.00),
				_Row(account="Receiver Obligation - M", credit=900.00),
			]
		)

		self.fx.auto_balance_fx_residual(doc)

		self.assertEqual([], _auto_rows(doc, self.fx))

	def test_the_auto_row_is_replaced_rather_than_stacked(self):
		"""Idempotence, which a `before_validate` hook cannot do without.

		It runs again on every save and again on submit. A second pass that
		appended rather than replaced would grow one Exchange Gain/Loss row per
		save until the entry no longer balanced at all.
		"""
		doc = _Journal(
			[
				_Row(account="Origin Cash - M", debit=100.00),
				_Row(account="Receiver Obligation - M", credit=99.99),
			]
		)

		self.fx.auto_balance_fx_residual(doc)
		self.fx.auto_balance_fx_residual(doc)

		self.assertEqual(1, len(_auto_rows(doc, self.fx)))


class HookWiringTest(unittest.TestCase):
	"""A hook nobody registered is not a hook.

	Everything above proves what the function decides. None of it would run on a
	real save if the doc-event entry were dropped, and nothing else in the suite
	would notice — which is how this module reached production with no test at
	all.
	"""

	@classmethod
	def setUpClass(cls):
		with open(os.path.join(_APP, "hooks.py"), encoding="utf-8") as handle:
			cls.hooks = handle.read()

	def test_it_runs_before_validate_on_both_doctypes(self):
		self.assertIn("stabler.api.fx_balance.auto_balance_fx_residual", self.hooks)
		for doctype in ("Journal Entry", "Payment Entry"):
			with self.subTest(doctype=doctype):
				start = self.hooks.index(f'"{doctype}": {{')
				block = self.hooks[start : start + 900]
				before_validate = block[
					block.index("before_validate") : block.index("]", block.index("before_validate"))
				]
				self.assertIn(
					"stabler.api.fx_balance.auto_balance_fx_residual",
					before_validate,
					f"{doctype} no longer auto-balances its FX residual on save",
				)

	def test_the_module_is_in_the_frappe_free_list(self):
		"""Or `make check` would not gate it and this file would run nowhere."""
		listing = os.path.join(os.path.dirname(_APP), ".github", "frappe-free-tests.txt")
		with open(listing, encoding="utf-8") as handle:
			self.assertIn("stabler.tests.test_fx_balance", handle.read().split())


if __name__ == "__main__":
	unittest.main()
