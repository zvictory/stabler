"""The opening Journal Entry `create_account` posts, and the two ways it lied.

Opening a ledger is the one moment where a mistake is both easy and expensive:
the entry is submitted immediately, so the only correction is a cancellation
that stays in the books forever, and it is usually noticed months later when the
period reports refuse to agree.

Two failures live in that entry.

**The date.** A blank opening date silently became `today()` on a row flagged
`is_opening = "Yes"`. That puts an opening balance inside the OPEN period — and
for an income or expense account, straight into this period's profit and loss.
Nothing on screen says so; the form leaves the field empty and optional.

**The currency.** The entry never set `multi_currency`, gave both legs the same
raw number, and put an exchange rate on neither. So a foreign-currency opening
balance could not be created at all: ERPNext refused the multi-currency document,
the transaction rolled back, and the ACCOUNT disappeared with it — the user asked
for "Bank USD with 1 000 USD" and was told, in English, that something was wrong
with a currency they had not mentioned.

Bench-free: the sandbox from ``test_money_je_guards`` imports ``stabler.api.money``
against a hand-built ``frappe``, so this runs inside ``make check`` rather than
only under a live bench.

  PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_opening_balance_entry -v
"""

from __future__ import annotations

import unittest

from stabler.tests.test_money_je_guards import _SANDBOX, I18N, _load_money


def tearDownModule():
	# Borrowed sandbox, inherited duty: sys.modules is process-wide.
	_SANDBOX.restore()


TEMP = "Temporary Opening - X"
PARENT = "Bank Accounts - X"
BASE = "UZS"

ACCOUNTS = {
	TEMP: {"company": "Test Co", "is_group": 0, "account_currency": BASE},
	PARENT: {"company": "Test Co", "is_group": 1, "account_currency": BASE},
}


def _journal_of(ctx):
	"""The Journal Entry the call created, or None if it never got that far."""
	for doc in ctx.docs:
		if doc.doctype == "Journal Entry":
			return doc
	return None


class OpeningDateTest(unittest.TestCase):
	"""AF5 — an opening balance with no date landed in the open period."""

	def test_an_opening_balance_without_a_date_is_refused(self):
		"""`today()` is never a defensible guess for an opening date. The row is
		flagged `is_opening = "Yes"` and submitted on the spot, so a silent default
		files this period's books with last year's balance — and on a P&L account
		it walks straight into this period's result."""
		money, ctx = _load_money(accounts=ACCOUNTS)

		with self.assertRaises(Exception) as caught:
			money.create_account("Test Co", "Cash", PARENT, opening_balance=1000)

		self.assertIn(I18N, str(caught.exception))
		self.assertNotIn("insert", ctx.trace)

	def test_an_account_with_no_opening_balance_still_needs_no_date(self):
		"""Most accounts are created empty. The date matters only when there is a
		balance to date."""
		money, ctx = _load_money(accounts=ACCOUNTS)

		money.create_account("Test Co", "Cash", PARENT)

		self.assertIn("insert", ctx.trace)
		self.assertIsNone(_journal_of(ctx))

	def test_the_opening_entry_is_posted_on_the_date_given(self):
		money, ctx = _load_money(accounts=ACCOUNTS)

		money.create_account("Test Co", "Cash", PARENT, opening_balance=1000, opening_date="2026-01-01")

		self.assertEqual(str(_journal_of(ctx).posting_date), "2026-01-01")


#: A UZS-based company, a USD account, and the CBU rate on the opening date. The
#: rate is deliberately not today's: the whole point of an opening balance is that
#: it belongs to a date in the past.
OPENING_DATE = "2026-01-01"
USD_RATE = 12335.0


class ForeignCurrencyOpeningBalanceTest(unittest.TestCase):
	"""AF3 — a foreign-currency opening balance could not be created at all.

	Three faults compounded: `multi_currency` was never set, so ERPNext refused
	the document outright; both legs got the same raw number, so even with the
	flag the entry was out by the exchange rate (1 000 USD against 1 000 so'm);
	and no leg carried a rate, so nothing said what the number meant. Because the
	account and its opening entry are created in one transaction, the refusal
	rolled the account back too — the user asked for "Bank USD" and got no
	account, no entry, and an English message about a currency they never named.
	"""

	def _create_usd_account(self, **kwargs):
		money, ctx = _load_money(
			accounts=ACCOUNTS,
			new_account_currency="USD",
			exchange_rates={("USD", BASE): USD_RATE},
			**kwargs,
		)
		money.create_account(
			"Test Co",
			"Bank USD",
			PARENT,
			account_currency="USD",
			opening_balance=1000,
			opening_date=OPENING_DATE,
		)
		return _journal_of(ctx)

	def test_the_entry_declares_itself_multi_currency(self):
		"""Without the flag ERPNext refuses the document — and the refusal takes
		the account with it, because both are one transaction."""
		self.assertEqual(self._create_usd_account().multi_currency, 1)

	def test_the_account_leg_keeps_the_amount_the_user_typed(self):
		"""1 000 USD is the fact. Everything else is derived from it."""
		account_leg = self._create_usd_account().accounts[0]

		self.assertEqual(account_leg["debit_in_account_currency"], 1000)
		self.assertEqual(account_leg["exchange_rate"], USD_RATE)

	def test_the_temporary_opening_leg_carries_the_base_equivalent(self):
		"""The counter-leg is in company currency. Copying the raw 1 000 there
		left the entry short by twelve million so'm — the second failure that
		would have survived fixing only the multi-currency flag."""
		temp_leg = self._create_usd_account().accounts[1]

		self.assertEqual(temp_leg["account"], TEMP)
		self.assertEqual(temp_leg["credit_in_account_currency"], 1000 * USD_RATE)
		self.assertEqual(temp_leg["exchange_rate"], 1.0)

	def test_the_rate_is_the_one_from_the_opening_date(self):
		"""An opening balance is dated in the past on purpose. Valuing it at
		today's rate misstates the ledger by however far the som has moved."""
		money, _ctx = _load_money(
			accounts=ACCOUNTS,
			new_account_currency="USD",
			exchange_rates={("USD", BASE): USD_RATE},
		)
		asked = []
		erpnext_utils = __import__("sys").modules["erpnext.setup.utils"]
		original = erpnext_utils.get_exchange_rate
		erpnext_utils.get_exchange_rate = lambda frm, to, date=None: (
			asked.append((frm, to, str(date))) or original(frm, to, date)
		)
		try:
			money.create_account(
				"Test Co",
				"Bank USD",
				PARENT,
				account_currency="USD",
				opening_balance=1000,
				opening_date=OPENING_DATE,
			)
		finally:
			erpnext_utils.get_exchange_rate = original

		self.assertIn(("USD", BASE, OPENING_DATE), asked)

	def test_a_missing_rate_is_refused_in_the_user_s_own_words(self):
		"""ERPNext's own message for this is English-only and talks about
		multi-currency, not about the missing rate. Ours names the pair and the
		date, which is the only thing that tells the user what to go and fix."""
		money, _ctx = _load_money(
			accounts=ACCOUNTS,
			new_account_currency="USD",
			exchange_rates={},
		)

		with self.assertRaises(Exception) as caught:
			money.create_account(
				"Test Co",
				"Bank USD",
				PARENT,
				account_currency="USD",
				opening_balance=1000,
				opening_date=OPENING_DATE,
			)

		message = str(caught.exception)
		self.assertIn(I18N, message)
		self.assertIn("USD", message)
		self.assertIn(BASE, message)
		self.assertIn(OPENING_DATE, message)

	def test_a_base_currency_account_is_left_exactly_as_it_was(self):
		"""The common case must not acquire a rate lookup or a multi-currency
		flag it never needed."""
		money, ctx = _load_money(accounts=ACCOUNTS)

		money.create_account("Test Co", "Cash", PARENT, opening_balance=1000, opening_date=OPENING_DATE)

		journal = _journal_of(ctx)
		self.assertEqual(journal.multi_currency, 0)
		self.assertEqual(journal.accounts[0]["debit_in_account_currency"], 1000)
		self.assertEqual(journal.accounts[1]["credit_in_account_currency"], 1000)


if __name__ == "__main__":
	unittest.main()
