"""Money module — Accounts, Journal Entries, Payment Entries, Reports.

Read endpoints + create endpoints for JE / PE (save as Draft).
All queries are company-scoped and parameterised.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint, flt, getdate, today

EXPORT_FORMATS = {"Excel", "CSV"}


def _invoice_payment_can_allocate(docstatus) -> bool:
	"""Payment Entries can only allocate against submitted invoices."""
	return cint(docstatus) == 1


def _invoice_payment_amount(doc) -> float:
	"""Return the payment cap for an invoice payment action.

	Submitted invoices use outstanding amount. Draft invoices have no AR/AP
	reference yet, so the payment is recorded as an advance capped at grand total.
	"""
	if _invoice_payment_can_allocate(getattr(doc, "docstatus", None)):
		return flt(getattr(doc, "outstanding_amount", 0))
	if cint(getattr(doc, "docstatus", None)) == 0:
		return flt(getattr(doc, "grand_total", 0))
	return 0.0


ALLOWED_REPORTS = {
	"Profit and Loss Statement",
	"Balance Sheet",
	"Trial Balance",
	"Cash Flow",
	"General Ledger",
}


from stabler.api._common import _assert_can_read, _require_company, check_concurrency


@frappe.whitelist()
def chart_of_accounts(company: str):
	"""Return the full chart of accounts for `company` as a flat list.
	The client assembles the tree from (name, parent_account)."""
	_require_company(company)
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "disabled": 0},
		fields=[
			"name",
			"account_name",
			"parent_account",
			"is_group",
			"root_type",
			"account_type",
			"account_currency",
			"account_number",
		],
		order_by="lft asc",
		limit_page_length=5000,
	)
	return rows


@frappe.whitelist()
def chart_balances(company: str, as_of: str | None = None):
	"""Closing balances for EVERY account (leaf + group) up to `as_of`.

	One GROUP BY for per-account direct sums, then a nested-set roll-up in
	Python so each group carries the total of all its descendants. Replaces the
	COA page's N per-leaf `account_balance` calls. Account-currency totals are
	leaf-only (rolling them up across mixed-currency children is meaningless —
	same rule as `account_balance`)."""
	_require_company(company)
	as_of = as_of or today()
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	# Full tree (incl. disabled) so ancestor totals stay complete and parent
	# chains never break; the client only looks up the names it renders.
	accounts = frappe.get_all(
		"Account",
		filters={"company": company},
		fields=["name", "parent_account", "is_group", "account_currency"],
		order_by="lft asc",
		limit_page_length=5000,
	)
	parent_of = {a.name: a.parent_account for a in accounts}

	rows = frappe.db.sql(
		"""
		SELECT account,
		       COALESCE(SUM(debit - credit), 0) AS base,
		       COALESCE(SUM(debit_in_account_currency - credit_in_account_currency), 0) AS acc
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND is_cancelled = 0
		  AND posting_date <= %(as_of)s
		GROUP BY account
		""",
		{"company": company, "as_of": as_of},
		as_dict=True,
	)
	direct_base = {r.account: flt(r.base) for r in rows}
	direct_acc = {r.account: flt(r.acc) for r in rows}

	# Add each account's own balance to itself and every ancestor.
	rollup = {a.name: 0.0 for a in accounts}
	for acct, val in direct_base.items():
		node, seen = acct, set()
		while node and node in rollup and node not in seen:
			seen.add(node)
			rollup[node] += val
			node = parent_of.get(node)

	balances = {
		a.name: {
			"base": rollup.get(a.name, 0.0),
			"acc": None if a.is_group else direct_acc.get(a.name, 0.0),
			"account_currency": a.account_currency or company_currency,
		}
		for a in accounts
	}
	return {"company_currency": company_currency, "as_of": str(as_of), "balances": balances}


@frappe.whitelist()
def gl_entries(
	company: str,
	account: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 100,
	start: int = 0,
	order: str = "desc",
):
	"""GL Entries for a single account, paginated, with server-side running balance.

	Pagination: `start` is the 0-based row offset; `limit` is the page size
	(clamped to 500). Callers accumulate pages client-side for scroll-to-load.

	Running balance is computed via a window function over the full filtered set
	(before LIMIT/OFFSET) so paged results are self-consistent regardless of offset.

	Zero-movement rows (both debit and credit == 0) are excluded — they represent
	internal accounting adjustments with no cash effect.

	Returns:
		entries      – list of dicts (includes running_balance, running_balance_base)
		total_count  – COUNT of the full filtered set (for has_more detection)
		has_more     – bool, whether rows exist beyond this page
		opening_base / opening_account – balance before from_date (0 when no from_date)
		as_of        – effective to_date used for closing balance
	"""
	_require_company(company)
	if not account:
		frappe.throw("Account is required.")
	limit = max(1, min(500, int(limit)))
	start = max(0, int(start))
	order = "asc" if str(order).lower() == "asc" else "desc"

	from_d = getdate(from_date) if from_date else None
	to_d = getdate(to_date) if to_date else None

	# Build WHERE for the filtered set (excludes zero-movement rows).
	# The same conditions go into every query in this function.
	base_conds = [
		"company = %(company)s",
		"account = %(account)s",
		"is_cancelled = 0",
		"(debit_in_account_currency != 0 OR credit_in_account_currency != 0)",
	]
	params: dict = {"company": company, "account": account}
	if from_d:
		base_conds.append("posting_date >= %(from_date)s")
		params["from_date"] = from_d
	if to_d:
		base_conds.append("posting_date <= %(to_date)s")
		params["to_date"] = to_d
	where = " AND ".join(base_conds)

	# Opening balance: sum of ALL movements strictly before from_date, in both
	# currencies. Zero when no from_date (opening = "beginning of time").
	opening_acc = 0.0
	opening_base = 0.0
	if from_d:
		op = frappe.db.sql(
			"""
			SELECT
				COALESCE(SUM(debit - credit), 0) AS base,
				COALESCE(SUM(debit_in_account_currency - credit_in_account_currency), 0) AS acc
			FROM `tabGL Entry`
			WHERE company = %(company)s AND account = %(account)s
			  AND is_cancelled = 0 AND posting_date < %(from_date)s
			""",
			{"company": company, "account": account, "from_date": from_d},
			as_dict=True,
		)
		if op:
			opening_base = flt(op[0]["base"])
			opening_acc = flt(op[0]["acc"])

	# Total count of filtered rows (for has_more).
	count_row = frappe.db.sql(
		f"SELECT COUNT(*) AS n FROM `tabGL Entry` WHERE {where}",
		params,
		as_dict=True,
	)
	total_count = count_row[0]["n"] if count_row else 0

	# Main query: compute running balance as a window function (SUM OVER ORDER BY)
	# anchored to opening_base/opening_acc. The inner subquery covers the full
	# filtered set so each row's running_balance is correct at any offset.
	# The outer ORDER BY + LIMIT/OFFSET then selects the requested page.
	# MariaDB 10.6+ supports SUM() OVER (ORDER BY ...).
	dir_sql = "ASC" if order == "asc" else "DESC"
	paged_params = {**params, "opening_acc": opening_acc, "opening_base": opening_base}
	rows = frappe.db.sql(
		f"""
		SELECT *
		FROM (
			SELECT
				name, creation, posting_date, voucher_type, voucher_no, against, remarks,
				party_type, party,
				debit, credit,
				debit_in_account_currency, credit_in_account_currency,
				account_currency,
				%(opening_acc)s + SUM(debit_in_account_currency - credit_in_account_currency)
					OVER (ORDER BY posting_date ASC, creation ASC, name ASC)
					AS running_balance,
				%(opening_base)s + SUM(debit - credit)
					OVER (ORDER BY posting_date ASC, creation ASC, name ASC)
					AS running_balance_base
			FROM `tabGL Entry`
			WHERE {where}
		) _windowed
		ORDER BY posting_date {dir_sql}, creation {dir_sql}, name {dir_sql}
		LIMIT %(limit)s OFFSET %(start)s
		""",
		{**paged_params, "limit": limit, "start": start},
		as_dict=True,
	)

	as_of = to_d or today()
	for r in rows:
		r["posting_date"] = str(r["posting_date"]) if r["posting_date"] else ""

	return {
		"entries": rows,
		"total_count": total_count,
		"has_more": (start + len(rows)) < total_count,
		"opening_base": opening_base,
		"opening_account": opening_acc,
		"as_of": str(as_of),
	}


@frappe.whitelist()
def account_balance(company: str, account: str, as_of: str | None = None):
	"""Closing balance of a single account up to `as_of` (default: today).

	Returns both company-currency (`balance_base`) and account-currency
	(`balance_acc`) aggregates. `balance` is kept as an alias for
	`balance_base` for backward compatibility with existing callers."""
	_require_company(company)
	if not account:
		frappe.throw("Account is required.")
	as_of = as_of or today()
	acc_meta = frappe.db.get_value(
		"Account",
		account,
		["account_currency", "is_group"],
		as_dict=True,
	)
	if not acc_meta:
		frappe.throw(f"Unknown account: {account}")
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(debit - credit), 0) AS base,
		       COALESCE(SUM(debit_in_account_currency - credit_in_account_currency), 0) AS acc
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND account = %(account)s
		  AND is_cancelled = 0
		  AND posting_date <= %(as_of)s
		""",
		{"company": company, "account": account, "as_of": as_of},
		as_dict=True,
	)
	base = flt(row[0]["base"]) if row else 0.0
	# Group accounts: account-currency sum is meaningless across mixed-currency
	# children, so surface it as None and let the UI render em-dash.
	acc = None if acc_meta.is_group else (flt(row[0]["acc"]) if row else 0.0)
	return {
		"account": account,
		"account_currency": acc_meta.account_currency or company_currency,
		"company_currency": company_currency,
		"balance_base": base,
		"balance_acc": acc,
		"balance": base,
		"as_of": str(as_of),
	}


@frappe.whitelist()
def account_summary(
	company: str,
	account: str,
	from_date: str | None = None,
	to_date: str | None = None,
):
	"""Opening / period / closing balance for an account using the
	debit-minus-credit signed convention (positive for asset/expense, negative
	for liability/equity/income). Caller renders sign as appropriate."""
	_require_company(company)
	if not account:
		frappe.throw("Account is required.")
	acc_row = frappe.db.get_value(
		"Account",
		account,
		["account_name", "account_currency", "root_type"],
		as_dict=True,
	)
	if not acc_row:
		frappe.throw(f"Unknown account: {account}")

	from_d = getdate(from_date) if from_date else None
	to_d = getdate(to_date) if to_date else None

	opening = 0.0
	if from_d:
		op = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(debit_in_account_currency - credit_in_account_currency), 0) AS bal
			FROM `tabGL Entry`
			WHERE company = %(company)s AND account = %(account)s
			  AND is_cancelled = 0 AND posting_date < %(from_date)s
			""",
			{"company": company, "account": account, "from_date": from_d},
			as_dict=True,
		)
		opening = flt(op[0]["bal"]) if op else 0.0

	per_conds = ["company = %(company)s", "account = %(account)s", "is_cancelled = 0"]
	per_params: dict = {"company": company, "account": account}
	if from_d:
		per_conds.append("posting_date >= %(from_date)s")
		per_params["from_date"] = from_d
	if to_d:
		per_conds.append("posting_date <= %(to_date)s")
		per_params["to_date"] = to_d
	per_where = " AND ".join(per_conds)
	per = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(debit_in_account_currency), 0) AS dr,
		       COALESCE(SUM(credit_in_account_currency), 0) AS cr
		FROM `tabGL Entry`
		WHERE {per_where}
		""",
		per_params,
		as_dict=True,
	)
	period_debit = flt(per[0]["dr"]) if per else 0.0
	period_credit = flt(per[0]["cr"]) if per else 0.0
	closing = opening + period_debit - period_credit
	return {
		"account": account,
		"account_name": acc_row.account_name,
		"account_currency": acc_row.account_currency,
		"root_type": acc_row.root_type,
		"opening_balance": opening,
		"period_debit": period_debit,
		"period_credit": period_credit,
		"closing_balance": closing,
		"from_date": str(from_d) if from_d else None,
		"to_date": str(to_d) if to_d else None,
	}


def _date_filters(from_date: str | None, to_date: str | None):
	clauses = []
	params: dict = {}
	if from_date:
		clauses.append("posting_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		clauses.append("posting_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	return clauses, params


@frappe.whitelist()
def list_journal_entries(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 50,
):
	_require_company(company)
	clauses, params = _date_filters(from_date, to_date)
	params["company"] = company
	params["limit"] = int(limit)
	qualified_clauses = [c.replace("posting_date", "je.posting_date") for c in clauses]
	where = " AND ".join([
		"je.company = %(company)s",
		"je.docstatus < 2",
		*qualified_clauses,
	])
	# JE.total_debit/total_credit are base-currency totals. Surface them as
	# *_base + base_currency so the UI can never confuse them with a row's
	# native account-currency amount.
	rows = frappe.db.sql(
		f"""
		SELECT je.name, je.posting_date, je.voucher_type, je.cheque_no, je.user_remark,
		       je.total_debit AS total_debit_base,
		       je.total_credit AS total_credit_base,
		       je.multi_currency,
		       je.docstatus,
		       c.default_currency AS base_currency
		FROM `tabJournal Entry` je
		JOIN `tabCompany` c ON c.name = je.company
		WHERE {where}
		ORDER BY je.posting_date DESC, je.name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	return rows


@frappe.whitelist()
def journal_entry_detail(name: str):
	if not name:
		frappe.throw("Journal Entry name is required.")
	_assert_can_read("Journal Entry", name)
	doc = frappe.get_doc("Journal Entry", name)
	base_currency = frappe.db.get_value("Company", doc.company, "default_currency") or ""
	# JE.total_debit/total_credit on the parent doc are base-currency totals.
	# Per-row values come in both account-currency (what the user entered) and
	# base-currency (what hits GL). Expose BOTH explicitly so the UI never has
	# to guess which dimension a number lives in.
	return {
		"name": doc.name,
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"voucher_type": doc.voucher_type,
		"user_remark": doc.user_remark,
		"entry_kind": "Asset Purchase" if (doc.user_remark or "").startswith("[Asset Purchase]") else None,
		"pay_to_recd_from": doc.pay_to_recd_from,
		"cheque_no": doc.cheque_no,
		"cheque_date": str(doc.cheque_date) if doc.cheque_date else None,
		"total_debit_base": flt(doc.total_debit),
		"total_credit_base": flt(doc.total_credit),
		"base_currency": base_currency,
		"multi_currency": int(doc.multi_currency or 0),
		"company": doc.company,
		"docstatus": doc.docstatus,
		"accounts": [
			{
				"account": a.account,
				"party_type": a.party_type,
				"party": a.party,
				"debit_in_account_currency": flt(a.debit_in_account_currency),
				"credit_in_account_currency": flt(a.credit_in_account_currency),
				"debit_base": flt(a.debit),
				"credit_base": flt(a.credit),
				"account_currency": a.account_currency,
				"exchange_rate": flt(a.exchange_rate or 1.0),
				"reference_type": a.reference_type,
				"reference_name": a.reference_name,
				"user_remark": a.user_remark,
			}
			for a in doc.accounts
		],
	}


@frappe.whitelist()
def create_journal_entry(
	company: str,
	posting_date: str,
	accounts: list | str,
	voucher_type: str = "Journal Entry",
	user_remark: str | None = None,
	cheque_no: str | None = None,
	cheque_date: str | None = None,
) -> dict:
	"""Create a Journal Entry as Draft (docstatus=0).

	`accounts` is a list of dicts with keys:
	  account (required), party_type, party, debit, credit, reference_type, reference_name.
	Exactly one of debit/credit per line must be non-zero. Totals must balance.
	"""
	_require_company(company)
	if isinstance(accounts, str):
		try:
			accounts = json.loads(accounts)
		except Exception:
			frappe.throw("Invalid accounts payload.")
	if not isinstance(accounts, list) or len(accounts) < 2:
		frappe.throw("At least two account lines are required.")

	total_debit = 0.0
	total_credit = 0.0
	cleaned: list[dict] = []
	for idx, row in enumerate(accounts, start=1):
		acc = (row or {}).get("account")
		if not acc:
			frappe.throw(f"Row {idx}: account is required.")
		debit = flt(row.get("debit"))
		credit = flt(row.get("credit"))
		if debit < 0 or credit < 0:
			frappe.throw(f"Row {idx}: debit / credit must be non-negative.")
		if debit and credit:
			frappe.throw(f"Row {idx}: only one of debit / credit may be set.")
		if not debit and not credit:
			frappe.throw(f"Row {idx}: enter a debit or credit amount.")
		acc_doc = frappe.db.get_value(
			"Account",
			acc,
			["company", "is_group", "account_currency"],
			as_dict=True,
		)
		if not acc_doc:
			frappe.throw(f"Row {idx}: account '{acc}' does not exist.")
		if acc_doc.company != company:
			frappe.throw(f"Row {idx}: account '{acc}' is not in company '{company}'.")
		if acc_doc.is_group:
			frappe.throw(f"Row {idx}: '{acc}' is a group account.")
		total_debit += debit
		total_credit += credit
		cleaned.append(
			{
				"account": acc,
				"party_type": row.get("party_type") or None,
				"party": row.get("party") or None,
				"debit_in_account_currency": debit,
				"credit_in_account_currency": credit,
				"reference_type": row.get("reference_type") or None,
				"reference_name": row.get("reference_name") or None,
				"_ccy": acc_doc.account_currency or "",
			}
		)

	# Allow a 1-cent rounding wobble — the doc.validate() will catch real mismatches.
	if abs(total_debit - total_credit) > 0.01:
		frappe.throw(
			f"Debit ({total_debit:.2f}) and credit ({total_credit:.2f}) must balance."
		)

	base_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	any_non_base = any(r.pop("_ccy", "") != base_currency for r in cleaned)

	doc = frappe.new_doc("Journal Entry")
	doc.company = company
	doc.posting_date = getdate(posting_date)
	doc.voucher_type = voucher_type
	doc.multi_currency = 1 if any_non_base else 0
	if user_remark:
		doc.user_remark = user_remark
	if cheque_no:
		doc.cheque_no = cheque_no
	if cheque_date:
		doc.cheque_date = getdate(cheque_date)
	for row in cleaned:
		doc.append("accounts", row)
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def list_payment_entries(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 50,
):
	_require_company(company)
	clauses, params = _date_filters(from_date, to_date)
	params["company"] = company
	params["limit"] = int(limit)
	where = " AND ".join(["company = %(company)s", "docstatus < 2", *clauses])
	rows = frappe.db.sql(
		f"""
		SELECT name, posting_date, payment_type, party_type, party, party_name,
		       paid_from, paid_to, paid_amount, received_amount, reference_no,
		       reference_date, mode_of_payment, docstatus,
		       paid_from_account_currency, paid_to_account_currency,
		       source_exchange_rate, target_exchange_rate
		FROM `tabPayment Entry`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	return rows


@frappe.whitelist()
def payment_entry_detail(name: str):
	if not name:
		frappe.throw("Payment Entry name is required.")
	_assert_can_read("Payment Entry", name)
	doc = frappe.get_doc("Payment Entry", name)
	return {
		"name": doc.name,
		"modified": str(doc.modified),
		"posting_date": str(doc.posting_date) if doc.posting_date else None,

		"payment_type": doc.payment_type,
		"party_type": doc.party_type,
		"party": doc.party,
		"party_name": doc.party_name,
		"paid_from": doc.paid_from,
		"paid_to": doc.paid_to,
		"paid_amount": flt(doc.paid_amount),
		"received_amount": flt(doc.received_amount),
		"paid_from_account_currency": doc.paid_from_account_currency,
		"paid_to_account_currency": doc.paid_to_account_currency,
		"source_exchange_rate": flt(doc.source_exchange_rate),
		"target_exchange_rate": flt(doc.target_exchange_rate),
		"reference_no": doc.reference_no,
		"reference_date": str(doc.reference_date) if doc.reference_date else None,
		"mode_of_payment": doc.mode_of_payment,
		"docstatus": doc.docstatus,
		"references": [
			{
				"reference_doctype": r.reference_doctype,
				"reference_name": r.reference_name,
				"total_amount": flt(r.total_amount),
				"outstanding_amount": flt(r.outstanding_amount),
				"allocated_amount": flt(r.allocated_amount),
			}
			for r in (doc.references or [])
		],
	}


@frappe.whitelist()
def update_payment_entry(
	name: str,
	posting_date: str | None = None,
	mode_of_payment: str | None = None,
	reference_no: str | None = None,
	reference_date: str | None = None,
	paid_amount: float | str | None = None,
	received_amount: float | str | None = None,
	modified: str | None = None,
):
	if not name:
		frappe.throw("Payment Entry name is required.")
	check_concurrency("Payment Entry", name, modified)
	doc = frappe.get_doc("Payment Entry", name)
	if doc.docstatus != 0:
		frappe.throw("Only Draft Payment Entries can be edited.")

	if posting_date:
		doc.posting_date = getdate(posting_date)
	doc.mode_of_payment = mode_of_payment or None
	doc.reference_no = reference_no or None
	doc.reference_date = getdate(reference_date) if reference_date else None

	if paid_amount not in (None, ""):
		paid = flt(paid_amount)
		if paid <= 0:
			frappe.throw("Paid amount must be greater than zero.")
		doc.paid_amount = paid
	if received_amount not in (None, ""):
		received = flt(received_amount)
		if received <= 0:
			frappe.throw("Received amount must be greater than zero.")
		doc.received_amount = received

	party_amount = flt(doc.paid_amount) if doc.payment_type == "Receive" else flt(doc.received_amount)
	total_allocated = sum(flt(r.allocated_amount) for r in (doc.references or []))
	if total_allocated > party_amount + 0.005:
		frappe.throw(
			f"Total allocated ({total_allocated:.2f}) exceeds payment amount ({party_amount:.2f})."
		)

	doc.save(ignore_permissions=False)
	return payment_entry_detail(doc.name)


@frappe.whitelist()
def party_payment_defaults(company: str, party_type: str, party: str) -> dict:
	"""Return party account, outstanding invoices, and cash/bank accounts for the New Payment form."""
	_require_company(company)
	if party_type not in {"Customer", "Supplier"}:
		frappe.throw("party_type must be Customer or Supplier.")
	if not party or not frappe.db.exists(party_type, party):
		frappe.throw(f"{party_type} '{party}' does not exist.")

	from erpnext.accounts.party import get_party_account
	from erpnext.accounts.utils import get_outstanding_invoices

	party_account = get_party_account(party_type, party=party, company=company)
	party_account_currency = (
		frappe.db.get_value("Account", party_account, "account_currency") or ""
	)

	raw = get_outstanding_invoices(party_type, party, [party_account]) or []
	invoices = sorted(
		[
			{
				"voucher_type": r.get("voucher_type", ""),
				"voucher_no": r.get("voucher_no", ""),
				"posting_date": str(r.get("posting_date") or ""),
				"due_date": str(r.get("due_date") or ""),
				"invoice_amount": flt(r.get("invoice_amount", 0)),
				"outstanding_amount": flt(r.get("outstanding_amount", 0)),
			}
			for r in raw
			if flt(r.get("outstanding_amount", 0)) > 0
		],
		key=lambda x: x["posting_date"],
	)

	cash_bank = list_cash_bank_accounts(company)
	suggested = cash_bank[0]["name"] if cash_bank else None

	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	paying_account_currency = company_currency
	if suggested:
		paying_account_currency = frappe.db.get_value("Account", suggested, "account_currency") or company_currency

	needs_exchange = party_account_currency != paying_account_currency

	effective_rate = 1.0
	rate_date = today()
	if needs_exchange:
		if "UZS" in (party_account_currency, paying_account_currency):
			foreign = party_account_currency if party_account_currency != "UZS" else paying_account_currency
			local = "UZS"
		else:
			foreign = party_account_currency
			local = paying_account_currency

		cbu = frappe.get_all(
			"Currency Exchange",
			filters={"from_currency": foreign, "to_currency": local, "date": ("<= ", today())},
			fields=["exchange_rate", "date"],
			order_by="date desc",
			limit=1
		)
		if cbu:
			effective_rate = flt(cbu[0].exchange_rate)
			rate_date = str(cbu[0].date)

	return {
		"party_account": party_account,
		"party_account_currency": party_account_currency,
		"outstanding_invoices": invoices,
		"total_outstanding": sum(r["outstanding_amount"] for r in invoices),
		"cash_bank_accounts": cash_bank,
		"suggested_cash_bank_account": suggested,
		"paying_account_currency": paying_account_currency,
		"needs_exchange": needs_exchange,
		"effective_rate": effective_rate,
		"rate_date": rate_date,
	}


def setup_payment_entry_exchange_rates(doc, exchange_rate: float | str | None = None) -> None:
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "UZS"
	paid_from_currency = frappe.db.get_value("Account", doc.paid_from, "account_currency") or company_currency
	paid_to_currency = frappe.db.get_value("Account", doc.paid_to, "account_currency") or company_currency

	if paid_from_currency != paid_to_currency:
		# Cross-currency payment! Verify exchange gain/loss account is set
		gain_loss_account = frappe.db.get_value("Company", doc.company, "exchange_gain_loss_account")
		if not gain_loss_account:
			frappe.throw(
				_("Default Exchange Gain/Loss Account is missing for company {0}. "
				  "Please configure it in Company settings before posting cross-currency transactions.").format(doc.company),
				frappe.ValidationError
			)

		# Apply exchange rate to source/target exchange rate fields
		if paid_from_currency == company_currency:
			doc.source_exchange_rate = 1.0
		if paid_to_currency == company_currency:
			doc.target_exchange_rate = 1.0

		if paid_from_currency != company_currency:
			if exchange_rate and flt(exchange_rate) > 0:
				if paid_from_currency == "UZS" and company_currency == "USD":
					doc.source_exchange_rate = 1.0 / flt(exchange_rate)
				elif paid_from_currency == "USD" and company_currency == "UZS":
					doc.source_exchange_rate = flt(exchange_rate)
				else:
					doc.source_exchange_rate = flt(exchange_rate)
			else:
				doc.source_exchange_rate = flt(get_exchange_rate_for_currencies(paid_from_currency, company_currency, doc.posting_date))

		if paid_to_currency != company_currency:
			if exchange_rate and flt(exchange_rate) > 0:
				if paid_to_currency == "UZS" and company_currency == "USD":
					doc.target_exchange_rate = 1.0 / flt(exchange_rate)
				elif paid_to_currency == "USD" and company_currency == "UZS":
					doc.target_exchange_rate = flt(exchange_rate)
				else:
					doc.target_exchange_rate = flt(exchange_rate)
			else:
				doc.target_exchange_rate = flt(get_exchange_rate_for_currencies(paid_to_currency, company_currency, doc.posting_date))


@frappe.whitelist()
def create_payment_entry(
	company: str,
	posting_date: str,
	payment_type: str,
	party_type: str,
	party: str,
	paid_from: str,
	paid_to: str,
	paid_amount: float | str,
	received_amount: float | str | None = None,
	mode_of_payment: str | None = None,
	reference_no: str | None = None,
	reference_date: str | None = None,
	references: list | str | None = None,
	exchange_rate: float | str | None = None,
) -> dict:
	"""Create a Payment Entry as Draft (docstatus=0).

	payment_type:
	  - "Receive" — paid_from is the party's receivable account, paid_to is bank/cash.
	  - "Pay"     — paid_from is bank/cash, paid_to is the party's payable account.
	"""
	_require_company(company)
	if payment_type not in {"Receive", "Pay"}:
		frappe.throw("payment_type must be 'Receive' or 'Pay'.")
	if party_type not in {"Customer", "Supplier", "Employee"}:
		frappe.throw("party_type must be Customer, Supplier or Employee.")
	if not (party and paid_from and paid_to):
		frappe.throw("Party, paid_from and paid_to are required.")
	if not frappe.db.exists(party_type, party):
		frappe.throw(f"{party_type} '{party}' does not exist.")

	for acct_field, acct in (("paid_from", paid_from), ("paid_to", paid_to)):
		row = frappe.db.get_value(
			"Account", acct, ["company", "is_group"], as_dict=True
		)
		if not row:
			frappe.throw(f"{acct_field}: account '{acct}' does not exist.")
		if row.company != company:
			frappe.throw(f"{acct_field}: account '{acct}' is not in company '{company}'.")
		if row.is_group:
			frappe.throw(f"{acct_field}: '{acct}' is a group account.")

	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or company_currency
	paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency

	paid = flt(paid_amount)
	if paid <= 0:
		frappe.throw("Paid amount must be greater than zero.")
	recv = flt(received_amount) if received_amount not in (None, "") else 0.0

	if paid_from_currency != paid_to_currency:
		if exchange_rate and flt(exchange_rate) > 0:
			rate = flt(exchange_rate)
			if paid > 0 and recv == 0:
				if payment_type == "Receive":
					if paid_from_currency == "USD" and paid_to_currency == "UZS":
						recv = paid * rate
					elif paid_from_currency == "UZS" and paid_to_currency == "USD":
						recv = paid / rate
					else:
						recv = paid * rate
				else:
					if paid_from_currency == "UZS" and paid_to_currency == "USD":
						recv = paid / rate
					elif paid_from_currency == "USD" and paid_to_currency == "UZS":
						recv = paid * rate
					else:
						recv = paid / rate
			elif recv > 0 and paid == 0:
				if payment_type == "Receive":
					if paid_from_currency == "USD" and paid_to_currency == "UZS":
						paid = recv / rate
					elif paid_from_currency == "UZS" and paid_to_currency == "USD":
						paid = recv * rate
					else:
						paid = recv / rate
				else:
					if paid_from_currency == "UZS" and paid_to_currency == "USD":
						paid = recv * rate
					elif paid_from_currency == "USD" and paid_to_currency == "UZS":
						paid = recv / rate
					else:
						paid = recv * rate

		if recv == 0:
			recv = paid
	else:
		recv = paid if recv == 0 else recv

	doc = frappe.new_doc("Payment Entry")
	doc.company = company
	doc.posting_date = getdate(posting_date)
	doc.payment_type = payment_type
	doc.party_type = party_type
	doc.party = party
	doc.paid_from = paid_from
	doc.paid_to = paid_to
	doc.paid_amount = paid
	doc.received_amount = recv
	if mode_of_payment:
		doc.mode_of_payment = mode_of_payment
	if reference_no:
		doc.reference_no = reference_no
	if reference_date:
		doc.reference_date = getdate(reference_date)
	if references:
		refs = json.loads(references) if isinstance(references, str) else references
		party_amt = paid if payment_type == "Receive" else recv
		total_alloc = sum(flt(r.get("allocated_amount", 0)) for r in refs)
		if total_alloc > party_amt + 0.005:
			frappe.throw(
				f"Total allocated ({total_alloc:.2f}) exceeds payment amount ({party_amt:.2f})."
			)
		for r in refs:
			doc.append(
				"references",
				{
					"reference_doctype": r.get("reference_doctype"),
					"reference_name": r.get("reference_name"),
					"total_amount": flt(r.get("total_amount", 0)),
					"outstanding_amount": flt(r.get("outstanding_amount", 0)),
					"allocated_amount": flt(r.get("allocated_amount", 0)),
				},
			)
	setup_payment_entry_exchange_rates(doc, exchange_rate)
	doc.setup_party_account_field()
	doc.set_missing_values()
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def list_modes_of_payment(limit: int = 100):
	"""Modes of Payment available globally (Cash, Bank, Wire, etc.)."""
	return frappe.db.sql(
		"""
		SELECT name, type FROM `tabMode of Payment`
		WHERE enabled = 1
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def list_cash_bank_accounts(company: str, limit: int = 100):
	"""Cash + Bank leaf accounts for the given company — used to populate paid_from / paid_to pickers."""
	_require_company(company)
	return frappe.db.sql(
		"""
		SELECT name, account_name, account_type, account_currency
		FROM `tabAccount`
		WHERE company = %(company)s
		  AND disabled = 0
		  AND is_group = 0
		  AND account_type IN ('Cash', 'Bank')
		ORDER BY account_type, account_name
		LIMIT %(limit)s
		""",
		{"company": company, "limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def submit_payment_entry(name: str, modified: str | None = None):
	"""Submit a Draft Payment Entry (docstatus 0 → 1)."""
	if not name:
		frappe.throw("Payment Entry name is required.")
	check_concurrency("Payment Entry", name, modified)
	doc = frappe.get_doc("Payment Entry", name)
	if doc.docstatus == 1:
		frappe.throw("Payment Entry is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Payment Entry is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def cancel_payment_entry(name: str, modified: str | None = None):
	"""Cancel a submitted Payment Entry."""
	if not name:
		frappe.throw("Payment Entry name is required.")
	check_concurrency("Payment Entry", name, modified)
	doc = frappe.get_doc("Payment Entry", name)
	if doc.docstatus == 0:
		frappe.throw("Draft Payment Entry cannot be cancelled. Delete it instead.")
	if doc.docstatus == 2:
		frappe.throw("Payment Entry is already cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def delete_payment_entry(name: str, modified: str | None = None):
	"""Delete a Draft Payment Entry."""
	if not name:
		frappe.throw("Payment Entry name is required.")
	check_concurrency("Payment Entry", name, modified)
	doc = frappe.get_doc("Payment Entry", name)
	if doc.docstatus != 0:
		frappe.throw("Only Draft Payment Entries can be deleted.")
	doc.delete()
	return {"name": name, "deleted": True}


@frappe.whitelist()
def payment_defaults_for_invoice(company: str, invoice_type: str, invoice_name: str):
	"""Pre-fill data for paying a Sales/Purchase invoice.

	Returns:
	  party_type, party, party_name, party_account, currency, outstanding_amount,
	  payment_type ('Receive' for SI, 'Pay' for PI), suggested_cash_bank_account.
	"""
	_require_company(company)
	if invoice_type not in {"Sales Invoice", "Purchase Invoice"}:
		frappe.throw("invoice_type must be 'Sales Invoice' or 'Purchase Invoice'.")
	if not invoice_name or not frappe.db.exists(invoice_type, invoice_name):
		frappe.throw(f"Unknown {invoice_type}: {invoice_name}")
	_assert_can_read(invoice_type, invoice_name)
	doc = frappe.get_doc(invoice_type, invoice_name)
	if doc.docstatus == 2:
		frappe.throw("Cancelled invoices cannot be paid.")
	if doc.company != company:
		frappe.throw("Invoice belongs to a different company.")

	if invoice_type == "Sales Invoice":
		payment_type = "Receive"
		party_type = "Customer"
		party = doc.customer
		party_name = doc.customer_name
		party_account = doc.debit_to
	else:
		payment_type = "Pay"
		party_type = "Supplier"
		party = doc.supplier
		party_name = doc.supplier_name
		party_account = doc.credit_to

	cash_bank = list_cash_bank_accounts(company, limit=100)
	suggested = cash_bank[0]["name"] if cash_bank else None

	party_account_currency = doc.currency
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	paying_account_currency = company_currency
	if suggested:
		paying_account_currency = frappe.db.get_value("Account", suggested, "account_currency") or company_currency

	needs_exchange = party_account_currency != paying_account_currency

	effective_rate = 1.0
	rate_date = today()
	if needs_exchange:
		if "UZS" in (party_account_currency, paying_account_currency):
			foreign = party_account_currency if party_account_currency != "UZS" else paying_account_currency
			local = "UZS"
		else:
			foreign = party_account_currency
			local = paying_account_currency

		cbu = frappe.get_all(
			"Currency Exchange",
			filters={"from_currency": foreign, "to_currency": local, "date": ("<= ", today())},
			fields=["exchange_rate", "date"],
			order_by="date desc",
			limit=1
		)
		if cbu:
			effective_rate = flt(cbu[0].exchange_rate)
			rate_date = str(cbu[0].date)

	return {
		"invoice_type": invoice_type,
		"invoice_name": invoice_name,
		"company": company,
		"payment_type": payment_type,
		"party_type": party_type,
		"party": party,
		"party_name": party_name,
		"party_account": party_account,
		"currency": doc.currency,
		"docstatus": doc.docstatus,
		"can_allocate_to_invoice": _invoice_payment_can_allocate(doc.docstatus),
		"outstanding_amount": _invoice_payment_amount(doc),
		"grand_total": flt(doc.grand_total),
		"cash_bank_accounts": cash_bank,
		"suggested_cash_bank_account": suggested,
		"party_account_currency": party_account_currency,
		"paying_account_currency": paying_account_currency,
		"needs_exchange": needs_exchange,
		"effective_rate": effective_rate,
		"rate_date": rate_date,
	}


@frappe.whitelist()
def create_payment_for_invoice(
	company: str,
	invoice_type: str,
	invoice_name: str,
	bank_account: str,
	paid_amount: float | str,
	posting_date: str | None = None,
	mode_of_payment: str | None = None,
	reference_no: str | None = None,
	reference_date: str | None = None,
	allocated_amount: float | str | None = None,
	submit: int = 1,
	modified: str | None = None,
	received_amount: float | str | None = None,
	exchange_rate: float | str | None = None,
):
	"""Create a Payment Entry allocated to a single invoice, optionally submit it in the same call."""
	check_concurrency(invoice_type, invoice_name, modified)
	defaults = payment_defaults_for_invoice(company, invoice_type, invoice_name)
	posting_date = posting_date or today()

	if defaults["payment_type"] == "Receive":
		paid_from = defaults["party_account"]
		paid_to = bank_account
	else:
		paid_from = bank_account
		paid_to = defaults["party_account"]

	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or company_currency
	paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency

	paid = flt(paid_amount)
	if paid <= 0:
		frappe.throw("Paid amount must be greater than zero.")
	recv = flt(received_amount) if received_amount not in (None, "") else 0.0

	if paid_from_currency != paid_to_currency:
		if exchange_rate and flt(exchange_rate) > 0:
			rate = flt(exchange_rate)
			if paid > 0 and recv == 0:
				if defaults["payment_type"] == "Receive":
					if paid_from_currency == "USD" and paid_to_currency == "UZS":
						recv = paid * rate
					elif paid_from_currency == "UZS" and paid_to_currency == "USD":
						recv = paid / rate
					else:
						recv = paid * rate
				else:
					if paid_from_currency == "UZS" and paid_to_currency == "USD":
						recv = paid / rate
					elif paid_from_currency == "USD" and paid_to_currency == "UZS":
						recv = paid * rate
					else:
						recv = paid / rate
			elif recv > 0 and paid == 0:
				if defaults["payment_type"] == "Receive":
					if paid_from_currency == "USD" and paid_to_currency == "UZS":
						paid = recv / rate
					elif paid_from_currency == "UZS" and paid_to_currency == "USD":
						paid = recv * rate
					else:
						paid = recv / rate
				else:
					if paid_from_currency == "UZS" and paid_to_currency == "USD":
						paid = recv * rate
					elif paid_from_currency == "USD" and paid_to_currency == "UZS":
						paid = recv / rate
					else:
						paid = recv * rate

		if recv == 0:
			recv = paid
	else:
		recv = paid if recv == 0 else recv

	party_amount = paid if defaults["payment_type"] == "Receive" else recv

	can_allocate = bool(defaults.get("can_allocate_to_invoice"))
	allocated = flt(allocated_amount) if allocated_amount not in (None, "") else party_amount
	if allocated <= 0 or allocated > flt(defaults["outstanding_amount"]):
		frappe.throw(
			f"Allocated amount must be between 0 and outstanding ({defaults['outstanding_amount']:.2f})."
		)

	doc = frappe.new_doc("Payment Entry")
	doc.company = company
	doc.posting_date = getdate(posting_date)
	doc.payment_type = defaults["payment_type"]
	doc.party_type = defaults["party_type"]
	doc.party = defaults["party"]
	doc.paid_from = paid_from
	doc.paid_to = paid_to
	doc.paid_amount = paid
	doc.received_amount = recv
	if mode_of_payment:
		doc.mode_of_payment = mode_of_payment
	if reference_no:
		doc.reference_no = reference_no
	if reference_date:
		doc.reference_date = getdate(reference_date)
	if can_allocate:
		doc.append(
			"references",
			{
				"reference_doctype": invoice_type,
				"reference_name": invoice_name,
				"total_amount": flt(defaults["grand_total"]),
				"outstanding_amount": flt(defaults["outstanding_amount"]),
				"allocated_amount": allocated,
			},
		)
	setup_payment_entry_exchange_rates(doc, exchange_rate)
	doc.setup_party_account_field()
	doc.set_missing_values()
	doc.insert(ignore_permissions=False)
	if int(submit):
		try:
			doc.submit()
		except Exception:
			# Roll back the just-inserted Draft so no orphan remains in the DB.
			# The validation error is re-raised and surfaced as a toast in the UI.
			frappe.db.rollback()
			raise
	return {"name": doc.name, "docstatus": doc.docstatus, "allocated_to_invoice": can_allocate}


def _resolve_fiscal_year(date_str: str | None) -> str | None:
	"""Return the Fiscal Year record name enclosing `date_str`, or None."""
	if not date_str:
		return None
	row = frappe.db.sql(
		"""SELECT name FROM `tabFiscal Year`
		   WHERE year_start_date <= %(d)s AND year_end_date >= %(d)s
		   ORDER BY year_start_date DESC LIMIT 1""",
		{"d": getdate(date_str)},
		as_dict=True,
	)
	return row[0]["name"] if row else None


@frappe.whitelist()
def run_report(report_name: str, filters: dict | str | None = None):
	"""Thin wrapper around frappe.desk.query_report.run with an allow-list.
	Returns the same `{columns, result, ...}` shape as the underlying call.

	Auto-resolves `fiscal_year` from `to_date` / `period_end_date` when the
	caller's value is missing or doesn't match an existing FY record."""
	if report_name not in ALLOWED_REPORTS:
		frappe.throw(f"Report '{report_name}' is not exposed via Stabler.")
	if isinstance(filters, str):
		import json as _json

		try:
			filters = _json.loads(filters)
		except Exception:
			frappe.throw("Invalid filters payload.")
	filters = dict(filters or {})
	supplied = filters.get("fiscal_year")
	if not supplied or not frappe.db.exists("Fiscal Year", supplied):
		anchor = filters.get("to_date") or filters.get("period_end_date") or today()
		resolved = _resolve_fiscal_year(anchor)
		if resolved:
			filters["fiscal_year"] = resolved
		else:
			filters.pop("fiscal_year", None)

	from frappe.desk.query_report import run as _run

	return _run(report_name=report_name, filters=filters)


@frappe.whitelist()
def export_report(
	report_name: str,
	file_format_type: str,
	filters: dict | str | None = None,
):
	"""Export an allow-listed report as Excel or CSV.

	Frappe's export_query writes the file to frappe.response (filename, filecontent,
	type='binary'); the HTTP layer then serves it as a download. We return nothing
	so the response stays as set up by export_query.
	"""
	if report_name not in ALLOWED_REPORTS:
		frappe.throw(f"Report '{report_name}' is not exposed via Stabler.")
	if file_format_type not in EXPORT_FORMATS:
		frappe.throw(f"Unsupported file format: {file_format_type}.")
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except Exception:
			frappe.throw("Invalid filters payload.")
	filters = dict(filters or {})
	supplied = filters.get("fiscal_year")
	if not supplied or not frappe.db.exists("Fiscal Year", supplied):
		anchor = filters.get("to_date") or filters.get("period_end_date") or today()
		resolved = _resolve_fiscal_year(anchor)
		if resolved:
			filters["fiscal_year"] = resolved
		else:
			filters.pop("fiscal_year", None)

	from frappe.desk.query_report import export_query, run as _run

	# Run once to compute visible_idx (all rows) — export_query needs it explicitly.
	report_data = _run(report_name=report_name, filters=filters)
	visible_idx = list(range(len(report_data.get("result") or [])))

	export_query(
		report_name=report_name,
		file_format_type=file_format_type,
		filters=filters,
		visible_idx=json.dumps(visible_idx),
		include_indentation=1,
	)


# ---------------------------------------------------------------------------
# Expense / Transfer endpoints
# ---------------------------------------------------------------------------
#
# Both flows submit a single Journal Entry with voucher_type "Bank Entry".
# ERPNext multi-currency quirk: doc.validate() re-derives base-currency
# debit/credit from (amount_in_account_currency × exchange_rate). To avoid
# sub-cent imbalance, we anchor BOTH sides of every entry to a single
# base-currency total and back-solve each leg's exchange_rate.


def _round2(n) -> float:
	return round(float(flt(n)), 2)


def _validate_account(name: str, company: str, idx: int) -> dict:
	"""Resolve an Account, asserting it belongs to `company` and is a leaf."""
	row = frappe.db.get_value(
		"Account",
		name,
		["name", "company", "is_group", "account_currency", "account_type", "root_type"],
		as_dict=True,
	)
	if not row:
		frappe.throw(f"Row {idx}: account '{name}' does not exist.")
	if row.company != company:
		frappe.throw(f"Row {idx}: account '{name}' is not in company '{company}'.")
	if row.is_group:
		frappe.throw(f"Row {idx}: '{name}' is a group account.")
	return row


@frappe.whitelist()
def bank_cash_accounts(company: str, include_equity: int = 0):
	"""Leaf Bank/Cash accounts for `company` (the "payment from" pool).

	`include_equity=1` adds Equity leaves too (occasionally needed for owner
	draw / capital-contribution flows; not used by the default UI)."""
	_require_company(company)
	types = ["Bank", "Cash"]
	rows = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"disabled": 0,
			"is_group": 0,
			"account_type": ["in", types],
		},
		fields=["name", "account_name", "account_number", "account_currency", "account_type"],
		order_by="account_type asc, account_name asc",
		limit_page_length=500,
	)
	if int(include_equity or 0):
		eq = frappe.get_all(
			"Account",
			filters={
				"company": company,
				"disabled": 0,
				"is_group": 0,
				"root_type": "Equity",
			},
			fields=["name", "account_name", "account_number", "account_currency", "account_type"],
			order_by="account_name asc",
			limit_page_length=200,
		)
		rows.extend(eq)
	return rows


@frappe.whitelist()
def expense_accounts(company: str):
	"""Leaf Expense-rooted accounts for `company` (the debit side of an expense)."""
	_require_company(company)
	return frappe.get_all(
		"Account",
		filters={
			"company": company,
			"disabled": 0,
			"is_group": 0,
			"root_type": "Expense",
		},
		fields=["name", "account_name", "account_number", "account_currency", "account_type"],
		order_by="account_name asc",
		limit_page_length=1000,
	)


@frappe.whitelist()
def fixed_asset_accounts(company: str):
	"""Leaf Fixed Asset accounts for asset-purchase expense mode."""
	_require_company(company)
	return frappe.get_all(
		"Account",
		filters={
			"company": company,
			"disabled": 0,
			"is_group": 0,
			"root_type": "Asset",
			"account_type": "Fixed Asset",
		},
		fields=["name", "account_name", "account_number", "account_currency", "account_type"],
		order_by="account_name asc",
		limit_page_length=1000,
	)


def _bank_entry_kind_sql(alias: str = "je") -> str:
	return f"""
		CASE
			WHEN {alias}.user_remark LIKE '[Asset Purchase]%%' THEN 'Asset Purchase'
			WHEN EXISTS (
				SELECT 1 FROM `tabJournal Entry Account` jec
				JOIN `tabAccount` a ON a.name = jec.account
				WHERE jec.parent = {alias}.name AND a.root_type = 'Expense'
			) THEN 'Expense'
			ELSE 'Transfer'
		END
	"""


def _normalize_bank_entry_kind(entry_kind: str | None) -> str:
	kind = (entry_kind or "Expense").strip()
	if kind not in {"Expense", "Asset Purchase"}:
		raise frappe.ValidationError("Entry kind must be Expense or Asset Purchase.")
	return kind


@frappe.whitelist()
def list_bank_entries(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 50,
	voucher_type: str = "Bank Entry",
	entry_type: str = "All",
):
	"""Recent Bank Entries for the Expense / Transfer history panel."""
	_require_company(company)
	clauses, params = _date_filters(from_date, to_date)
	params["company"] = company
	params["voucher_type"] = voucher_type
	params["limit"] = max(1, min(500, int(limit)))
	
	type_clause = ""
	if entry_type == "Expense":
		type_clause = """AND (
			je.user_remark LIKE '[Asset Purchase]%%'
			OR EXISTS (
			SELECT 1 FROM `tabJournal Entry Account` jec
			JOIN `tabAccount` a ON a.name = jec.account
			WHERE jec.parent = je.name AND a.root_type = 'Expense'
			)
		)"""
	elif entry_type == "Transfer":
		type_clause = """AND COALESCE(je.user_remark, '') NOT LIKE '[Asset Purchase]%%'
		AND NOT EXISTS (
			SELECT 1 FROM `tabJournal Entry Account` jec
			JOIN `tabAccount` a ON a.name = jec.account
			WHERE jec.parent = je.name AND a.root_type = 'Expense'
		)"""
	elif entry_type == "Asset Purchase":
		type_clause = "AND je.user_remark LIKE '[Asset Purchase]%%'"

	qualified_clauses = [c.replace("posting_date", "je.posting_date") for c in clauses]
	where = " AND ".join([
		"je.company = %(company)s",
		"je.voucher_type = %(voucher_type)s",
		"je.docstatus < 2",
		*qualified_clauses,
	])
	return frappe.db.sql(
		f"""
		SELECT je.name, je.posting_date, je.voucher_type, je.user_remark,
		       je.total_debit AS total_debit_base,
		       je.total_credit AS total_credit_base,
		       je.multi_currency,
		       je.docstatus,
		       {_bank_entry_kind_sql("je")} AS entry_kind,
		       c.default_currency AS base_currency,
		       COALESCE(
		           (SELECT SUM(credit_in_account_currency) FROM `tabJournal Entry Account` WHERE parent = je.name AND credit_in_account_currency > 0),
		           je.total_credit
		       ) AS total_amount,
		       COALESCE(
		           (SELECT account_currency FROM `tabJournal Entry Account` WHERE parent = je.name AND credit_in_account_currency > 0 LIMIT 1),
		           c.default_currency
		       ) AS currency
		FROM `tabJournal Entry` je
		JOIN `tabCompany` c ON c.name = je.company
		WHERE {where} {type_clause}
		ORDER BY je.posting_date DESC, je.name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def submit_expense_entry(
	company: str,
	posting_date: str,
	payment_from: str,
	lines: list | str,
	payee: str | None = None,
	exchange_rate: float | None = None,
	submit: int = 1,
	entry_kind: str = "Expense",
) -> dict:
	"""Create (and optionally submit) an expense Journal Entry.

	`lines`: [{account, amount, memo?}]. `amount` is in the EXPENSE account's
	currency. The payment-from leg credits its native currency; both sides are
	anchored to a single base-currency total derived from `exchange_rate`
	(payment-from → base) or 1.0 when currencies already match."""
	_require_company(company)
	if isinstance(lines, str):
		try:
			lines = json.loads(lines)
		except Exception:
			frappe.throw("Invalid lines payload.")
	if not isinstance(lines, list) or not lines:
		frappe.throw("At least one expense line is required.")

	entry_kind = _normalize_bank_entry_kind(entry_kind)
	pay_acc = _validate_account(payment_from, company, 0)
	base_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	cleaned: list[dict] = []
	total_pay_amount = 0.0  # in payment-from account currency
	memos: list[str] = []
	for idx, raw in enumerate(lines, start=1):
		acc_name = (raw or {}).get("account")
		amount = _round2((raw or {}).get("amount"))
		if not acc_name:
			frappe.throw(f"Row {idx}: account is required.")
		if amount <= 0:
			frappe.throw(f"Row {idx}: amount must be greater than zero.")
		exp_acc = _validate_account(acc_name, company, idx)
		if entry_kind == "Expense" and exp_acc.root_type != "Expense":
			frappe.throw(f"Row {idx}: account must be an Expense account.")
		if entry_kind == "Asset Purchase" and exp_acc.account_type != "Fixed Asset":
			frappe.throw(f"Row {idx}: account must be a Fixed Asset account.")
		# v1: expense account must share currency with payment-from. Cross-currency
		# per-line FX is non-trivial; defer to a future iteration.
		if exp_acc.account_currency != pay_acc.account_currency:
			frappe.throw(
				f"Row {idx}: expense account currency ({exp_acc.account_currency}) must match "
				f"payment account currency ({pay_acc.account_currency}). Cross-currency expense lines "
				"are not yet supported."
			)
		memo = (raw or {}).get("memo")
		if memo:
			memos.append(str(memo).strip())
		total_pay_amount += amount
		cleaned.append({"account": acc_name, "amount": amount, "memo": memo})

	total_pay_amount = _round2(total_pay_amount)
	if total_pay_amount <= 0:
		frappe.throw("Total expense amount must be greater than zero.")

	# Anchor: derive a single base-currency total from the payment-from leg.
	if pay_acc.account_currency == base_currency:
		rate = 1.0
	else:
		rate = float(flt(exchange_rate)) if exchange_rate else 0.0
		if rate <= 0:
			frappe.throw(
				f"Exchange rate ({pay_acc.account_currency} → {base_currency}) is required."
			)
	base_total = _round2(total_pay_amount * rate)
	if base_total <= 0:
		frappe.throw("Computed base-currency total is zero.")

	# Build remark.
	parts = []
	if payee:
		parts.append(f"Paid to {payee}")
	if memos:
		parts.append("; ".join(memos))
	remark = " | ".join(parts) if parts else None
	if entry_kind == "Asset Purchase":
		remark = f"[Asset Purchase] {remark or 'Asset purchase'}"

	doc = frappe.new_doc("Journal Entry")
	doc.company = company
	doc.posting_date = getdate(posting_date)
	doc.voucher_type = "Bank Entry"
	doc.cheque_no = f"Exp-{posting_date}"
	doc.cheque_date = getdate(posting_date)
	doc.multi_currency = 1 if pay_acc.account_currency != base_currency else 0
	if remark:
		doc.user_remark = remark
	if payee:
		doc.pay_to_recd_from = payee

	# Credit leg (payment_from). Rates are kept at full float precision —
	# ERPNext does `round(amount * rate, 2)` itself, so any pre-rounding of
	# the rate would compound into 1-cent JE-imbalance errors.
	pay_rate = (base_total / total_pay_amount) if total_pay_amount else 1.0
	doc.append("accounts", {
		"account": payment_from,
		"credit_in_account_currency": total_pay_amount,
		"exchange_rate": pay_rate,
		"account_currency": pay_acc.account_currency,
	})

	# Debit legs: split base_total across lines so per-leg shares sum exactly
	# to base_total (last line absorbs the rounding residual). Per-leg rate is
	# back-solved so ERPNext's `round(amt * rate, 2)` reproduces the share.
	base_shares: list[float] = []
	running = 0.0
	for j, row in enumerate(cleaned):
		if j < len(cleaned) - 1:
			share = _round2(base_total * (row["amount"] / total_pay_amount))
			base_shares.append(share)
			running += share
		else:
			base_shares.append(_round2(base_total - running))

	for row, base_share in zip(cleaned, base_shares):
		debit_acc_amount = row["amount"]
		debit_rate = (base_share / debit_acc_amount) if debit_acc_amount else 1.0
		entry = {
			"account": row["account"],
			"debit_in_account_currency": debit_acc_amount,
			"exchange_rate": debit_rate,
		}
		if row.get("memo"):
			entry["user_remark"] = row["memo"]
		doc.append("accounts", entry)

	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


def _load_bank_entry(name: str):
	if not name or not frappe.db.exists("Journal Entry", name):
		frappe.throw(f"Unknown Journal Entry: {name}")
	doc = frappe.get_doc("Journal Entry", name)
	_require_company(doc.company)
	if doc.voucher_type != "Bank Entry":
		frappe.throw("Only Bank Entry journal entries are supported here.")
	return doc


@frappe.whitelist()
def cancel_bank_entry(name: str) -> dict:
	doc = _load_bank_entry(name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted Bank Entries can be cancelled.")
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def delete_bank_entry(name: str) -> dict:
	doc = _load_bank_entry(name)
	if doc.docstatus != 0:
		frappe.throw("Only draft Bank Entries can be deleted.")
	doc.delete()
	frappe.db.commit()
	return {"name": name, "deleted": 1}


@frappe.whitelist()
def amend_expense_entry(source_name: str, **kwargs) -> dict:
	source = _load_bank_entry(source_name)
	if source.docstatus == 1:
		source.cancel()
	elif source.docstatus == 0:
		source.delete()
	else:
		frappe.throw("Cancelled Bank Entries cannot be amended.")
	result = submit_expense_entry(**kwargs)
	frappe.db.commit()
	result["amended_from"] = source_name
	return result


@frappe.whitelist()
def amend_transfer_entry(source_name: str, **kwargs) -> dict:
	source = _load_bank_entry(source_name)
	if source.docstatus == 1:
		source.cancel()
	elif source.docstatus == 0:
		source.delete()
	else:
		frappe.throw("Cancelled Bank Entries cannot be amended.")
	result = submit_transfer_entry(**kwargs)
	frappe.db.commit()
	result["amended_from"] = source_name
	return result


@frappe.whitelist()
def submit_transfer_entry(
	company: str,
	posting_date: str,
	from_account: str,
	to_account: str,
	from_amount: float,
	to_amount: float | None = None,
	exchange_rate: float | None = None,
	memo: str | None = None,
	submit: int = 1,
) -> dict:
	"""Create (and optionally submit) a fund-transfer Journal Entry.

	Same-currency: `to_amount` defaults to `from_amount`. Cross-currency:
	caller must supply EITHER `to_amount` OR `exchange_rate` (from→to). We
	anchor both legs to a single base-currency total so the JE balances by
	construction regardless of rate-truncation drift."""
	_require_company(company)
	if from_account == to_account:
		frappe.throw("From and To accounts must differ.")

	from_acc = _validate_account(from_account, company, 1)
	to_acc = _validate_account(to_account, company, 2)
	base_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	from_amt = _round2(from_amount)
	if from_amt <= 0:
		frappe.throw("Amount must be greater than zero.")

	# Resolve to_amount.
	if from_acc.account_currency == to_acc.account_currency:
		to_amt = _round2(to_amount) if to_amount else from_amt
		if abs(to_amt - from_amt) > 0.01:
			frappe.throw("Same-currency transfer: From and To amounts must match.")
		to_amt = from_amt
	else:
		if to_amount and float(flt(to_amount)) > 0:
			to_amt = _round2(to_amount)
		elif exchange_rate and float(flt(exchange_rate)) > 0:
			to_amt = _round2(from_amt * float(flt(exchange_rate)))
		else:
			frappe.throw(
				f"Cross-currency transfer ({from_acc.account_currency} → {to_acc.account_currency}) "
				"requires either a destination amount or an exchange rate."
			)
		if to_amt <= 0:
			frappe.throw("Computed destination amount is zero.")

	# Anchor: single base-currency total.
	if from_acc.account_currency == base_currency:
		base_total = from_amt
	elif to_acc.account_currency == base_currency:
		base_total = to_amt
	else:
		# Neither leg is base currency (triple-foreign transfer). Derive the
		# base-currency total via the live exchange rate from the from-leg
		# currency to the base currency on the posting date. Without this,
		# the JE would silently mis-post the foreign amount as if it were
		# base currency.
		from erpnext.setup.utils import get_exchange_rate
		from_to_base_rate = flt(get_exchange_rate(
			from_acc.account_currency, base_currency, getdate(posting_date)
		))
		if from_to_base_rate <= 0:
			frappe.throw(
				f"Triple-foreign transfer ({from_acc.account_currency} → "
				f"{to_acc.account_currency}, base={base_currency}): no "
				f"{from_acc.account_currency}→{base_currency} exchange rate "
				f"available on {posting_date}. Add one in Currency Exchange "
				"before posting."
			)
		base_total = _round2(from_amt * from_to_base_rate)

	# Full-precision rates so ERPNext's `round(amount * rate, 2)` recovers
	# base_total exactly for both legs.
	from_rate = (base_total / from_amt) if from_amt else 1.0
	to_rate = (base_total / to_amt) if to_amt else 1.0

	doc = frappe.new_doc("Journal Entry")
	doc.company = company
	doc.posting_date = getdate(posting_date)
	doc.voucher_type = "Bank Entry"
	doc.cheque_no = f"Trf-{posting_date}"
	doc.cheque_date = getdate(posting_date)
	doc.multi_currency = 1 if (from_acc.account_currency != base_currency or to_acc.account_currency != base_currency) else 0
	if memo:
		doc.user_remark = memo

	doc.append("accounts", {
		"account": from_account,
		"credit_in_account_currency": from_amt,
		"exchange_rate": from_rate,
		"account_currency": from_acc.account_currency,
	})
	doc.append("accounts", {
		"account": to_account,
		"debit_in_account_currency": to_amt,
		"exchange_rate": to_rate,
		"account_currency": to_acc.account_currency,
	})

	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def get_exchange_rate_for_currencies(from_currency: str, to_currency: str, posting_date: str | None = None):
	"""Return the exchange rate between `from_currency` and `to_currency` on `posting_date`."""
	from erpnext.setup.utils import get_exchange_rate

	date = getdate(posting_date or today())
	try:
		rate = get_exchange_rate(from_currency, to_currency, date)
		if not rate or flt(rate) <= 0.0:
			frappe.throw(
				_("No exchange rate found for {0} to {1} on {2}").format(from_currency, to_currency, date),
				frappe.ValidationError
			)
		return flt(rate)
	except Exception as e:
		if frappe.message_log and "No exchange rate found" in str(frappe.message_log[-1]):
			raise
		frappe.throw(
			_("No exchange rate found for {0} to {1} on {2}: {3}").format(from_currency, to_currency, date, str(e)),
			frappe.ValidationError
		)
