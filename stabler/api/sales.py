"""Sales module — Customers, Sales Invoices, AR aging."""

from __future__ import annotations

import json
import re

import frappe
from stabler.api._money import money_epsilon
from stabler.api.approvals import _assert_company_scope
from frappe import _
from frappe.utils import cint, flt, getdate, today

from stabler.api._common import _assert_can_read, _assert_can_write, _require_company, _validate_money_overrides, check_concurrency
from stabler.api._sales_margin import attach_margins
from stabler.api.organization import module_map_for
from stabler.stabler.customer_hierarchy import (
	ERR_ALLOC_EMPTY,
	ERR_ALLOC_EXCEEDS,
	ERR_ALLOC_NONPOSITIVE,
	ERR_ALLOC_UNKNOWN_INVOICE,
	ERR_XFER_EMPTY,
	ERR_XFER_EXCEEDS,
	ERR_XFER_NONPOSITIVE,
	ERR_XFER_UNKNOWN_CHILD,
	children_balance_map,
	cumulative_balance,
	group_allocations_by_party,
	validate_bulk_allocations,
	validate_transfers,
)


def _has_parent_field() -> bool:
	"""True when the customer parent/child hierarchy Custom Field exists on this
	site. Every read of custom_parent_customer is guarded by this so the shared
	app stays safe on tenants that never ran the v44 patch."""
	return frappe.db.has_column("Customer", "custom_parent_customer")


def _has_job_status_field() -> bool:
	return frappe.db.has_column("Customer", "custom_job_status")


def _validate_agreement(company: str, customer: str, agreement: str | None) -> str | None:
	"""Validate an optional native Contract link for a company-scoped sale."""
	if not agreement:
		return None
	if not module_map_for(company).get("agreements"):
		frappe.throw(_("Agreement management is not enabled for {0}.").format(company), frappe.PermissionError)
	if not frappe.db.exists("Contract", agreement):
		frappe.throw(_("Unknown agreement: {0}").format(agreement))
	contract_customer = frappe.db.get_value("Contract", agreement, "party_name")
	if contract_customer and contract_customer != customer:
		frappe.throw(_("Agreement {0} belongs to another customer.").format(agreement), frappe.ValidationError)
	if not frappe.has_permission("Contract", "read", agreement):
		frappe.throw(_("You are not permitted to view this agreement."), frappe.PermissionError)
	return agreement


def _gl_balances_for_parties(company: str, parties: list[str]) -> dict:
	"""{customer: {balance_base, balance_acc, account_currency}} from GL Entry.

	Same signed convention as list_customers_with_balances (positive = owes us).
	Empty parties → {}."""
	if not parties:
		return {}
	params: dict = {"company": company}
	placeholders = []
	for i, name in enumerate(parties):
		key = f"p{i}"
		params[key] = name
		placeholders.append(f"%({key})s")
	rows = frappe.db.sql(
		f"""
		SELECT
		  party,
		  SUM(debit - credit) AS balance_base,
		  SUM(debit_in_account_currency - credit_in_account_currency) AS balance_acc,
		  MAX(account_currency) AS account_currency
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND party_type = 'Customer'
		  AND is_cancelled = 0
		  AND party IN ({", ".join(placeholders)})
		GROUP BY party
		""",
		params,
		as_dict=True,
	)
	return {
		r["party"]: {
			"balance_base": flt(r["balance_base"]),
			"balance_acc": flt(r["balance_acc"]),
			"account_currency": r["account_currency"],
		}
		for r in rows
	}


def _apply_hierarchy_fields(doc, parent_customer, job_status) -> None:
	"""Set the optional hierarchy fields on a Customer doc, guarded by column
	presence. The Customer.validate hook (customer_hooks.validate_hierarchy)
	enforces the single-level rules on save. `None` means "leave unchanged"; ""
	clears the value."""
	if parent_customer is not None and _has_parent_field():
		parent_customer = (parent_customer or "").strip()
		if parent_customer and not frappe.db.exists("Customer", parent_customer):
			frappe.throw(_("The selected parent customer does not exist."))
		doc.custom_parent_customer = parent_customer or None
	if job_status is not None and _has_job_status_field():
		doc.custom_job_status = (job_status or "").strip() or None


_BOILERPLATE_RE = re.compile(
    r"^Amount [A-Z]{3} \d|received from|paid to|New Payment Entry",
    re.IGNORECASE,
)


def _build_display_remark(remarks: str, against_vouchers: list) -> str:
    if against_vouchers and (not remarks or _BOILERPLATE_RE.search(remarks)):
        shown = against_vouchers[:3]
        rest = len(against_vouchers) - 3
        text = "against " + ", ".join(shown)
        if rest > 0:
            text += f" +{rest}"
        return text
    if remarks:
        return remarks.split("\n")[0].strip()
    if against_vouchers:
        return "against " + against_vouchers[0]
    return ""


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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Customer", "read"):
		frappe.throw(_("You are not permitted to view customers."), frappe.PermissionError)
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
def list_agreements(company: str, customer: str | None = None, search: str = "", limit: int = 100):
	"""List readable native Contracts for agreement-aware sales forms."""
	_require_company(company)
	_assert_company_scope(company)
	if not module_map_for(company).get("agreements"):
		frappe.throw(_("Agreement management is not enabled for {0}.").format(company), frappe.PermissionError)
	if not frappe.has_permission("Contract", "read"):
		frappe.throw(_("You are not permitted to view agreements."), frappe.PermissionError)
	has_agreement_no = frappe.db.has_column("Contract", "custom_agreement_no")
	agreement_no_expr = "COALESCE(custom_agreement_no, name)" if has_agreement_no else "name"
	conditions = ["party_type = 'Customer'"]
	params: dict = {"limit": min(max(int(limit), 1), 100)}
	if customer:
		conditions.append("party_name = %(customer)s")
		params["customer"] = customer
	if search:
		agreement_search = " OR custom_agreement_no LIKE %(search)s" if has_agreement_no else ""
		conditions.append(f"(name LIKE %(search)s{agreement_search})")
		params["search"] = f"%{search}%"
	return frappe.db.sql(
		f"""
		SELECT name, party_name, status, start_date, end_date,
		       {agreement_no_expr} AS agreement_no
		FROM `tabContract`
		WHERE {' AND '.join(conditions)}
		ORDER BY agreement_no ASC
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Customer", "read"):
		frappe.throw(_("You are not permitted to view customers."), frappe.PermissionError)
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
def get_currency_exchange_rate(from_currency: str, to_currency: str, date: str | None = None) -> dict:
	"""Return exchange rate: 1 from_currency = N to_currency.

	Fetches from CBU (Central Bank of Uzbekistan) cbu.uz for pairs involving UZS.
	Falls back to ERPNext Currency Exchange for cross rates.
	"""
	if from_currency == to_currency:
		return {"exchange_rate": 1.0}

	def _cbu_uzs_rate(ccy: str, date_iso: str | None) -> float | None:
		"""Return UZS per 1 unit of ccy from cbu.uz, or None on failure."""
		import requests
		try:
			if date_iso:
				from datetime import datetime
				d = datetime.strptime(date_iso, "%Y-%m-%d")
				url = f"https://cbu.uz/uz/arkhiv-kursov-valyut/json/{ccy}/{d.strftime('%d.%m.%Y')}/"
			else:
				url = f"https://cbu.uz/uz/arkhiv-kursov-valyut/json/{ccy}/"
			resp = requests.get(url, timeout=5)
			resp.raise_for_status()
			data = resp.json()
			if data and isinstance(data, list):
				row = data[0]
				return float(row["Rate"]) / max(float(row.get("Nominal") or 1), 1)
		except Exception as exc:
			frappe.log_error(f"CBU rate fetch failed for {ccy}: {exc}", "CBU Exchange Rate")
		return None

	if from_currency == "UZS":
		# 1 UZS = ? to_currency → invert CBU rate for to_currency
		uzs_per_to = _cbu_uzs_rate(to_currency, date)
		if uzs_per_to and uzs_per_to > 0:
			return {"exchange_rate": 1.0 / uzs_per_to}
	elif to_currency == "UZS":
		# 1 from_currency = ? UZS → direct CBU rate
		rate = _cbu_uzs_rate(from_currency, date)
		if rate:
			return {"exchange_rate": rate}
	else:
		# Cross rate: from → UZS → to
		uzs_per_from = _cbu_uzs_rate(from_currency, date)
		uzs_per_to = _cbu_uzs_rate(to_currency, date)
		if uzs_per_from and uzs_per_to and uzs_per_to > 0:
			return {"exchange_rate": uzs_per_from / uzs_per_to}

	# Fallback: ERPNext Currency Exchange doctype
	try:
		from frappe.utils import nowdate
		from erpnext.setup.utils import get_exchange_rate  # type: ignore[import]
		rate = get_exchange_rate(from_currency, to_currency, date or nowdate()) or 1.0
		return {"exchange_rate": float(rate)}
	except Exception:
		pass

	return {"exchange_rate": 1.0}


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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Customer", "read"):
		frappe.throw(_("You are not permitted to view customers."), frappe.PermissionError)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	has_parent_field = _has_parent_field()
	# Column is optional across tenants — select it only when it exists, else NULL.
	parent_select = "c.custom_parent_customer" if has_parent_field else "NULL"
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
		  {parent_select} AS parent_customer,
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
		r["parent_customer"] = r.get("parent_customer") or None
	if cint(only_with_balance):
		rows = [r for r in rows if flt(r["balance_base"]) != 0]
	# has_hierarchy drives the frontend tree/flat auto-detect. True when ANY
	# customer on this site carries a parent (independent of search/pagination),
	# so the toggle appears even while a filtered page shows no parents.
	has_hierarchy = bool(
		has_parent_field
		and frappe.db.exists("Customer", {"custom_parent_customer": ["!=", ""]})
	)
	return {
		"rows": rows,
		"company_currency": company_currency,
		"has_hierarchy": has_hierarchy,
	}


@frappe.whitelist()
def customer_children_balance_map(company: str):
	"""{parent_name: cumulative children balance} for the whole company.

	Server-side, GL-accurate (same GL Entry party source as the customer list),
	so parent rollups stay correct regardless of the list's search/pagination.
	Returns two maps — base currency and account currency — plus company_currency.
	No-op ({} maps) on tenants without the hierarchy field."""
	_require_company(company)
	_assert_company_scope(company)
	if not frappe.has_permission("Customer", "read"):
		frappe.throw(_("You are not permitted to view customers."), frappe.PermissionError)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	if not _has_parent_field():
		return {"base": {}, "acc": {}, "company_currency": company_currency}

	child_rows = frappe.db.sql(
		"""
		SELECT
		  c.name AS name,
		  c.custom_parent_customer AS parent_customer,
		  COALESCE(g.balance_base, 0) AS balance_base,
		  COALESCE(g.balance_acc, 0) AS balance_acc
		FROM `tabCustomer` c
		LEFT JOIN (
		  SELECT
		    party,
		    SUM(debit - credit) AS balance_base,
		    SUM(debit_in_account_currency - credit_in_account_currency) AS balance_acc
		  FROM `tabGL Entry`
		  WHERE company = %(company)s
		    AND party_type = 'Customer'
		    AND is_cancelled = 0
		  GROUP BY party
		) g ON g.party = c.name
		WHERE c.disabled = 0
		  AND c.custom_parent_customer IS NOT NULL
		  AND c.custom_parent_customer != ''
		""",
		{"company": company},
		as_dict=True,
	)
	for r in child_rows:
		r["balance_base"] = flt(r["balance_base"])
		r["balance_acc"] = flt(r["balance_acc"])
	base_map = children_balance_map(child_rows, balance_key="balance_base")
	acc_map = children_balance_map(child_rows, balance_key="balance_acc")
	return {"base": base_map, "acc": acc_map, "company_currency": company_currency}


# ===========================================================================
# Parent consolidation node — phase 2 (plan §2 K2)
# ---------------------------------------------------------------------------
# A parent never carries new transactions; its children do. These endpoints let
# the operator (1) take one bulk payment on the parent and split it into per-
# child Payment Entries, and (2) reallocate legacy unallocated advances that
# were historically booked directly on the parent down to its children.
# All hierarchy math is delegated to the pure customer_hierarchy module.
# ===========================================================================

_ALLOC_MESSAGES = {
	ERR_ALLOC_EMPTY: lambda: _("Enter at least one allocation amount."),
	ERR_ALLOC_NONPOSITIVE: lambda: _("Allocation amounts must be greater than zero."),
	ERR_ALLOC_UNKNOWN_INVOICE: lambda: _(
		"An allocated invoice does not belong to this customer chain."
	),
	ERR_ALLOC_EXCEEDS: lambda: _("An allocation exceeds the invoice's outstanding amount."),
}

_XFER_MESSAGES = {
	ERR_XFER_EMPTY: lambda: _("Enter at least one transfer amount."),
	ERR_XFER_NONPOSITIVE: lambda: _("Transfer amounts must be greater than zero."),
	ERR_XFER_UNKNOWN_CHILD: lambda: _(
		"A selected location does not belong to this customer chain."
	),
	ERR_XFER_EXCEEDS: lambda: _("Transfers exceed the payment's unallocated amount."),
}


def _chain_children(parent: str) -> list[str]:
	"""Active child customer names under `parent`. Empty when the hierarchy field
	is absent (shared-bench safety) — the caller then treats the parent as a plain
	customer with no consolidation behaviour."""
	if not _has_parent_field():
		return []
	return frappe.db.get_all(
		"Customer",
		filters={"custom_parent_customer": parent, "disabled": 0},
		pluck="name",
	)


def _mode_of_payment_account(company: str, mode_of_payment: str) -> str:
	"""Resolve the cash/bank Account for a Mode of Payment in this company.

	Mirrors stabler.api.pos._payment_account — the Mode of Payment Account child
	table carries one default_account per company."""
	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode_of_payment, "company": company},
		"default_account",
	)
	if not account:
		frappe.throw(
			_("Payment mode {0} has no account configured for this company.").format(mode_of_payment),
			frappe.ValidationError,
		)
	return account


def _parent_open_invoice_index(company: str, parent: str) -> dict:
	"""Open (submitted, outstanding>0) Sales Invoices for a parent's chain.

	Surfaces both the children's invoices and any legacy invoices booked directly
	on the parent. Returns per-invoice maps keyed by invoice name plus an ordered
	(oldest-first) row list ready for the UI grid. Each invoice's `party` is its
	real GL customer (child, or the parent for legacy rows) — that is the key the
	bulk-payment split groups on."""
	children = _chain_children(parent)
	parties = [*children, parent]
	has_child_ref = frappe.db.has_column("Sales Invoice", "custom_child_reference")
	child_ref_select = "custom_child_reference" if has_child_ref else "NULL AS custom_child_reference"
	placeholders = []
	params: dict = {"company": company, "today": today()}
	for i, name in enumerate(parties):
		key = f"pt{i}"
		params[key] = name
		placeholders.append(f"%({key})s")
	rows = frappe.db.sql(
		f"""
		SELECT name, customer, customer_name, {child_ref_select},
		       posting_date, due_date, grand_total, outstanding_amount, currency
		FROM `tabSales Invoice`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		  AND customer IN ({", ".join(placeholders)})
		ORDER BY posting_date ASC, name ASC
		""",
		params,
		as_dict=True,
	)
	party_map: dict[str, str] = {}
	outstanding_map: dict[str, float] = {}
	grand_total_map: dict[str, float] = {}
	currency_map: dict[str, str] = {}
	out_rows: list[dict] = []
	for r in rows:
		inv = r["name"]
		party_map[inv] = r["customer"]
		outstanding_map[inv] = flt(r["outstanding_amount"])
		grand_total_map[inv] = flt(r["grand_total"])
		currency_map[inv] = r["currency"]
		is_legacy = r["customer"] == parent
		days_overdue = 0
		if r["due_date"]:
			days_overdue = max(0, (getdate(today()) - getdate(r["due_date"])).days)
		out_rows.append({
			"invoice": inv,
			"party": r["customer"],
			# Display the legacy child reference when the invoice sits on the parent,
			# otherwise the child customer's own name.
			"child": r["customer"],
			"child_name": (r.get("custom_child_reference") or r["customer_name"]) if is_legacy else r["customer_name"],
			"posting_date": str(r["posting_date"]) if r["posting_date"] else None,
			"due_date": str(r["due_date"]) if r["due_date"] else None,
			"grand_total": flt(r["grand_total"]),
			"outstanding": flt(r["outstanding_amount"]),
			"currency": r["currency"],
			"days_overdue": days_overdue,
			"is_legacy": is_legacy,
		})
	return {
		"rows": out_rows,
		"party_map": party_map,
		"outstanding_map": outstanding_map,
		"grand_total_map": grand_total_map,
		"currency_map": currency_map,
	}


@frappe.whitelist()
def parent_open_invoices(company: str, parent: str):
	"""Open Sales Invoices across a parent's chain, oldest first, for the parent
	bulk-payment grid."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Customer", "read"):
		frappe.throw(_("You are not permitted to view customers."), frappe.PermissionError)
	if not parent or not frappe.db.exists("Customer", parent):
		frappe.throw(_("Unknown customer: {0}").format(parent or ""), frappe.DoesNotExistError)
	_assert_can_read("Customer", parent)
	idx = _parent_open_invoice_index(company, parent)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
	return {
		"parent": parent,
		"parent_name": frappe.db.get_value("Customer", parent, "customer_name") or parent,
		"rows": idx["rows"],
		"total_outstanding": sum(r["outstanding"] for r in idx["rows"]),
		"company_currency": company_currency,
	}


@frappe.whitelist()
def create_parent_bulk_payment(
	company: str,
	parent: str,
	mode_of_payment: str,
	payment_date: str,
	reference_no: str | None = None,
	allocations=None,
):
	"""Split one bulk payment on the parent into one submitted Payment Entry per
	child party.

	`allocations` = [{invoice, amount}]. Each open invoice already belongs to a
	real GL party (a child, or the parent for legacy rows). We validate the grid,
	group it by that party, and create one Receive Payment Entry per party via the
	shared money.create_payment_entry path — so FX handling, maker-checker
	approvals, GL logging and request-scoped rollback all behave exactly like a
	normal single-customer payment. Any failure aborts the whole request (Frappe
	wraps it in one transaction), so the split is all-or-nothing."""
	from stabler.api import money as _money
	from stabler.api._accounts import resolve_party_account

	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not parent or not frappe.db.exists("Customer", parent):
		frappe.throw(_("Unknown customer: {0}").format(parent or ""), frappe.DoesNotExistError)
	if not frappe.has_permission("Payment Entry", "create"):
		frappe.throw(_("You are not permitted to record payments."), frappe.PermissionError)
	if not mode_of_payment:
		frappe.throw(_("Select a payment mode."), frappe.ValidationError)

	if isinstance(allocations, str):
		allocations = frappe.parse_json(allocations) or []
	allocations = [
		{"invoice": (r or {}).get("invoice"), "amount": flt((r or {}).get("amount"))}
		for r in (allocations or [])
		if isinstance(r, dict)
	]

	idx = _parent_open_invoice_index(company, parent)
	code = validate_bulk_allocations(allocations, idx["party_map"], idx["outstanding_map"])
	if code:
		frappe.throw(_ALLOC_MESSAGES[code]())

	bank_account = _mode_of_payment_account(company, mode_of_payment)
	bank_currency = frappe.db.get_value("Account", bank_account, "account_currency") or (
		frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	)
	groups = group_allocations_by_party(allocations, idx["party_map"])

	created: list[dict] = []
	for party, party_allocs in groups.items():
		currencies = {idx["currency_map"][a["invoice"]] for a in party_allocs}
		if len(currencies) > 1:
			frappe.throw(
				_("{0} has invoices in more than one currency — record those payments separately.").format(
					frappe.db.get_value("Customer", party, "customer_name") or party
				),
				frappe.ValidationError,
			)
		ccy = currencies.pop()
		paid_from = resolve_party_account("Customer", party, company, ccy)
		total = round(sum(a["amount"] for a in party_allocs), 2)
		references = [
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": a["invoice"],
				"total_amount": idx["grand_total_map"].get(a["invoice"], 0.0),
				"outstanding_amount": idx["outstanding_map"].get(a["invoice"], 0.0),
				"allocated_amount": a["amount"],
			}
			for a in party_allocs
		]
		exchange_rate = None
		if ccy != bank_currency:
			exchange_rate = _money.get_exchange_rate_for_currencies(ccy, bank_currency, payment_date)
		res = _money.create_payment_entry(
			company=company,
			posting_date=payment_date,
			payment_type="Receive",
			party_type="Customer",
			party=party,
			paid_from=paid_from,
			paid_to=bank_account,
			paid_amount=total,
			mode_of_payment=mode_of_payment,
			reference_no=reference_no or None,
			reference_date=payment_date,
			references=references,
			exchange_rate=exchange_rate,
			submit=1,
		)
		created.append({
			"child": party,
			"child_name": frappe.db.get_value("Customer", party, "customer_name") or party,
			"payment_entry": res.get("name"),
			"amount": total,
			"currency": ccy,
			"pending_approval": bool(res.get("pending_approval")),
		})

	return {"parent": parent, "count": len(created), "created": created}


@frappe.whitelist()
def parent_unallocated_payments(company: str, parent: str):
	"""Submitted Payment Entries booked directly on the parent that still carry an
	unallocated balance — the legacy advances that need reallocating to children."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not frappe.has_permission("Customer", "read"):
		frappe.throw(_("You are not permitted to view customers."), frappe.PermissionError)
	if not parent or not frappe.db.exists("Customer", parent):
		frappe.throw(_("Unknown customer: {0}").format(parent or ""), frappe.DoesNotExistError)
	_assert_can_read("Customer", parent)
	rows = frappe.db.sql(
		"""
		SELECT name, posting_date, paid_amount, unallocated_amount, mode_of_payment,
		       paid_from_account_currency, paid_to_account_currency
		FROM `tabPayment Entry`
		WHERE company = %(company)s
		  AND party_type = 'Customer' AND party = %(parent)s
		  AND docstatus = 1
		  AND unallocated_amount > 0
		ORDER BY posting_date ASC, name ASC
		""",
		{"company": company, "parent": parent},
		as_dict=True,
	)
	children = frappe.db.sql(
		"""
		SELECT c.name AS name, c.customer_name AS customer_name
		FROM `tabCustomer` c
		WHERE c.custom_parent_customer = %(parent)s AND c.disabled = 0
		ORDER BY c.customer_name ASC
		""",
		{"parent": parent},
		as_dict=True,
	) if _has_parent_field() else []
	return {
		"parent": parent,
		"parent_name": frappe.db.get_value("Customer", parent, "customer_name") or parent,
		"rows": [
			{
				"name": r["name"],
				"posting_date": str(r["posting_date"]) if r["posting_date"] else None,
				"paid_amount": flt(r["paid_amount"]),
				"unallocated_amount": flt(r["unallocated_amount"]),
				"mode_of_payment": r["mode_of_payment"] or None,
				"currency": r["paid_from_account_currency"] or r["paid_to_account_currency"] or None,
			}
			for r in rows
		],
		"children": children,
	}


def _assert_reallocation_role() -> None:
	"""Reallocation moves receivable credit between parties — gate it to finance
	roles. This is the backend enforcement; the SPA also hides the action."""
	roles = set(frappe.get_roles())
	if not ({"Accounts Manager", "System Manager"} & roles):
		frappe.throw(
			_("Only Accounts Managers can reallocate a payment."), frappe.PermissionError
		)


@frappe.whitelist()
def reallocate_parent_payment(company: str, payment_entry: str, transfers=None):
	"""Move unallocated credit from a legacy parent Payment Entry down to children
	via ONE submitted Journal Entry.

	The source Payment Entry is deliberately left untouched (no cancel/amend) so
	the original audit trail stays intact — the reallocation is a fresh JE that
	debits the parent's receivable (reducing its advance credit) and credits each
	child's receivable (giving them that credit). The JE user_remark links back to
	the source PE; nothing is written onto the PE itself."""
	from stabler.api import money as _money

	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_assert_reallocation_role()
	if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
		frappe.throw(_("Unknown Payment Entry: {0}").format(payment_entry or ""), frappe.DoesNotExistError)
	pe = frappe.db.get_value(
		"Payment Entry",
		payment_entry,
		["company", "party_type", "party", "docstatus", "unallocated_amount"],
		as_dict=True,
	)
	if pe.company != company:
		frappe.throw(_("Payment belongs to a different company."), frappe.PermissionError)
	if pe.party_type != "Customer" or pe.docstatus != 1:
		frappe.throw(_("Only submitted customer payments can be reallocated."), frappe.ValidationError)
	parent = pe.party

	if isinstance(transfers, str):
		transfers = frappe.parse_json(transfers) or []
	transfers = [
		{"child": (r or {}).get("child"), "amount": flt((r or {}).get("amount"))}
		for r in (transfers or [])
		if isinstance(r, dict)
	]

	children = set(_chain_children(parent))
	code = validate_transfers(transfers, flt(pe.unallocated_amount), children)
	if code:
		frappe.throw(_XFER_MESSAGES[code]())

	# Per plan §2 K2 the whole chain settles against the company's default
	# receivable account; fall back to the parent's resolved party account.
	receivable = frappe.get_cached_value("Company", company, "default_receivable_account")
	if not receivable:
		from erpnext.accounts.party import get_party_account

		receivable = get_party_account("Customer", party=parent, company=company)
	if not receivable:
		frappe.throw(_("No default receivable account is configured for this company."))

	non_zero = [t for t in transfers if flt(t["amount"]) > 0]
	total = round(sum(flt(t["amount"]) for t in non_zero), 2)
	remark = _("Reallocation of unallocated advance from {0}").format(payment_entry)
	accounts = [
		{"account": receivable, "party_type": "Customer", "party": parent, "debit": total, "credit": 0},
	]
	for t in non_zero:
		accounts.append({
			"account": receivable,
			"party_type": "Customer",
			"party": t["child"],
			"debit": 0,
			"credit": round(flt(t["amount"]), 2),
		})

	je = _money.create_journal_entry(
		company=company,
		posting_date=today(),
		accounts=accounts,
		user_remark=remark,
	)
	_money.submit_journal_entry(je["name"])
	return {"journal_entry": je["name"], "parent": parent, "source_payment": payment_entry, "total": total}


@frappe.whitelist()
def customer_ledger(
	company: str,
	customer: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 1000,
	include_children: bool | str = False,
):
	"""Trial-balance-style ledger for a single customer or parent+children in `company`."""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")
	limit = max(1, min(5000, int(limit)))

	from_d = getdate(from_date) if from_date else None
	to_d = getdate(to_date) if to_date else None

	incl_kids = frappe.parse_json(include_children) if isinstance(include_children, str) else bool(include_children)

	has_parent_field = _has_parent_field()
	children = []
	if has_parent_field:
		children = frappe.db.sql(
			"""
			SELECT c.name, c.customer_name
			FROM `tabCustomer` c
			WHERE c.custom_parent_customer = %(name)s AND c.disabled = 0
			ORDER BY c.customer_name ASC
			""",
			{"name": customer},
			as_dict=True,
		)

	parties = [customer]
	if incl_kids and children:
		parties = [customer, *[c["name"] for c in children]]

	rows = _fetch_party_ledger_rows(
		company=company, party_type="Customer", party=parties, to_date=to_d,
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

	in_window = [r for r in rows if not _before_from(r)]
	if len(in_window) > limit:
		dropped = in_window[:-limit]  # en eski in-window satırlar
		opening_base += sum(r["debit"] - r["credit"] for r in dropped)
		opening_acc += sum(
			r["debit_in_account_currency"] - r["credit_in_account_currency"]
			for r in dropped
		)
		window = in_window[-limit:]  # en YENİ limit satır görünür
	else:
		window = in_window
	for r in window:
		r["posting_date"] = str(r["posting_date"]) if r["posting_date"] else ""

	account_currency = next(
		(r["account_currency"] for r in reversed(window) if r["account_currency"]),
		None,
	)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	return {
		"customer": customer,
		"is_parent": bool(children),
		"child_count": len(children),
		"children": children,
		"include_children": incl_kids,
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
	party: str | list[str] | tuple[str, ...],
	to_date,
):
	"""Fetch GL Entry rows for a party leg, overriding account-currency amounts
	with the source voucher's originally-entered amount."""
	upper = "AND posting_date <= %(to_date)s" if to_date else ""
	if isinstance(party, (list, tuple, set)):
		party_clause = "party IN %(parties)s"
		params = {"company": company, "party_type": party_type, "parties": tuple(party)}
	else:
		party_clause = "party = %(party)s"
		params = {"company": company, "party_type": party_type, "party": party}
	if to_date:
		params["to_date"] = to_date

	rows = frappe.db.sql(
		f"""
		SELECT name, posting_date, voucher_type, voucher_no, against, remarks,
		       against_voucher, against_voucher_type, party,
		       account, account_currency,
		       debit, credit,
		       debit_in_account_currency, credit_in_account_currency
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND party_type = %(party_type)s AND {party_clause}
		  AND is_cancelled = 0
		  {upper}
		ORDER BY posting_date ASC, creation ASC
		""",
		params,
		as_dict=True,
	)
	if not rows:
		return []

	unique_parties = {r["party"] for r in rows if r.get("party")}
	if unique_parties:
		party_names = dict(
			frappe.db.sql(
				"SELECT name, customer_name FROM `tabCustomer` WHERE name IN %(names)s",
				{"names": tuple(unique_parties)},
			)
		)
		for r in rows:
			r["party_name"] = party_names.get(r["party"], r["party"])

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

	# Aggregate by voucher: collapse multi-allocation rows (e.g. one PE paying
	# N invoices → N GL rows) into a single ledger line per voucher.
	groups: dict = {}
	group_order: list = []
	for r in rows:
		key = r["voucher_no"]
		if key not in groups:
			groups[key] = {
				"name": r["name"],
				"posting_date": r["posting_date"],
				"voucher_type": r["voucher_type"],
				"voucher_no": r["voucher_no"],
				"party": r.get("party") or "",
				"party_name": r.get("party_name") or "",
				"account": r["account"],
				"account_currency": r["account_currency"],
				"debit": 0.0,
				"credit": 0.0,
				"debit_in_account_currency": 0.0,
				"credit_in_account_currency": 0.0,
				"_against_vouchers": [],
				"_remarks": r.get("remarks") or "",
			}
			group_order.append(key)
		g = groups[key]
		g["debit"] = flt(g["debit"] + r["debit"], 2)
		g["credit"] = flt(g["credit"] + r["credit"], 2)
		g["debit_in_account_currency"] = flt(g["debit_in_account_currency"] + r["debit_in_account_currency"], 2)
		g["credit_in_account_currency"] = flt(g["credit_in_account_currency"] + r["credit_in_account_currency"], 2)
		av = r.get("against_voucher")
		if av and av not in g["_against_vouchers"]:
			g["_against_vouchers"].append(av)

	aggregated = []
	for key in group_order:
		g = groups[key]
		g["display_remark"] = _build_display_remark(g.pop("_remarks"), g.pop("_against_vouchers"))
		aggregated.append(g)
	return aggregated


@frappe.whitelist()
@frappe.whitelist()
def customer_detail(name: str, company: str, include_children: bool | str = False):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not name or not frappe.db.exists("Customer", name):
		frappe.throw(f"Unknown customer: {name}")
	_assert_can_read("Customer", name)
	doc = frappe.get_doc("Customer", name)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or ""

	incl_kids = frappe.parse_json(include_children) if isinstance(include_children, str) else bool(include_children)
	has_parent_field = _has_parent_field()
	child_names: list[str] = []
	if has_parent_field:
		child_names = frappe.db.sql_list(
			"SELECT c.name FROM `tabCustomer` c WHERE c.custom_parent_customer = %s AND c.disabled = 0",
			name,
		)

	target_customers = [name]
	if incl_kids and child_names:
		target_customers = [name, *child_names]

	# AR per transaction currency
	ar_by_currency = frappe.db.sql(
		"""
		SELECT
		  currency,
		  COALESCE(SUM(outstanding_amount), 0) AS outstanding
		FROM `tabSales Invoice`
		WHERE customer IN %(target_customers)s AND company = %(company)s
		  AND docstatus = 1
		GROUP BY currency
		HAVING SUM(outstanding_amount) <> 0
		""",
		{"target_customers": tuple(target_customers), "company": company},
		as_dict=True,
	) or []
	lifetime_row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(base_grand_total), 0) AS lifetime
		FROM `tabSales Invoice`
		WHERE customer IN %(target_customers)s AND company = %(company)s
		  AND docstatus = 1
		""",
		{"target_customers": tuple(target_customers), "company": company},
		as_dict=True,
	)
	lifetime_base = flt(lifetime_row[0]["lifetime"]) if lifetime_row else 0.0
	lifetime_by_currency = frappe.db.sql(
		"""
		SELECT currency,
		       COALESCE(SUM(grand_total), 0) AS lifetime,
		       COALESCE(SUM(base_grand_total), 0) AS lifetime_base
		FROM `tabSales Invoice`
		WHERE customer IN %(target_customers)s AND company = %(company)s
		  AND docstatus = 1
		GROUP BY currency
		HAVING SUM(grand_total) <> 0
		""",
		{"target_customers": tuple(target_customers), "company": company},
		as_dict=True,
	) or []
	if len(lifetime_by_currency) == 1:
		lifetime_amount = flt(lifetime_by_currency[0]["lifetime"])
		lifetime_currency = lifetime_by_currency[0]["currency"]
	else:
		lifetime_amount = lifetime_base
		lifetime_currency = company_currency

	overdue_by_currency = frappe.db.sql(
		"""
		SELECT currency,
		       COALESCE(SUM(outstanding_amount), 0) AS overdue,
		       COALESCE(SUM(outstanding_amount * conversion_rate), 0) AS overdue_base
		FROM `tabSales Invoice`
		WHERE customer IN %(target_customers)s AND company = %(company)s
		  AND docstatus = 1
		  AND due_date < %(today)s
		  AND outstanding_amount > 0
		GROUP BY currency
		""",
		{"target_customers": tuple(target_customers), "company": company, "today": today()},
		as_dict=True,
	) or []
	if len(overdue_by_currency) == 1:
		overdue_amount = flt(overdue_by_currency[0]["overdue"])
		overdue_currency = overdue_by_currency[0]["currency"]
	else:
		overdue_amount = sum(flt(r["overdue_base"]) for r in overdue_by_currency)
		overdue_currency = company_currency

	last_payment_row = frappe.db.sql(
		"""
		SELECT posting_date
		FROM `tabPayment Entry`
		WHERE party_type = 'Customer' AND party IN %(target_customers)s AND company = %(company)s
		  AND docstatus = 1
		ORDER BY posting_date DESC
		LIMIT 1
		""",
		{"target_customers": tuple(target_customers), "company": company},
	)
	last_payment_date = str(last_payment_row[0][0]) if last_payment_row and last_payment_row[0][0] else None

	recent = frappe.db.sql(
		"""
		SELECT name, posting_date, due_date, grand_total, outstanding_amount, status, currency, customer, customer_name
		FROM `tabSales Invoice`
		WHERE customer IN %(target_customers)s AND company = %(company)s AND docstatus = 1
		ORDER BY posting_date DESC, name DESC
		LIMIT 200
		""",
		{"target_customers": tuple(target_customers), "company": company},
		as_dict=True,
	)

	# --- Parent/child hierarchy (plan §2 K2) -------------------------------
	has_parent_field = _has_parent_field()
	has_job_field = _has_job_status_field()
	parent_customer = getattr(doc, "custom_parent_customer", None) if has_parent_field else None
	job_status = getattr(doc, "custom_job_status", None) if has_job_field else None
	parent_name = (
		frappe.db.get_value("Customer", parent_customer, "customer_name")
		if parent_customer
		else None
	)

	children: list[dict] = []
	child_names: list[str] = []
	if has_parent_field:
		job_col = ", c.custom_job_status AS job_status" if has_job_field else ", NULL AS job_status"
		child_recs = frappe.db.sql(
			f"""
			SELECT c.name AS name, c.customer_name AS customer_name{job_col}
			FROM `tabCustomer` c
			WHERE c.custom_parent_customer = %(name)s AND c.disabled = 0
			ORDER BY c.customer_name ASC
			""",
			{"name": name},
			as_dict=True,
		)
		child_names = [r["name"] for r in child_recs]
		# Own + children balances in one GL query; GL-accurate cumulative rollup.
		bal = _gl_balances_for_parties(company, [name, *child_names])
		for r in child_recs:
			b = bal.get(r["name"], {})
			children.append({
				"name": r["name"],
				"customer_name": r["customer_name"],
				"balance_base": b.get("balance_base", 0.0),
				"balance_acc": b.get("balance_acc", 0.0),
				"account_currency": b.get("account_currency"),
				"job_status": r.get("job_status") or None,
			})
	else:
		bal = _gl_balances_for_parties(company, [name])

	own = bal.get(name, {})
	own_base = own.get("balance_base", 0.0)
	own_acc = own.get("balance_acc", 0.0)
	own_acc_currency = own.get("account_currency") or company_currency
	children_base = sum(flt(c["balance_base"]) for c in children)
	children_acc = sum(flt(c["balance_acc"]) for c in children)

	return {
		"parent_customer": parent_customer or None,
		"parent_customer_name": parent_name,
		"job_status": job_status or None,
		"is_parent": bool(children),
		"children": children,
		"own_balance_base": flt(own_base),
		"own_balance_acc": flt(own_acc),
		"children_balance_base": flt(children_base),
		"children_balance_acc": flt(children_acc),
		"cumulative_balance_base": cumulative_balance(own_base, children_base),
		"cumulative_balance_acc": cumulative_balance(own_acc, children_acc),
		"account_currency": own_acc_currency,
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
		"lifetime_amount": lifetime_amount,
		"lifetime_currency": lifetime_currency,
		"overdue_amount": overdue_amount,
		"overdue_currency": overdue_currency,
		"last_payment_date": last_payment_date,
		"recent_invoices": recent,
	}


@frappe.whitelist()
def list_sales_invoices(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	customer: str | None = None,
	status: str | None = None,
	search: str | None = None,
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
	if customer:
		conds.append("customer = %(customer)s")
		params["customer"] = customer
	if search:
		conds.append("(name LIKE %(s)s OR customer LIKE %(s)s OR customer_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
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


def _edo_status(invoice_name: str) -> dict | None:
	"""Latest Didox EDO submission summary for a Sales Invoice, or None.

	Internal helper only — NOT whitelisted. It is called from
	``sales_invoice_detail`` (which already runs ``_assert_can_read`` on the
	invoice), so exposing it as its own endpoint would let any authenticated
	user enumerate Didox status for arbitrary invoices with no permission
	check. Reach EDO status through ``stabler.api.edo.didox_status`` instead.

	Guarded: the ``Didox Submission`` doctype ships with the EDO module and may
	not exist on every tenant. Return None (not an error) so the invoice form
	still loads where EDO is not installed.
	"""
	if not frappe.db.exists("DocType", "Didox Submission"):
		return None
	rows = frappe.get_all(
		"Didox Submission",
		filters={"reference_invoice": invoice_name},
		fields=["name", "doc_type", "status", "didox_doc_id", "submitted_at"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return None
	r = rows[0]
	return {
		"name": r.name,
		"doc_type": r.doc_type,
		"status": r.status,
		"didox_doc_id": r.didox_doc_id or None,
		"submitted_at": str(r.submitted_at) if r.submitted_at else None,
	}


@frappe.whitelist()
def sales_invoice_detail(name: str):
	if not name:
		frappe.throw("Invoice name is required.")
	_assert_can_read("Sales Invoice", name)
	doc = frappe.get_doc("Sales Invoice", name)
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
		"set_warehouse": doc.set_warehouse or None,
		"set_warehouse_name": (
			frappe.get_cached_value("Warehouse", doc.set_warehouse, "warehouse_name")
			if doc.set_warehouse else None
		),
		"edo": _edo_status(doc.name),
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
				"custom_dimension_mode": _dim_mode(it.item_code),
				"custom_length": flt(getattr(it, "custom_length", 0)) or None,
				"custom_width": flt(getattr(it, "custom_width", 0)) or None,
				"custom_height": flt(getattr(it, "custom_height", 0)) or None,
				"custom_pieces": flt(getattr(it, "custom_pieces", 0)) or None,
				"warehouse": getattr(it, "warehouse", None),
				"warehouse_name": (
					frappe.get_cached_value("Warehouse", it.warehouse, "warehouse_name")
					if getattr(it, "warehouse", None) else None
				),
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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

	balance_acc = frappe.db.sql(
		"""
		SELECT SUM(debit_in_account_currency - credit_in_account_currency)
		FROM `tabGL Entry`
		WHERE company = %s AND party_type = 'Customer' AND party = %s AND is_cancelled = 0
		""",
		(doc.company, doc.customer),
	)
	customer_balance = flt(balance_acc[0][0]) if balance_acc and balance_acc[0][0] is not None else 0.0

	return {
		**base,
		"company_name": company_doc.company_name,
		"company_abbr": company_doc.abbr,
		"company_tax_id": getattr(company_doc, "tax_id", "") or "",
		"discount_amount": flt(doc.discount_amount),
		"in_words": doc.in_words or "",
		"payment_terms_template": doc.payment_terms_template or "",
		"customer_balance": customer_balance,
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
	# IDOR guard: @frappe.whitelist gates method access only, not record access.
	# Without this, a user could issue (and with submit=1, post) a credit note
	# against another company's invoice by guessing its sequential name.
	_assert_can_read("Sales Invoice", sales_invoice)
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


def _validation_error(message: str) -> None:
	raise frappe.ValidationError(message)


def _normalize_direct_return_items(items) -> list[dict]:
	if isinstance(items, str):
		items = frappe.parse_json(items) or []
	if not isinstance(items, list) or not items:
		_validation_error("Return items are required.")

	out = []
	for raw in items:
		if not isinstance(raw, dict):
			_validation_error("Invalid return line.")
		item_code = (raw.get("item_code") or "").strip()
		uom = (raw.get("uom") or "").strip()
		qty = flt(raw.get("qty"))
		rate = flt(raw.get("rate"))
		if not item_code:
			_validation_error("Item code is required.")
		if qty <= 0:
			_validation_error(f"Return quantity must be greater than zero for {item_code}.")
		if rate <= 0:
			_validation_error(f"Return rate must be greater than zero for {item_code}.")
		out.append({"item_code": item_code, "qty": qty, "rate": rate, "uom": uom or None})
	if not out:
		_validation_error("Return items are required.")
	return out


@frappe.whitelist()
def create_direct_sales_return(
	company: str,
	customer: str,
	warehouse: str,
	items=None,
	posting_date: str | None = None,
):
	"""Create a submitted direct Sales Invoice credit note without return_against.

	UI quantities are entered positive; ERPNext receives negative quantities on
	the return invoice. No payment rows are created, so the submitted credit note
	leaves credit on the customer's receivable balance.
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(_("Unknown customer: {0}").format(customer or ""), frappe.DoesNotExistError)
	if not warehouse or not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(_("Unknown warehouse: {0}").format(warehouse or ""), frappe.DoesNotExistError)
	warehouse_row = frappe.db.get_value(
		"Warehouse",
		warehouse,
		["company", "is_group", "disabled"],
		as_dict=True,
	)
	if warehouse_row.company != company:
		frappe.throw(_("Warehouse belongs to a different company."), frappe.PermissionError)
	if cint(warehouse_row.is_group) or cint(warehouse_row.disabled):
		frappe.throw(_("Select an active leaf warehouse for returns."), frappe.ValidationError)

	lines = _normalize_direct_return_items(items)
	for line in lines:
		item = frappe.db.get_value(
			"Item",
			line["item_code"],
			["disabled", "is_stock_item", "is_sales_item", "stock_uom"],
			as_dict=True,
		)
		if not item:
			frappe.throw(_("Unknown item: {0}").format(line["item_code"]), frappe.DoesNotExistError)
		if cint(item.disabled) or not cint(item.is_sales_item) or not cint(item.is_stock_item):
			frappe.throw(
				_("{0} must be an enabled stock sales item.").format(line["item_code"]),
				frappe.ValidationError,
			)

	doc = frappe.new_doc("Sales Invoice")
	doc.company = company
	doc.customer = customer
	doc.is_return = 1
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	doc.posting_date = getdate(posting_date or today())
	doc.due_date = doc.posting_date
	doc.remarks = _("Direct sales return")

	for line in lines:
		row = {
			"item_code": line["item_code"],
			"qty": -abs(line["qty"]),
			"rate": line["rate"],
			"price_list_rate": line["rate"],
			"warehouse": warehouse,
		}
		if line["uom"]:
			row["uom"] = line["uom"]
		doc.append("items", row)

	doc.set_missing_values()
	doc.calculate_taxes_and_totals()
	doc.insert(ignore_permissions=False)
	doc.submit()
	return {
		"name": doc.name,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"is_return": cint(doc.is_return),
		"return_against": doc.return_against or "",
		"grand_total": flt(doc.grand_total),
		"currency": doc.currency,
		"customer": doc.customer,
		"warehouse": warehouse,
	}


def _sales_report_period_expr(granularity: str, date_field: str = "posting_date") -> str:
	if granularity == "month":
		return f"DATE_FORMAT(si.{date_field}, '%%Y-%%m')"
	if granularity == "day":
		return f"DATE_FORMAT(si.{date_field}, '%%Y-%%m-%%d')"
	raise frappe.ValidationError("Granularity must be day or month.")


def _sales_report_date_field(date_basis: str | None, *, alias: str = "") -> str:
	"""Which Sales Invoice date column the report filters/groups on. Whitelisted to
	a fixed column name (never raw user text) so it is safe to interpolate in SQL.
	Default is posting_date; 'due' switches to due_date."""
	col = "due_date" if (date_basis or "posting") == "due" else "posting_date"
	return f"{alias}.{col}" if alias else col


def _sales_report_docstatus(include_drafts, *, alias: str = "") -> str:
	"""Docstatus filter. Default = submitted only (ties to the GL). When drafts are
	included we widen to (0, 1) — the UI shows an 'unposted' banner in that case."""
	col = f"{alias}.docstatus" if alias else "docstatus"
	return f"{col} IN (0, 1)" if cint(include_drafts) else f"{col} = 1"


def _sales_report_dates(from_date: str, to_date: str) -> tuple:
	start = getdate(from_date)
	end = getdate(to_date)
	if start > end:
		frappe.throw(_("From date cannot be after To date."), frappe.ValidationError)
	return start, end


def _sii_cost_expr() -> str:
	"""Per-line COGS expression in COMPANY (base) currency: prefer the line's
	captured buying rate (incoming_rate), fall back to the item's valuation rate.
	Mirrors reports._cost_expr so margin numbers agree across the two pages."""
	if frappe.get_meta("Sales Invoice Item").has_field("incoming_rate"):
		return "COALESCE(NULLIF(sii.incoming_rate, 0), i.valuation_rate, 0)"
	return "COALESCE(i.valuation_rate, 0)"


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
	parent_customer: str | None = None,
	job_status: str | None = None,
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
	_apply_hierarchy_fields(doc, parent_customer, job_status)
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
		"parent_customer": (getattr(doc, "custom_parent_customer", None) if _has_parent_field() else None) or "",
		"job_status": (getattr(doc, "custom_job_status", None) if _has_job_status_field() else None) or "",
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
	parent_customer: str | None = None,
	job_status: str | None = None,
):
	_assert_can_write("Customer", name, "write")
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
	_apply_hierarchy_fields(doc, parent_customer, job_status)
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "customer_name": doc.customer_name}


@frappe.whitelist()
def delete_customer(name: str):
	_assert_can_write("Customer", name, "delete")
	if not frappe.db.exists("Customer", name):
		frappe.throw(f"Unknown customer: {name}")
	frappe.delete_doc("Customer", name, ignore_permissions=False)
	return {"deleted": name}


@frappe.whitelist()
def delete_sales_order(name: str, modified: str | None = None):
	"""Delete a Draft Sales Order. Raises if docstatus != 0."""
	_assert_can_read("Sales Order", name)
	check_concurrency("Sales Order", name, modified)
	doc = frappe.get_doc("Sales Order", name)
	if doc.docstatus != 0:
		frappe.throw(f"Only Draft Sales Orders can be deleted (docstatus={doc.docstatus}).")
	frappe.delete_doc("Sales Order", name, ignore_permissions=False)
	return {"deleted": name}


@frappe.whitelist()
def delete_sales_invoice(name: str, modified: str | None = None):
	"""Delete a Draft Sales Invoice. Raises if docstatus != 0."""
	_assert_can_read("Sales Invoice", name)
	check_concurrency("Sales Invoice", name, modified)
	doc = frappe.get_doc("Sales Invoice", name)
	if doc.docstatus != 0:
		frappe.throw(f"Only Draft Sales Invoices can be deleted (docstatus={doc.docstatus}).")
	frappe.delete_doc("Sales Invoice", name, ignore_permissions=False)
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
	item_overrides=None,
):
	"""Create a Draft Sales Invoice copied from a submitted Sales Order.

	`sales_order` is mandatory — Stabler enforces SO-driven sales. `item_overrides`
	is an optional list of `{so_detail|item_code, qty?, rate?}` to tweak the
	auto-mapped lines before insert. SO/so_detail linkage is preserved by
	ERPNext's `make_sales_invoice`, which is what releases stock reservations
	on SI submit.

	Stabler sells directly from the warehouse (no separate Delivery Note), so the
	SI ALWAYS carries `update_stock=1`: on submit ERPNext deducts the stock ledger
	AND releases the Sales Order reservation (marking delivery done). See
	`erpnext/.../sales_invoice.py:on_submit`.
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
	if frappe.db.has_column("Sales Invoice", "custom_agreement"):
		doc.custom_agreement = getattr(so, "custom_agreement", None)
	doc.posting_date = getdate(posting_date or today())
	if due_date:
		doc.due_date = getdate(due_date)
	# Stabler ships from the warehouse on invoice — always update stock so the SO
	# reservation is released and the stock ledger is written on submit.
	doc.update_stock = 1
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

	# update_stock=1 needs a warehouse on every stock line, else submit throws an
	# opaque core error. Surface a clear, item-named message up front instead.
	_require_warehouses_for_stock_update(doc)

	doc.insert(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"customer": doc.customer,
		"sales_order": sales_order,
	}


def _require_warehouses_for_stock_update(doc) -> None:
	"""Raise a clear i18n error if any stock line lacks a warehouse.

	A Stabler SI always submits with `update_stock=1`, which requires a warehouse
	on every stock item. Service / non-stock items are exempt.
	"""
	missing = [
		line.item_code
		for line in doc.items
		if not line.warehouse
		and frappe.get_cached_value("Item", line.item_code, "is_stock_item")
	]
	if missing:
		frappe.throw(
			_("Cannot create invoice: no warehouse set for stock item(s) {0}.").format(
				", ".join(dict.fromkeys(missing))
			)
		)


@frappe.whitelist()
def create_direct_sales_invoice(
	company: str,
	customer: str,
	items: str | list[dict],
	posting_date: str | None = None,
	due_date: str | None = None,
	set_warehouse: str | None = None,
	price_list: str | None = None,
	remarks: str | None = None,
	currency: str | None = None,
	submit_now: bool | str = False,
):
	"""Create a direct Sales Invoice without requiring a prior Sales Order."""
	_require_company(company)
	_assert_company_scope(company)
	if "MSA" not in str(company or "").upper():
		frappe.throw(
			_("Direct Sales Invoicing is only enabled for MSA. For company {0}, Sales Invoices must be created from a submitted Sales Order.").format(company),
			frappe.ValidationError,
		)
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(_("Please select a valid customer."))

	if isinstance(items, str):
		items = frappe.parse_json(items) or []

	if not items or not isinstance(items, list):
		frappe.throw(_("Please add at least one line item."))

	should_submit = frappe.parse_json(submit_now) if isinstance(submit_now, str) else bool(submit_now)

	doc = frappe.new_doc("Sales Invoice")
	doc.company = company
	doc.customer = customer
	doc.posting_date = getdate(posting_date or today())
	if due_date:
		doc.due_date = getdate(due_date)
	if set_warehouse and frappe.db.exists("Warehouse", set_warehouse):
		doc.set_warehouse = set_warehouse
	if price_list and frappe.db.exists("Price List", price_list):
		doc.selling_price_list = price_list
	if remarks:
		doc.remarks = remarks.strip()
	if currency:
		doc.currency = currency

	doc.update_stock = 1  # Stabler direct sales deduct stock immediately

	for it in (items or []):
		if not isinstance(it, dict):
			continue
		item_code = it.get("item_code")
		if not item_code or not frappe.db.exists("Item", item_code):
			continue
		qty = flt(it.get("qty") or 1)
		rate = flt(it.get("rate") or 0)
		wh = it.get("warehouse") or doc.set_warehouse
		row = {
			"item_code": item_code,
			"qty": qty,
			"rate": rate,
		}
		if wh:
			row["warehouse"] = wh
		if it.get("uom"):
			row["uom"] = it.get("uom")
		if it.get("description"):
			row["description"] = it.get("description")
		doc.append("items", row)

	if not doc.items:
		frappe.throw(_("No valid line items provided."))

	doc.insert()

	if should_submit:
		doc.submit()

	return {"name": doc.name, "docstatus": doc.docstatus, "grand_total": flt(doc.grand_total)}


@frappe.whitelist()
def submit_sales_invoice(name: str, modified: str | None = None):
	"""Submit a Draft Sales Invoice (docstatus 0 → 1)."""
	from frappe.utils import add_days, getdate, today

	_assert_can_write("Sales Invoice", name, "submit")
	if not name:
		frappe.throw("Invoice name is required.")
	check_concurrency("Sales Invoice", name, modified)
	doc = frappe.get_doc("Sales Invoice", name)
	if doc.docstatus == 1:
		frappe.throw("Invoice is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Invoice is cancelled and cannot be submitted.")

	needs_save = False

	# Drafts created before the "always update stock" change may still carry
	# update_stock=0 — force it on so submit deducts stock + releases the SO
	# reservation. Persist the flip before submit so the validation sees it.
	if not doc.update_stock:
		doc.update_stock = 1
		_require_warehouses_for_stock_update(doc)
		needs_save = True

	# ERPNext's validate_posting_time() resets posting_date to today() whenever
	# set_posting_time is falsy.  If the invoice was drafted yesterday, due_date
	# ends up *before* the updated posting_date and validate throws "Due Date
	# cannot be before Posting Date" (417).
	# Fix: pre-correct due_date to effective_posting_date + 5 days before submit
	# so the payment schedule is always forward of the (possibly bumped) posting date.
	effective_posting_date = doc.posting_date if doc.set_posting_time else today()
	target_due_date = add_days(effective_posting_date, 5)
	if getdate(doc.due_date) < getdate(target_due_date):
		doc.due_date = target_due_date
		for row in doc.get("payment_schedule") or []:
			if getdate(row.due_date) < getdate(target_due_date):
				row.due_date = target_due_date
		needs_save = True

	if needs_save:
		doc.save()
		doc.reload()

	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_sales_invoice(name: str, modified: str | None = None):
	"""Cancel a Submitted Sales Invoice (docstatus 1 → 2)."""
	_assert_can_write("Sales Invoice", name, "cancel")
	if not name:
		frappe.throw("Invoice name is required.")
	check_concurrency("Sales Invoice", name, modified)
	doc = frappe.get_doc("Sales Invoice", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted invoices can be cancelled.")

	# ERPNext's on_cancel calls check_sales_order_on_hold_or_close which reads
	# SO.status from DB and throws when status == "Closed".  SOs may be Closed
	# because our on_si_submit hook auto-closed them when this SI was submitted.
	# Temporarily reset those SOs to "To Deliver and Bill" so the check passes;
	# ERPNext's own on_cancel → update_prevdoc_status() recalculates status
	# correctly once per_billed drops (SI cancelled).
	# We only unblock "Closed" — "On Hold" is set manually and should still block.
	so_names = {item.sales_order for item in doc.items if item.sales_order}
	closed_sos = [
		so for so in so_names
		if frappe.db.get_value("Sales Order", so, "status") == "Closed"
	]
	for so in closed_sos:
		frappe.db.set_value(
			"Sales Order", so, "status", "To Deliver and Bill", update_modified=False
		)

	# skip creation-time validators (e.g. so_dn_required) that fire on cancel too
	doc.flags.ignore_validate = True
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
def list_price_lists(selling_only: int = 1, buying_only: int = 0, limit: int = 200):
	"""Return enabled Price Lists. By default only selling lists (selling=1).
	Pass buying_only=1 to get buying price lists instead."""
	conds = ["enabled = 1"]
	if int(buying_only):
		conds.append("buying = 1")
	elif int(selling_only):
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
	if not hit and price_list != "Standard Selling":
		hit = _lookup_item_price(item_code, "Standard Selling", uom=uom)

	if not hit:
		std_rate = frappe.db.get_value("Item", item_code, "standard_rate") or 0.0
		pl_currency = frappe.db.get_value("Price List", price_list, "currency") or "UZS"
		return {
			"price_list": price_list,
			"price_list_rate": flt(std_rate),
			"currency": pl_currency,
			"unresolved": std_rate <= 0,
			"reason": "standard_rate" if std_rate > 0 else "no_item_price",
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
		"modified": str(doc.modified),
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
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
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
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
		line.custom_line_note = row.get("custom_line_note") or None
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
def update_quotation(
	name: str,
	items,
	customer: str | None = None,
	transaction_date: str | None = None,
	valid_till: str | None = None,
	remarks: str | None = None,
	modified: str | None = None,
):
	"""Update an existing Draft Quotation in-place.

	Only docstatus=0 (Draft) quotations may be edited.
	"""
	_assert_can_write("Quotation", name, "write")
	if not name:
		frappe.throw("Quotation name is required.")
	check_concurrency("Quotation", name, modified)
	doc = frappe.get_doc("Quotation", name)
	if doc.docstatus != 0:
		frappe.throw("Only draft quotations can be edited.")

	if customer and customer != doc.party_name:
		if not frappe.db.exists("Customer", customer):
			frappe.throw(f"Unknown customer: {customer}")
		doc.party_name = customer

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
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
			}
		)

	doc.transaction_date = getdate(transaction_date or doc.transaction_date)
	if valid_till:
		doc.valid_till = getdate(valid_till)
	else:
		doc.valid_till = None

	if remarks is not None:
		doc.terms = remarks.strip()

	doc.set("items", [])
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.custom_line_note = row.get("custom_line_note") or None
		line.qty = row["qty"]
		if row["rate"]:
			line.rate = row["rate"]
		if row["uom"]:
			line.uom = row["uom"]

	doc.save(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"customer": doc.party_name,
	}


@frappe.whitelist()
def delete_quotation(name: str, modified: str | None = None):
	"""Delete a Draft Quotation."""
	_assert_can_write("Quotation", name, "delete")
	if not name:
		frappe.throw("Quotation name is required.")
	check_concurrency("Quotation", name, modified)
	doc = frappe.get_doc("Quotation", name)
	if doc.docstatus != 0:
		frappe.throw("Only draft quotations can be deleted.")
	doc.delete()
	return {"name": name}


@frappe.whitelist()
def submit_quotation(name: str, modified: str | None = None):

	_assert_can_write("Quotation", name, "submit")
	if not name:
		frappe.throw("Quotation name is required.")
	check_concurrency("Quotation", name, modified)
	doc = frappe.get_doc("Quotation", name)
	if doc.docstatus == 1:
		frappe.throw("Quotation is already submitted.")
	if doc.docstatus == 2:
		frappe.throw("Quotation is cancelled and cannot be submitted.")
	doc.submit()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def cancel_quotation(name: str, modified: str | None = None):
	_assert_can_write("Quotation", name, "cancel")
	if not name:
		frappe.throw("Quotation name is required.")
	check_concurrency("Quotation", name, modified)
	doc = frappe.get_doc("Quotation", name)
	if doc.docstatus != 1:
		frappe.throw("Only submitted quotations can be cancelled.")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


# ─────────────────────────── Sales Orders ───────────────────────────

@frappe.whitelist()
@frappe.whitelist()
def list_sales_orders(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	customer: str | None = None,
	status: str | None = None,
	search: str | None = None,
	limit: int = 100,
	include_children: bool | str = False,
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
	if customer:
		incl_kids = frappe.parse_json(include_children) if isinstance(include_children, str) else bool(include_children)
		children = []
		if incl_kids and _has_parent_field():
			children = frappe.db.sql_list("SELECT name FROM `tabCustomer` WHERE custom_parent_customer = %s AND disabled = 0", customer)
		if children:
			conds.append("customer IN %(customers)s")
			params["customers"] = tuple([customer, *children])
		else:
			conds.append("customer = %(customer)s")
			params["customer"] = customer
	if search:
		conds.append("(name LIKE %(s)s OR customer LIKE %(s)s OR customer_name LIKE %(s)s)")
		params["s"] = f"%{search}%"
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
	_has_dim = frappe.db.has_column("Item", "custom_dimension_mode")

	def _dim_mode(code):
		if not _has_dim or not code:
			return ""
		return frappe.get_cached_value("Item", code, "custom_dimension_mode") or ""
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
		SELECT DISTINCT si.name, si.docstatus, si.status,
			si.outstanding_amount, si.grand_total, si.update_stock, si.posting_date
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.sales_order = %(name)s AND si.docstatus < 2
		""",
		{"name": name},
		as_dict=True,
	)
	return {
		"name": doc.name,
		"modified": str(doc.modified),
		"transaction_date": str(doc.transaction_date) if doc.transaction_date else None,

		"delivery_date": str(doc.delivery_date) if doc.delivery_date else None,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"company": doc.company,
		"set_warehouse": getattr(doc, "set_warehouse", None),
		"currency": doc.currency,
		"selling_price_list": getattr(doc, "selling_price_list", None),
		"custom_agreement": getattr(doc, "custom_agreement", None),
		"conversion_rate": flt(doc.conversion_rate),
		"net_total": flt(doc.net_total),
		"grand_total": flt(doc.grand_total),
		"advance_paid": flt(doc.advance_paid),
		"per_delivered": flt(doc.per_delivered),
		"per_billed": flt(doc.per_billed),
		"billing_status": doc.billing_status,
		"delivery_status": doc.delivery_status,
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
				"custom_line_note": getattr(it, "custom_line_note", None) or None,
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
def close_sales_order(name: str, modified: str | None = None):
	"""Manually close a submitted SO, releasing both reservation layers.

	1. update_status("Closed") drops the classic reserved_qty (tabBin.reserved_qty)
	   via get_reserved_qty() filtering OUT Closed SOs — no new SLE is created.
	2. Any still-open Stock Reservation Entries are cancelled (sre_list= form so
	   already-Delivered SREs are left intact).
	"""
	if not name:
		frappe.throw(_("Sales order name is required."))
	_assert_can_write("Sales Order", name, "write")
	check_concurrency("Sales Order", name, modified)
	so = frappe.get_doc("Sales Order", name)
	if so.docstatus != 1:
		frappe.throw(_("Only submitted Sales Orders can be closed."))
	if so.status in ("Closed", "On Hold"):
		frappe.throw(_("Sales Order is already {0}.").format(so.status))
	so.update_status("Closed")
	try:
		from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
			cancel_stock_reservation_entries,
		)

		open_sres = frappe.get_all(
			"Stock Reservation Entry",
			filters={
				"voucher_type": "Sales Order",
				"voucher_no": name,
				"docstatus": 1,
				"status": ["not in", ["Delivered", "Cancelled"]],
			},
			pluck="name",
		)
		if open_sres:
			cancel_stock_reservation_entries(sre_list=open_sres, notify=False)
	except Exception:
		# Swallow — the SO is already Closed; a stale SRE is preferable to
		# surfacing a confusing error to the user for a manual close action.
		pass
	return {"status": "Closed", "reservations_released": True}


@frappe.whitelist()
def reopen_sales_order(name: str, modified: str | None = None):
	"""Reopen a Closed or On Hold SO, recalculating its status from delivery/billing.

	Use when a SO was closed by mistake. ERPNext's set_status() recomputes the
	correct open status (To Deliver and Bill / To Bill / To Deliver / Completed)
	from per_delivered and per_billed, then update_reserved_qty() restores the
	classic reserved_qty contribution to tabBin.
	"""
	if not name:
		frappe.throw(_("Sales order name is required."))
	_assert_can_write("Sales Order", name, "write")
	check_concurrency("Sales Order", name, modified)
	so = frappe.get_doc("Sales Order", name)
	if so.docstatus != 1:
		frappe.throw(_("Only submitted Sales Orders can be reopened."))
	if so.status not in ("Closed", "On Hold"):
		frappe.throw(_("Sales Order is not closed or on hold."))
	so.set_status(update=True)
	so.update_reserved_qty()
	return {"status": so.status}


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


def _humanize_sales_order_cancel_error(message: str) -> str:
	match = re.search(
		r"Sales Invoice\s+(?:<a\b[^>]*>)?([^<\s]+)(?:</a>)?\s+must be deleted before cancelling this Sales Order",
		message,
	)
	if not match:
		return message
	return _("Cancel or delete Sales Invoice {0} before cancelling this Sales Order.").format(
		match.group(1)
	)


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
	crm_deal: str | None = None,
	agreement: str | None = None,
):
	"""Create a Sales Order; default behaviour is create + submit + reserve.

	`set_warehouse` is required (Stabler enforces SO-driven warehouse picking).
	Each line may override via `warehouse`. When `auto_submit` is truthy (default)
	the SO is submitted and stock reservation entries are created per line. The
	response includes `reservation_errors`; non-empty means SO submitted but some
	lines could not be fully reserved (e.g. insufficient stock).
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	if not customer:
		frappe.throw("Customer is required.")
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Unknown customer: {customer}")
	if not set_warehouse:
		frappe.throw(_("Warehouse is required for Sales Orders"))
	if not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(_("Unknown warehouse: {0}").format(set_warehouse))
	agreement = _validate_agreement(company, customer, agreement)

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
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
				"warehouse": wh,
				"conversion_factor": flt(row.get("conversion_factor")) or None,
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
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
	# Tender spine: link the winning CRM Deal (F7) when present + the field exists.
	if crm_deal and frappe.db.has_column("Sales Order", "custom_crm_deal") and frappe.db.exists("CRM Deal", crm_deal):
		doc.custom_crm_deal = crm_deal
	if agreement and frappe.db.has_column("Sales Order", "custom_agreement"):
		doc.custom_agreement = agreement

	sre_enabled = _company_stock_reservation_enabled(company)
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.custom_line_note = row.get("custom_line_note") or None
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
		# Dimensional inputs — qty is recomputed authoritatively by the
		# apply_dimensional_qty before_validate hook from these.
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))
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
def prepare_so_from_deal(deal: str) -> dict:
	"""F7 — prep a Sales Order from a won CRM Deal (the contract spine).

	CRM Deal has no line items, so we don't build the SO here. We ensure the
	deal has a linked Customer (creating it via the won-deal hand-off if needed)
	and return a prefill payload the SO form opens with. The actual SO is created
	through ``create_sales_order(..., crm_deal=deal)`` once the user adds positions.
	If a Sales Order is already linked to this deal, we return it so the caller
	can open it instead of creating a duplicate.
	"""
	from stabler.api.crm import convert_deal_to_customer

	if not frappe.db.exists("CRM Deal", deal):
		frappe.throw(_("Unknown deal: {0}").format(deal))
	if not frappe.has_permission("CRM Deal", "read", deal):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	d = frappe.get_doc("CRM Deal", deal)
	company = d.get("company") or frappe.defaults.get_user_default("Company") or (
		frappe.get_all("Company", pluck="name", limit=1) or [None]
	)[0]
	if not company:
		frappe.throw(_("No company is configured."))
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg

	# Already linked? Hand back the existing SO.
	existing = None
	if frappe.db.has_column("Sales Order", "custom_crm_deal"):
		existing = frappe.db.get_value(
			"Sales Order", {"custom_crm_deal": deal, "docstatus": ["<", 2]}, "name"
		)

	# Ensure a customer exists for the deal.
	customer = d.get("linked_customer")
	if not (customer and frappe.db.exists("Customer", customer)):
		customer = convert_deal_to_customer(deal).get("customer")
	if not customer:
		frappe.throw(_("Could not resolve a customer for this deal."))

	return {
		"deal": deal,
		"existing_so": existing,
		"customer": customer,
		"customer_name": frappe.db.get_value("Customer", customer, "customer_name") or customer,
		"company": company,
		"currency": d.get("currency") or frappe.get_cached_value("Company", company, "default_currency"),
		"deal_value": flt(d.get("deal_value")),
		"bid_value": flt(d.get("bid_value")) if frappe.db.has_column("CRM Deal", "bid_value") else 0.0,
		"tender_no": d.get("tender_no") if frappe.db.has_column("CRM Deal", "tender_no") else None,
	}


@frappe.whitelist()
def submit_sales_order(name: str, modified: str | None = None):
	_assert_can_write("Sales Order", name, "submit")
	if not name:
		frappe.throw("Sales order name is required.")
	check_concurrency("Sales Order", name, modified)
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
def update_sales_order(
	name: str,
	items,
	set_warehouse: str | None = None,
	transaction_date: str | None = None,
	delivery_date: str | None = None,
	remarks: str | None = None,
	currency: str | None = None,
	price_list: str | None = None,
	modified: str | None = None,
	agreement: str | None = None,
):
	"""Update an existing Draft Sales Order in-place.

	Only docstatus=0 (Draft) orders may be edited — submitted orders are immutable.
	Replaces item lines entirely (matching create_sales_order validation). Does NOT
	submit or create Stock Reservation Entries; those happen in submit_sales_order.
	"""
	_assert_can_write("Sales Order", name, "write")
	if not name:
		frappe.throw("Sales order name is required.")
	check_concurrency("Sales Order", name, modified)
	doc = frappe.get_doc("Sales Order", name)
	if doc.docstatus != 0:
		frappe.throw(_("Only draft sales orders can be edited."))
	agreement = _validate_agreement(doc.company, doc.customer, agreement)
	if frappe.db.has_column("Sales Order", "custom_agreement"):
		doc.custom_agreement = agreement

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw("Invalid items payload.")
	if not isinstance(items, list) or not items:
		frappe.throw("At least one item is required.")

	wh = set_warehouse or doc.set_warehouse
	if not wh:
		frappe.throw(_("Warehouse is required for Sales Orders"))
	if set_warehouse and set_warehouse != doc.set_warehouse and not frappe.db.exists("Warehouse", set_warehouse):
		frappe.throw(_("Unknown warehouse: {0}").format(set_warehouse))

	txn_date = getdate(transaction_date or doc.transaction_date)
	deliver_on = getdate(delivery_date) if delivery_date else (getdate(doc.delivery_date) if doc.delivery_date else txn_date)

	# Validate and clean item lines exactly as in create_sales_order.
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
		row_wh = (row.get("warehouse") or "").strip() or wh
		if row_wh != wh and not frappe.db.exists("Warehouse", row_wh):
			frappe.throw(f"Row {idx}: unknown warehouse '{row_wh}'.")
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
				"custom_line_note": (str(row.get("custom_line_note") or "").strip()[:500] or None),
				"warehouse": row_wh,
				"conversion_factor": flt(row.get("conversion_factor")) or None,
				"discount_percentage": disc_pct,
				"discount_amount": flt(row.get("discount_amount")),
				"custom_length": row.get("custom_length"),
				"custom_width": row.get("custom_width"),
				"custom_height": row.get("custom_height"),
				"custom_pieces": row.get("custom_pieces"),
			}
		)

	# Update header fields.
	doc.set_warehouse = wh
	doc.transaction_date = txn_date
	doc.delivery_date = deliver_on
	if remarks is not None:
		doc.terms = remarks.strip()
	if currency:
		doc.currency = currency
	resolved_pl = price_list or _resolve_price_list(doc.customer)
	if resolved_pl:
		doc.selling_price_list = resolved_pl

	# Replace item lines entirely.
	doc.set("items", [])
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.custom_line_note = row.get("custom_line_note") or None
		line.qty = row["qty"]
		line.delivery_date = deliver_on
		line.warehouse = row["warehouse"]
		rate = row["rate"]
		if not rate and resolved_pl:
			hit = _lookup_item_price(row["item_code"], resolved_pl)
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
		# Dimensional inputs — qty recomputed authoritatively by the hook.
		for _df in ("custom_length", "custom_width", "custom_height", "custom_pieces"):
			if row.get(_df) not in (None, ""):
				line.set(_df, flt(row.get(_df)))

	doc.save(ignore_permissions=False)
	return {
		"name": doc.name,
		"grand_total": flt(doc.grand_total),
		"customer": doc.customer,
		"docstatus": doc.docstatus,
		"status": doc.status,
	}


@frappe.whitelist()
def cancel_sales_order(name: str, modified: str | None = None):
	_assert_can_write("Sales Order", name, "cancel")
	if not name:
		frappe.throw("Sales order name is required.")
	check_concurrency("Sales Order", name, modified)
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
	try:
		doc.cancel()
	except frappe.ValidationError as exc:
		message = _humanize_sales_order_cancel_error(str(exc))
		if message == str(exc):
			raise
		frappe.throw(message, frappe.ValidationError)
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def clear_open_reservations(company: str):
	"""Admin: cancel all OPEN Stock Reservation Entries for a company.

	"Open" = submitted (docstatus=1), not Delivered/Cancelled. Cancels (never
	deletes) so reserved_qty is released back on tabBin. Groups by voucher and
	reuses ERPNext's cancel_stock_reservation_entries — the same path
	cancel_sales_order uses. Never aborts: per-voucher failures are collected and
	returned, matching _reserve_for_sales_order's "surface errors, don't raise"
	philosophy.
	"""
	from stabler.api.organization import _require_admin

	_require_admin()
	if not company:
		frappe.throw(_("Company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Unknown company: {0}").format(company))

	rows = frappe.get_all(
		"Stock Reservation Entry",
		filters={
			"company": company,
			"docstatus": 1,
			"status": ["not in", ["Delivered", "Cancelled"]],
		},
		fields=["name", "voucher_type", "voucher_no"],
	)

	# Group by voucher — ERPNext's helper cancels per-voucher, not per-row.
	vouchers: dict[tuple, int] = {}
	for r in rows:
		key = (r.voucher_type, r.voucher_no)
		vouchers[key] = vouchers.get(key, 0) + 1

	try:
		from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
			cancel_stock_reservation_entries,
		)
	except Exception as exc:
		frappe.throw(_("SRE module unavailable: {0}").format(exc))

	cleared, errors = 0, []
	for (vtype, vno), count in vouchers.items():
		try:
			cancel_stock_reservation_entries(voucher_type=vtype, voucher_no=vno, notify=False)
			cleared += count
		except Exception as exc:
			errors.append({"voucher": vno, "error": str(exc)})

	return {"company": company, "total": len(rows), "cleared": cleared, "errors": errors}


@frappe.whitelist()
def amend_sales_order(name: str):
	"""Create a new draft Sales Order as an amendment of a cancelled one."""
	_assert_can_write("Sales Order", name, "cancel")
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
	_assert_can_write("Sales Invoice", name, "cancel")
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
	_assert_can_read(doctype, name)
	allowed_doctypes = {"Sales Order", "Sales Invoice", "Delivery Note", "Payment Entry"}
	if doctype not in {"Sales Order", "Sales Invoice"}:
		frappe.throw("doctype must be Sales Order or Sales Invoice")
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"Unknown {doctype}: {name}")

	from frappe.desk.form.linked_with import get_linked_docs, get_linked_doctypes

	linkinfo = get_linked_doctypes(doctype)
	raw = get_linked_docs(doctype, name, linkinfo) or {}
	out: dict = {}
	for dt, payload in raw.items():
		if dt not in allowed_doctypes:
			continue
		# get_linked_docs returns {doctype: {"docs": [...], "hidden_count": N}} —
		# the row list lives under "docs", NOT the payload itself (iterating the
		# payload would walk its keys, not the documents).
		docs = (payload or {}).get("docs") or []
		rows = [
			{"name": d.get("name"), "docstatus": d.get("docstatus")}
			for d in docs
			if isinstance(d, dict) and d.get("name")
		]
		if rows:
			out[dt] = rows
	return out


@frappe.whitelist()
def reserved_stock_analysis(company: str, warehouse: str | None = None):
	"""Live Stock Reservation Entries for a company, grouped for the analyzer.

	Returns KPI headline figures plus a per-(item_code, warehouse) rollup with every
	contributing SRE nested as 'entries'.

	'Open' reservation = submitted SRE not yet Delivered/Cancelled — identical to the
	filter used by clear_open_reservations(), so the analyzer and the bulk-clear admin
	action always agree on what is currently reserved.

	Value approximation: outstanding_value = outstanding_qty × Item.valuation_rate.
	Valuation rate drifts over time and is not the SRE's original reservation value,
	so treat this as an operational estimate, not an accounting figure.

	Optional `warehouse` narrows all results (rows, groups, and KPIs) to a single
	warehouse.  The comparison is case-insensitive on MariaDB (utf8mb4_unicode_ci).
	"""
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg

	wh_clause = "AND sre.warehouse = %(warehouse)s" if warehouse else ""

	rows = frappe.db.sql(
		f"""
		SELECT
		  sre.name                                                            AS sre,
		  sre.item_code,
		  itm.item_name,
		  sre.warehouse,
		  sre.voucher_no                                                      AS sales_order,
		  so.customer,
		  so.customer_name,
		  so.transaction_date                                                 AS so_date,
		  so.creation                                                         AS so_creation,
		  so.modified                                                         AS so_modified,
		  sre.creation                                                        AS reserved_on,
		  sre.status,
		  sre.reserved_qty,
		  sre.delivered_qty,
		  (sre.reserved_qty - sre.delivered_qty)                             AS outstanding_qty,
		  (sre.reserved_qty - sre.delivered_qty)
		    * COALESCE(itm.valuation_rate, 0)                                AS outstanding_value,
		  sre.stock_uom
		FROM `tabStock Reservation Entry` sre
		LEFT JOIN `tabItem`        itm ON itm.name  = sre.item_code
		LEFT JOIN `tabSales Order` so  ON so.name   = sre.voucher_no
		                              AND sre.voucher_type = 'Sales Order'
		WHERE sre.company  = %(company)s
		  AND sre.docstatus = 1
		  AND sre.status NOT IN ('Delivered', 'Cancelled')
		  {wh_clause}
		ORDER BY sre.warehouse, sre.item_code, sre.creation
		""",
		{"company": company, "warehouse": warehouse},
		as_dict=True,
	)

	# ── Roll up per (item_code, warehouse) ──────────────────────────────────
	group_map: dict[tuple, dict] = {}
	for r in rows:
		key = (r.item_code, r.warehouse)
		if key not in group_map:
			group_map[key] = {
				"item_code": r.item_code,
				"item_name": r.item_name or r.item_code,
				"warehouse": r.warehouse,
				"stock_uom": r.stock_uom,
				"total_outstanding": 0.0,
				"total_value": 0.0,
				"entries": [],
			}
		g = group_map[key]
		g["total_outstanding"] = flt(g["total_outstanding"]) + flt(r.outstanding_qty)
		g["total_value"] = flt(g["total_value"]) + flt(r.outstanding_value)
		g["entries"].append(
			{
				"sre": r.sre,
				"sales_order": r.sales_order,
				"customer": r.customer,
				"customer_name": r.customer_name,
				"so_date": str(r.so_date) if r.so_date else None,
				"so_creation": str(r.so_creation) if r.so_creation else None,
				"so_modified": str(r.so_modified) if r.so_modified else None,
				"reserved_on": str(r.reserved_on) if r.reserved_on else None,
				"status": r.status,
				"reserved_qty": flt(r.reserved_qty),
				"delivered_qty": flt(r.delivered_qty),
				"outstanding_qty": flt(r.outstanding_qty),
				"outstanding_value": flt(r.outstanding_value),
			}
		)

	groups = list(group_map.values())

	# ── KPIs ────────────────────────────────────────────────────────────────
	total_value = sum(flt(g["total_value"]) for g in groups)
	total_qty = sum(flt(g["total_outstanding"]) for g in groups)
	oldest = None
	for r in rows:
		ts = str(r.reserved_on) if r.reserved_on else None
		if ts and (oldest is None or ts < oldest):
			oldest = ts

	kpis = {
		"open_sre_count": len(rows),
		"item_count": len(groups),
		"total_outstanding_value": total_value,
		"total_outstanding_qty": total_qty,
		"oldest_reserved_on": oldest,
	}

	return {"kpis": kpis, "groups": groups}


@frappe.whitelist()
def receivables_cockpit(company: str):
	_require_company(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	
	# Current total receivables balance
	current_total = flt(frappe.db.sql(
		"""
		SELECT COALESCE(SUM(debit - credit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Customer' AND is_cancelled = 0
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
			SELECT COALESCE(SUM(debit - credit), 0)
			FROM `tabGL Entry`
			WHERE company = %(company)s AND party_type = 'Customer' AND posting_date > %(w_end)s AND is_cancelled = 0
			""",
			{"company": company, "w_end": w_end},
		)[0][0])
		trend.append(round(current_total - change_since, 2))

	# Payments received today
	received_today = flt(frappe.db.sql(
		"""
		SELECT COALESCE(SUM(credit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Customer' AND posting_date = %(today)s AND is_cancelled = 0
		""",
		{"company": company, "today": today()},
	)[0][0])

	# Top 10 debtors. Include account-currency fields so selecting a debtor
	# from the cockpit has the same balance shape as the main customer list.
	eps = money_epsilon(frappe.get_cached_value("Company", company, "default_currency"))
	top_debtors_raw = frappe.db.sql(
		"""
		SELECT
		  party AS name,
		  COALESCE(SUM(debit - credit), 0) AS balance_base,
		  COALESCE(SUM(debit_in_account_currency - credit_in_account_currency), 0) AS balance_acc,
		  CASE WHEN COUNT(DISTINCT account_currency) = 1 THEN MAX(account_currency) ELSE NULL END AS account_currency,
		  COUNT(DISTINCT account_currency) AS acc_currency_count
		FROM `tabGL Entry`
		WHERE company = %(company)s AND party_type = 'Customer' AND is_cancelled = 0
		GROUP BY party
		HAVING SUM(debit - credit) > %(eps)s
		ORDER BY balance_base DESC
		LIMIT 10
		""",
		{"company": company, "eps": eps},
		as_dict=True,
	) or []

	for debtor in top_debtors_raw:
		debtor["customer_name"] = frappe.db.get_value("Customer", debtor["name"], "customer_name") or debtor["name"]
		debtor["balance_base"] = flt(debtor["balance_base"])
		debtor["balance_acc"] = flt(debtor["balance_acc"])
		debtor["balance"] = debtor["balance_acc"] if debtor.get("account_currency") else debtor["balance_base"]
		debtor["acc_currency_count"] = cint(debtor.get("acc_currency_count") or 0)

	return {
		"total_receivable": current_total,
		"payments_received_today": received_today,
		"trend_8_weeks": trend,
		"top_debtors": top_debtors_raw,
	}
