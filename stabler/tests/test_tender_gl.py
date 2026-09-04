"""ADR-609 P5b — how a tender's ledger rows become a profit and loss (Frappe-free).

WHY this file exists at all. `_actual_block` assembles a tender's realized figures
by walking DOCUMENTS: the Sales Order's invoiced percentage, the Purchase Order's
total, the Journal Entries carrying `custom_crm_deal`. That representation and the
ledger disagree in three measured ways — a PO placed but not received reads as
"landed", a stamped Purchase Invoice with no PO behind it is invisible, and a
cancelled Sales Invoice never leaves revenue. P5a made every stamped voucher's GL
row carry the tender, so the ledger can now answer the same question itself.

Everything that DECIDES anything lives here and is measured here:

  * which bucket an account belongs to, and in what precedence — an account can
    satisfy two rules at once (a "Cost of Goods Sold" account named in
    `Stabler Settings.landed_cost_expense_account`), and the order is the answer;
  * the sign — a revenue account is credited and a cost account debited, so one
    formula applied to both would report a tender's revenue as a loss;
  * that a balance-sheet row never reaches a bucket. P5a deliberately stamps BOTH
    legs of a voucher, so the receivable behind an invoice carries the tender too;
    summing it would double every figure on the screen;
  * that the documents side and the ledger side are compared on the same basis,
    and that the difference is the SERVER's arithmetic, not the browser's.

The DB layer (`stabler.api.tender_gl`) holds one query and no rules. Nothing in
this module imports frappe, so every rule above is provable without a bench:

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_gl -v
"""

from __future__ import annotations

import unittest

from stabler.api._tender_gl import BUCKETS, bucket_amount, classify_account, reconcile, summarize

#: The one account the settings name as the landed-cost expense account on a site
#: that has configured it. On the test site both settings fields are empty, which
#: is why the rule they feed can only be measured here.
_SETTINGS_LANDED = "LCV Clearing - _TC"


def _row(
	account: str,
	*,
	account_name: str | None = None,
	report_type: str = "Profit and Loss",
	root_type: str = "Expense",
	account_type: str = "",
	voucher_type: str = "Journal Entry",
	debit: float = 0.0,
	credit: float = 0.0,
	count: int = 1,
) -> dict:
	"""One `account x voucher_type` group, shaped exactly as the SQL returns it."""
	return {
		"account": account,
		"account_name": account_name or account,
		"report_type": report_type,
		"root_type": root_type,
		"account_type": account_type,
		"voucher_type": voucher_type,
		"debit": debit,
		"credit": credit,
		"count": count,
	}


def _income(account="Sales - _TC", **kw) -> dict:
	kw.setdefault("root_type", "Income")
	return _row(account, **kw)


def _balance_sheet(account, **kw) -> dict:
	kw["report_type"] = "Balance Sheet"
	kw.setdefault("root_type", "Asset")
	return _row(account, **kw)


class TestClassification(unittest.TestCase):
	"""Which bucket an account falls into, and why the ORDER of the rules is the rule."""

	def test_a_balance_sheet_row_reaches_no_bucket(self):
		"""P5a stamps both legs, so the debtor behind an invoice carries the tender.

		WHAT WOULD MAKE THIS FAIL: dropping the report_type guard. The receivable
		leg of a Sales Invoice is the same amount as its revenue leg, so a tender
		would report exactly twice its income, and the cash leg of every expense
		would be counted a second time as a cost.
		"""
		self.assertIsNone(
			classify_account("Balance Sheet", "Asset", "Receivable", frozenset(), "Debtors - _TC")
		)
		self.assertIsNone(
			classify_account("Balance Sheet", "Asset", "Stock", frozenset(), "Stock In Hand - _TC")
		)
		self.assertIsNone(classify_account("", "Liability", "Payable", frozenset(), "Creditors - _TC"))

	def test_an_income_account_is_revenue(self):
		"""WHAT WOULD MAKE THIS FAIL: classifying by `account_type` here. An income
		account's `account_type` is empty on this chart, so the row would fall
		through to `expenses` and a tender's whole turnover would read as a cost."""
		self.assertEqual(
			classify_account("Profit and Loss", "Income", "", frozenset(), "Sales - _TC"), "revenue"
		)

	def test_an_account_named_in_settings_is_landed_whatever_its_own_type_says(self):
		"""Rule 3 sits ABOVE rule 4, and that precedence is the decision.

		A site that points `Stabler Settings.landed_cost_expense_account` at an
		account whose `account_type` is "Cost of Goods Sold" has said, in the one
		place the LCV writer reads, that this account holds landed charges.

		WHAT WOULD MAKE THIS FAIL: swapping rules 3 and 4. The account would land
		in `cogs`, both figures would move by the whole of the site's landed cost,
		and the reconciliation's landed row — which sums cogs + landed — would
		still balance, so nothing on the screen would show it.
		"""
		self.assertEqual(
			classify_account(
				"Profit and Loss",
				"Expense",
				"Cost of Goods Sold",
				frozenset({_SETTINGS_LANDED}),
				_SETTINGS_LANDED,
			),
			"landed",
		)
		# The same account, on a site that never configured the setting, is what
		# its own type says it is.
		self.assertEqual(
			classify_account(
				"Profit and Loss", "Expense", "Cost of Goods Sold", frozenset(), _SETTINGS_LANDED
			),
			"cogs",
		)

	def test_an_expenses_included_in_valuation_account_is_landed_with_no_settings_at_all(self):
		"""The test site configures neither settings field, so this is the ONLY
		route a landed charge has into its bucket there.

		WHAT WOULD MAKE THIS FAIL: reading the settings alone. Every LCV the app
		posts through `lcv.py`'s fallback lands on an "Expenses Included In
		Valuation" account, and the landed bucket would be empty on every site
		that left the setting blank — which is all of them today.
		"""
		self.assertEqual(
			classify_account(
				"Profit and Loss", "Expense", "Expenses Included In Valuation", frozenset(), "EIV - _TC"
			),
			"landed",
		)

	def test_a_cost_of_goods_sold_account_is_cogs(self):
		self.assertEqual(
			classify_account("Profit and Loss", "Expense", "Cost of Goods Sold", frozenset(), "COGS - _TC"),
			"cogs",
		)

	def test_no_profit_and_loss_row_is_ever_silently_dropped(self):
		"""Anything left on the P&L is a tender expense, including rows whose
		`root_type` this code has never heard of.

		WHAT WOULD MAKE THIS FAIL: a `return None` fallback. The row would vanish
		from every bucket AND from `result`, so the screen would show a tender
		more profitable than it is and name nothing as missing — the exact failure
		mode of the document-side reader this feature replaces.
		"""
		self.assertEqual(
			classify_account("Profit and Loss", "Expense", "", frozenset(), "Freight - _TC"), "expenses"
		)
		self.assertEqual(classify_account("Profit and Loss", "", "", frozenset(), "Odd - _TC"), "expenses")
		self.assertEqual(
			classify_account("Profit and Loss", "Chart Of Accounts", "", frozenset(), "X - _TC"), "expenses"
		)


class TestSign(unittest.TestCase):
	"""Revenue is credited, cost is debited; one formula for both reports a loss."""

	def test_revenue_is_credit_minus_debit(self):
		"""WHAT WOULD MAKE THIS FAIL: `debit - credit` for revenue too. A tender
		with 100 of sales would report -100 of revenue, and `result` would be
		twice its turnover in the wrong direction."""
		self.assertEqual(bucket_amount("revenue", 0.0, 100.0), 100.0)
		# A credit note reduces revenue rather than becoming a cost.
		self.assertEqual(bucket_amount("revenue", 30.0, 100.0), 70.0)

	def test_every_cost_bucket_is_debit_minus_credit(self):
		for bucket in ("cogs", "landed", "expenses"):
			with self.subTest(bucket=bucket):
				self.assertEqual(bucket_amount(bucket, 100.0, 0.0), 100.0)

	def test_a_landed_credit_surplus_stays_negative(self):
		"""The finding this whole bucket exists to surface.

		A Landed Cost Voucher CREDITS the expense account on the receipt that
		capitalizes it. If that receipt was tagged to another tender (or to GENEL
		GIDER) while the bill was tagged to this one, this tender keeps the credit
		and loses the debit: a negative landed figure that says "somebody's charge
		was capitalized somewhere else".

		WHAT WOULD MAKE THIS FAIL: `max(0.0, ...)`. The number would read as a
		clean zero, the reconciliation note would never fire, and the mis-tagged
		bill would stay mis-tagged.
		"""
		self.assertEqual(bucket_amount("landed", 0.0, 250.0), -250.0)


class TestSummarize(unittest.TestCase):
	"""What the endpoint hands the screen, from rows shaped as the SQL returns them."""

	def _gl(self):
		return summarize(
			[
				_income(voucher_type="Sales Invoice", credit=1000.0, count=2),
				_row(
					"COGS - _TC", account_type="Cost of Goods Sold", voucher_type="Delivery Note", debit=400.0
				),
				_row(
					"EIV - _TC",
					account_type="Expenses Included In Valuation",
					voucher_type="Purchase Receipt",
					credit=50.0,
				),
				_row("Freight - _TC", voucher_type="Journal Entry", debit=120.0, count=3),
				_row("Bank Fees - _TC", voucher_type="Journal Entry", debit=30.0),
				_balance_sheet(
					"Stock In Hand - _TC", account_type="Stock", voucher_type="Purchase Receipt", debit=700.0
				),
				_balance_sheet(
					"Debtors - _TC", account_type="Receivable", voucher_type="Sales Invoice", debit=1120.0
				),
			],
			frozenset(),
		)

	def test_the_result_is_revenue_minus_every_cost_bucket(self):
		"""WHAT WOULD MAKE THIS FAIL: leaving one bucket out of the subtraction —
		the landed bucket is the easy one to forget, because on a site with no LCV
		it is empty and the number still looks right."""
		gl = self._gl()
		self.assertEqual(gl["buckets"]["revenue"]["total"], 1000.0)
		self.assertEqual(gl["buckets"]["cogs"]["total"], 400.0)
		self.assertEqual(gl["buckets"]["landed"]["total"], -50.0)
		self.assertEqual(gl["buckets"]["expenses"]["total"], 150.0)
		self.assertEqual(gl["result"], 1000.0 - 400.0 - (-50.0) - 150.0)

	def test_stock_on_hand_is_reported_and_never_enters_the_result(self):
		"""Goods received and not yet delivered are an ASSET; they become cost on
		the delivery note. Adding them to `result` would show a tender at a loss
		for the whole period between receipt and delivery.

		WHAT WOULD MAKE THIS FAIL: bucketing the stock row as a cost — which is
		what happens the moment the report_type guard is relaxed "just for stock".
		"""
		gl = self._gl()
		self.assertEqual(gl["stock_on_hand"], 700.0)
		self.assertEqual(gl["result"], 500.0)
		self.assertNotIn(
			"Stock In Hand - _TC", [r["account"] for b in BUCKETS for r in gl["buckets"][b]["rows"]]
		)

	def test_only_profit_and_loss_rows_reach_the_voucher_summary(self):
		"""The voucher table answers "where did this figure come from"; a Sales
		Invoice appearing there with its receivable leg folded in would name a
		number that is on no other line of the screen.

		WHAT WOULD MAKE THIS FAIL: summing every row per voucher type. The Sales
		Invoice's net would become 1000 - 1120 = -120 and the sum of the column
		would stop equalling `result`.
		"""
		gl = self._gl()
		by_type = {v["voucher_type"]: v for v in gl["by_voucher"]}
		self.assertEqual(
			sorted(by_type), ["Delivery Note", "Journal Entry", "Purchase Receipt", "Sales Invoice"]
		)
		self.assertEqual(by_type["Sales Invoice"]["net"], 1000.0)
		self.assertEqual(by_type["Sales Invoice"]["count"], 2)
		# The invariant that makes the table trustworthy: every P&L row's
		# contribution to the result is `credit - debit`, so the column adds up.
		self.assertEqual(round(sum(v["net"] for v in gl["by_voucher"]), 2), gl["result"])

	def test_row_count_counts_the_profit_and_loss_groups_only(self):
		"""`row_count == 0` is what the screen renders its empty state from. If
		balance-sheet rows counted, a tender whose only stamped document was a
		payment would claim a ledger side and then show four zeroes.

		WHAT WOULD MAKE THIS FAIL: counting `len(rows)`.
		"""
		self.assertEqual(self._gl()["row_count"], 5)
		self.assertEqual(summarize([], frozenset())["row_count"], 0)

	def test_an_empty_ledger_still_has_the_full_shape(self):
		"""The unavailable and empty states return this shape too, and the screen
		indexes into it without guards.

		WHAT WOULD MAKE THIS FAIL: building `buckets` from the rows present, which
		leaves the dict short on a tender with no cost yet — the common case — and
		the ledger section renders `undefined` where a zero belongs.
		"""
		gl = summarize([], frozenset())
		self.assertEqual(sorted(gl["buckets"]), sorted(BUCKETS))
		for bucket in BUCKETS:
			self.assertEqual(gl["buckets"][bucket], {"total": 0.0, "rows": []})
		self.assertEqual(gl["result"], 0.0)
		self.assertEqual(gl["by_voucher"], [])
		self.assertEqual(gl["stock_on_hand"], 0.0)

	def test_the_biggest_account_is_first_so_the_reader_starts_where_the_money_is(self):
		"""Ordered by SIZE, not by sign: a -900 landed credit surplus is the most
		important line in its bucket and would sink to the bottom of an ordinary
		descending sort.

		WHAT WOULD MAKE THIS FAIL: sorting on `amount` instead of `abs(amount)`.
		"""
		gl = summarize(
			[
				_row("A - _TC", debit=10.0),
				_row("B - _TC", credit=900.0),
				_row("C - _TC", debit=100.0),
			],
			frozenset(),
		)
		self.assertEqual(
			[r["account"] for r in gl["buckets"]["expenses"]["rows"]], ["B - _TC", "C - _TC", "A - _TC"]
		)

	def test_one_account_billed_through_two_voucher_types_is_one_row(self):
		"""The SQL groups by `account x voucher_type`, so the same expense account
		arrives twice whenever it was both invoiced and journalled — which is the
		ordinary shape of a tender that had a bill and a cash expense.

		WHAT WOULD MAKE THIS FAIL: emitting the SQL groups as-is. The account
		would be listed twice at half its figure each, and a reader checking one
		line against the ledger would find it short.
		"""
		gl = summarize(
			[
				_row("Freight - _TC", voucher_type="Purchase Invoice", debit=60.0, count=1),
				_row("Freight - _TC", voucher_type="Journal Entry", debit=40.0, count=2),
			],
			frozenset(),
		)
		rows = gl["buckets"]["expenses"]["rows"]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["amount"], 100.0)
		self.assertEqual(rows[0]["count"], 3)
		# ...and the voucher table still separates them, because that is its job.
		self.assertEqual(len(gl["by_voucher"]), 2)


class TestReconcile(unittest.TestCase):
	"""The documents side beside the ledger side, and the difference between them."""

	def _gl(self, **over):
		gl = summarize(
			[
				_income(voucher_type="Sales Invoice", credit=1000.0),
				_row(
					"COGS - _TC", account_type="Cost of Goods Sold", voucher_type="Delivery Note", debit=400.0
				),
				_row(
					"EIV - _TC",
					account_type="Expenses Included In Valuation",
					voucher_type="Purchase Invoice",
					debit=100.0,
				),
				_row("Freight - _TC", voucher_type="Journal Entry", debit=150.0),
			],
			frozenset(),
		)
		gl.update(over)
		return gl

	def _actual(self, **over):
		block = {
			"invoiced": True,
			"planned_landed": 600.0,
			"actual_landed": 480.0,
			"actual_revenue": 1120.0,
			"kassa_actual": [{"label": "Freight", "amount": 150.0}],
			"kassa_actual_total": 150.0,
			"pnl": {"net_revenue": 1000.0, "ostatok": 0.0},
			"ostatok_delta": 0.0,
		}
		block.update(over)
		return block

	def test_the_four_rows_come_in_the_frozen_order(self):
		"""The screen renders `reconciliation` in order and labels each row from
		its `key`. A different order relabels every figure.

		WHAT WOULD MAKE THIS FAIL: building the list from a dict comprehension.
		"""
		self.assertEqual(
			[r["key"] for r in reconcile(self._actual(), self._gl())],
			["revenue", "landed", "expenses", "result"],
		)

	def test_the_landed_row_compares_the_documents_landed_against_cogs_plus_landed(self):
		"""The document side's `actual_landed` is a PURCHASE total: goods plus the
		charges recorded against them. In the ledger that same money is split — the
		goods reach `cogs` when they are delivered, the charges sit in `landed` —
		so comparing it against either bucket alone reports a difference that is
		not one.

		WHAT WOULD MAKE THIS FAIL: comparing against `landed` only. The delta
		would read -380 on a tender whose two sides agree perfectly.
		"""
		row = reconcile(self._actual(), self._gl())[1]
		self.assertEqual(row["documents"], 480.0)
		self.assertEqual(row["gl"], 500.0)
		self.assertEqual(row["delta"], 20.0)

	def test_delta_is_the_ledger_minus_the_documents_on_every_row(self):
		"""The sign is the message: a positive delta on a cost row means the
		ledger holds MORE cost than the documents knew about.

		WHAT WOULD MAKE THIS FAIL: `documents - gl`. Every colour on the screen
		would invert, and an overrun would render green.
		"""
		for row in reconcile(self._actual(), self._gl()):
			with self.subTest(key=row["key"]):
				self.assertEqual(row["delta"], round(row["gl"] - row["documents"], 2))

	def test_the_result_row_is_derived_from_the_three_document_figures(self):
		"""NOT from the waterfall's `profit`, which subtracts an exchange
		commission that was never posted to any ledger. Comparing that against a
		GL result would show a permanent difference the size of the commission and
		invite somebody to "fix" the ledger.

		WHAT WOULD MAKE THIS FAIL: reading `actual["pnl"]["profit"]` here.
		"""
		rows = reconcile(self._actual(), self._gl())
		by_key = {r["key"]: r for r in rows}
		self.assertEqual(by_key["result"]["documents"], 1000.0 - 480.0 - 150.0)
		self.assertEqual(by_key["result"]["gl"], self._gl()["result"])

	def test_an_uninvoiced_tender_reads_zero_on_the_documents_side_and_says_so(self):
		"""`_actual_block` falls back to the PLANNED bid price when nothing is
		invoiced (`bid_price = actual_revenue or planned`), so `net_revenue` is
		then a plan figure wearing an actual's name. Printing it beside a ledger
		that holds nothing would show a tender that has "lost" its whole revenue.

		WHAT WOULD MAKE THIS FAIL: printing `net_revenue` unconditionally.
		"""
		rows = reconcile(self._actual(invoiced=False, actual_revenue=0.0), self._gl())
		self.assertEqual(rows[0]["documents"], 0.0)
		self.assertIn("not_invoiced", rows[0]["notes"])
		# The result row is built from the same zero, or it would disagree with
		# the row above it.
		self.assertEqual(rows[3]["documents"], 0.0 - 480.0 - 150.0)

	def test_an_invoiced_tender_carries_no_uninvoiced_note(self):
		"""WHAT WOULD MAKE THIS FAIL: an unconditional note, which trains the
		reader to ignore the one case it is there to announce."""
		self.assertEqual(reconcile(self._actual(), self._gl())[0]["notes"], [])

	def test_a_landed_credit_surplus_is_named_on_the_row_it_distorts(self):
		"""WHAT WOULD MAKE THIS FAIL: no note. The landed row would simply read
		low, which looks like good news, and the mis-tagged bill stays lost."""
		gl = self._gl()
		gl["buckets"]["landed"]["total"] = -75.0
		notes = reconcile(self._actual(), gl)[1]["notes"]
		self.assertIn("landed_credit_surplus", notes)

	def test_stock_still_on_hand_is_named_on_the_landed_row(self):
		"""Goods bought for this tender and not yet delivered are the ordinary
		reason the ledger's cost is lower than the documents': the money is in an
		asset, not in COGS. Without the note the delta looks like a bug.

		WHAT WOULD MAKE THIS FAIL: no note, or firing it on zero stock — which
		would put the sentence on every tender and make it unreadable.
		"""
		self.assertIn("stock_on_hand", reconcile(self._actual(), self._gl(stock_on_hand=900.0))[1]["notes"])
		self.assertNotIn("stock_on_hand", reconcile(self._actual(), self._gl(stock_on_hand=0.0))[1]["notes"])

	def test_a_missing_documents_block_is_a_note_and_not_an_exception(self):
		"""`_actual_block` can legitimately return nothing useful — a deal with no
		PO, no SO and no kassa entry. The ledger side is still worth showing.

		WHAT WOULD MAKE THIS FAIL: indexing into `actual["pnl"]`, which raises and
		takes the whole ledger section down with it on exactly the tenders that
		have only just started posting.
		"""
		rows = reconcile(None, self._gl())
		self.assertIn("no_documents", rows[0]["notes"])
		self.assertEqual([r["documents"] for r in rows], [0.0, 0.0, 0.0, 0.0])
		self.assertEqual(rows[3]["gl"], self._gl()["result"])
		self.assertEqual(reconcile({}, self._gl())[0]["notes"][0], "no_documents")


if __name__ == "__main__":
	unittest.main()
