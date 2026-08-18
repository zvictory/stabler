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

#: The precision ERPNext actually reports for a Journal Entry's money fields on
#: the UZS company this app runs on. MEASURED on genesis-test.local rather than
#: assumed: `JE.precision("total_debit")` is 2, NOT 0, because `currency_precision`
#: is unset and `use_number_format_from_currency` is 0, so `get_field_precision`
#: falls through to the global "#,###.##" (frappe/model/meta.py:910-913). The
#: module's own `base_precision_for("UZS")` says 0 — the two notions disagree, on
#: purpose and in the open; see the note in `_balance_journal_entry`. Both are
#: pinned below so the mismatch cannot drift unnoticed.
DOC_PRECISION = 2


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


def _load(currency: str = BASE):
	"""Load the module under fakes, with the company booking in `currency`.

	The currency is a parameter because `residual_tolerance` is sized from
	`base_precision_for`, which splits the world into 2-decimal currencies and
	whole-unit ones. A file that only ever exercised one of them could not tell a
	tolerance that is right from one that is two orders of magnitude wrong.
	"""
	_COMPANY_VALUES["default_currency"] = currency
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
		return DOC_PRECISION


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
		return DOC_PRECISION

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

	def test_a_real_residual_is_still_booked(self):
		"""The behaviour the module exists for, unchanged.

		A difference the document's own precision can still see is a realized
		exchange gain or loss (IAS 21 §28), not noise, and ERPNext would refuse
		the submit outright over it. Fixing the artefact must not cost this.

		Deliberately NOT described as "one minor unit": on a UZS company the
		minor unit is a whole som, and 0,01 is a hundredth of one. It is booked
		anyway, because the difference is measured at the DOCUMENT's precision
		(2) while the tolerance is sized at the CURRENCY's (0). That gap is the
		subject of ToleranceBoundaryTest below.
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
		"""Far above the tolerance it is an allocation error, and must stay loud."""
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


class ToleranceBoundaryTest(unittest.TestCase):
	"""Exactly where "rounding residual" ends and "allocation error" begins.

	Booking a residual writes to the P&L without anyone being asked, so the line
	has to sit somewhere defensible and it has to be pinned. Before this, the two
	tests that touched it sat 400x inside the boundary and 25x outside it:
	`residual_tolerance` could have been wrong by two orders of magnitude in
	either direction and both stayed green.

	Both currency classes are exercised, because the tolerance is sized from
	`base_precision_for`, which splits them — 0,01-based for USD, whole-unit for
	UZS. Two rows means `residual_tolerance(2, ...)`: 0,04 for USD, 4 for UZS.
	"""

	@classmethod
	def tearDownClass(cls):
		_load(BASE)  # hand the module back booking in the currency it ships with

	def _booked(self, currency: str, debit: float, credit: float) -> list:
		fx = _load(currency)
		doc = _Journal(
			[
				_Row(account="Origin Cash - M", debit=debit),
				_Row(account="Receiver Obligation - M", credit=credit),
			]
		)
		fx.auto_balance_fx_residual(doc)
		return _auto_rows(doc, fx)

	def test_a_two_decimal_currency_books_up_to_four_cents(self):
		self.assertEqual(1, len(self._booked("USD", 100.00, 99.96)), "0,04 is the boundary")

	def test_a_two_decimal_currency_refuses_five_cents(self):
		self.assertEqual([], self._booked("USD", 100.00, 99.95), "0,05 is an allocation error")

	def test_a_whole_unit_currency_books_up_to_four_units(self):
		self.assertEqual(1, len(self._booked(BASE, 100.00, 96.00)), "4 is the boundary")

	def test_a_whole_unit_currency_refuses_five_units(self):
		self.assertEqual([], self._booked(BASE, 100.00, 95.00), "5 is an allocation error")

	def test_the_two_currency_classes_really_are_scaled_apart(self):
		"""Guards the four above: they mean something only while the split holds.

		4,00 is booked in UZS and refused in USD; 0,04 is booked in USD and — on
		the same two rows — booked in UZS too, because UZS tolerates a thousand
		times more. If `base_precision_for` ever stopped splitting the two, half
		of the assertions above would keep passing for the wrong reason.
		"""
		self.assertEqual([], self._booked("USD", 100.00, 96.00), "USD tolerated 4,00")
		self.assertEqual(1, len(self._booked(BASE, 100.00, 99.96)), "UZS refused 0,04")


class HookWiringTest(unittest.TestCase):
	"""A hook nobody registered is not a hook.

	Everything above proves what the function decides. None of it would run on a
	real save if the doc-event entry were dropped, and nothing else in the suite
	would notice — which is how this module reached production with no test at
	all.
	"""

	@classmethod
	def setUpClass(cls):
		# The real mapping, not a text slice of the file. `stabler/hooks.py` is
		# literals and imports with no frappe present, so reading `doc_events`
		# costs nothing and cannot wander into a neighbouring doctype's block —
		# which is exactly what the first version of this test did. It sliced a
		# fixed 900-character window from `"Payment Entry": {`, and Journal
		# Entry's own `before_validate` list begins 875 characters later, inside
		# it. Deleting the Payment Entry hook outright left this test green,
		# because it then matched Journal Entry's copy of the same string.
		cls.doc_events = importlib.import_module("stabler.hooks").doc_events

	def test_it_runs_before_validate_on_both_doctypes(self):
		for doctype in ("Journal Entry", "Payment Entry"):
			with self.subTest(doctype=doctype):
				self.assertIn(
					"stabler.api.fx_balance.auto_balance_fx_residual",
					self.doc_events[doctype]["before_validate"],
					f"{doctype} no longer auto-balances its FX residual on save",
				)

	def test_the_two_doctypes_are_registered_separately(self):
		"""The property the slicing version could not see.

		One registration standing in for both is the whole failure it shipped
		with: drop the Payment Entry hook and Journal Entry's list still contains
		the string being searched for.
		"""
		self.assertIsNot(
			self.doc_events["Journal Entry"]["before_validate"],
			self.doc_events["Payment Entry"]["before_validate"],
			"both doctypes share one list object, so one registration covers both",
		)

	def test_the_module_is_in_the_frappe_free_list(self):
		"""Or `make check` would not gate it and this file would run nowhere."""
		listing = os.path.join(os.path.dirname(_APP), ".github", "frappe-free-tests.txt")
		with open(listing, encoding="utf-8") as handle:
			self.assertIn("stabler.tests.test_fx_balance", handle.read().split())


if __name__ == "__main__":
	unittest.main()
