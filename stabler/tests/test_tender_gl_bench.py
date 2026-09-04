"""ADR-609 P5b's ledger P&L against a live General Ledger.

`test_tender_gl` proves every RULE without a bench: which bucket an account
falls into, in what precedence, with what sign, and how the two sides are
reconciled. What a stubbed frappe cannot show is the only thing the feature is
actually for — that real vouchers, posted by ERPNext's own controllers, land in
the buckets this code claims they land in.

  * The SHAPE of a posting is ERPNext's decision, not ours. A Sales Invoice
    writes revenue and a receivable; a Delivery Note writes a cost of goods and a
    stock credit. The frappe-free suite feeds `summarize` rows it wrote itself,
    so it proves the rule and not that a real invoice produces rows of that
    shape — nor that the delivery's expense account is typed "Cost of Goods
    Sold" on this chart, which is what decides whether its cost reaches the
    landed reconciliation row or the tender-expenses one.
  * The two readers must agree. `_deal_kassa_actual` reads a kassa expense
    through `custom_crm_deal`; this endpoint reads the SAME voucher through the
    dimension. A stub can make both return whatever it likes; only a live ledger
    can say they return the same number.
  * The gate is `_deal_scope`, shared with `deal_bid_pricing`. That an unknown
    deal raises rather than returning an empty ledger is a permission property,
    and permission checks are exactly what passes in a test that stubbed them.
  * `deal_bid_pricing` must not have moved. P5b adds a second endpoint beside it
    and changes nothing in it; the key set is asserted here because a stubbed
    test cannot see an accidental extra key.

    cd /path/to/frappe-bench && bench --site <site> run-tests \\
        --module stabler.tests.test_tender_gl_bench

NOT in `.github/frappe-free-tests.txt` on purpose: it needs a live bench, so it
runs under `make test-bench`, never under `make check`.

Nothing here SKIPS. `_Fixture` skips when the site carries no tender company,
and `TestSalesSide` skips when it holds no stock — reasonable for a suite that
measures a hook on whatever site it is pointed at, and wrong for this one: a
ledger reader that reported "0 tests, all passed" on a site with no stock would
be exactly as green as one that works. When a fixture is missing, this module
says so and fails.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, today

from stabler.api._tender_gl import BUCKETS
from stabler.api.tender import deal_bid_pricing
from stabler.api.tender_gl import tender_gl_pnl
from stabler.tests.test_tender_dimension_bench import _an_account, _Fixture, _gl_rows, _report_type

#: `deal_bid_pricing`'s top-level keys as P5a left them: the four the function
#: names plus everything `_bid_inputs` returns as `refs`. Measured on main @
#: 53bd2aa and asserted from the live return, because the risk this guards
#: against is a key appearing or vanishing without anyone editing this list.
_P5A_BID_PRICING_KEYS = {
	"deal",
	"currency",
	"inputs",
	"pnl",
	"actual",
	"po_landed",
	"po_count",
	"so_revenue",
	"so_count",
	"quotation_landed_estimate",
	"quotation_landed_source",
	"quotation_landed_unvalued",
	"quotation_landed_denied",
}


class _LedgerFixture(_Fixture):
	"""`_Fixture`, with its skip replaced by a failure.

	The parent skips the whole class when the site has no tender-enabled company
	with the dimension installed. Here that is not a site this suite has nothing
	to say about — it is a site the feature cannot work on, and a silent skip
	would report the same green as a passing run.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not cls.ready:
			raise AssertionError(
				"no tender-enabled company with the dimension installed on this site: "
				f"company={cls.company!r} fieldname={cls.fieldname!r} overhead={cls.overhead!r} "
				f"cash={cls.cash!r} expense={cls.expense!r}"
			)

	def _bucket_accounts(self, gl: dict) -> set:
		return {row["account"] for bucket in BUCKETS for row in gl["buckets"][bucket]["rows"]}


class TestExpenseSide(_LedgerFixture):
	"""A kassa expense, read twice: through the deal link and through the dimension."""

	def test_the_two_readers_of_one_expense_return_one_number(self):
		"""`_deal_kassa_actual` walks Journal Entries carrying `custom_crm_deal`;
		this endpoint walks GL rows carrying the dimension. They are two readers
		of the SAME voucher, and the reconciliation's whole claim is that a
		difference between the columns means something. If the two disagree on a
		voucher they both saw, every delta on the screen is noise.
		"""
		self._expense_entry(deal=self.tender, amount=1234.0)
		gl = tender_gl_pnl(self.tender)

		self.assertTrue(gl["available"], f"the ledger view is unavailable: {gl['reason']}")
		self.assertEqual(gl["buckets"]["expenses"]["total"], 1234.0)
		rows = gl["buckets"]["expenses"]["rows"]
		self.assertEqual([row["account"] for row in rows], [self.expense])
		self.assertEqual(rows[0]["amount"], 1234.0)

		expenses = next(row for row in gl["reconciliation"] if row["key"] == "expenses")
		self.assertEqual(expenses["documents"], 1234.0, "the document-side kassa total moved")
		self.assertEqual(expenses["gl"], 1234.0)
		self.assertEqual(expenses["delta"], 0.0, "two readers of one voucher disagreed")

	def test_the_cash_leg_of_that_expense_reaches_no_bucket(self):
		"""P5a stamps both legs on purpose, so the cash account credited by a
		kassa expense carries the tender exactly as the expense account does.
		Bucketing it would subtract the same money twice and show every tender
		spending double what it spent.
		"""
		name = self._expense_entry(deal=self.tender, amount=500.0)
		balance_sheet = [
			row["account"]
			for row in _gl_rows("Journal Entry", name, self.fieldname)
			if _report_type(row["account"]) != "Profit and Loss"
		]
		self.assertTrue(balance_sheet, "the expense posted no balance-sheet leg; fixture is wrong")
		self.assertEqual(
			{row[self.fieldname] for row in _gl_rows("Journal Entry", name, self.fieldname)},
			{self.tender},
			"P5a stopped stamping both legs; this test no longer measures what it claims",
		)
		gl = tender_gl_pnl(self.tender)
		self.assertEqual(self._bucket_accounts(gl) & set(balance_sheet), set())
		self.assertEqual(gl["buckets"]["expenses"]["total"], 500.0)

	def test_a_bill_with_no_tender_stays_out_of_this_tenders_ledger(self):
		"""An expense with no deal is stamped GENEL GIDER by `stamp_tender`. If it
		leaked into a tender's buckets, every tender in the company would carry
		the whole company's overhead and no tender would ever look profitable.
		"""
		# GENEL GİDER is ONE deal shared by the whole company, and it is where every
		# untagged posting on this site lands — including any that outlived a
		# cleanup. An absolute assertion on its total measures the site's history
		# rather than this test; only the DELTA is this expense.
		before = tender_gl_pnl(self.overhead)["buckets"]["expenses"]["total"]
		name = self._expense_entry(deal=None, amount=777.0)
		rows = _gl_rows("Journal Entry", name, self.fieldname)
		# Measured, and exactly what `default_gl_tender` documents: it never ADDS a
		# value to a balance-sheet row, so the cash leg of an untagged expense
		# carries no tender at all while the expense leg carries GENEL GIDER. Both
		# halves matter here — the second is what keeps this money off the tender,
		# the first is why a reader that summed every account would still be wrong.
		self.assertEqual(
			{row[self.fieldname] for row in rows if _report_type(row["account"]) == "Profit and Loss"},
			{self.overhead},
			"the unstamped expense did not go to GENEL GIDER",
		)
		self.assertNotIn(self.tender, {row[self.fieldname] for row in rows})

		gl = tender_gl_pnl(self.tender)
		self.assertEqual(gl["row_count"], 0, f"overhead leaked into the tender: {gl['buckets']}")
		self.assertEqual(gl["buckets"]["expenses"]["total"], 0.0)
		self.assertEqual(gl["result"], 0.0)

		after = tender_gl_pnl(self.overhead)["buckets"]["expenses"]["total"]
		self.assertEqual(round(after - before, 2), 777.0, "GENEL GIDER did not receive it")


class TestUnavailable(_LedgerFixture):
	"""What a site without the dimension, and a caller without a deal, get back."""

	def test_a_site_without_the_dimension_is_told_so_instead_of_shown_zero(self):
		"""A site that never ran v103 has no tender column on GL Entry, so nothing
		was ever stamped. Returning an empty P&L there would assert that the
		tender has no postings — which is a statement about the money, and false.
		The screen needs to say "not set up", and it needs a `reason` to do it.
		"""
		import stabler.api.tender_gl as module

		original = module.dimension_fieldname
		module.dimension_fieldname = lambda: None
		self.addCleanup(setattr, module, "dimension_fieldname", original)

		gl = tender_gl_pnl(self.tender)
		self.assertFalse(gl["available"])
		self.assertEqual(gl["reason"], "no_dimension")
		self.assertEqual(gl["fieldname"], "")
		self.assertEqual(gl["reconciliation"], [], "an unavailable ledger offered a reconciliation")
		self.assertEqual(gl["row_count"], 0)
		# Same shape as a loaded answer: the screen indexes into it either way.
		self.assertEqual(sorted(gl["buckets"]), sorted(BUCKETS))
		for bucket in BUCKETS:
			self.assertEqual(gl["buckets"][bucket], {"total": 0.0, "rows": []})

	def test_an_unknown_deal_raises_rather_than_reporting_an_empty_ledger(self):
		"""Proof that `_deal_scope` is the gate and was not re-implemented. A
		nonexistent tender and a tender with no postings must not look alike.
		"""
		with self.assertRaises(frappe.DoesNotExistError):
			tender_gl_pnl("CRM-DEAL-does-not-exist-p5b")

	def test_the_bid_pricing_endpoint_still_returns_exactly_what_p5a_returned(self):
		"""P5b adds an endpoint beside `deal_bid_pricing` and changes nothing in
		it — the transition period's premise is that both sources stay on screen.
		A key added or lost here is a silent contract break for BidPricing.vue.
		"""
		self.assertEqual(set(deal_bid_pricing(self.tender)), _P5A_BID_PRICING_KEYS)


class TestSalesSide(_LedgerFixture):
	"""Revenue and cost of goods, posted by ERPNext's own controllers."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		# `valuation_rate >= 1`, biggest first: erpnext books NO ledger row for a
		# stock value difference that rounds to zero, so an item held at 0.1 UZS
		# delivers happily and posts nothing — the test would then measure the
		# fixture's rounding instead of the tender.
		cls.stock = frappe.db.get_value(
			"Bin",
			{"actual_qty": [">", 1], "valuation_rate": [">=", 1]},
			["item_code", "warehouse", "valuation_rate"],
			as_dict=True,
			order_by="valuation_rate desc",
		)
		if not (cls.customer and cls.stock and frappe.db.has_column("Sales Order", "custom_crm_deal")):
			raise AssertionError(
				"the sales fixture cannot be built on this site: "
				f"customer={cls.customer!r} stock={cls.stock!r} "
				f"so_deal_column={frappe.db.has_column('Sales Order', 'custom_crm_deal')}"
			)

	def _order(self) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": self.company,
				"customer": self.customer,
				"transaction_date": today(),
				"delivery_date": today(),
				"custom_crm_deal": self.tender,
				"items": [
					{
						"item_code": self.stock.item_code,
						"warehouse": self.stock.warehouse,
						"qty": 1,
						"rate": 1000,
						"delivery_date": today(),
					}
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Sales Order", doc.name)
		doc.flags.ignore_permissions = True
		doc.submit()
		return doc.name

	def test_a_stamped_invoices_revenue_is_the_revenue_bucket_and_its_debtor_is_in_none(self):
		"""The measurement the document-side reader cannot make: revenue as the
		LEDGER holds it, net of VAT, from the account ERPNext actually credited.

		The receivable leg carries the tender too (P5a stamps both), and it is the
		same order of magnitude as the revenue — so if it reached a bucket the
		screen would show roughly twice the turnover and nothing would look wrong.
		"""
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		si = make_sales_invoice(self._order())
		si.flags.ignore_permissions = True
		si.insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Sales Invoice", si.name)
		si.submit()

		rows = _gl_rows("Sales Invoice", si.name, self.fieldname)
		balance_sheet = [r["account"] for r in rows if _report_type(r["account"]) != "Profit and Loss"]
		self.assertTrue(balance_sheet, "the invoice posted no receivable leg; fixture is wrong")
		self.assertEqual({r[self.fieldname] for r in rows}, {self.tender})

		gl = tender_gl_pnl(self.tender)
		self.assertEqual(gl["buckets"]["revenue"]["total"], flt(si.base_net_total))
		self.assertEqual(self._bucket_accounts(gl) & set(balance_sheet), set())
		self.assertIn("Sales Invoice", [v["voucher_type"] for v in gl["by_voucher"]])
		# The invariant that makes the voucher table checkable rather than decorative.
		self.assertEqual(round(sum(v["net"] for v in gl["by_voucher"]), 2), gl["result"])

	def test_a_stamped_delivery_puts_its_cost_in_cogs_and_takes_it_out_of_stock(self):
		"""Where the document-side reader is most wrong. It calls a Purchase Order
		"landed" the moment it is placed; the ledger only records a cost when the
		goods LEAVE, and until then the money sits in stock.

		Two things are asserted because they answer different questions. That the
		delivery's expense account is typed "Cost of Goods Sold" decides whether
		its cost joins the landed reconciliation row (cogs + landed) or inflates
		tender expenses instead — a misfiling that moves two lines at once and
		leaves the totals looking plausible. And that the stock leg reaches
		`stock_on_hand` rather than a bucket is what keeps an asset out of the
		result.
		"""
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		dn = make_delivery_note(self._order())
		# `make_delivery_note` re-resolves the warehouse from the item's defaults,
		# which may hold the item at a valuation that rounds to nothing.
		for row in dn.items:
			row.warehouse = self.stock.warehouse
		dn.flags.ignore_permissions = True
		dn.insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Delivery Note", dn.name)
		dn.submit()

		rows = _gl_rows("Delivery Note", dn.name, self.fieldname)
		cost = [r for r in rows if _report_type(r["account"]) == "Profit and Loss"]
		stock = [r for r in rows if _report_type(r["account"]) != "Profit and Loss"]
		self.assertTrue(cost, f"the delivery booked no cost row; it booked {rows}")
		self.assertTrue(stock, f"the delivery credited no stock account; it booked {rows}")
		expected = round(sum(flt(r["debit"]) - flt(r["credit"]) for r in cost), 2)

		gl = tender_gl_pnl(self.tender)
		self.assertEqual(
			gl["buckets"]["cogs"]["total"],
			expected,
			"the delivery's expense account is not typed 'Cost of Goods Sold' on this chart, "
			"so its cost is being reported as a tender expense instead of a cost of goods",
		)
		self.assertEqual(gl["buckets"]["expenses"]["total"], 0.0)
		self.assertEqual(self._bucket_accounts(gl) & {r["account"] for r in stock}, set())
		self.assertLess(
			gl["stock_on_hand"], 0.0, "the stock leg did not reduce stock on hand; an asset was left standing"
		)


class TestLedgerFilters(_LedgerFixture):
	"""The row set this screen reads is the Profit and Loss Statement's, exactly.

	Not the Trial Balance's, and that distinction is the whole test. Both reports
	call `set_gl_entries_by_account`, and they pass it different flags:

	  * `profit_and_loss_statement.py:37-54` passes `ignore_closing_entries=True`
	    and nothing else, so `ignore_opening_entries` keeps its default False
	    (`financial_statements.py:444`, `:515`) and the site's own P&L **includes**
	    opening rows;
	  * `trial_balance.py:114` passes `ignore_opening_entries=True`, and the
	    balance-sheet branch sets it at `:480`. Those are the readers that drop
	    opening rows, and this screen is neither of them.

	Three filters remain, and every one is the P&L's:

	  * **cancelled** — a cancelled voucher's reversal rows are cancelled too, so
	    the net effect is already nil; the filter keeps the counts honest.
	  * **not a Period Closing Voucher** (`financial_statements.py:596-598`, under
	    `ignore_closing_entries=True`). Closing the year posts the reverse of every
	    P&L balance into retained earnings, and `update_default_dimensions`
	    (`period_closing_voucher.py:264`) stamps every accounting dimension onto
	    those rows — the tender included, since P5a made it one. Read naively, a
	    closed tender's every bucket nets to ~0 and all four reconciliation deltas
	    become the negative of the documents side. Nothing looks broken. The tender
	    simply reports that it earned and spent nothing.
	  * **the books a default P&L run reads** (`financial_statements.py:616-632`).
	    Not "no finance book": that `if/else` is a FORK, and the Profit and Loss
	    Statement ships `include_default_book_entries` with `default: 1`
	    (`profit_and_loss_statement/profit_and_loss_statement.js:45-48`), so a
	    default run takes the FIRST arm (`:624-627`) — no book, the empty book, and
	    the company's default book (`:617`). The `else` at `:628-632` is what a
	    reader sees only after unchecking that box. A site that keeps a SECOND book
	    must not have its rows summed alongside the ordinary ones; a site that keeps
	    a DEFAULT book must not have its rows dropped. Both are one predicate.

	The opening row below is IN, and that is the point of it. It is posted with
	`flags.from_repost` because the ordinary write path will not create one at
	all — `gl_entry.py::check_pl_account` throws for `is_opening = "Yes"` on a P&L
	account — so a repost or a data migration is the only way such a row exists.
	Rare, but when it exists the site's P&L counts it and so must this screen.

	Built as GL Entry documents directly, the way `general_ledger.make_entry`
	does, because a real Period Closing Voucher would close the site's fiscal year
	to measure a WHERE clause.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.income = _an_account(cls.company, root_type="Income")
		# A P&L row without one is refused by `pl_must_have_cost_center`.
		cls.cost_center = frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0}, "name")
		if not (cls.income and cls.cost_center):
			raise AssertionError(
				f"cannot post a P&L row on this site: income={cls.income!r} cost_center={cls.cost_center!r}"
			)
		# The site has no default finance book — and that absence is what hid the
		# bug. Measured 2026-09-04 on this site: no `Finance Book` row exists, no GL
		# row carries one, and both companies' `default_finance_book` is NULL. With
		# no default book the P&L's two arms select the same rows, so the wrong arm
		# can be copied and every test still passes. The fixture supplies the
		# difference the site does not have.
		book_name = "ADR609 P5B Default Book"
		if frappe.db.exists("Finance Book", book_name):
			# A previous run that died between the insert and its cleanup. The name is
			# this module's own, so removing it is finishing that run's rollback — the
			# company pointer first, so the restore below captures the true prior value.
			if frappe.db.get_value("Company", cls.company, "default_finance_book") == book_name:
				frappe.db.set_value("Company", cls.company, "default_finance_book", None)
			frappe.delete_doc("Finance Book", book_name, force=True, ignore_permissions=True)
		book = frappe.get_doc({"doctype": "Finance Book", "finance_book_name": book_name})
		book.flags.ignore_permissions = True
		book.insert()
		cls.default_book = cls._track("Finance Book", book.name)
		# Registered AFTER the delete, so LIFO runs the restore FIRST — before the book
		# row goes and before `_Fixture`'s single commit — so the committed company is
		# the original. (`force=True` skips link checks; the order is not about errors.)
		cls.addClassCleanup(
			frappe.db.set_value,
			"Company",
			cls.company,
			"default_finance_book",
			frappe.db.get_value("Company", cls.company, "default_finance_book"),
		)
		frappe.db.set_value("Company", cls.company, "default_finance_book", cls.default_book)

	def _post_row(
		self,
		*,
		account,
		voucher_type,
		voucher_no,
		debit=0.0,
		credit=0.0,
		is_opening="No",
		from_repost=False,
		finance_book=None,
	):
		"""One submitted GL row carrying the tender, erased when the test ends."""
		currency = frappe.db.get_value("Account", account, "account_currency") or self.currency
		row = frappe.new_doc("GL Entry")
		row.update(
			{
				"account": account,
				"company": self.company,
				"posting_date": today(),
				"debit": debit,
				"credit": credit,
				"debit_in_account_currency": debit,
				"credit_in_account_currency": credit,
				"account_currency": currency,
				"cost_center": self.cost_center,
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
				"is_opening": is_opening,
				"finance_book": finance_book,
				# Set explicitly: `default_gl_tender` deliberately skips a closing
				# voucher, so on a real site this value arrives from ERPNext's own
				# `update_default_dimensions` — which is exactly the row shape here.
				self.fieldname: self.tender,
			}
		)
		row.flags.ignore_permissions = 1
		row.flags.notify_update = False
		# `check_pl_account` REFUSES a P&L account on an opening row — measured, and
		# a good thing. It is skipped for a repost (`gl_entry.py` validate guards on
		# `flags.from_repost`) and for a closing voucher, which is precisely why the
		# opening row below is written the way a repost writes it: that is the only
		# path such a row exists on, and the only case where the filter earns its keep.
		row.flags.from_repost = from_repost
		# `voucher_no` is a Dynamic Link, so a synthetic name is refused. Creating a
		# real Period Closing Voucher instead would CLOSE THE SITE'S FISCAL YEAR to
		# measure a WHERE clause; the row shape is what this test is about, and it
		# is identical either way.
		row.flags.ignore_links = True
		row.submit()
		self.addCleanup(
			frappe.db.delete, "GL Entry", {"voucher_type": voucher_type, "voucher_no": voucher_no}
		)
		return row.name

	def test_the_reader_keeps_exactly_the_rows_the_sites_own_p_and_l_keeps(self):
		"""WHAT WOULD MAKE THIS FAIL: any of the three predicates dropped, the
		finance-book one NARROWED to `= ''`, or an `is_opening` predicate ADDED —
		the last two are how this screen has already diverged twice.

		The excluded rows are deliberately far larger than the ordinary one, so a
		version that reads them does not merely drift: it reports a year of
		closed-out income as this tender's revenue, or a second set of books as its
		costs. The default-book row is large for the mirror reason — dropping it
		does not shave a rounding error off the total, it loses a posting.
		"""
		self._post_row(
			account=self.income,
			voucher_type="Period Closing Voucher",
			voucher_no="ADR609-P5B-PCV",
			credit=9_000_000.0,
		)
		self._post_row(
			account=self.expense,
			voucher_type="Journal Entry",
			voucher_no="ADR609-P5B-FB",
			debit=4_000_000.0,
			finance_book="ADR609 P5B Book",
		)
		# IN. A default P&L run keeps the COMPANY'S DEFAULT book beside the bookless
		# rows, and reading only the bookless ones silently loses every posting a
		# site with a default book makes — which, on such a site, is most of them.
		self._post_row(
			account=self.expense,
			voucher_type="Journal Entry",
			voucher_no="ADR609-P5B-DEFAULT-FB",
			debit=600_000.0,
			finance_book=self.default_book,
		)
		# IN. The site's own P&L counts it, so this screen must too.
		self._post_row(
			account=self.expense,
			voucher_type="Journal Entry",
			voucher_no="ADR609-P5B-OPENING",
			debit=5_000_000.0,
			is_opening="Yes",
			from_repost=True,
		)
		self._post_row(
			account=self.expense,
			voucher_type="Journal Entry",
			voucher_no="ADR609-P5B-ORDINARY",
			debit=321.0,
		)

		gl = tender_gl_pnl(self.tender)
		self.assertEqual(
			gl["buckets"]["revenue"]["total"], 0.0, "the year-end close was read as this tender's revenue"
		)
		self.assertEqual(
			gl["buckets"]["expenses"]["total"],
			5_600_321.0,
			"the ledger read is no longer the rows the site's own P&L keeps: an opening row was "
			"dropped or the company's default finance book was dropped (both should be kept), "
			"or a NON-default finance book was summed (it should not)",
		)
		self.assertEqual(gl["result"], -5_600_321.0)
		self.assertEqual(
			[v["voucher_type"] for v in gl["by_voucher"]],
			["Journal Entry"],
			"an excluded voucher type was listed as a source of these figures",
		)
		self.assertEqual(
			gl["by_voucher"][0]["count"],
			3,
			"the row count no longer matches the P&L's: the non-default finance book was "
			"counted in, or the default one was counted out",
		)
