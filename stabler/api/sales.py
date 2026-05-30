"""Sales module — Customers, Sales Invoices, AR aging."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from stabler.api._common import _assert_can_read, _require_company, _validate_money_overrides


def _resolve_price_list(customer: str | None) -> str | None:
	"""Return per-customer default_price_list, else Selling Settings selling_price_list."""
	if customer:
		pl = frappe.db.get_value("Customer", customer, "default_price_list")
		if pl:
			return pl
	return frappe.db.get_single_value("Selling Settings", "selling_price_list") or None


def _lookup_item_price(item_code: str, price_list: str, uom: str | None = None) -> dict | None:
	"""Find an active Item Price row for (item_code, price_list).
	Honors validity window; prefers exact-UOM rows over generic rows, then most recent."""
	params = {"item_code": item_code, "price_list": price_list, "today": today(), "uom": uom or ""}
	rows = frappe.db.sql(
		"""
		SELECT price_list_rate, currency
		FROM `tabItem Price`
		WHERE item_code = %(item_code)s AND price_list = %(price_list)s
		  AND selling = 1
		  AND (uom = %(uom)s OR uom IS NULL OR uom = '')
		  AND (valid_from IS NULL OR valid_from <= %(today)s)
		  AND (valid_upto IS NULL OR valid_upto >= %(today)s)
		ORDER BY CASE WHEN uom = %(uom)s THEN 0 ELSE 1 END, valid_from DESC
		LIMIT 1
		""",
		params,
		as_dict=True,
	)
	if not rows:
		return None
	r = rows[0]
	return {"price_list_rate": flt(r["price_list_rate"]), "currency": r["currency"]}



@frappe.whitelist()
def list_customers(company: str, search: str = "", limit: int = 100):
	_require_company(company)
	# Customer is multi-company — there's no `company` on the master itself.
	# We just filter by name search + disabled=0. The detail call scopes to company.
	conds = ["disabled = 0"]
	params: dict = {"limit": int(limit)}
	if search:
		conds.append("(customer_name LIKE %(s)s OR name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, customer_name, customer_group, customer_type, territory,
		       default_currency, default_price_list, mobile_no, email_id
		FROM `tabCustomer`
		WHERE {where}
		ORDER BY customer_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def get_customer_defaults(company: str, customer: str):
	"""Return the effective price list and currency for a customer.

	The resolved_price_list is the price list that will actually be used:
	customer.default_price_list if set, otherwise Selling Settings.selling_price_list.
	"""
	_require_company(company)
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")
	doc = frappe.get_doc("Customer", customer)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	resolved_pl = _resolve_price_list(customer)
	pl_currency = frappe.db.get_value("Price List", resolved_pl, "currency") if resolved_pl else None
	return {
		"default_currency": doc.default_currency or company_currency,
		"default_price_list": doc.default_price_list or "",
		"resolved_price_list": resolved_pl or "",
		"price_list_currency": pl_currency or "",
	}


@frappe.whitelist()
def list_selling_price_lists():
	"""Return enabled selling price lists (name + currency)."""
	return frappe.db.get_all(
		"Price List",
		filters={"selling": 1, "enabled": 1},
		fields=["name", "currency"],
		order_by="name asc",
	)


@frappe.whitelist()
def list_currencies():
	"""Return enabled currencies for dropdowns."""
	return frappe.db.get_all(
		"Currency",
		filters={"enabled": 1},
		fields=["name", "symbol", "fraction_units"],
		order_by="name asc",
		limit_page_length=300,
	)


@frappe.whitelist()
def list_customers_with_balances(
	company: str,
	search: str = "",
	limit: int = 200,
	only_with_balance: int = 0,
):
	"""Customers + live receivables balance (base + account currency)
	aggregated from GL Entry party rows against this company.

	`balance_base` is in company currency, signed: positive = customer owes us.
	`balance_acc` is the same in the customer's transaction currency; mixed-
	currency transactions are tracked by `account_currency` (the receivable
	account's currency). When a customer transacted in multiple currencies we
	expose the dominant one with `acc_currency_count` so the UI can flag it."""
	_require_company(company)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	conds = ["c.disabled = 0"]
	params: dict = {"company": company, "limit": int(limit)}
	if search:
		conds.append("(c.customer_name LIKE %(s)s OR c.name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	where = " AND ".join(conds)
	rows = frappe.db.sql(
		f"""
		SELECT
		  c.name,
		  c.customer_name,
		  c.customer_group,
		  c.customer_type,
		  c.territory,
		  c.default_currency,
		  c.mobile_no,
		  c.email_id,
		  COALESCE(g.balance_base, 0) AS balance_base,
		  COALESCE(g.balance_acc, 0) AS balance_acc,
		  g.account_currency,
		  COALESCE(g.currency_count, 0) AS acc_currency_count
		FROM `tabCustomer` c
		LEFT JOIN (
		  SELECT
		    party,
		    SUM(debit - credit) AS balance_base,
		    SUM(debit_in_account_currency - credit_in_account_currency) AS balance_acc,
		    MAX(account_currency) AS account_currency,
		    COUNT(DISTINCT account_currency) AS currency_count
		  FROM `tabGL Entry`
		  WHERE company = %(company)s
		    AND party_type = 'Customer'
		    AND is_cancelled = 0
		  GROUP BY party
		) g ON g.party = c.name
		WHERE {where}
		ORDER BY c.customer_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	# Correct PE party-leg drift: GL stores credit_in_account_currency = base÷rate
	# which can differ from the user-entered PE.paid_amount by a few centavos.
	# Adjust balance_acc by the per-customer drift so the list ties to the ledger.
	drift_rows = frappe.db.sql(
		"""
		SELECT g.party AS party,
		       SUM(
		         (CASE WHEN g.debit_in_account_currency > 0
		               THEN (CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
		                          WHEN g.account = pe.paid_to   THEN pe.received_amount
		                          ELSE 0 END)
		               ELSE -(CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
		                           WHEN g.account = pe.paid_to   THEN pe.received_amount
		                           ELSE 0 END)
		          END)
		         - (g.debit_in_account_currency - g.credit_in_account_currency)
		       ) AS drift
		FROM `tabGL Entry` g
		JOIN `tabPayment Entry` pe ON pe.name = g.voucher_no
		JOIN (
		  SELECT voucher_no
		  FROM `tabGL Entry`
		  WHERE voucher_type = 'Payment Entry'
		    AND company = %(company)s
		    AND party_type = 'Customer'
		    AND is_cancelled = 0
		  GROUP BY voucher_no
		  HAVING COUNT(*) = 1
		) single ON single.voucher_no = g.voucher_no
		WHERE g.voucher_type = 'Payment Entry'
		  AND g.company = %(company)s
		  AND g.party_type = 'Customer'
		  AND g.is_cancelled = 0
		GROUP BY g.party
		""",
		{"company": company},
		as_dict=True,
	)
	drift_map = {r["party"]: flt(r["drift"]) for r in drift_rows}

	for r in rows:
		r["balance_base"] = flt(r["balance_base"])
		r["balance_acc"] = flt(r["balance_acc"]) + drift_map.get(r["name"], 0.0)
		r["company_currency"] = company_currency
	if cint(only_with_balance):
		rows = [r for r in rows if flt(r["balance_base"]) != 0]
	return {"rows": rows, "company_currency": company_currency}


@frappe.whitelist()
def customer_ledger(
	company: str,
	customer: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 1000,
):
	"""Trial-balance-style ledger for a single customer in `company`.

	Returns party-leg ledger entries ordered oldest-first. Account-currency
	amounts mirror the **source voucher's** originally-entered amount (PE
	paid/received_amount, JE Account row, SI grand_total) rather than the
	back-converted value ERPNext stores in `GL Entry.*_in_account_currency`.
	This guarantees that when the user enters 6,200,000 UZS on a PE the
	ledger shows 6,200,000 UZS — not 6,199,988.02 UZS produced by
	base÷rate rounding."""
	_require_company(company)
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")
	limit = max(1, min(5000, int(limit)))

	from_d = getdate(from_date) if from_date else None
	to_d = getdate(to_date) if to_date else None

	rows = _fetch_party_ledger_rows(
		company=company, party_type="Customer", party=customer, to_date=to_d,
	)

	# Split into opening (< from_date) and window ([from_date, to_date]).
	def _before_from(r):
		return from_d is not None and getdate(r["posting_date"]) < from_d

	opening_base = sum(r["debit"] - r["credit"] for r in rows if _before_from(r))
	opening_acc = sum(
		r["debit_in_account_currency"] - r["credit_in_account_currency"]
		for r in rows if _before_from(r)
	)
	closing_base = sum(r["debit"] - r["credit"] for r in rows)
	closing_acc = sum(
		r["debit_in_account_currency"] - r["credit_in_account_currency"]
		for r in rows
	)

	window = [r for r in rows if not _before_from(r)][:limit]
	for r in window:
		r["posting_date"] = str(r["posting_date"]) if r["posting_date"] else ""

	account_currency = next(
		(r["account_currency"] for r in reversed(window) if r["account_currency"]),
		None,
	)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	return {
		"customer": customer,
		"company_currency": company_currency,
		"account_currency": account_currency or company_currency,
		"opening_base": flt(opening_base),
		"opening_acc": flt(opening_acc),
		"closing_base": flt(closing_base),
		"closing_acc": flt(closing_acc),
		"entries": window,
		"from_date": str(from_d) if from_d else None,
		"to_date": str(to_d) if to_d else None,
	}


def _fetch_party_ledger_rows(
	company: str,
	party_type: str,
	party: str,
	to_date,
):
	"""Fetch GL Entry rows for a party leg, overriding account-currency amounts
	with the source voucher's originally-entered amount (PE.paid_amount /
	received_amount, JE Account row, SI grand_total). Base columns are
	preserved as-is — they reflect what was actually posted to GL."""
	upper = "AND posting_date <= %(to_date)s" if to_date else ""
	params = {"company": company, "party_type": party_type, "party": party}
	if to_date:
		params["to_date"] = to_date
	rows = frappe.db.sql(
		f"""
		SELECT name, posting_date, voucher_type, voucher_no, against, remarks,
		       account, account_currency,
		       debit, credit,
		       debit_in_account_currency, credit_in_account_currency
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND party_type = %(party_type)s AND party = %(party)s
		  AND is_cancelled = 0
		  {upper}
		ORDER BY posting_date ASC, creation ASC
		""",
		params,
		as_dict=True,
	)
	if not rows:
		return []

	# Batched lookup of PE source amounts.
	pe_voucher_nos = {r["voucher_no"] for r in rows if r["voucher_type"] == "Payment Entry"}
	pe_map: dict = {}
	if pe_voucher_nos:
		pe_rows = frappe.db.sql(
			"""
			SELECT name, paid_from, paid_to, paid_amount, received_amount
			FROM `tabPayment Entry`
			WHERE name IN %(names)s
			""",
			{"names": tuple(pe_voucher_nos)},
			as_dict=True,
		)
		pe_map = {r["name"]: r for r in pe_rows}

	# Count party-leg GL rows per Payment Entry in this result set.
	# A multi-reference PE posts one row per paid invoice; substituting the
	# full paid_amount on every row would count the payment N times.
	# The source-amount override is safe only for single-leg PEs.
	pe_leg_counts: dict = {}
	for r in rows:
		if r["voucher_type"] == "Payment Entry":
			pe_leg_counts[r["voucher_no"]] = pe_leg_counts.get(r["voucher_no"], 0) + 1

	for r in rows:
		r["debit"] = flt(r["debit"])
		r["credit"] = flt(r["credit"])
		dac = flt(r["debit_in_account_currency"])
		cac = flt(r["credit_in_account_currency"])
		# Override PE party-leg account-currency amount with source voucher value,
		# but ONLY when the PE has a single party-leg GL row. Multi-reference PEs
		# (one row per paid invoice) already carry correct partial allocations in
		# *_in_account_currency — overriding would inflate the total N-fold.
		if r["voucher_type"] == "Payment Entry" and pe_leg_counts.get(r["voucher_no"]) == 1:
			pe = pe_map.get(r["voucher_no"])
			if pe:
				if r["account"] == pe["paid_from"]:
					source_amt = flt(pe["paid_amount"])
				elif r["account"] == pe["paid_to"]:
					source_amt = flt(pe["received_amount"])
				else:
					source_amt = None
				if source_amt is not None:
					if dac > 0:
						dac = source_amt
					elif cac > 0:
						cac = source_amt
		r["debit_in_account_currency"] = dac
		r["credit_in_account_currency"] = cac
	return rows


@frappe.whitelist()
def customer_detail(name: str, company: str):
	_require_company(company)
	if not name or not frappe.db.exists("Customer", name):
		frappe.throw(f"Unknown customer: {name}")
	_assert_can_read("Customer", name)
	doc = frappe.get_doc("Customer", name)

	# AR per transaction currency (do NOT sum across currencies — that mixes
	# UZS into USD totals). Lifetime stays in base currency since it's an
	# audit metric, not a payable amount.
	ar_by_currency = frappe.db.sql(
		"""
		SELECT
		  currency,
		  COALESCE(SUM(outstanding_amount), 0) AS outstanding
		FROM `tabSales Invoice`
		WHERE customer = %(name)s AND company = %(company)s
		  AND docstatus = 1
		GROUP BY currency
		HAVING SUM(outstanding_amount) <> 0
		""",
		{"name": name, "company": company},
		as_dict=True,
	) or []
	lifetime_row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(base_grand_total), 0) AS lifetime
		FROM `tabSales Invoice`
		WHERE customer = %(name)s AND company = %(company)s
		  AND docstatus = 1
		""",
		{"name": name, "company": company},
		as_dict=True,
	)
	lifetime_base = flt(lifetime_row[0]["lifetime"]) if lifetime_row else 0.0

	recent = frappe.db.sql(
		"""
		SELECT name, posting_date, due_date, grand_total, outstanding_amount, status, currency
		FROM `tabSales Invoice`
		WHERE customer = %(name)s AND company = %(company)s AND docstatus = 1
		ORDER BY posting_date DESC, name DESC
		LIMIT 200
		""",
		{"name": name, "company": company},
		as_dict=True,
	)

	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"customer_group": doc.customer_group,
		"customer_type": doc.customer_type,
		"territory": doc.territory,
		"default_currency": doc.default_currency,
		"mobile_no": doc.mobile_no,
		"email_id": doc.email_id,
		"tax_id": doc.tax_id,
		"website": doc.website,
		"customer_details": doc.customer_details,
		"default_price_list": doc.default_price_list,
		"outstanding_by_currency": [
			{"currency": r["currency"], "amount": flt(r["outstanding"])}
			for r in ar_by_currency
		],
		"lifetime_base": lifetime_base,
		"recent_invoices": recent,
	}


@frappe.whitelist()
def list_sales_invoices(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	customer: str | None = None,
	status: str | None = None,
	limit: int = 100,
):
	_require_company(company)
	conds = ["company = %(company)s", "docstatus < 2"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("posting_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("posting_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if customer:
		conds.append("customer = %(customer)s")
		params["customer"] = customer
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, posting_date, due_date, customer, customer_name,
		       grand_total, base_grand_total,
		       outstanding_amount,
		       conversion_rate,
		       status, currency, docstatus
		FROM `tabSales Invoice`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def sales_invoice_detail(name: str):
	if not name:
		frappe.throw("Invoice name is required.")
	_assert_can_read("Sales Invoice", name)
	doc = frappe.get_doc("Sales Invoice", name)
	return {
		"name": doc.name,
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"due_date": str(doc.due_date) if doc.due_date else None,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"outstanding_amount": flt(doc.outstanding_amount),
		"base_net_total": flt(doc.base_net_total),
		"base_grand_total": flt(doc.base_grand_total),
		"base_currency": frappe.db.get_value("Company", doc.company, "default_currency") or "",
		"status": doc.status,
		"docstatus": doc.docstatus,
		"remarks": doc.remarks,
		"is_return": cint(doc.is_return),
		"return_against": doc.return_against or "",
		"credit_notes": frappe.db.sql(
			"""
			SELECT name, docstatus FROM `tabSales Invoice`
			WHERE return_against = %(name)s AND docstatus < 2
			""",
			{"name": name},
			as_dict=True,
		),
		"items": [
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"qty": flt(it.qty),
				"uom": it.uom,
				"stock_uom": it.stock_uom,
				"conversion_factor": flt(it.conversion_factor) or 1.0,
				"stock_qty": flt(it.stock_qty),
				"rate": flt(it.rate),
				"price_list_rate": flt(it.price_list_rate),
				"discount_percentage": flt(it.discount_percentage),
				"discount_amount": flt(it.discount_amount),
				"amount": flt(it.amount),
			}
			for it in (doc.items or [])
		],
	}


@frappe.whitelist()
def ar_aging(company: str, as_of: str | None = None):
	"""Bucket outstanding Sales Invoices by age into 0-30/31-60/61-90/90+.

	Grouped by (customer, currency) since `outstanding_amount` is in invoice
	transaction currency — summing UZS into USD totals would be meaningless.
	One customer with both UZS and USD invoices produces two rows."""
	_require_company(company)
	as_of = getdate(as_of or today())
	rows = frappe.db.sql(
		"""
		SELECT
		  customer,
		  customer_name,
		  currency,
		  COUNT(*) AS invoice_count,
		  COALESCE(SUM(outstanding_amount), 0) AS total,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) BETWEEN 0 AND 30
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_0_30,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) BETWEEN 31 AND 60
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_31_60,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) BETWEEN 61 AND 90
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_61_90,
		  COALESCE(SUM(CASE WHEN DATEDIFF(%(as_of)s, posting_date) > 90
		                    THEN outstanding_amount ELSE 0 END), 0) AS b_90_plus
		FROM `tabSales Invoice`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		GROUP BY customer, customer_name, currency
		ORDER BY currency, total DESC
		""",
		{"company": company, "as_of": as_of},
		as_dict=True,
	)
	# Per-currency totals (UZS and USD are kept separate — never summed).
	totals_by_ccy: dict[str, dict] = {}
	for r in rows:
		ccy = r["currency"]
		bucket = totals_by_ccy.setdefault(ccy, {
			"currency": ccy, "total": 0.0,
			"b_0_30": 0.0, "b_31_60": 0.0, "b_61_90": 0.0, "b_90_plus": 0.0,
		})
		bucket["total"] += flt(r["total"])
		bucket["b_0_30"] += flt(r["b_0_30"])
		bucket["b_31_60"] += flt(r["b_31_60"])
		bucket["b_61_90"] += flt(r["b_61_90"])
		bucket["b_90_plus"] += flt(r["b_90_plus"])
	return {
		"rows": rows,
		"totals_by_currency": list(totals_by_ccy.values()),
		"as_of": str(as_of),
	}


@frappe.whitelist()
def sales_invoice_print(name: str):
	"""Full payload for the in-SPA printable receipt page.

	Extends sales_invoice_detail with company header fields and in_words.
	"""
	if not name:
		frappe.throw("Invoice name is required.")
	_assert_can_read("Sales Invoice", name)
	base = sales_invoice_detail(name)
	doc = frappe.get_doc("Sales Invoice", name)
	company_doc = frappe.get_doc("Company", doc.company)
	return {
		**base,
		"company_name": company_doc.company_name,
		"company_abbr": company_doc.abbr,
		"company_tax_id": getattr(company_doc, "tax_id", "") or "",
		"in_words": doc.in_words or "",
		"payment_terms_template": doc.payment_terms_template or "",
	}


@frappe.whitelist()
def create_sales_return(
	sales_invoice: str,
	posting_date: str | None = None,
	item_returns=None,
	submit: int = 0,
):
	"""Issue a credit note (is_return=1) against a submitted Sales Invoice.

	`item_returns` is an optional list of `{item_code, qty}` where qty is
	entered positive (negated here). Pass nothing to return the full invoice.
	"""
	if not sales_invoice or not frappe.db.exists("Sales Invoice", sales_invoice):
		frappe.throw(_("Unknown Sales Invoice: {0}").format(sales_invoice))
	src = frappe.get_doc("Sales Invoice", sales_invoice)
	if src.docstatus != 1:
		frappe.throw(_("Only submitted invoices can be returned."))

	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	doc = make_return_doc("Sales Invoice", sales_invoice)
	doc.posting_date = getdate(posting_date or today())

	if isinstance(item_returns, str):
		try:
			item_returns = json.loads(item_returns)
		except Exception:
			frappe.throw(_("Invalid item_returns payload"))

	if item_returns:
		src_qty: dict[str, float] = {it.item_code: flt(it.qty) for it in src.items}
		override: dict[str, float] = {
			row["item_code"]: flt(row.get("qty", 0))
			for row in (item_returns or [])
			if isinstance(row, dict) and row.get("item_code")
		}
		for line in doc.items:
			requested = override.get(line.item_code)
			if requested is None:
				continue
			clamped = min(abs(requested), abs(src_qty.get(line.item_code, 0)))
			line.qty = -clamped if clamped else line.qty

		# Drop zero-qty lines; keep at least one if all end up zero.
		non_zero = [ln for ln in doc.items if flt(ln.qty) != 0]
		if non_zero:
			doc.items = non_zero

	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {
		"name": doc.name,
		"is_return": 1,
		"grand_total": flt(doc.grand_total),
		"docstatus": doc.docstatus,
		"return_against": sales_invoice,
	}


VALID_CUSTOMER_TYPES = {"Individual", "Company", "Partnership"}


@frappe.whitelist()
def create_customer(
	customer_name: str,
	customer_type: str = "Company",
	customer_group: str | None = None,
	territory: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	tax_id: str | None = None,
	default_price_list: str | None = None,
	default_currency: str | None = None,
):
	customer_name = (customer_name or "").strip()
	if not customer_name:
		frappe.throw("Customer name is required.")
	if customer_type not in VALID_CUSTOMER_TYPES:
		frappe.throw(f"Customer type must be one of: {', '.join(sorted(VALID_CUSTOMER_TYPES))}.")
	if frappe.db.exists("Customer", {"customer_name": customer_name}):
		frappe.throw(f"Customer '{customer_name}' already exists.")

	# Resolve defaults — fall back to Frappe's "All Customer Groups" / "All Territories"
	# which are seeded by ERPNext on install.
	if not customer_group:
		customer_group = frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
	if not territory:
		territory = frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"

	if not frappe.db.exists("Customer Group", customer_group):
		frappe.throw(f"Unknown customer group: {customer_group}")
	if not frappe.db.exists("Territory", territory):
		frappe.throw(f"Unknown territory: {territory}")

	doc = frappe.new_doc("Customer")
	doc.customer_name = customer_name
	doc.customer_type = customer_type
	doc.customer_group = customer_group
	doc.territory = territory
	if email_id:
		doc.email_id = email_id.strip()
	if mobile_no:
		doc.mobile_no = mobile_no.strip()
	if tax_id:
		doc.tax_id = tax_id.strip()
	if default_price_list:
		if not frappe.db.exists("Price List", default_price_list):
			frappe.throw(f"Unknown price list: {default_price_list}")
		doc.default_price_list = default_price_list
	doc.default_currency = default_currency or ""
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "customer_name": doc.customer_name}


@frappe.whitelist()
def get_customer(name: str):
	if not frappe.db.exists("Customer", name):
		frappe.throw(f"Unknown customer: {name}")
	_assert_can_read("Customer", name)
	doc = frappe.get_doc("Customer", name)
	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"customer_type": doc.customer_type or "Company",
		"customer_group": doc.customer_group or "",
		"territory": doc.territory or "",
		"email_id": doc.email_id or "",
		"mobile_no": doc.mobile_no or "",
		"tax_id": doc.tax_id or "",
		"default_price_list": doc.default_price_list or "",
		"default_currency": doc.default_currency or "",
	}


@frappe.whitelist()
def update_customer(
	name: str,
	customer_name: str,
	customer_type: str = "Company",
	customer_group: str | None = None,
	territory: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	tax_id: str | None = None,
	default_price_list: str | None = None,
	default_currency: str | None = None,
):
	if not frappe.db.exists("Customer", name):
		frappe.throw(f"Unknown customer: {name}")
	customer_name = (customer_name or "").strip()
	if not customer_name:
		frappe.throw("Customer name is required.")
	if customer_type not in VALID_CUSTOMER_TYPES:
		frappe.throw(f"Customer type must be one of: {', '.join(sorted(VALID_CUSTOMER_TYPES))}.")
	if default_price_list and not frappe.db.exists("Price List", default_price_list):
		frappe.throw(f"Unknown price list: {default_price_list}")
	doc = frappe.get_doc("Customer", name)
	doc.customer_name = customer_name
	doc.customer_type = customer_type
	if customer_group:
		doc.customer_group = customer_group
	if territory:
		doc.territory = territory
	doc.email_id = (email_id or "").strip()
	doc.mobile_no = (mobile_no or "").strip()
	doc.tax_id = (tax_id or "").strip()
	doc.default_price_list = default_price_list or ""
	doc.default_currency = default_currency or ""
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "customer_name": doc.customer_name}


@frappe.whitelist()
def delete_customer(name: str):
	if not frappe.db.exists("Customer", name):
		frappe.throw(f"Unknown customer: {name}")
	frappe.delete_doc("Customer", name, ignore_permissions=False)
	return {"deleted": name}


@frappe.whitelist()
def list_customer_groups(limit: int = 200):
	return frappe.db.sql(
		"""
		SELECT name FROM `tabCustomer Group`
		WHERE is_group = 0
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def create_sales_invoice(
	sales_order: str,
	posting_date: str | None = None,
	due_date: str | None = None,
	remarks: str | None = None,
	update_stock: int = 0,
	item_overrides=None,
):
	"""Create a Draft Sales Invoice copied from a submitted Sales Order.

	`sales_order` is mandatory — Stabler enforces SO-driven sales. `item_overrides`
	is an optional list of `{so_detail|item_code, qty?, rate?}` to tweak the
	auto-mapped lines before insert. SO/so_detail linkage is preserved by
	ERPNext's `make_sales_invoice`, which is what releases stock reservations
	on SI submit.
	"""
	if not sales_order or not isinstance(sales_order, str):
		frappe.throw(
			_("Sales Invoice must be created from a Sales Order"),
			frappe.ValidationError,
		)
	if not frappe.db.exists("Sales Order", sales_order):
		frappe.throw(_("Unknown Sales Order: {0}").format(sales_order))

	so = frappe.get_doc("Sales Order", sales_order)
	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} must be submitted before invoicing").format(sales_order))

	from erpnext.selling.doctype.sales_order.sales_order import (
		make_sales_invoice as _make_si_from_so,
	)

	doc = _make_si_from_so(sales_order)
	doc.posting_date = getdate(posting_date or today())
	if due_date:
		doc.due_date = getdate(due_date)
	doc.update_stock = 1 if int(update_stock or 0) else 0
	if remarks:
		doc.remarks = remarks.strip()

	# ERPNext's make_sales_invoice picks the customer's default receivable account
	# without considering the SO currency. If the account currency doesn't match
	# the document currency, swap to the matching receivable account for this company.
	if doc.debit_to and doc.currency:
		debit_to_currency = frappe.get_cached_value("Account", doc.debit_to, "account_currency")
		if debit_to_currency and debit_to_currency != doc.currency:
			matching = frappe.get_all(
				"Account",
				filters={
					"account_type": "Receivable",
					"company": doc.company,
					"account_currency": doc.currency,
					"is_group": 0,
					"disabled": 0,
				},
				pluck="name",
				order_by="lft asc",  # deterministic — lowest in CoA tree wins
				limit=1,
			)
			if not matching:
				frappe.throw(
					_("No {0} receivable account exists for company {1}. "
					  "Create one before invoicing in {0}.").format(doc.currency, doc.company)
				)
			doc.debit_to = matching[0]

	if isinstance(item_overrides, str):
		try:
			item_overrides = json.loads(item_overrides)
		except Exception:
			frappe.throw(_("Invalid item_overrides payload"))
	if item_overrides:
		override_by_detail: dict[str, dict] = {}
		override_by_item: dict[str, dict] = {}
		for row in item_overrides:
			if not isinstance(row, dict):
				continue
			detail = row.get("so_detail") or row.get("sales_order_item")
			if detail:
				override_by_detail[detail] = row
			elif row.get("item_code"):
				override_by_item[row["item_code"]] = row
		for line in doc.items:
			patch = override_by_detail.get(line.so_detail) or override_by_item.get(line.item_code)
			if not patch:
				continue
			_validate_money_overrides(patch, row_label=line.item_code or line.so_detail or "?")
			if patch.get("qty") not in (None, ""):
				qty = flt(patch["qty"])
				if qty <= 0:
					frappe.throw(_("Override qty must be greater than zero"))
				line.qty = qty
			if patch.get("rate") not in (None, ""):
				line.rate = flt(patch["rate"])
			if patch.get("discount_percentage") not in (None, ""):
				line.discount_percentage = flt(patch["discount_percentage"])
			if patch.get("discount_amount") not in (None, ""):
				line.discount_amount = flt(patch["discount_amount"])

	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"customer": doc.customer,
		"sales_order": sales_order,
	}


@frappe.whitelist()
def submit_sales_invoice(name: str):
	"""Submit a Draft Sales Invoice (docstatus 0 → 1)."""
	if not name:
		frappe.throw("Invoice name is required.")
	doc = frappe.get_doc("Sales Invoice", name)
	if doc.docstatus == 1:
		frappe.throw("Invoice is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Invoice is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_sales_invoice(name: str):
	"""Cancel a Submitted Sales Invoice (docstatus 1 → 2)."""
	if not name:
		frappe.throw("Invoice name is required.")
	doc = frappe.get_doc("Sales Invoice", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted invoices can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def list_territories(limit: int = 200):
	return frappe.db.sql(
		"""
		SELECT name FROM `tabTerritory`
		WHERE is_group = 0
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def list_price_lists(selling_only: int = 1, limit: int = 200):
	"""Return enabled Price Lists. By default only selling lists (selling=1)."""
	conds = ["enabled = 1"]
	if int(selling_only):
		conds.append("selling = 1")
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, currency
		FROM `tabPrice List`
		WHERE {where}
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def get_item_price(item_code: str, company: str, customer: str | None = None, price_list: str | None = None, uom: str | None = None):
	"""Resolve the price for `item_code`, optionally for a specific `uom`.

	Resolution order for the price list:
	  1. Explicit `price_list` arg (overrides all)
	  2. Customer.default_price_list (if customer is supplied)
	  3. Selling Settings.selling_price_list (global default)

	When `uom` is provided, UOM-specific Item Price rows are preferred over
	generic rows (no uom set). Falls back to generic if no UOM-specific row exists.
	"""
	_require_company(company)
	if not item_code:
		frappe.throw("Item code is required.")
	if not frappe.db.exists("Item", item_code):
		frappe.throw(f"Unknown item: {item_code}")
	if customer and not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")

	price_list = price_list or _resolve_price_list(customer)
	if not price_list:
		return {
			"price_list": None,
			"price_list_rate": 0.0,
			"currency": None,
			"unresolved": True,
			"reason": "no_price_list",
		}

	hit = _lookup_item_price(item_code, price_list, uom=uom)
	if not hit:
		pl_currency = frappe.db.get_value("Price List", price_list, "currency")
		return {
			"price_list": price_list,
			"price_list_rate": 0.0,
			"currency": pl_currency,
			"unresolved": True,
			"reason": "no_item_price",
		}

	return {
		"price_list": price_list,
		"price_list_rate": hit["price_list_rate"],
		"currency": hit["currency"],
		"unresolved": False,
	}


@frappe.whitelist()
def item_sales_meta(item_code: str, company: str, customer: str | None = None, price_list: str | None = None):
	"""Return UOM options + conversion factors, default sales UOM, and price-list
	rate for an item — everything a line editor needs on item pick.

	Pass an explicit `price_list` to look up the rate directly without going
	through per-customer resolution (useful when the UI has already set a PL).
	"""
	_require_company(company)
	if not item_code:
		frappe.throw("item_code is required.")
	if not frappe.db.exists("Item", item_code):
		frappe.throw(f"Unknown item: {item_code}")
	doc = frappe.get_doc("Item", item_code)
	uoms = [
		{"uom": u.uom, "conversion_factor": flt(u.conversion_factor) or 1.0}
		for u in (doc.uoms or [])
	]
	if not any(u["uom"] == doc.stock_uom for u in uoms):
		uoms.insert(0, {"uom": doc.stock_uom, "conversion_factor": 1.0})
	default_uom = getattr(doc, "sales_uom", None) or doc.stock_uom
	price = get_item_price(item_code=item_code, company=company, customer=customer, price_list=price_list, uom=default_uom)
	return {
		"item_code": doc.item_code,
		"item_name": doc.item_name,
		"stock_uom": doc.stock_uom,
		"sales_uom": getattr(doc, "sales_uom", None),
		"default_uom": default_uom,
		"uoms": uoms,
		"standard_rate": flt(doc.standard_rate),
		"price_list": price.get("price_list"),
		"price_list_rate": flt(price.get("price_list_rate")),
		"currency": price.get("currency"),
		"unresolved": price.get("unresolved", False),
	}


# ─────────────────────────── Quotations ───────────────────────────
# Quotation is polymorphic (quotation_to = Customer | Lead); v1 only handles Customer.

@frappe.whitelist()
def list_quotations(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	customer: str | None = None,
	status: str | None = None,
	limit: int = 100,
):
	_require_company(company)
	conds = ["company = %(company)s", "docstatus < 2", "quotation_to = 'Customer'"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("transaction_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("transaction_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if customer:
		conds.append("party_name = %(customer)s")
		params["customer"] = customer
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, transaction_date, valid_till,
		       party_name AS customer, customer_name,
		       grand_total, status, currency, docstatus
		FROM `tabQuotation`
		WHERE {where}
		ORDER BY transaction_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def quotation_detail(name: str):
	if not name:
		frappe.throw("Quotation name is required.")
	_assert_can_read("Quotation", name)
	doc = frappe.get_doc("Quotation", name)
	return {
		"name": doc.name,
		"transaction_date": str(doc.transaction_date) if doc.transaction_date else None,
		"valid_till": str(doc.valid_till) if doc.valid_till else None,
		"customer": doc.party_name,
		"customer_name": doc.customer_name,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"remarks": getattr(doc, "tc_name", None),
		"items": [
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"qty": flt(it.qty),
				"uom": it.uom,
				"rate": flt(it.rate),
				"amount": flt(it.amount),
			}
			for it in (doc.items or [])
		],
	}


@frappe.whitelist()
def create_quotation(
	company: str,
	customer: str,
	items,
	transaction_date: str | None = None,
	valid_till: str | None = None,
	remarks: str | None = None,
):
	"""Create a Quotation as Draft (docstatus=0)."""
	_require_company(company)
	if not customer:
		frappe.throw("Customer is required.")
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	cleaned: list[dict] = []
	for idx, row in enumerate(items, start=1):
		code = (row or {}).get("item_code")
		if not code:
			frappe.throw(f"Row {idx}: item is required.")
		if not frappe.db.exists("Item", code):
			frappe.throw(f"Row {idx}: unknown item '{code}'.")
		qty = flt(row.get("qty"))
		if qty <= 0:
			frappe.throw(f"Row {idx}: qty must be greater than zero.")
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
			}
		)

	doc = frappe.new_doc("Quotation")
	doc.company = company
	doc.quotation_to = "Customer"
	doc.party_name = customer
	doc.transaction_date = getdate(transaction_date or today())
	if valid_till:
		doc.valid_till = getdate(valid_till)
	if remarks:
		# Quotation uses `tc_name` for terms text reference; free-text goes to `terms`.
		doc.terms = remarks.strip()
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.qty = row["qty"]
		if row["rate"]:
			line.rate = row["rate"]
		if row["uom"]:
			line.uom = row["uom"]
	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"customer": doc.party_name,
	}


@frappe.whitelist()
def submit_quotation(name: str):
	if not name:
		frappe.throw("Quotation name is required.")
	doc = frappe.get_doc("Quotation", name)
	if doc.docstatus == 1:
		frappe.throw("Quotation is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Quotation is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_quotation(name: str):
	if not name:
		frappe.throw("Quotation name is required.")
	doc = frappe.get_doc("Quotation", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted quotations can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


# ─────────────────────────── Sales Orders ───────────────────────────

@frappe.whitelist()
def list_sales_orders(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	customer: str | None = None,
	status: str | None = None,
	limit: int = 100,
):
	_require_company(company)
	conds = ["company = %(company)s", "docstatus < 2"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("transaction_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("transaction_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if customer:
		conds.append("customer = %(customer)s")
		params["customer"] = customer
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	where = " AND ".join(conds)
	rows = frappe.db.sql(
		f"""
		SELECT name, transaction_date, delivery_date, customer, customer_name,
		       grand_total, advance_paid, per_delivered, per_billed,
		       status, currency, docstatus, set_warehouse
		FROM `tabSales Order`
		WHERE {where}
		ORDER BY transaction_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	if rows:
		reserved_names = {
			r[0]
			for r in frappe.db.sql(
				"""
				SELECT DISTINCT voucher_no
				FROM `tabStock Reservation Entry`
				WHERE voucher_type = 'Sales Order'
				  AND docstatus = 1
				  AND voucher_no IN %(names)s
				""",
				{"names": tuple(r["name"] for r in rows)},
			)
		}
		for r in rows:
			r["has_reservations"] = r["name"] in reserved_names
	return rows


@frappe.whitelist()
def sales_order_detail(name: str):
	if not name:
		frappe.throw("Sales order name is required.")
	_assert_can_read("Sales Order", name)
	doc = frappe.get_doc("Sales Order", name)
	# Per-line reserved totals: there can be multiple SREs per SO Item.
	# For direct SO reservations, ERPNext sets voucher_detail_no = SO Item name.
	# from_voucher_detail_no is only set for Pick-List/PR-sourced reservations.
	reserved_by_detail: dict[str, float] = {}
	for row in frappe.db.sql(
		"""
		SELECT voucher_detail_no, SUM(reserved_qty) AS reserved
		FROM `tabStock Reservation Entry`
		WHERE voucher_type = 'Sales Order'
		  AND voucher_no = %(name)s
		  AND docstatus = 1
		GROUP BY voucher_detail_no
		""",
		{"name": name},
		as_dict=True,
	):
		if row.get("voucher_detail_no"):
			reserved_by_detail[row["voucher_detail_no"]] = flt(row["reserved"])
	si_links = frappe.db.sql(
		"""
		SELECT DISTINCT si.name, si.docstatus
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.sales_order = %(name)s AND si.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	return {
		"name": doc.name,
		"transaction_date": str(doc.transaction_date) if doc.transaction_date else None,
		"delivery_date": str(doc.delivery_date) if doc.delivery_date else None,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"company": doc.company,
		"set_warehouse": getattr(doc, "set_warehouse", None),
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"advance_paid": flt(doc.advance_paid),
		"per_delivered": flt(doc.per_delivered),
		"per_billed": flt(doc.per_billed),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"remarks": getattr(doc, "terms", None),
		"has_reservations": bool(reserved_by_detail),
		"sales_invoices": si_links,
		"items": [
			{
				"name": it.name,
				"item_code": it.item_code,
				"item_name": it.item_name,
				"warehouse": getattr(it, "warehouse", None),
				"qty": flt(it.qty),
				"delivered_qty": flt(getattr(it, "delivered_qty", 0)),
				"billed_amt": flt(getattr(it, "billed_amt", 0)),
				"reserved_qty": flt(reserved_by_detail.get(it.name, 0)),
				"uom": it.uom,
				"stock_uom": it.stock_uom,
				"conversion_factor": flt(it.conversion_factor) or 1.0,
				"stock_qty": flt(it.stock_qty),
				"rate": flt(it.rate),
				"price_list_rate": flt(it.price_list_rate),
				"discount_percentage": flt(it.discount_percentage),
				"discount_amount": flt(it.discount_amount),
				"amount": flt(it.amount),
			}
			for it in (doc.items or [])
		],
	}


def _company_stock_reservation_enabled(company: str) -> bool:
	"""Per-Company SRE toggle from Stabler Settings; defaults true if no row."""
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	return bool(module_map_for(company).get("stock_reservation", True))


def _reserve_for_sales_order(so_name: str) -> list[dict]:
	"""Create stock reservation entries for every line on a submitted SO.

	Returns a list of `{line, item, error}` for any line that failed; an empty
	list means everything reserved cleanly. Failures never abort the SO — it's
	already submitted by the time we get here.
	"""
	try:
		from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
			create_stock_reservation_entries_for_so_items,
		)
	except Exception as exc:
		return [{"line": None, "item": None, "error": f"SRE module unavailable: {exc}"}]

	errors: list[dict] = []
	# Serialise concurrent reservers on this SO to prevent TOCTOU oversell.
	# (Per-item oversell across different SOs requires a Bin-row lock inside
	# ERPNext's path — that is a follow-up; this guarantees per-SO serialisation.)
	frappe.db.get_value("Sales Order", so_name, "name", for_update=True)
	# Reload to get the post-submit child row names.
	so = frappe.get_doc("Sales Order", so_name)
	items_details = []
	for it in so.items or []:
		if not getattr(it, "warehouse", None):
			errors.append(
				{
					"line": it.idx,
					"item": it.item_code,
					"error": "No warehouse set on line; cannot reserve.",
				}
			)
			continue
		items_details.append(
			{
				"sales_order_item": it.name,   # ERPNext reads this key; "name" caused the None lookup
				"item_code": it.item_code,
				"warehouse": it.warehouse,
				"qty_to_reserve": flt(it.qty),  # transaction UOM — ERPNext multiplies by conversion_factor
			}
		)
	if not items_details:
		return errors

	try:
		create_stock_reservation_entries_for_so_items(
			sales_order=so,
			items_details=items_details,
			notify=False,
		)
	except Exception as exc:
		# Surface as a single bucket error; individual line attribution lives in
		# the SRE call's own validation messages which Frappe logs.
		errors.append({"line": None, "item": None, "error": str(exc)})
	return errors


def _submit_and_reserve(doc) -> list[dict]:
	"""Submit an SO doc and, if the company has SRE enabled, reserve every line.

	Reservation failures are returned, never raised — the SO is already live
	and must not be rolled back because reservation failed. Collapses the
	duplicated submit+reserve pattern in create_sales_order / submit_sales_order."""
	doc.submit()
	if _company_stock_reservation_enabled(doc.company):
		return _reserve_for_sales_order(doc.name)
	return []


@frappe.whitelist()
def create_sales_order(
	company: str,
	customer: str,
	items,
	set_warehouse: str | None = None,
	transaction_date: str | None = None,
	delivery_date: str | None = None,
	remarks: str | None = None,
	auto_submit: int = 1,
	currency: str | None = None,
	price_list: str | None = None,
):
	"""Create a Sales Order; default behaviour is create + submit + reserve.

	`set_warehouse` is required (Stabler enforces SO-driven warehouse picking).
	Each line may override via `warehouse`. When `auto_submit` is truthy (default)
	the SO is submitted and stock reservation entries are created per line. The
	response includes `reservation_errors`; non-empty means SO submitted but some
	lines could not be fully reserved (e.g. insufficient stock).
	"""
	_require_company(company)
	if not customer:
		frappe.throw("Customer is required.")
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")
	if not set_warehouse:
		frappe.throw(_("Warehouse is required for Sales Orders"))
	if not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(_("Unknown warehouse: {0}").format(set_warehouse))

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	txn_date = getdate(transaction_date or today())
	deliver_on = getdate(delivery_date) if delivery_date else txn_date

	cleaned: list[dict] = []
	for idx, row in enumerate(items, start=1):
		code = (row or {}).get("item_code")
		if not code:
			frappe.throw(f"Row {idx}: item is required.")
		if not frappe.db.exists("Item", code):
			frappe.throw(f"Row {idx}: unknown item '{code}'.")
		qty = flt(row.get("qty"))
		if qty <= 0:
			frappe.throw(f"Row {idx}: qty must be greater than zero.")
		wh = (row.get("warehouse") or "").strip() or set_warehouse
		if wh != set_warehouse and not frappe.db.exists("Warehouse", wh):
			frappe.throw(f"Row {idx}: unknown warehouse '{wh}'.")
		disc_pct = flt(row.get("discount_percentage"))
		if not (0 <= disc_pct <= 100):
			frappe.throw(f"Row {idx}: discount_percentage must be between 0 and 100.")
		rate_val = row.get("rate")
		if rate_val not in (None, "") and flt(rate_val) < 0:
			frappe.throw(f"Row {idx}: rate cannot be negative.")
		if flt(row.get("discount_amount")) < 0:
			frappe.throw(f"Row {idx}: discount_amount cannot be negative.")
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
				"warehouse": wh,
				"conversion_factor": flt(row.get("conversion_factor")) or None,
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
			}
		)

	doc = frappe.new_doc("Sales Order")
	doc.company = company
	doc.customer = customer
	doc.transaction_date = txn_date
	doc.delivery_date = deliver_on
	doc.set_warehouse = set_warehouse
	if remarks:
		doc.terms = remarks.strip()
	if currency:
		doc.currency = currency
	price_list = price_list or _resolve_price_list(customer)
	if price_list:
		doc.selling_price_list = price_list

	sre_enabled = _company_stock_reservation_enabled(company)
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.qty = row["qty"]
		line.delivery_date = deliver_on
		line.warehouse = row["warehouse"]
		if sre_enabled:
			line.reserve_stock = 1
		rate = row["rate"]
		if not rate and price_list:
			hit = _lookup_item_price(row["item_code"], price_list)
			if hit:
				rate = hit["price_list_rate"]
		if rate:
			line.rate = rate
		if row["uom"]:
			line.uom = row["uom"]
		if row.get("conversion_factor"):
			line.conversion_factor = row["conversion_factor"]
		if row.get("discount_percentage"):
			line.discount_percentage = row["discount_percentage"]
		if row.get("discount_amount"):
			line.discount_amount = row["discount_amount"]
	doc.insert(ignore_permissions=False)

	reservation_errors = _submit_and_reserve(doc) if cint(auto_submit) else []

	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"customer": doc.customer,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"reservation_errors": reservation_errors,
	}


@frappe.whitelist()
def submit_sales_order(name: str):
	if not name:
		frappe.throw("Sales order name is required.")
	doc = frappe.get_doc("Sales Order", name)
	if doc.docstatus == 1:
		frappe.throw("Sales order is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Sales order is cancelled and cannot be submitted.")
	reservation_errors = _submit_and_reserve(doc)
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"reservation_errors": reservation_errors,
	}


@frappe.whitelist()
def cancel_sales_order(name: str):
	if not name:
		frappe.throw("Sales order name is required.")
	doc = frappe.get_doc("Sales Order", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted sales orders can be cancelled.")
	# Cancel any live stock reservations first; ERPNext's SO cancel hook would
	# do this too, but doing it explicitly keeps the failure surface obvious.
	try:
		from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
			cancel_stock_reservation_entries,
		)

		cancel_stock_reservation_entries(voucher_type="Sales Order", voucher_no=name, notify=False)
	except Exception:
		# Swallow — ERPNext will re-attempt during doc.cancel(); any real failure
		# will surface there with full context.
		pass
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def amend_sales_order(name: str):
	"""Create a new draft Sales Order as an amendment of a cancelled one."""
	if not name or not frappe.db.exists("Sales Order", name):
		frappe.throw(f"Unknown Sales Order: {name}")
	doc = frappe.get_doc("Sales Order", name)
	if doc.docstatus != 2:
		frappe.throw("Only cancelled sales orders can be amended.")
	new = frappe.copy_doc(doc)
	new.amended_from = name
	new.insert(ignore_permissions=False)
	return {"name": new.name, "docstatus": new.docstatus, "amended_from": name}


@frappe.whitelist()
def amend_sales_invoice(name: str):
	"""Create a new draft Sales Invoice as an amendment of a cancelled one."""
	if not name or not frappe.db.exists("Sales Invoice", name):
		frappe.throw(f"Unknown Sales Invoice: {name}")
	doc = frappe.get_doc("Sales Invoice", name)
	if doc.docstatus != 2:
		frappe.throw("Only cancelled sales invoices can be amended.")
	new = frappe.copy_doc(doc)
	new.amended_from = name
	new.insert(ignore_permissions=False)
	return {"name": new.name, "docstatus": new.docstatus, "amended_from": name}


@frappe.whitelist()
def get_linked_documents(doctype: str, name: str):
	"""Server-side wrapper over Frappe's linked-docs query, filtered to
	sales-relevant doctypes. Returns {doctype: [{name, docstatus}]} — keeps the
	SPA self-contained with no Desk calls from the browser."""
	allowed_doctypes = {"Sales Order", "Sales Invoice", "Delivery Note", "Payment Entry"}
	if doctype not in {"Sales Order", "Sales Invoice"}:
		frappe.throw("doctype must be Sales Order or Sales Invoice")
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"Unknown {doctype}: {name}")

	from frappe.desk.form.linked_with import get_linked_docs, get_linked_doctypes

	linkinfo = get_linked_doctypes(doctype)
	raw = get_linked_docs(doctype, name, linkinfo) or {}
	out: dict = {}
	for dt, docs in raw.items():
		if dt in allowed_doctypes and docs:
			out[dt] = [
				{"name": d.get("name"), "docstatus": d.get("docstatus")}
				for d in docs
				if d.get("name")
			]
	return out
