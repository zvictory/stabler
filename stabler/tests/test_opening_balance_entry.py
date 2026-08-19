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


if __name__ == "__main__":
	unittest.main()
