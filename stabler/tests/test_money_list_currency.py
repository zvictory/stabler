"""What the Amount column on /money/expenses and /money/transfers is allowed to claim.

A currency label is not decoration. Rendered next to a number it is a *claim
about what the number counts*, and the list column made two claims it could not
support (council finding P0-MONEY-1):

1. **It added two currencies into one number.** The amount came from
   ``SUM(credit_in_account_currency)`` over every credit leg of the voucher.
   ``credit_in_account_currency`` is denominated in *that leg's* account
   currency, so on any multi-currency voucher the sum was
   ``1 000 000 UZS + 0.02 USD`` — 1 000 000.02 of nothing. A total that adds two
   currencies is not a total; it is a typographic accident that looks like money.

2. **It picked the label at random.** The currency came from a subquery with
   ``LIMIT 1`` and no ``ORDER BY``, so which of the voucher's currencies got to
   name the sum was whatever the storage engine handed back first. The same row
   could render ``$1,000,000.02`` today and ``1 000 000,02 сўм`` after a table
   rebuild, with neither figure ever having existed.

The second leg was very often not a leg the user entered at all:
``stabler.api.fx_balance`` books a ``fx-rounding-auto`` residual on multi-currency
vouchers, in the COMPANY currency, to close a sub-unit base-currency gap. Every
other reader in the codebase already treats it as a GL detail rather than part of
the transaction — ``money._je_detail`` flags it ``is_fx_rounding`` (money.py),
``update_journal_entry`` drops it before rebuilding the account table, and
``Expenses.vue`` / ``Transfers.vue`` / ``JournalEntryDrawer.vue`` filter it out of
the leg table. The list column was the last reader that still counted it.

So two rules, and the tests below are named for them rather than for the branches
they take:

* the residual leg is never part of the amount, and
* a sum may carry a currency label only when every leg it added is in that
  currency. When the legs genuinely span more than one, no single-currency total
  exists — the endpoint reports the voucher's BASE-currency equivalent (the
  translation ERPNext already stored on each leg) and marks it as such, rather
  than inventing a figure in a currency of its own choosing.

Bench-free by construction: ``list_bank_entries`` is driven against a hand-built
``frappe`` whose ``db.sql`` serves canned rows, so the decision under test is the
real endpoint's, not a re-implementation of it, and ``make check`` gates it.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_money_list_currency -v
"""

from __future__ import annotations

import datetime
import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


#: The remark ``stabler.api.fx_balance`` stamps on the auto-balancing leg
#: (``fx_balance._JE_MARKER``). Spelled out here rather than imported, so that
#: renaming the marker has to be a deliberate act in both places instead of a
#: test that silently stops testing anything.
FX_REMARK = "fx-rounding-auto"


def _je_row(name, *, base_currency="UZS", total_credit=0.0, total_debit=None):
	"""One row as the list query returns it, before the amount is decided."""
	return {
		"name": name,
		"posting_date": datetime.date(2026, 8, 19),
		"voucher_type": "Bank Entry",
		"user_remark": None,
		"crm_deal": None,
		"commercial_invoice": None,
		"import_truck": None,
		"import_container": None,
		"import_category": None,
		"total_debit_base": total_debit if total_debit is not None else total_credit,
		"total_credit_base": total_credit,
		"multi_currency": 1,
		"docstatus": 1,
		"entry_kind": "Expense",
		"base_currency": base_currency,
	}


def _leg(parent, currency, amount, amount_base, *, user_remark=None):
	"""One credit leg of a Journal Entry.

	``amount`` is in ``currency``; ``amount_base`` is ERPNext's own translation of
	it into the company currency. Keeping both is the whole point: the base
	amounts are the only figures from different legs that may legitimately be
	added together.
	"""
	return {
		"parent": parent,
		"account_currency": currency,
		"amount": amount,
		"amount_base": amount_base,
		"user_remark": user_remark,
	}


#: The council's own example, in the shape the database stores it: a USD leg and
#: a UZS leg, both credits, on one voucher in a UZS-base company.
MIXED_LEGS = [
	_leg("JV-0001", "USD", 100.0, 1_233_500.0),
	_leg("JV-0001", "UZS", 1_000_000.0, 1_000_000.0),
]


def _load_money(*, je_rows, legs):
	"""Import ``stabler.api.money`` against a hand-built ``frappe``.

	Returns ``(module, ctx)``; ``ctx.queries`` records every statement issued, so
	a test can assert what the endpoint asked the database as well as what it did
	with the answer.
	"""
	_SANDBOX.evict(
		"stabler.api.money",
		"stabler.api._common",
		"stabler.api.approvals",
		"stabler.api.supplier_payment_guard",
		"frappe",
		"frappe.utils",
		"frappe.rate_limiter",
		"erpnext",
		"erpnext.setup",
		"erpnext.setup.utils",
	)

	ctx = types.SimpleNamespace(queries=[])

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.message_log = []

	class _ValidationError(Exception):
		pass

	frappe.ValidationError = _ValidationError
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
	frappe.TimestampMismatchError = type("TimestampMismatchError", (_ValidationError,), {})

	def _throw(message, exc=None, *args, **kwargs):
		raise (exc or _ValidationError)(str(message))

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: lambda fn: fn
	frappe.session = types.SimpleNamespace(user="accountant@example.com")
	frappe.get_roles = lambda _user=None: []
	frappe.local = types.SimpleNamespace(response={})
	frappe.log_error = lambda *a, **k: None
	frappe.get_all = lambda *a, **k: []
	frappe.get_meta = lambda doctype: types.SimpleNamespace(has_field=lambda f: True)

	def _sql(query, params=None, **kwargs):
		ctx.queries.append((query, params))
		# The list query is the only one that opens `tabJournal Entry` under the
		# alias `je`; both statements mention `tabJournal Entry Account`, so the
		# child table is not a discriminator.
		if "`tabJournal Entry` je" not in query:
			return [dict(r) for r in legs]

		rows = [dict(r) for r in je_rows]
		if "SUM(credit_in_account_currency)" in query:
			# The statement is asking the DATABASE to decide the amount, so the
			# double has to answer the way MariaDB would — otherwise this test
			# cannot be red for the defect it exists to describe. Two faithful
			# details: the SUM has no currency and no `user_remark` predicate, so
			# every positive credit leg is added whatever unit it is in; and the
			# label comes from `LIMIT 1` with no `ORDER BY`, which is storage
			# order, modelled here as fixture order.
			for row in rows:
				mine = [leg for leg in legs if leg["parent"] == row["name"] and leg["amount"] > 0]
				row["total_amount"] = sum(leg["amount"] for leg in mine) if mine else row["total_credit_base"]
				row["currency"] = mine[0]["account_currency"] if mine else row["base_currency"]
		return rows

	frappe.db = types.SimpleNamespace(
		sql=_sql,
		has_column=lambda doctype, column: True,
		get_value=lambda *a, **k: None,
		exists=lambda *a, **k: True,
	)

	utils = types.ModuleType("frappe.utils")

	def _flt(value, precision=None):
		try:
			out = float(value or 0)
		except (TypeError, ValueError):
			out = 0.0
		return round(out, precision) if precision is not None else out

	def _getdate(value=None):
		if value in (None, ""):
			return datetime.date(2026, 8, 19)
		if isinstance(value, datetime.date):
			return value
		return datetime.date.fromisoformat(str(value)[:10])

	utils.flt = _flt
	utils.cint = lambda value=0: int(float(value or 0))
	utils.getdate = _getdate
	utils.today = lambda: "2026-08-19"
	utils.formatdate = lambda value, fmt=None: str(value)
	utils.nowdate = lambda: "2026-08-19"
	frappe.utils = utils

	rate_limiter = types.ModuleType("frappe.rate_limiter")
	rate_limiter.rate_limit = lambda *a, **k: lambda fn: fn
	frappe.rate_limiter = rate_limiter

	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: company
	common._assert_can_read = lambda *a, **k: None
	common._assert_can_write = lambda *a, **k: None
	common.check_concurrency = lambda *a, **k: None

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: None

	guard = types.ModuleType("stabler.api.supplier_payment_guard")
	guard.assert_supplier_payment_currency = lambda *a, **k: None

	erpnext = types.ModuleType("erpnext")
	erpnext_setup = types.ModuleType("erpnext.setup")
	erpnext_utils = types.ModuleType("erpnext.setup.utils")
	erpnext_utils.get_exchange_rate = lambda frm, to, date=None: 0.0
	erpnext.setup = erpnext_setup
	erpnext_setup.utils = erpnext_utils

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"frappe.rate_limiter": rate_limiter,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.api.supplier_payment_guard": guard,
			"erpnext": erpnext,
			"erpnext.setup": erpnext_setup,
			"erpnext.setup.utils": erpnext_utils,
		}
	)
	return importlib.import_module("stabler.api.money"), ctx


def _one_row(*, je_rows, legs):
	money, ctx = _load_money(je_rows=je_rows, legs=legs)
	rows = money.list_bank_entries(company="Test Co")
	return rows[0], ctx


class MixedCurrencyTotalTest(unittest.TestCase):
	"""A voucher whose credit side really does span two currencies.

	The council's example, in the shape the database stores it: a USD leg and a
	UZS leg, both credits, on one voucher in a UZS-base company. There is no
	honest single-currency total here, and the previous implementation produced
	one anyway by adding the two raw leg amounts.
	"""

	def test_the_two_leg_amounts_are_never_added_together(self):
		# 100 + 1 000 000 = 1 000 100 is the number the old SUM produced. It is
		# not a quantity of dollars, not a quantity of so'm, and not a quantity
		# of anything else: 100 of one unit and 1 000 000 of another were added
		# as if the units were the same.
		row, _ = _one_row(
			je_rows=[_je_row("JV-0001", total_credit=2_233_500.0)],
			legs=MIXED_LEGS,
		)

		self.assertNotEqual(row["total_amount"], 1_000_100.0)

	def test_a_mixed_voucher_reports_its_base_currency_equivalent(self):
		# What CAN be produced honestly: the sum of the base-currency amounts
		# ERPNext already translated each leg to, labelled with the base
		# currency. 1 233 500 + 1 000 000 so'm.
		row, _ = _one_row(
			je_rows=[_je_row("JV-0001", total_credit=2_233_500.0)],
			legs=MIXED_LEGS,
		)

		self.assertEqual(row["total_amount"], 2_233_500.0)
		self.assertEqual(row["currency"], "UZS")

	def test_a_mixed_voucher_says_that_the_figure_is_a_conversion(self):
		# Without this flag a converted figure is indistinguishable from a leg
		# total, and the screen cannot tell the reader that the amount shown is
		# not the amount anybody typed.
		row, _ = _one_row(
			je_rows=[_je_row("JV-0001", total_credit=2_233_500.0)],
			legs=MIXED_LEGS,
		)

		self.assertEqual(row.get("amount_is_base_equivalent"), 1)

	def test_the_answer_does_not_depend_on_which_leg_the_database_returns_first(self):
		# The defect's second half: the label came from `LIMIT 1` with no
		# `ORDER BY`. Row order is not part of the question being asked, so it
		# must not be part of the answer — and the fix does not achieve that by
		# sorting, it achieves it by only ever labelling a sum whose legs all
		# agree.
		forward, _ = _one_row(
			je_rows=[_je_row("JV-0001", total_credit=2_233_500.0)],
			legs=MIXED_LEGS,
		)
		reversed_, _ = _one_row(
			je_rows=[_je_row("JV-0001", total_credit=2_233_500.0)],
			legs=list(reversed(MIXED_LEGS)),
		)

		self.assertEqual(
			(forward["total_amount"], forward["currency"]),
			(reversed_["total_amount"], reversed_["currency"]),
		)


class FxRoundingLegTest(unittest.TestCase):
	"""The synthetic leg `fx_balance` books, and why the list must not count it.

	It is not money anybody spent. It is a sub-unit correction booked in the
	COMPANY currency so the voucher balances in the ledger, which is exactly why
	it turned single-currency vouchers into mixed ones: the user's leg is in the
	account currency, the correction is in the base currency.
	"""

	def test_the_auto_rounding_leg_is_not_part_of_the_amount(self):
		# The council's rendering: a 1 000 000 сўм expense in a USD-base company
		# showing as $1,000,000.02. The 0.02 is the residual; without it the
		# voucher has exactly one credit currency and a perfectly honest total.
		row, _ = _one_row(
			je_rows=[_je_row("JV-0002", base_currency="USD", total_credit=81.09)],
			legs=[
				_leg("JV-0002", "UZS", 1_000_000.0, 81.07),
				_leg("JV-0002", "USD", 0.02, 0.02, user_remark=FX_REMARK),
			],
		)

		self.assertEqual(row["total_amount"], 1_000_000.0)
		self.assertEqual(row["currency"], "UZS")

	def test_dropping_the_residual_leaves_a_real_single_currency_total(self):
		# Not a base equivalent: once the synthetic leg is gone this voucher has
		# one currency, so the figure shown is the amount the user actually
		# entered rather than a conversion of it.
		row, _ = _one_row(
			je_rows=[_je_row("JV-0002", base_currency="USD", total_credit=81.09)],
			legs=[
				_leg("JV-0002", "UZS", 1_000_000.0, 81.07),
				_leg("JV-0002", "USD", 0.02, 0.02, user_remark=FX_REMARK),
			],
		)

		self.assertEqual(row.get("amount_is_base_equivalent"), 0)


class OrdinaryVoucherTest(unittest.TestCase):
	"""The common case must be left exactly as it was.

	A fix that reported every voucher as a base-currency conversion would satisfy
	"never mixes currencies" and be a worse screen than the bug: a USD transfer
	must still say USD.
	"""

	def test_a_single_currency_voucher_reports_its_own_currency_and_amount(self):
		row, _ = _one_row(
			je_rows=[_je_row("JV-0003", total_credit=1_000_000.0)],
			legs=[_leg("JV-0003", "UZS", 1_000_000.0, 1_000_000.0)],
		)

		self.assertEqual(row["total_amount"], 1_000_000.0)
		self.assertEqual(row["currency"], "UZS")
		self.assertEqual(row.get("amount_is_base_equivalent"), 0)

	def test_several_legs_in_one_currency_are_still_added_up(self):
		# Adding two UZS legs is not the defect; adding a UZS leg to a USD leg
		# is. The rule is about the unit, not about the number of legs.
		row, _ = _one_row(
			je_rows=[_je_row("JV-0004", total_credit=1_500_000.0)],
			legs=[
				_leg("JV-0004", "UZS", 1_000_000.0, 1_000_000.0),
				_leg("JV-0004", "UZS", 500_000.0, 500_000.0),
			],
		)

		self.assertEqual(row["total_amount"], 1_500_000.0)
		self.assertEqual(row["currency"], "UZS")

	def test_a_voucher_with_no_credit_leg_falls_back_to_the_document_total(self):
		# Defensive: a balanced Journal Entry always has a credit side, so this
		# branch should be unreachable. It exists because the alternative to a
		# defined fallback is a KeyError in a list endpoint.
		row, _ = _one_row(
			je_rows=[_je_row("JV-0005", total_credit=750_000.0)],
			legs=[],
		)

		self.assertEqual(row["total_amount"], 750_000.0)
		self.assertEqual(row["currency"], "UZS")


class QueryScopeTest(unittest.TestCase):
	"""Tenant isolation survives the extra round trip.

	The amount is no longer computed by a correlated subquery inside the
	company-scoped statement, so the second query has to inherit that scope
	rather than assume it: it may only ask about vouchers the first query
	already returned.
	"""

	def test_the_leg_query_asks_only_about_the_vouchers_the_list_returned(self):
		_, ctx = _one_row(
			je_rows=[_je_row("JV-0001", total_credit=2_233_500.0)],
			legs=MIXED_LEGS,
		)

		leg_queries = [(q, p) for q, p in ctx.queries if "`tabJournal Entry` je" not in q]
		self.assertEqual(len(leg_queries), 1)
		# A tuple, not a list: that is how the rest of the codebase feeds
		# `IN %(names)s`, and pymysql escapes the sequence into `(...)`.
		self.assertEqual(leg_queries[0][1]["names"], ("JV-0001",))

	def test_no_leg_query_is_issued_when_the_list_is_empty(self):
		money, ctx = _load_money(je_rows=[], legs=[])

		self.assertEqual(money.list_bank_entries(company="Test Co"), [])
		self.assertEqual([q for q, _ in ctx.queries if "`tabJournal Entry` je" not in q], [])


class RegistrationTest(unittest.TestCase):
	def test_the_module_is_in_the_frappe_free_list(self):
		# A bench-free test that `make check` does not run gates nothing. This is
		# the P0's own regression test, so it has to be in the fast set.
		import pathlib

		root = pathlib.Path(__file__).resolve().parents[2]
		listed = (root / ".github" / "frappe-free-tests.txt").read_text().split()

		# assertTrue, not assertIn: the list is ~200 entries and assertIn prints
		# every one of them, burying the one line that says what is wrong.
		self.assertTrue(
			"stabler.tests.test_money_list_currency" in listed,
			"module missing from .github/frappe-free-tests.txt — `make check` would not run it",
		)


if __name__ == "__main__":
	unittest.main()
