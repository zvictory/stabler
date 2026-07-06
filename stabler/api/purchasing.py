"""Purchasing module — Suppliers, Purchase Invoices, AP aging."""

from __future__ import annotations

import json

import frappe
from stabler.api._money import money_epsilon
from stabler.api.approvals import _assert_company_scope
from frappe.utils import cint, flt, getdate, today


from stabler.api._common import _assert_can_read, _assert_can_write, _require_company, check_concurrency


@frappe.whitelist()
def list_suppliers(company: str, search: str = "", limit: int = 100):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Supplier", "read"):
		frappe.throw(frappe._("You are not permitted to view suppliers."), frappe.PermissionError)
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
		JOIN (
		  SELECT voucher_no
		  FROM `tabGL Entry`
		  WHERE voucher_type = 'Payment Entry'
		    AND company = %(company)s
		    AND party_type = 'Supplier'
		    AND is_cancelled = 0
		  GROUP BY voucher_no
		  HAVING COUNT(*) = 1
		) single ON single.voucher_no = g.voucher_no
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
	if cint(only_with_balance):
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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

	overdue_row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(outstanding_amount), 0) AS overdue
		FROM `tabPurchase Invoice`
		WHERE supplier = %(name)s AND company = %(company)s
		  AND docstatus = 1
		  AND due_date < %(today)s
		  AND outstanding_amount > 0
		""",
		{"name": name, "company": company, "today": today()},
		as_dict=True,
	)
	overdue_amount = flt(overdue_row[0]["overdue"]) if overdue_row else 0.0

	last_payment_row = frappe.db.sql(
		"""
		SELECT posting_date
		FROM `tabPayment Entry`
		WHERE party_type = 'Supplier' AND party = %(name)s AND company = %(company)s
		  AND docstatus = 1
		ORDER BY posting_date DESC
		LIMIT 1
		""",
		{"name": name, "company": company},
	)
	last_payment_date = str(last_payment_row[0][0]) if last_payment_row and last_payment_row[0][0] else None

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
		"overdue_amount": overdue_amount,
		"last_payment_date": last_payment_date,
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
	_has_dim = frappe.db.has_column("Item", "custom_dimension_mode")

	def _dim_mode(code):
		if not _has_dim or not code:
			return ""
		return frappe.get_cached_value("Item", code, "custom_dimension_mode") or ""

	return {
		"name": doc.name,
		"modified": str(doc.modified),
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
		"update_stock": cint(doc.update_stock),
		"set_warehouse": doc.set_warehouse or "",
		"taxes_and_charges": doc.taxes_and_charges or "",
		"buying_price_list": doc.buying_price_list or "",
		"items": [
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"qty": flt(it.qty),
				"uom": it.uom,
				"rate": flt(it.rate),
				"amount": flt(it.amount),
				"discount_percentage": flt(it.discount_percentage),
				"discount_amount": flt(it.discount_amount),
				"price_list_rate": flt(it.price_list_rate),
				"purchase_order": it.purchase_order or "",
				"custom_dimension_mode": _dim_mode(it.item_code),
				"custom_length": flt(getattr(it, "custom_length", 0)) or None,
				"custom_width": flt(getattr(it, "custom_width", 0)) or None,
				"custom_height": flt(getattr(it, "custom_height", 0)) or None,
				"custom_pieces": flt(getattr(it, "custom_pieces", 0)) or None,
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
		"is_return": cint(doc.is_return),
		"return_against": doc.return_against or "",
		"amended_from": doc.amended_from or "",
		"debit_notes": frappe.db.sql(
			"""
			SELECT name, docstatus FROM `tabPurchase Invoice`
			WHERE return_against = %(name)s AND docstatus < 2
			""",
			{"name": name},
			as_dict=True,
		),
	}


@frappe.whitelist()
def purchase_invoice_print(name: str):
	"""Full payload for the in-SPA printable PI receipt (extends detail with
	company header, in_words, and supplier running balance from GL)."""
	if not name:
		frappe.throw("Invoice name is required.")
	_assert_can_read("Purchase Invoice", name)
	base = purchase_invoice_detail(name)
	doc = frappe.get_doc("Purchase Invoice", name)
	company_doc = frappe.get_doc("Company", doc.company)
	bal = frappe.db.sql(
		"""SELECT SUM(debit_in_account_currency - credit_in_account_currency)
		   FROM `tabGL Entry`
		   WHERE company=%s AND party_type='Supplier' AND party=%s AND is_cancelled=0""",
		(doc.company, doc.supplier),
	)
	supplier_balance = flt(bal[0][0]) if bal and bal[0][0] is not None else 0.0
	return {
		**base,
		"company_name": company_doc.company_name,
		"company_abbr": company_doc.abbr,
		"company_tax_id": getattr(company_doc, "tax_id", "") or "",
		"discount_amount": flt(doc.discount_amount),
		"in_words": doc.in_words or "",
		"supplier_balance": supplier_balance,
	}


@frappe.whitelist()
def ap_aging(company: str, as_of: str | None = None):
	"""Bucket outstanding Purchase Invoices by age into 0-30/31-60/61-90/90+.

	Grouped by (supplier, currency); totals broken out per currency."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
	default_price_list: str | None = None,
	default_currency: str | None = None,
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
	if default_price_list:
		if not frappe.db.exists("Price List", default_price_list):
			frappe.throw(f"Unknown price list: {default_price_list}")
		doc.default_price_list = default_price_list
	doc.default_currency = default_currency or ""
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "supplier_name": doc.supplier_name}


@frappe.whitelist()
def get_supplier(name: str):
	if not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	_assert_can_read("Supplier", name)
	doc = frappe.get_doc("Supplier", name)
	return {
		"name": doc.name,
		"supplier_name": doc.supplier_name,
		"supplier_type": doc.supplier_type or "Company",
		"supplier_group": doc.supplier_group or "",
		"country": doc.country or "",
		"email_id": doc.email_id or "",
		"mobile_no": doc.mobile_no or "",
		"tax_id": doc.tax_id or "",
		"default_price_list": doc.default_price_list or "",
		"default_currency": doc.default_currency or "",
	}


@frappe.whitelist()
def update_supplier(
	name: str,
	supplier_name: str,
	supplier_type: str = "Company",
	supplier_group: str | None = None,
	country: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	tax_id: str | None = None,
	default_price_list: str | None = None,
	default_currency: str | None = None,
):
	_assert_can_write("Supplier", name, "write")
	if not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw("Supplier name is required.")
	if supplier_type not in VALID_SUPPLIER_TYPES:
		frappe.throw(f"Supplier type must be one of: {', '.join(sorted(VALID_SUPPLIER_TYPES))}.")
	if default_price_list and not frappe.db.exists("Price List", default_price_list):
		frappe.throw(f"Unknown price list: {default_price_list}")
	doc = frappe.get_doc("Supplier", name)
	doc.supplier_name = supplier_name
	doc.supplier_type = supplier_type
	if supplier_group:
		doc.supplier_group = supplier_group
	if country:
		doc.country = country
	doc.email_id = (email_id or "").strip()
	doc.mobile_no = (mobile_no or "").strip()
	doc.tax_id = (tax_id or "").strip()
	doc.default_price_list = default_price_list or ""
	doc.default_currency = default_currency or ""
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "supplier_name": doc.supplier_name}


@frappe.whitelist()
def delete_supplier(name: str):
	_assert_can_write("Supplier", name, "delete")
	if not frappe.db.exists("Supplier", name):
		frappe.throw(f"Unknown supplier: {name}")
	frappe.delete_doc("Supplier", name, ignore_permissions=False)
	return {"deleted": name}


def _clean_invoice_items(items) -> list[dict]:
	"""Validate and normalize the PI items payload (shared by create/update)."""
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
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
			}
		)
	return cleaned


def _validate_invoice_inputs(
	company: str,
	update_stock: int,
	set_warehouse: str | None,
	currency: str | None,
	conversion_rate,
	price_list: str | None,
	taxes_template: str | None,
) -> float:
	"""Shared create/update validation. Returns the resolved conversion rate."""
	if update_stock and not set_warehouse:
		frappe.throw("Warehouse is required when receiving goods into stock.")
	if set_warehouse and not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(f"Unknown warehouse: {set_warehouse}")
	if currency and not frappe.db.exists("Currency", currency):
		frappe.throw(f"Unknown currency: {currency}")
	if price_list and not frappe.db.exists("Price List", price_list):
		frappe.throw(f"Unknown price list: {price_list}")
	if taxes_template and not frappe.db.exists(
		"Purchase Taxes and Charges Template", {"name": taxes_template, "company": company}
	):
		frappe.throw(f"Unknown purchase tax template: {taxes_template}")

	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	if currency and currency != company_currency:
		rate = flt(conversion_rate)
		if rate <= 0:
			frappe.throw("Exchange rate must be greater than zero for foreign-currency bills.")
		return rate
	# Same currency as the company → rate is 1 by definition.
	return 1.0


def _apply_invoice_payload(
	doc,
	cleaned: list[dict],
	posting_date,
	due_date,
	bill_no,
	bill_date,
	remarks,
	update_stock: int,
	set_warehouse,
	currency,
	rate: float,
	price_list,
	taxes_template,
):
	"""Write validated PI fields + item/tax rows onto `doc` (new or draft)."""
	doc.posting_date = getdate(posting_date or today())
	doc.due_date = getdate(due_date) if due_date else None
	doc.bill_no = (bill_no or "").strip() or None
	doc.bill_date = getdate(bill_date) if bill_date else None
	doc.remarks = (remarks or "").strip() or None
	doc.update_stock = 1 if update_stock else 0
	doc.set_warehouse = set_warehouse or None
	if currency:
		doc.currency = currency
		doc.conversion_rate = rate
	doc.buying_price_list = price_list or ""

	doc.set("items", [])
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.qty = row["qty"]
		if update_stock and set_warehouse:
			line.warehouse = set_warehouse
		if row["rate"]:
			line.rate = row["rate"]
		if row["uom"]:
			line.uom = row["uom"]
		if row["discount_percentage"]:
			line.discount_percentage = row["discount_percentage"]
		if row["discount_amount"]:
			line.discount_amount = row["discount_amount"]
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))

	doc.set("taxes", [])
	doc.taxes_and_charges = taxes_template or None
	if taxes_template:
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		for tax_row in get_taxes_and_charges("Purchase Taxes and Charges Template", taxes_template):
			doc.append("taxes", tax_row)


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
	set_warehouse: str | None = None,
	currency: str | None = None,
	conversion_rate=None,
	price_list: str | None = None,
	taxes_template: str | None = None,
):
	"""Create a Purchase Invoice as Draft (docstatus=0).

	`items` is a list of dicts with keys: item_code (required), qty, rate, uom,
	discount_percentage, discount_amount.
	When `update_stock` is truthy, `set_warehouse` is required and goods are
	received into stock on submit. Foreign-currency bills require a positive
	`conversion_rate` (1 foreign = X company currency)."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")

	update_stock = cint(update_stock)
	cleaned = _clean_invoice_items(items)
	rate = _validate_invoice_inputs(
		company, update_stock, set_warehouse, currency, conversion_rate, price_list, taxes_template
	)

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = company
	doc.supplier = supplier
	_apply_invoice_payload(
		doc, cleaned, posting_date, due_date, bill_no, bill_date, remarks,
		update_stock, set_warehouse, currency, rate, price_list, taxes_template,
	)
	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
	}


@frappe.whitelist()
def update_purchase_invoice(
	name: str,
	supplier: str,
	items,
	posting_date: str | None = None,
	due_date: str | None = None,
	bill_no: str | None = None,
	bill_date: str | None = None,
	remarks: str | None = None,
	update_stock: int = 0,
	set_warehouse: str | None = None,
	currency: str | None = None,
	conversion_rate=None,
	price_list: str | None = None,
	taxes_template: str | None = None,
	modified: str | None = None,
):
	"""Replace a draft Purchase Invoice's fields and rows (full-row replace).

	Submitted/cancelled invoices are immutable — use cancel + amend instead."""
	_assert_can_write("Purchase Invoice", name, "write")
	if not name or not frappe.db.exists("Purchase Invoice", name):
		frappe.throw(f"Unknown Purchase Invoice: {name}")
	check_concurrency("Purchase Invoice", name, modified)
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus != 0:
		frappe.throw("Only draft bills can be edited.")
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")

	update_stock = cint(update_stock)
	cleaned = _clean_invoice_items(items)
	rate = _validate_invoice_inputs(
		doc.company, update_stock, set_warehouse, currency, conversion_rate, price_list, taxes_template
	)

	if supplier != doc.supplier:
		doc.supplier = supplier
		# Force set_missing_values to re-resolve the payable account for the
		# new supplier (a stale credit_to can carry the wrong account currency).
		doc.credit_to = None
	_apply_invoice_payload(
		doc, cleaned, posting_date, due_date, bill_no, bill_date, remarks,
		update_stock, set_warehouse, currency, rate, price_list, taxes_template,
	)
	doc.save(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
	}


@frappe.whitelist()
def delete_purchase_invoice(name: str, modified: str | None = None):
	"""Delete a draft Purchase Invoice. Submitted documents cannot be deleted."""
	_assert_can_write("Purchase Invoice", name, "delete")
	if not name or not frappe.db.exists("Purchase Invoice", name):
		frappe.throw(f"Unknown Purchase Invoice: {name}")
	check_concurrency("Purchase Invoice", name, modified)
	docstatus = cint(frappe.db.get_value("Purchase Invoice", name, "docstatus"))
	if docstatus != 0:
		frappe.throw("Only draft bills can be deleted.")
	frappe.delete_doc("Purchase Invoice", name, ignore_permissions=False)
	return {"deleted": name}


@frappe.whitelist()
def list_purchase_tax_templates(company: str):
	"""Purchase tax templates for `company`, each with its tax rows so the UI
	can preview tax/grand totals before the server computes them."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	templates = frappe.db.get_all(
		"Purchase Taxes and Charges Template",
		filters={"company": company, "disabled": 0},
		fields=["name", "title", "is_default"],
		order_by="is_default desc, title asc",
	)
	for tpl in templates:
		tpl["taxes"] = frappe.db.get_all(
			"Purchase Taxes and Charges",
			filters={"parent": tpl["name"], "parenttype": "Purchase Taxes and Charges Template"},
			fields=["charge_type", "description", "rate", "tax_amount"],
			order_by="idx asc",
		)
	return templates


@frappe.whitelist()
def get_purchase_exchange_rate(
	company: str,
	currency: str,
	posting_date: str | None = None,
	supplier: str | None = None,
):
	"""Suggested conversion rate for a foreign-currency bill.

	Sources in priority order: ERPNext Currency Exchange records for the
	posting date, then the supplier's most recent submitted PI in that
	currency. Returns rate=0 when no trustworthy source exists — the UI must
	then require manual entry (never default a foreign rate to 1.0)."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	if not currency or currency == company_currency:
		return {"rate": 1.0, "source": "company"}

	date = getdate(posting_date or today())
	rate = 0.0
	try:
		from erpnext.setup.utils import get_exchange_rate as _erp_rate

		rate = flt(_erp_rate(currency, company_currency, str(date), "for_buying"))
	except Exception:
		rate = 0.0
	# ERPNext falls back to 1.0/0.0 when it has no record — for a foreign
	# currency that is "not found", not a real rate.
	if rate > 0 and rate != 1.0:
		return {"rate": rate, "source": "erpnext", "date": str(date)}

	if supplier:
		row = frappe.db.sql(
			"""
			SELECT conversion_rate
			FROM `tabPurchase Invoice`
			WHERE supplier = %(supplier)s AND company = %(company)s
			  AND currency = %(currency)s AND docstatus = 1
			  AND conversion_rate > 0 AND conversion_rate <> 1
			ORDER BY posting_date DESC, creation DESC
			LIMIT 1
			""",
			{"supplier": supplier, "company": company, "currency": currency},
			as_dict=True,
		)
		if row:
			return {"rate": flt(row[0]["conversion_rate"]), "source": "last_invoice"}

	return {"rate": 0.0, "source": None}


@frappe.whitelist()
def submit_purchase_invoice(name: str, modified: str | None = None):
	"""Submit a Draft Purchase Invoice (docstatus 0 → 1)."""
	_assert_can_write("Purchase Invoice", name, "submit")
	if not name:
		frappe.throw("Invoice name is required.")
	check_concurrency("Purchase Invoice", name, modified)
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus == 1:
		frappe.throw("Invoice is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Invoice is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_purchase_invoice(name: str, modified: str | None = None):
	"""Cancel a Submitted Purchase Invoice (docstatus 1 → 2)."""
	_assert_can_write("Purchase Invoice", name, "cancel")
	if not name:
		frappe.throw("Invoice name is required.")
	check_concurrency("Purchase Invoice", name, modified)
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted invoices can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def amend_purchase_invoice(name: str):
	"""Create a new draft Purchase Invoice as an amendment of a cancelled one."""
	_assert_can_write("Purchase Invoice", name, "cancel")
	if not name or not frappe.db.exists("Purchase Invoice", name):
		frappe.throw(f"Unknown Purchase Invoice: {name}")
	doc = frappe.get_doc("Purchase Invoice", name)
	if doc.docstatus != 2:
		frappe.throw("Only cancelled purchase invoices can be amended.")
	new = frappe.copy_doc(doc)
	new.amended_from = name
	new.insert(ignore_permissions=False)
	return {"name": new.name, "docstatus": new.docstatus, "amended_from": name}


@frappe.whitelist()
def create_purchase_return(
	purchase_invoice: str,
	posting_date: str | None = None,
	item_returns=None,
	submit: int = 0,
):
	"""Issue a debit note (is_return=1) against a submitted Purchase Invoice.

	`item_returns` is an optional list of `{item_code, qty}` where qty is
	entered positive (negated internally). Pass nothing to return the full invoice.
	"""
	from frappe.utils import today as _today, getdate
	from frappe.utils.data import flt as _flt

	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Unknown Purchase Invoice: {0}").format(purchase_invoice))
	# IDOR guard: @frappe.whitelist gates method access only, not record access.
	# Without this, a user could issue (and with submit=1, post) a debit note
	# against another company's invoice by guessing its sequential name.
	_assert_can_read("Purchase Invoice", purchase_invoice)
	src = frappe.get_doc("Purchase Invoice", purchase_invoice)
	if src.docstatus != 1:
		frappe.throw(_("Only submitted invoices can be returned."))
	if src.is_return:
		frappe.throw(_("Cannot create a return against a return document."))

	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	doc = make_return_doc("Purchase Invoice", purchase_invoice)
	doc.posting_date = getdate(posting_date or _today())

	if isinstance(item_returns, str):
		try:
			item_returns = frappe.parse_json(item_returns)
		except Exception:
			frappe.throw(_("Invalid item_returns payload"))

	if item_returns:
		src_qty: dict[str, float] = {it.item_code: _flt(it.qty) for it in src.items}
		override: dict[str, float] = {
			row["item_code"]: _flt(row.get("qty", 0))
			for row in (item_returns or [])
			if isinstance(row, dict) and row.get("item_code")
		}
		for line in doc.items:
			requested = override.get(line.item_code)
			if requested is None:
				continue
			clamped = min(abs(requested), abs(src_qty.get(line.item_code, 0)))
			line.qty = -clamped if clamped else line.qty

		non_zero = [ln for ln in doc.items if _flt(ln.qty) != 0]
		if non_zero:
			doc.items = non_zero

	doc.insert(ignore_permissions=False)
	if int(submit or 0):
		doc.submit()
	return {
		"name": doc.name,
		"is_return": 1,
		"grand_total": _flt(doc.grand_total),
		"docstatus": doc.docstatus,
		"return_against": purchase_invoice,
	}


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


# ── Purchase Order helpers ────────────────────────────────────────────────────


def _resolve_buy_price_list(supplier: str) -> str:
	"""Return the supplier's default buying price list, or empty string."""
	return frappe.db.get_value("Supplier", supplier, "default_price_list") or ""


def _lookup_item_buy_price(item_code: str, price_list: str, uom: str | None = None) -> dict | None:
	"""Look up the buying Item Price for the given item + price list."""
	conds = [
		"item_code = %(item_code)s",
		"price_list = %(price_list)s",
		"buying = 1",
	]
	params: dict = {"item_code": item_code, "price_list": price_list}
	if uom:
		conds.append("uom = %(uom)s")
		params["uom"] = uom
	rows = frappe.db.sql(
		f"SELECT price_list_rate FROM `tabItem Price` WHERE {' AND '.join(conds)} LIMIT 1",
		params,
		as_dict=True,
	)
	return rows[0] if rows else None


# ── Purchase Order endpoints ──────────────────────────────────────────────────


@frappe.whitelist()
def list_purchase_orders(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	supplier: str | None = None,
	status: str | None = None,
	limit: int = 100,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	conds = ["company = %(company)s", "docstatus < 2"]
	params: dict = {"company": company, "limit": int(limit)}
	if from_date:
		conds.append("transaction_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conds.append("transaction_date <= %(to_date)s")
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
		SELECT name, transaction_date, schedule_date, supplier, supplier_name,
		       grand_total, per_received, per_billed,
		       status, currency, docstatus, set_warehouse
		FROM `tabPurchase Order`
		WHERE {where}
		ORDER BY transaction_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def purchase_order_detail(name: str):
	if not name:
		frappe.throw("Purchase order name is required.")
	_assert_can_read("Purchase Order", name)
	doc = frappe.get_doc("Purchase Order", name)
	_has_dim = frappe.db.has_column("Item", "custom_dimension_mode")

	def _dim_mode(code):
		if not _has_dim or not code:
			return ""
		return frappe.get_cached_value("Item", code, "custom_dimension_mode") or ""

	# linked Purchase Invoices created via PO→PI bridge (or manually)
	pi_links = frappe.db.sql(
		"""
		SELECT DISTINCT pi.name, pi.docstatus
		FROM `tabPurchase Invoice Item` pii
		JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pii.purchase_order = %(name)s AND pi.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	# linked Purchase Receipts created via PO→PR bridge (or manually)
	pr_links = frappe.db.sql(
		"""
		SELECT DISTINCT pr.name, pr.docstatus
		FROM `tabPurchase Receipt Item` pri
		JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
		WHERE pri.purchase_order = %(name)s AND pr.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	return {
		"name": doc.name,
		"modified": str(doc.modified),
		"transaction_date": str(doc.transaction_date) if doc.transaction_date else None,

		"schedule_date": str(doc.schedule_date) if doc.schedule_date else None,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name,
		"company": doc.company,
		"set_warehouse": getattr(doc, "set_warehouse", None) or None,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"per_received": flt(doc.per_received),
		"per_billed": flt(doc.per_billed),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"amended_from": doc.amended_from or None,
		"remarks": getattr(doc, "terms", None) or None,
		"purchase_invoices": pi_links,
		"purchase_receipts": pr_links,
		"items": [
			{
				"name": it.name,
				"item_code": it.item_code,
				"item_name": it.item_name,
				"warehouse": getattr(it, "warehouse", None) or None,
				"qty": flt(it.qty),
				"received_qty": flt(getattr(it, "received_qty", 0)),
				"billed_amt": flt(getattr(it, "billed_amt", 0)),
				"uom": it.uom,
				"stock_uom": it.stock_uom,
				"conversion_factor": flt(it.conversion_factor) or 1.0,
				"stock_qty": flt(it.stock_qty),
				"rate": flt(it.rate),
				"price_list_rate": flt(it.price_list_rate),
				"discount_percentage": flt(it.discount_percentage),
				"discount_amount": flt(it.discount_amount),
				"amount": flt(it.amount),
				"schedule_date": str(it.schedule_date) if it.schedule_date else None,
				"custom_dimension_mode": _dim_mode(it.item_code),
				"custom_length": flt(getattr(it, "custom_length", 0)) or None,
				"custom_width": flt(getattr(it, "custom_width", 0)) or None,
				"custom_height": flt(getattr(it, "custom_height", 0)) or None,
				"custom_pieces": flt(getattr(it, "custom_pieces", 0)) or None,
			}
			for it in (doc.items or [])
		],
	}


@frappe.whitelist()
def create_purchase_order(
	company: str,
	supplier: str,
	items,
	set_warehouse: str | None = None,
	transaction_date: str | None = None,
	schedule_date: str | None = None,
	remarks: str | None = None,
	auto_submit: int = 1,
	currency: str | None = None,
	price_list: str | None = None,
	deal: str | None = None,
):
	"""Create (and optionally submit) a Purchase Order.

	`set_warehouse` is optional — POs are inbound, no stock-guard needed.
	When `auto_submit` is truthy (default) the PO is submitted immediately.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")
	if set_warehouse and not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(f"Unknown warehouse: {set_warehouse}")

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	txn_date = getdate(transaction_date or today())
	sched_date = getdate(schedule_date) if schedule_date else txn_date

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
				"conversion_factor": flt(row.get("conversion_factor")) or None,
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
			}
		)

	doc = frappe.new_doc("Purchase Order")
	doc.company = company
	doc.supplier = supplier
	doc.transaction_date = txn_date
	doc.schedule_date = sched_date
	# Tag the PO to a tender so it appears on the Tender PO control board. Guarded
	# on the custom field (patch v34) so it's a no-op before migrate runs.
	if deal and frappe.db.exists("CRM Deal", deal) and frappe.db.has_column("Purchase Order", "custom_crm_deal"):
		doc.custom_crm_deal = deal
	if set_warehouse:
		doc.set_warehouse = set_warehouse
	if remarks:
		doc.terms = remarks.strip()
	if currency:
		doc.currency = currency
	resolved_pl = price_list or _resolve_buy_price_list(supplier)
	if resolved_pl:
		doc.buying_price_list = resolved_pl

	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.qty = row["qty"]
		line.schedule_date = sched_date
		if set_warehouse:
			line.warehouse = set_warehouse
		rate = row["rate"]
		if not rate and resolved_pl:
			hit = _lookup_item_buy_price(row["item_code"], resolved_pl)
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
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))

	doc.insert(ignore_permissions=False)
	pending_approval = False
	approval_request = None
	if cint(auto_submit):
		from stabler.api.approvals import ensure_request_for_doc, requires_approval

		if requires_approval(doc):
			# Maker-checker: keep the PO a Draft and route it to the approvals
			# queue instead of self-submitting. A different user must approve.
			approval_request = ensure_request_for_doc(doc)
			pending_approval = True
		else:
			doc.submit()

	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"pending_approval": pending_approval,
		"approval_request": approval_request,
	}


@frappe.whitelist()
def update_purchase_order(
	name: str,
	items,
	set_warehouse: str | None = None,
	transaction_date: str | None = None,
	schedule_date: str | None = None,
	remarks: str | None = None,
	currency: str | None = None,
	price_list: str | None = None,
	modified: str | None = None,
):
	"""Update an existing Draft Purchase Order in-place.

	Only docstatus=0 (Draft) orders may be edited — submitted orders are immutable.
	Replaces item lines entirely.
	"""
	_assert_can_write("Purchase Order", name, "write")
	if not name:
		frappe.throw("Purchase order name is required.")
	check_concurrency("Purchase Order", name, modified)
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 0:
		frappe.throw("Only draft purchase orders can be edited.")

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	txn_date = getdate(transaction_date or doc.transaction_date)
	sched_date = getdate(schedule_date) if schedule_date else txn_date

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
				"conversion_factor": flt(row.get("conversion_factor")) or None,
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
			}
		)

	doc.transaction_date = txn_date
	doc.schedule_date = sched_date
	if set_warehouse:
		doc.set_warehouse = set_warehouse
	else:
		doc.set_warehouse = None

	if remarks is not None:
		doc.terms = remarks.strip()
	if currency:
		doc.currency = currency
	resolved_pl = price_list or _resolve_buy_price_list(doc.supplier)
	if resolved_pl:
		doc.buying_price_list = resolved_pl

	doc.set("items", [])
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.qty = row["qty"]
		line.schedule_date = sched_date
		if set_warehouse:
			line.warehouse = set_warehouse
		rate = row["rate"]
		if not rate and resolved_pl:
			hit = _lookup_item_buy_price(row["item_code"], resolved_pl)
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
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))

	doc.save(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"docstatus": doc.docstatus,
		"status": doc.status,
	}



@frappe.whitelist()
def submit_purchase_order(name: str, modified: str | None = None):
	"""Submit a draft Purchase Order (docstatus 0 → 1)."""
	_assert_can_write("Purchase Order", name, "submit")
	if not name:
		frappe.throw("Purchase order name is required.")
	check_concurrency("Purchase Order", name, modified)
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus == 1:
		frappe.throw("Purchase order is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Purchase order is cancelled and cannot be submitted.")

	from stabler.api.approvals import ensure_request_for_doc, requires_approval

	if requires_approval(doc):
		# Route to the approvals queue instead of submitting; a different user
		# must approve. (The before_submit gate is the backstop if anyone tries
		# to submit it directly.)
		req = ensure_request_for_doc(doc)
		return {
			"name": doc.name,
			"docstatus": doc.docstatus,
			"status": doc.status,
			"pending_approval": True,
			"approval_request": req,
		}
	doc.submit()
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"pending_approval": False,
	}


@frappe.whitelist()
def cancel_purchase_order(name: str, modified: str | None = None):
	"""Cancel a submitted Purchase Order (docstatus 1 → 2)."""
	_assert_can_write("Purchase Order", name, "cancel")
	if not name:
		frappe.throw("Purchase order name is required.")
	check_concurrency("Purchase Order", name, modified)
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted purchase orders can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def amend_purchase_order(name: str):
	"""Create a new draft Purchase Order as an amendment of a cancelled one."""
	_assert_can_write("Purchase Order", name, "cancel")
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(f"Unknown Purchase Order: {name}")
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 2:
		frappe.throw("Only cancelled purchase orders can be amended.")
	new = frappe.copy_doc(doc)
	new.amended_from = name
	new.insert(ignore_permissions=False)
	return {"name": new.name, "docstatus": new.docstatus, "amended_from": name}


@frappe.whitelist()
def create_purchase_invoice_from_po(name: str):
	"""Create a draft Purchase Invoice from a submitted Purchase Order.

	Uses ERPNext's make_purchase_invoice mapper which automatically sets
	po_detail + purchase_order on each PI item row and handles partial billing.
	"""
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(f"Unknown Purchase Order: {name}")
	_assert_can_read("Purchase Order", name)
	po = frappe.get_doc("Purchase Order", name)
	if po.docstatus != 1:
		frappe.throw("Only submitted purchase orders can be invoiced.")
	from erpnext.buying.doctype.purchase_order.purchase_order import (
		make_purchase_invoice as _make_pi,
	)
	doc = _make_pi(name)
	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"purchase_order": name,
	}


# ── Purchase Receipt endpoints ────────────────────────────────────────────────


@frappe.whitelist()
def list_purchase_receipts(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	supplier: str | None = None,
	status: str | None = None,
	limit: int = 100,
):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
		SELECT name, posting_date, supplier, supplier_name,
		       grand_total, per_billed,
		       status, currency, docstatus, set_warehouse
		FROM `tabPurchase Receipt`
		WHERE {where}
		ORDER BY posting_date DESC, name DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def purchase_receipt_detail(name: str):
	if not name:
		frappe.throw("Purchase receipt name is required.")
	_assert_can_read("Purchase Receipt", name)
	doc = frappe.get_doc("Purchase Receipt", name)
	# linked Purchase Invoices created via PR→PI bridge (or manually)
	pi_links = frappe.db.sql(
		"""
		SELECT DISTINCT pi.name, pi.docstatus
		FROM `tabPurchase Invoice Item` pii
		JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pii.purchase_receipt = %(name)s AND pi.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	# linked Landed Cost Vouchers referencing this receipt
	lcv_links = frappe.db.sql(
		"""
		SELECT DISTINCT lcv.name, lcv.docstatus
		FROM `tabLanded Cost Purchase Receipt` lpr
		JOIN `tabLanded Cost Voucher` lcv ON lcv.name = lpr.parent
		WHERE lpr.receipt_document_type = 'Purchase Receipt'
		  AND lpr.receipt_document = %(name)s AND lcv.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	return {
		"name": doc.name,
		"posting_date": str(doc.posting_date) if doc.posting_date else None,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name,
		"company": doc.company,
		"set_warehouse": getattr(doc, "set_warehouse", None) or None,
		"currency": doc.currency,
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"base_grand_total": flt(doc.base_grand_total),
		"per_billed": flt(doc.per_billed),
		"status": doc.status,
		"docstatus": doc.docstatus,
		"amended_from": doc.amended_from or None,
		"remarks": getattr(doc, "remarks", None) or None,
		"purchase_invoices": pi_links,
		"landed_cost_vouchers": lcv_links,
		"items": [
			{
				"name": it.name,
				"item_code": it.item_code,
				"item_name": it.item_name,
				"warehouse": getattr(it, "warehouse", None) or None,
				"qty": flt(it.qty),
				"rejected_qty": flt(getattr(it, "rejected_qty", 0)),
				"uom": it.uom,
				"stock_uom": it.stock_uom,
				"conversion_factor": flt(it.conversion_factor) or 1.0,
				"stock_qty": flt(it.stock_qty),
				"rate": flt(it.rate),
				"amount": flt(it.amount),
				"billed_amt": flt(getattr(it, "billed_amt", 0)),
				"purchase_order": getattr(it, "purchase_order", None) or None,
				"landed_cost_voucher_amount": flt(getattr(it, "landed_cost_voucher_amount", 0)),
			}
			for it in (doc.items or [])
		],
	}


@frappe.whitelist()
def create_purchase_receipt_from_po(name: str, items=None):
	"""Create a draft Purchase Receipt from a submitted Purchase Order.

	Uses ERPNext's make_purchase_receipt mapper, which maps only rows with
	pending qty (qty - received_qty) and sets purchase_order_item on each row.

	`items` (optional) enables partial receiving: a list of
	{"po_detail": <PO item row name>, "qty": <qty to receive>}.
	Rows not listed are dropped; requested qty is capped at the pending qty.
	"""
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(f"Unknown Purchase Order: {name}")
	_assert_can_read("Purchase Order", name)
	po = frappe.get_doc("Purchase Order", name)
	if po.docstatus != 1:
		frappe.throw("Only submitted purchase orders can be received.")

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if items is not None and (not isinstance(items, list) or not items):
		frappe.throw("Invalid items payload.")

	from erpnext.buying.doctype.purchase_order.purchase_order import (
		make_purchase_receipt as _make_pr,
	)

	doc = _make_pr(name)
	if not doc.get("items"):
		frappe.throw("Nothing left to receive on this purchase order.")

	if items:
		requested: dict[str, float] = {}
		for idx, row in enumerate(items, start=1):
			po_detail = (row or {}).get("po_detail")
			if not po_detail:
				frappe.throw(f"Row {idx}: po_detail is required.")
			qty = flt(row.get("qty"))
			if qty <= 0:
				frappe.throw(f"Row {idx}: qty must be greater than zero.")
			requested[po_detail] = qty

		mapped = {r.purchase_order_item: r for r in doc.items}
		unknown = [d for d in requested if d not in mapped]
		if unknown:
			frappe.throw(
				"These order rows have nothing pending to receive: "
				+ ", ".join(unknown)
			)

		kept = []
		for po_detail, qty in requested.items():
			row = mapped[po_detail]
			row.qty = min(qty, flt(row.qty))  # cap at pending
			kept.append(row)
		doc.items = kept
		for i, row in enumerate(doc.items, start=1):
			row.idx = i

	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"purchase_order": name,
		"docstatus": doc.docstatus,
	}


@frappe.whitelist()
def create_purchase_receipt(
	company: str,
	supplier: str,
	items,
	set_warehouse: str,
	posting_date: str | None = None,
	currency: str | None = None,
	remarks: str | None = None,
):
	"""Create a draft Purchase Receipt directly (no Purchase Order).

	A receipt moves stock, so `set_warehouse` is required.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not supplier:
		frappe.throw("Supplier is required.")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Unknown supplier: {supplier}")
	if not set_warehouse:
		frappe.throw("Warehouse is required — a receipt moves stock into it.")
	if not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(f"Unknown warehouse: {set_warehouse}")

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
		if row.get("rate") not in (None, "") and flt(row.get("rate")) < 0:
			frappe.throw(f"Row {idx}: rate cannot be negative.")
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
				"conversion_factor": flt(row.get("conversion_factor")) or None,
			}
		)

	doc = frappe.new_doc("Purchase Receipt")
	doc.company = company
	doc.supplier = supplier
	doc.posting_date = getdate(posting_date or today())
	doc.set_warehouse = set_warehouse
	if currency:
		doc.currency = currency
	if remarks:
		doc.remarks = remarks.strip()

	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.qty = row["qty"]
		line.warehouse = set_warehouse
		if row["rate"]:
			line.rate = row["rate"]
		if row["uom"]:
			line.uom = row["uom"]
		if row["conversion_factor"]:
			line.conversion_factor = row["conversion_factor"]

	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"docstatus": doc.docstatus,
	}


@frappe.whitelist()
def submit_purchase_receipt(name: str):
	"""Submit a draft Purchase Receipt (docstatus 0 → 1) — this moves stock."""
	_assert_can_write("Purchase Receipt", name, "submit")
	if not name:
		frappe.throw("Purchase receipt name is required.")
	doc = frappe.get_doc("Purchase Receipt", name)
	if doc.docstatus == 1:
		frappe.throw("Purchase receipt is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Purchase receipt is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_purchase_receipt(name: str):
	"""Cancel a submitted Purchase Receipt (docstatus 1 → 2) — reverses stock."""
	_assert_can_write("Purchase Receipt", name, "cancel")
	if not name:
		frappe.throw("Purchase receipt name is required.")
	doc = frappe.get_doc("Purchase Receipt", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted purchase receipts can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def create_purchase_invoice_from_pr(name: str):
	"""Create a draft Purchase Invoice from a submitted Purchase Receipt.

	The receipt already moved stock, so the bill must NOT move it again:
	update_stock is forced to 0 (ERPNext also guards this server-side).
	"""
	if not name or not frappe.db.exists("Purchase Receipt", name):
		frappe.throw(f"Unknown Purchase Receipt: {name}")
	_assert_can_read("Purchase Receipt", name)
	pr = frappe.get_doc("Purchase Receipt", name)
	if pr.docstatus != 1:
		frappe.throw("Only submitted purchase receipts can be billed.")
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
		make_purchase_invoice as _make_pi,
	)

	doc = _make_pi(name)
	doc.update_stock = 0
	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"supplier": doc.supplier,
		"purchase_receipt": name,
	}


@frappe.whitelist()
def payables_cockpit(company: str):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	
	# Current total payables balance (credit - debit)
	current_total = flt(frappe.db.sql(
		"""
		SELECT COALESCE(SUM(credit - debit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Supplier' AND is_cancelled = 0
		""",
		{"company": company},
	)[0][0])

	# 8-week trend (running balance at the end of each of the last 8 weeks)
	from datetime import datetime, timedelta
	from frappe.utils import getdate

	current_date = getdate(today())
	weeks = []
	for i in range(8):
		date_at_end = current_date - timedelta(days=i*7)
		weeks.append(date_at_end)
	weeks.reverse()

	trend = []
	for w_end in weeks:
		change_since = flt(frappe.db.sql(
			"""
			SELECT COALESCE(SUM(credit - debit), 0)
			FROM `tabGL Entry`
			WHERE company = %(company)s AND party_type = 'Supplier' AND posting_date > %(w_end)s AND is_cancelled = 0
			""",
			{"company": company, "w_end": w_end},
		)[0][0])
		trend.append(round(current_total - change_since, 2))

	# Payments paid today (debit side for Supplier)
	paid_today = flt(frappe.db.sql(
		"""
		SELECT COALESCE(SUM(debit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Supplier' AND posting_date = %(today)s AND is_cancelled = 0
		""",
		{"company": company, "today": today()},
	)[0][0])

	# Top 10 creditors
	eps = money_epsilon(frappe.get_cached_value("Company", company, "default_currency"))
	top_creditors_raw = frappe.db.sql(
		"""
		SELECT party AS name, COALESCE(SUM(credit - debit), 0) AS balance
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Supplier' AND is_cancelled = 0
		GROUP BY party
		HAVING SUM(credit - debit) > %(eps)s
		ORDER BY balance DESC
		LIMIT 10
		""",
		{"company": company, "eps": eps},
		as_dict=True,
	) or []
	
	for creditor in top_creditors_raw:
		creditor["supplier_name"] = frappe.db.get_value("Supplier", creditor["name"], "supplier_name") or creditor["name"]
		creditor["balance"] = flt(creditor["balance"])

	return {
		"total_payable": current_total,
		"payments_paid_today": paid_today,
		"trend_8_weeks": trend,
		"top_creditors": top_creditors_raw,
	}


# ──────────────────────────────────────────────────────────────────────────── #
# Tender sourcing (F3) — compare Supplier Quotations collected for one tender.
# ──────────────────────────────────────────────────────────────────────────── #
@frappe.whitelist()
def tender_quotations(deal: str) -> dict:
	"""Supplier Quotations tagged to a CRM Deal, side-by-side for comparison.

	Returns one row per quotation with the supplier's country and the base-currency
	total (the apples-to-apples figure), flags the cheapest, and surfaces the
	procurement-policy checks: at least 5 quotations from at least 2 countries.
	Gated to the deal's company having the tender module enabled.
	"""
	if not frappe.db.exists("CRM Deal", deal):
		frappe.throw(frappe._("Unknown deal: {0}").format(deal))
	company = frappe.db.get_value("CRM Deal", deal, "company") or frappe.defaults.get_user_default("Company") or (
		frappe.get_all("Company", pluck="name", limit=1) or [None]
	)[0]
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg

	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	if not module_map_for(company).get("tender"):
		frappe.throw(frappe._("Tender module is not enabled for {0}.").format(company), frappe.PermissionError)

	base_ccy = frappe.get_cached_value("Company", company, "default_currency")
	if not frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		return {"rows": [], "base_currency": base_ccy, "count": 0, "countries": 0,
		        "has_min_5": False, "has_2_countries": False}

	sqs = frappe.get_all(
		"Supplier Quotation",
		filters={"custom_crm_deal": deal, "docstatus": ["<", 2]},
		fields=[
			"name", "supplier", "supplier_name", "currency", "grand_total",
			"base_grand_total", "valid_till", "status", "transaction_date", "total_qty",
		],
		order_by="base_grand_total asc",
		limit_page_length=0,
	)
	# Supplier → country (for the 2-country policy check).
	suppliers = list({s["supplier"] for s in sqs if s.get("supplier")})
	country_map = {}
	if suppliers:
		for s in frappe.get_all(
			"Supplier", filters={"name": ["in", suppliers]}, fields=["name", "country"]
		):
			country_map[s["name"]] = s.get("country") or ""

	rows = []
	cheapest_base = None
	for s in sqs:
		base_total = flt(s.get("base_grand_total")) or flt(s.get("grand_total"))
		if base_total and (cheapest_base is None or base_total < cheapest_base):
			cheapest_base = base_total
		rows.append({
			"name": s["name"],
			"supplier": s["supplier"],
			"supplier_name": s.get("supplier_name") or s["supplier"],
			"country": country_map.get(s["supplier"], ""),
			"currency": s.get("currency"),
			"grand_total": flt(s.get("grand_total")),
			"base_total": base_total,
			"valid_till": str(s.get("valid_till") or ""),
			"status": s.get("status"),
			"transaction_date": str(s.get("transaction_date") or ""),
			"qty": flt(s.get("total_qty")),
		})
	for r in rows:
		r["cheapest"] = bool(cheapest_base is not None and r["base_total"] == cheapest_base and r["base_total"] > 0)

	countries = {r["country"] for r in rows if r["country"]}
	return {
		"rows": rows,
		"base_currency": base_ccy,
		"count": len(rows),
		"countries": len(countries),
		"has_min_5": len(rows) >= 5,
		"has_2_countries": len(countries) >= 2,
	}
