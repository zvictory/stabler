"""Purchasing module — Suppliers, Purchase Invoices, AP aging."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, getdate, today


from stabler.api._common import _assert_can_read, _require_company


@frappe.whitelist()
def list_suppliers(company: str, search: str = "", limit: int = 100):
	_require_company(company)
	conds = ["disabled = 0"]
	params: dict = {"limit": int(limit)}
	if search:
		conds.append("(supplier_name LIKE %(s)s OR name LIKE %(s)s)")
		params["s"] = f"%{search}%"
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, supplier_name, supplier_group, supplier_type, country,
		       default_currency, mobile_no, email_id
		FROM `tabSupplier`
		WHERE {where}
		ORDER BY supplier_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def list_suppliers_with_balances(
	company: str,
	search: str = "",
	limit: int = 200,
	only_with_balance: int = 0,
):
	"""Suppliers + live payables balance (base + account currency) aggregated
	from GL Entry party rows against this company.

	Sign convention follows QuickBooks A/P: `balance_base` positive = we owe
	the supplier. GL stores payables as credit-natured, so we aggregate
	`SUM(credit - debit)`."""
	_require_company(company)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	conds = ["s.disabled = 0"]
	params: dict = {"company": company, "limit": int(limit)}
	if search:
		conds.append("(s.supplier_name LIKE %(q)s OR s.name LIKE %(q)s)")
		params["q"] = f"%{search}%"
	where = " AND ".join(conds)
	rows = frappe.db.sql(
		f"""
		SELECT
		  s.name,
		  s.supplier_name,
		  s.supplier_group,
		  s.supplier_type,
		  s.country,
		  s.default_currency,
		  s.mobile_no,
		  s.email_id,
		  COALESCE(g.balance_base, 0) AS balance_base,
		  COALESCE(g.balance_acc, 0) AS balance_acc,
		  g.account_currency,
		  COALESCE(g.currency_count, 0) AS acc_currency_count
		FROM `tabSupplier` s
		LEFT JOIN (
		  SELECT
		    party,
		    SUM(credit - debit) AS balance_base,
		    SUM(credit_in_account_currency - debit_in_account_currency) AS balance_acc,
		    MAX(account_currency) AS account_currency,
		    COUNT(DISTINCT account_currency) AS currency_count
		  FROM `tabGL Entry`
		  WHERE company = %(company)s
		    AND party_type = 'Supplier'
		    AND is_cancelled = 0
		  GROUP BY party
		) g ON g.party = s.name
		WHERE {where}
		ORDER BY s.supplier_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)
	# Correct PE party-leg drift (see customers.py for rationale).
	# Supplier balance sign = credit − debit, so drift is computed in that direction.
	drift_rows = frappe.db.sql(
		"""
		SELECT g.party AS party,
		       SUM(
		         (CASE WHEN g.credit_in_account_currency > 0
		               THEN (CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
		                          WHEN g.account = pe.paid_to   THEN pe.received_amount
		                          ELSE 0 END)
		               ELSE -(CASE WHEN g.account = pe.paid_from THEN pe.paid_amount
		                           WHEN g.account = pe.paid_to   THEN pe.received_amount
		                           ELSE 0 END)
		          END)
		         - (g.credit_in_account_currency - g.debit_in_account_currency)
		       ) AS drift
		FROM `tabGL Entry` g
		JOIN `tabPayment Entry` pe ON pe.name = g.voucher_no
		WHERE g.voucher_type = 'Payment Entry'
		  AND g.company = %(company)s
		  AND g.party_type = 'Supplier'
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
	if only_with_balance:
		rows = [r for r in rows if flt(r["balance_base"]) != 0]
	return {"rows": rows, "company_currency": company_currency}


@frappe.whitelist()
def supplier_ledger(
	company: str,
	supplier: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 1000,
):
	"""Trial-balance-style ledger for a single supplier in `company`.

	Sign convention mirrors `list_suppliers_with_balances`: positive balance
	means we owe the supplier (credit - debit). Account-currency amounts
	mirror the source voucher's originally-entered amount (PE.paid_amount
	/ received_amount), preventing the base÷rate rounding drift baked into
	GL Entry's *_in_account_currency columns."""
	_require_company(company)
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")
	limit = max(1, min(5000, int(limit)))

	from_d = getdate(from_date) if from_date else None
	to_d = getdate(to_date) if to_date else None

	from stabler.api.sales import _fetch_party_ledger_rows
	rows = _fetch_party_ledger_rows(
		company=company, party_type="Supplier", party=supplier, to_date=to_d,
	)

	def _before_from(r):
		return from_d is not None and getdate(r["posting_date"]) < from_d

	# Payable sign: positive = we owe (credit − debit).
	opening_base = sum(r["credit"] - r["debit"] for r in rows if _before_from(r))
	opening_acc = sum(
		r["credit_in_account_currency"] - r["debit_in_account_currency"]
		for r in rows if _before_from(r)
	)
	closing_base = sum(r["credit"] - r["debit"] for r in rows)
	closing_acc = sum(
		r["credit_in_account_currency"] - r["debit_in_account_currency"]
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
		"supplier": supplier,
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


@frappe.whitelist()
def supplier_detail(name: str, company: str):
	_require_company(company)
	if not name or not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	_assert_can_read("Supplier", name)
	doc = frappe.get_doc("Supplier", name)

	# AP per transaction currency. Lifetime stays in base currency.
	ap_by_currency = frappe.db.sql(
		"""
		SELECT
		  currency,
		  COALESCE(SUM(outstanding_amount), 0) AS outstanding
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s
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
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s
		  AND docstatus = 1
		""",
		{"name": name, "company": company},
		as_dict=True,
	)
	lifetime_base = flt(lifetime_row[0]["lifetime"]) if lifetime_row else 0.0

	recent = frappe.db.sql(
		"""
		SELECT name, posting_date, due_date, grand_total, outstanding_amount, status, currency
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s AND docstatus = 1
		ORDER BY posting_date DESC, name DESC
		LIMIT 200
		""",
		{"name": name, "company": company},
		as_dict=True,
	)

	return {
		"name": doc.name,
		"supplier_name": doc.supplier_name,
		"supplier_group": doc.supplier_group,
		"supplier_type": doc.supplier_type,
		"country": doc.country,
		"default_currency": doc.default_currency,
		"mobile_no": doc.mobile_no,
		"email_id": doc.email_id,
		"tax_id": doc.tax_id,
		"website": doc.website,
		"supplier_details": doc.supplier_details,
		"outstanding_by_currency": [
			{"currency": r["currency"], "amount": flt(r["outstanding"])}
			for r in ap_by_currency
		],
		"lifetime_base": lifetime_base,
		"recent_invoices": recent,
	}


@frappe.whitelist()
def list_purchase_invoices(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	supplier: str | None = None,
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
	if supplier:
		conds.append("supplier = %(supplier)s")
		params["supplier"] = supplier
	if status:
		conds.append("status = %(status)s")
		params["status"] = status
	where = " AND ".join(conds)
	return frappe.db.sql(
		f"""
		SELECT name, posting_date, due_date, supplier, supplier_name, bill_no,
		       grand_total, base_grand_total,
		       outstanding_amount,
		       conversion_rate,
		       status, currency, docstatus
		FROM `tabPurchase Invoice`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def purchase_invoice_detail(name: str):
	if not name:
		frappe.throw("Invoice name is required.")
	_assert_can_read("Purchase Invoice", name)
	doc = frappe.get_doc("Purchase Invoice", name)
	return {
		"name": doc.name,
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"due_date": str(doc.due_date) if doc.due_date else None,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name,
		"bill_no": doc.bill_no,
		"bill_date": str(doc.bill_date) if doc.bill_date else None,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"total_taxes_and_charges": flt(doc.total_taxes_and_charges),
		"grand_total": flt(doc.grand_total),
		"outstanding_amount": flt(doc.outstanding_amount),
		"base_net_total": flt(doc.base_net_total),
		"base_total_taxes_and_charges": flt(doc.base_total_taxes_and_charges),
		"base_grand_total": flt(doc.base_grand_total),
		"base_currency": frappe.db.get_value("Company", doc.company, "default_currency") or "",
		"status": doc.status,
		"docstatus": doc.docstatus,
		"remarks": doc.remarks,
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
		"taxes": [
			{
				"description": t.description,
				"rate": flt(t.rate),
				"tax_amount": flt(t.tax_amount),
			}
			for t in (doc.taxes or [])
		],
	}


@frappe.whitelist()
def ap_aging(company: str, as_of: str | None = None):
	"""Bucket outstanding Purchase Invoices by age into 0-30/31-60/61-90/90+.

	Grouped by (supplier, currency); totals broken out per currency."""
	_require_company(company)
	as_of = getdate(as_of or today())
	rows = frappe.db.sql(
		"""
		SELECT
		  supplier,
		  supplier_name,
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
		FROM `tabPurchase Invoice`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		GROUP BY supplier, supplier_name, currency
		ORDER BY currency, total DESC
		""",
		{"company": company, "as_of": as_of},
		as_dict=True,
	)
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


VALID_SUPPLIER_TYPES = {"Individual", "Company", "Partnership"}


@frappe.whitelist()
def create_supplier(
	supplier_name: str,
	supplier_type: str = "Company",
	supplier_group: str | None = None,
	country: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	tax_id: str | None = None,
):
	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw("Supplier name is required.")
	if supplier_type not in VALID_SUPPLIER_TYPES:
		frappe.throw(f"Supplier type must be one of: {', '.join(sorted(VALID_SUPPLIER_TYPES))}.")
	if frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
		frappe.throw(f"Supplier '{supplier_name}' already exists.")

	if not supplier_group:
		supplier_group = (
			frappe.db.get_single_value("Buying Settings", "supplier_group") or "All Supplier Groups"
		)
	if not frappe.db.exists("Supplier Group", supplier_group):
		frappe.throw(f"Unknown supplier group: {supplier_group}")
	if country and not frappe.db.exists("Country", country):
		frappe.throw(f"Unknown country: {country}")

	doc = frappe.new_doc("Supplier")
	doc.supplier_name = supplier_name
	doc.supplier_type = supplier_type
	doc.supplier_group = supplier_group
	if country:
		doc.country = country
	if email_id:
		doc.email_id = email_id.strip()
	if mobile_no:
		doc.mobile_no = mobile_no.strip()
	if tax_id:
		doc.tax_id = tax_id.strip()
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "supplier_name": doc.supplier_name}


@frappe.whitelist()
def create_purchase_invoice(
	company: str,
	supplier: str,
	items,
	posting_date: str | None = None,
	due_date: str | None = None,
	bill_no: str | None = None,
	bill_date: str | None = None,
	remarks: str | None = None,
	update_stock: int = 0,
):
	"""Create a Purchase Invoice as Draft (docstatus=0).

	`items` is a list of dicts with keys: item_code (required), qty, rate, uom.
	"""
	_require_company(company)
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")

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

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = company
	doc.supplier = supplier
	doc.posting_date = getdate(posting_date or today())
	if due_date:
		doc.due_date = getdate(due_date)
	if bill_no:
		doc.bill_no = bill_no.strip()
	if bill_date:
		doc.bill_date = getdate(bill_date)
	doc.update_stock = 1 if int(update_stock) else 0
	if remarks:
		doc.remarks = remarks.strip()
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
		"supplier": doc.supplier,
	}


@frappe.whitelist()
def submit_purchase_invoice(name: str):
	"""Submit a Draft Purchase Invoice (docstatus 0 → 1)."""
	if not name:
		frappe.throw("Invoice name is required.")
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus == 1:
		frappe.throw("Invoice is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Invoice is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_purchase_invoice(name: str):
	"""Cancel a Submitted Purchase Invoice (docstatus 1 → 2)."""
	if not name:
		frappe.throw("Invoice name is required.")
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted invoices can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def list_supplier_groups(limit: int = 200):
	return frappe.db.sql(
		"""
		SELECT name FROM `tabSupplier Group`
		WHERE is_group = 0
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)
