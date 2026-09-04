"""ADR-609 P5b — a tender's profit and loss, read from the General Ledger (Frappe-free).

WHY. P5a turned the tender into an Accounting Dimension, so every stamped
voucher's GL row now names the tender it belongs to. This module is the only
place that decides what those rows MEAN: which bucket an account falls into, in
what precedence, with what sign, and how the resulting figures line up against
the document-derived block the bid-pricing screen has shown until now.

The rules live here, and only here, for the same reason `_bid_pnl` does: a rule
that lives in a query cannot be exercised without a database, and money maths
that is only ever measured against a live site is measured once.

Two invariants run through everything below.

  * **Only the profit and loss is a tender's result.** P5a stamps BOTH legs of a
    voucher on purpose, so the debtor behind an invoice and the cash behind an
    expense carry the tender as well. Summing them would report double the
    revenue and double the cost. A balance-sheet row therefore reaches no bucket
    at all; the one figure taken from that side is `stock_on_hand`, reported
    beside the result and never inside it.
  * **Nothing is silently dropped.** Every P&L row ends in a bucket — the last
    rule is a catch-all, not a filter — because the defect this feature exists to
    correct is precisely a reader that omitted postings without saying so.
"""

from __future__ import annotations

#: The four buckets, in the order the screen reads them.
BUCKETS = ("revenue", "cogs", "landed", "expenses")

_PROFIT_AND_LOSS = "Profit and Loss"
_EXPENSES_IN_VALUATION = "Expenses Included In Valuation"
_COST_OF_GOODS_SOLD = "Cost of Goods Sold"
_STOCK = "Stock"


def _num(value, default: float = 0.0) -> float:
	try:
		return float(value) if value not in (None, "") else default
	except (TypeError, ValueError):
		return default


def classify_account(
	report_type: str | None,
	root_type: str | None,
	account_type: str | None,
	landed_accounts: frozenset,
	account: str,
) -> str | None:
	"""Which bucket this account's rows belong to, or None for a non-P&L account.

	The ORDER is the decision, because an account can satisfy two rules at once:
	a site that points `Stabler Settings.landed_cost_expense_account` at an
	account whose own `account_type` is "Cost of Goods Sold" has declared, in the
	one place the LCV writer reads, that the account holds landed charges. The
	settings therefore outrank the chart.
	"""
	if (report_type or "") != _PROFIT_AND_LOSS:
		return None
	if (root_type or "") == "Income":
		return "revenue"
	if account in (landed_accounts or frozenset()) or (account_type or "") == _EXPENSES_IN_VALUATION:
		return "landed"
	if (account_type or "") == _COST_OF_GOODS_SOLD:
		return "cogs"
	return "expenses"


def bucket_amount(bucket: str, debit, credit) -> float:
	"""The bucket's own natural sign: revenue is credited, every cost is debited.

	Never clipped at zero. A negative landed figure is the FINDING that a Landed
	Cost Voucher credited this tender's expense account while the receipt that
	capitalized the charge was tagged to another tender — see the
	`landed_credit_surplus` note.
	"""
	debit, credit = _num(debit), _num(credit)
	return credit - debit if bucket == "revenue" else debit - credit


def summarize(rows: list[dict], landed_accounts: frozenset) -> dict:
	"""Group `account x voucher_type` ledger rows into the screen's four buckets.

	`rows` arrive grouped by account AND voucher type, so one expense account
	that was both billed and journalled arrives twice; the buckets merge it back
	into one account line while `by_voucher` keeps the split, because the two
	tables answer different questions.
	"""
	landed_accounts = frozenset(landed_accounts or ())
	accounts: dict[str, dict[str, dict]] = {bucket: {} for bucket in BUCKETS}
	vouchers: dict[str, dict] = {}
	stock_on_hand = 0.0
	row_count = 0

	for row in rows or []:
		account = row.get("account") or ""
		account_type = row.get("account_type") or ""
		debit, credit = _num(row.get("debit")), _num(row.get("credit"))
		count = int(_num(row.get("count")))
		bucket = classify_account(
			row.get("report_type"), row.get("root_type"), account_type, landed_accounts, account
		)
		if bucket is None:
			if account_type == _STOCK:
				stock_on_hand += debit - credit
			continue
		row_count += 1
		line = accounts[bucket].setdefault(
			account,
			{
				"account": account,
				"account_name": row.get("account_name") or account,
				"debit": 0.0,
				"credit": 0.0,
				"count": 0,
			},
		)
		line["debit"] += debit
		line["credit"] += credit
		line["count"] += count
		voucher_type = row.get("voucher_type") or ""
		voucher = vouchers.setdefault(
			voucher_type, {"voucher_type": voucher_type, "count": 0, "debit": 0.0, "credit": 0.0}
		)
		voucher["count"] += count
		voucher["debit"] += debit
		voucher["credit"] += credit

	buckets = {}
	for bucket in BUCKETS:
		lines = list(accounts[bucket].values())
		total = sum(bucket_amount(bucket, line["debit"], line["credit"]) for line in lines)
		rendered = [
			{
				"account": line["account"],
				"account_name": line["account_name"],
				"amount": round(bucket_amount(bucket, line["debit"], line["credit"]), 2),
				"debit": round(line["debit"], 2),
				"credit": round(line["credit"], 2),
				"count": line["count"],
			}
			for line in lines
		]
		# By SIZE, not by sign: a credit surplus is the most important line in its
		# bucket and an ordinary descending sort would bury it at the bottom.
		rendered.sort(key=lambda line: (-abs(line["amount"]), line["account"]))
		buckets[bucket] = {"total": round(total, 2), "rows": rendered}

	# `credit - debit` is a P&L row's contribution to the RESULT whichever bucket
	# it is in (revenue adds credit, a cost subtracts debit), so this column sums
	# to `result` exactly — which is what makes it checkable rather than decorative.
	by_voucher = [
		{
			"voucher_type": voucher["voucher_type"],
			"count": voucher["count"],
			"debit": round(voucher["debit"], 2),
			"credit": round(voucher["credit"], 2),
			"net": round(voucher["credit"] - voucher["debit"], 2),
		}
		for voucher in vouchers.values()
	]
	by_voucher.sort(key=lambda voucher: (-abs(voucher["net"]), voucher["voucher_type"]))

	# From the ROUNDED bucket totals, so the four figures the screen prints add up
	# to the fifth one it prints. A result computed from unrounded sums can differ
	# from the visible columns by a cent, and a reader who checks is then right.
	result = (
		buckets["revenue"]["total"]
		- buckets["cogs"]["total"]
		- buckets["landed"]["total"]
		- buckets["expenses"]["total"]
	)
	return {
		"buckets": buckets,
		"result": round(result, 2),
		"by_voucher": by_voucher,
		"stock_on_hand": round(stock_on_hand, 2),
		"row_count": row_count,
	}


def reconcile(actual: dict | None, gl: dict) -> list[dict]:
	"""The document-derived block beside the ledger, line by line, `gl - documents`.

	`actual` is `tender._actual_block`'s output. Its revenue figure is only an
	ACTUAL while something has been invoiced: with no invoice it falls back to the
	planned bid price (`bid_price = actual_revenue or planned`), so printing it
	beside an empty ledger would show a tender that had lost its whole turnover.

	The result row is derived from the three document figures rather than from the
	waterfall's `profit`, which subtracts an exchange commission no ledger ever
	received — a permanent difference that would invite somebody to correct the
	ledger to match a number that was never posted to it.
	"""
	documents = actual or {}
	pnl = documents.get("pnl") or {}
	gl = gl or {}
	buckets = gl.get("buckets") or {}

	def total(bucket: str) -> float:
		return _num((buckets.get(bucket) or {}).get("total"))

	invoiced = bool(documents.get("invoiced"))
	doc_revenue = _num(pnl.get("net_revenue")) if invoiced else 0.0
	doc_landed = _num(documents.get("actual_landed"))
	doc_expenses = _num(documents.get("kassa_actual_total"))

	revenue_notes: list[str] = []
	if not documents:
		revenue_notes.append("no_documents")
	if not invoiced:
		revenue_notes.append("not_invoiced")
	landed_notes: list[str] = []
	if total("landed") < 0:
		landed_notes.append("landed_credit_surplus")
	if _num(gl.get("stock_on_hand")) > 0:
		landed_notes.append("stock_on_hand")

	lines = [
		("revenue", doc_revenue, total("revenue"), revenue_notes),
		# The documents' landed is a PURCHASE total: goods and their charges. In
		# the ledger the goods reach `cogs` on delivery and the charges sit in
		# `landed`, so only the two together are the same quantity.
		("landed", doc_landed, total("cogs") + total("landed"), landed_notes),
		("expenses", doc_expenses, total("expenses"), []),
		("result", doc_revenue - doc_landed - doc_expenses, _num(gl.get("result")), []),
	]
	return [
		{
			"key": key,
			"documents": round(document_side, 2),
			"gl": round(ledger_side, 2),
			"delta": round(ledger_side - document_side, 2),
			"notes": notes,
		}
		for key, document_side, ledger_side, notes in lines
	]
