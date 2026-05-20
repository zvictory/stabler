"""Sales module — Customers, Sales Invoices, AR aging."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, today


def _require_company(company: str) -> str:
	if not company:
		frappe.throw("Company is required.")
	if not frappe.db.exists("Company", company):
		frappe.throw(f"Unknown company: {company}")
	return company


def _resolve_price_list(customer: str | None) -> str | None:
	"""Return per-customer default_price_list, else Selling Settings selling_price_list."""
	if customer:
		pl = frappe.db.get_value("Customer", customer, "default_price_list")
		if pl:
			return pl
	return frappe.db.get_single_value("Selling Settings", "selling_price_list") or None


def _lookup_item_price(item_code: str, price_list: str) -> dict | None:
	"""Find an active Item Price row for (item_code, price_list).
	Honors validity window; prefers a row valid today, then the most recent."""
	rows = frappe.db.sql(
		"""
		SELECT price_list_rate, currency, valid_from, valid_upto
		FROM `tabItem Price`
		WHERE item_code = %(item_code)s AND price_list = %(price_list)s
		  AND selling = 1
		  AND (valid_from IS NULL OR valid_from <= %(today)s)
		  AND (valid_upto IS NULL OR valid_upto >= %(today)s)
		ORDER BY valid_from DESC
		LIMIT 1
		""",
		{"item_code": item_code, "price_list": price_list, "today": today()},
		as_dict=True,
	)
	if not rows:
		return None
	r = rows[0]
	return {"price_list_rate": flt(r["price_list_rate"]), "currency": r["currency"]}


def _resolve_tax_template(company: str, customer: str | None) -> str | None:
	"""Resolve the Uzbek NDS Sales Taxes and Charges Template for a transaction.

	Priority:
	  1. Customer.tax_template (custom field — honored if present).
	  2. Customer.is_tax_exempt → company's "Uzbekistan NDS Exempt - <ABBR>".
	  3. Default → company's "Uzbekistan NDS 12% - <ABBR>".

	Returns None if none of the candidate templates exist for this company
	(e.g. v05 patch hasn't been able to discover a tax account); callers
	then leave taxes_and_charges untouched so ERPNext falls back to its
	own resolution path.
	"""
	abbr = frappe.db.get_value("Company", company, "abbr") if company else None
	if not abbr:
		return None

	exempt_template = f"Uzbekistan NDS Exempt - {abbr}"
	nds_template = f"Uzbekistan NDS 12% - {abbr}"

	if customer:
		custom = frappe.db.get_value("Customer", customer, "tax_template")
		if custom and frappe.db.exists("Sales Taxes and Charges Template", custom):
			return custom
		is_exempt = frappe.db.get_value("Customer", customer, "is_tax_exempt")
		if is_exempt and frappe.db.exists("Sales Taxes and Charges Template", exempt_template):
			return exempt_template

	if frappe.db.exists("Sales Taxes and Charges Template", nds_template):
		return nds_template
	if frappe.db.exists("Sales Taxes and Charges Template", exempt_template):
		return exempt_template
	return None


def _apply_tax_template(doc, template_name: str | None) -> None:
	"""Stamp `taxes_and_charges` on a sales doc and repopulate the taxes table.

	Clears any pre-existing rows so a Customer flag toggle on re-resolve
	produces a clean recompute. Safe to call on docs that already inherited
	taxes from a parent (e.g. SI from SO) — we treat the resolved template
	as authoritative.
	"""
	if not template_name:
		return
	doc.taxes_and_charges = template_name
	if doc.get("taxes"):
		doc.set("taxes", [])
	src_rows = frappe.get_all(
		"Sales Taxes and Charges",
		filters={"parent": template_name, "parenttype": "Sales Taxes and Charges Template"},
		fields=[
			"charge_type",
			"account_head",
			"description",
			"rate",
			"row_id",
			"included_in_print_rate",
			"cost_center",
		],
		order_by="idx asc",
	)
	for row in src_rows:
		doc.append("taxes", row)


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
		       default_currency, mobile_no, email_id
		FROM `tabCustomer`
		WHERE {where}
		ORDER BY customer_name ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def customer_detail(name: str, company: str):
	_require_company(company)
	if not name or not frappe.db.exists("Customer", name):
		frappe.throw(f"Unknown customer: {name}")
	doc = frappe.get_doc("Customer", name)

	# AR + recent invoices scoped to company
	ar_row = frappe.db.sql(
		"""
		SELECT
		  COALESCE(SUM(outstanding_amount), 0) AS outstanding,
		  COALESCE(SUM(base_grand_total), 0) AS lifetime
		FROM `tabSales Invoice`
		WHERE customer = %(name)s AND company = %(company)s
		  AND docstatus = 1
		""",
		{"name": name, "company": company},
		as_dict=True,
	)
	ar = ar_row[0] if ar_row else {"outstanding": 0, "lifetime": 0}

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
		"outstanding": flt(ar["outstanding"]),
		"lifetime": flt(ar["lifetime"]),
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
		       grand_total, outstanding_amount, status, currency, docstatus
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
		"total_taxes_and_charges": flt(doc.total_taxes_and_charges),
		"grand_total": flt(doc.grand_total),
		"outstanding_amount": flt(doc.outstanding_amount),
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
def ar_aging(company: str, as_of: str | None = None):
	"""Bucket outstanding Sales Invoices by age into 0-30/31-60/61-90/90+."""
	_require_company(company)
	as_of = getdate(as_of or today())
	rows = frappe.db.sql(
		"""
		SELECT
		  customer,
		  customer_name,
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
		GROUP BY customer, customer_name
		ORDER BY total DESC
		""",
		{"company": company, "as_of": as_of},
		as_dict=True,
	)
	totals = {
		"total": sum(flt(r["total"]) for r in rows),
		"b_0_30": sum(flt(r["b_0_30"]) for r in rows),
		"b_31_60": sum(flt(r["b_31_60"]) for r in rows),
		"b_61_90": sum(flt(r["b_61_90"]) for r in rows),
		"b_90_plus": sum(flt(r["b_90_plus"]) for r in rows),
	}
	return {"rows": rows, "totals": totals, "as_of": str(as_of)}


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
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "customer_name": doc.customer_name}


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
			if patch.get("qty") not in (None, ""):
				qty = flt(patch["qty"])
				if qty <= 0:
					frappe.throw(_("Override qty must be greater than zero"))
				line.qty = qty
			if patch.get("rate") not in (None, ""):
				line.rate = flt(patch["rate"])

	_apply_tax_template(doc, _resolve_tax_template(doc.company, doc.customer))
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
def get_item_price(item_code: str, company: str, customer: str | None = None):
	"""Resolve the price for `item_code` for an optional `customer`.

	Resolution order for the price list:
	  1. Customer.default_price_list (if customer is supplied)
	  2. Selling Settings.selling_price_list (global default)

	Returns the matching Item Price row's price_list_rate + currency, plus the
	resolved price_list name. If no price list is configured or no matching
	row exists, returns price_list_rate=0 with an `unresolved=True` flag so the
	caller can fall back to Item.standard_rate.
	"""
	_require_company(company)
	if not item_code:
		frappe.throw("Item code is required.")
	if not frappe.db.exists("Item", item_code):
		frappe.throw(f"Unknown item: {item_code}")
	if customer and not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")

	price_list = _resolve_price_list(customer)
	if not price_list:
		return {
			"price_list": None,
			"price_list_rate": 0.0,
			"currency": None,
			"unresolved": True,
			"reason": "no_price_list",
		}

	hit = _lookup_item_price(item_code, price_list)
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
		"total_taxes_and_charges": flt(doc.total_taxes_and_charges),
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
	doc = frappe.get_doc("Sales Order", name)
	# Per-line reserved totals: there can be multiple SREs per SO Item.
	reserved_by_detail: dict[str, float] = {}
	for row in frappe.db.sql(
		"""
		SELECT from_voucher_detail_no, SUM(reserved_qty) AS reserved
		FROM `tabStock Reservation Entry`
		WHERE voucher_type = 'Sales Order'
		  AND voucher_no = %(name)s
		  AND docstatus = 1
		GROUP BY from_voucher_detail_no
		""",
		{"name": name},
		as_dict=True,
	):
		if row.get("from_voucher_detail_no"):
			reserved_by_detail[row["from_voucher_detail_no"]] = flt(row["reserved"])
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
		"total_taxes_and_charges": flt(doc.total_taxes_and_charges),
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
				"name": it.name,
				"item_code": it.item_code,
				"warehouse": it.warehouse,
				"qty_to_reserve": flt(it.stock_qty) or flt(it.qty),
				"from_voucher_no": so.name,
				"from_voucher_detail_no": it.name,
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
		cleaned.append(
			{
				"item_code": code,
				"qty": qty,
				"rate": flt(row.get("rate")),
				"uom": row.get("uom") or None,
				"warehouse": wh,
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
	price_list = _resolve_price_list(customer)
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
	_apply_tax_template(doc, _resolve_tax_template(company, customer))
	doc.insert(ignore_permissions=False)

	reservation_errors: list[dict] = []
	if int(auto_submit or 0):
		doc.submit()
		if sre_enabled:
			reservation_errors = _reserve_for_sales_order(doc.name)

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
	doc.submit()
	reservation_errors: list[dict] = []
	if _company_stock_reservation_enabled(doc.company):
		reservation_errors = _reserve_for_sales_order(doc.name)
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
