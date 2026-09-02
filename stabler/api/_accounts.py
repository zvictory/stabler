from __future__ import annotations

import frappe
from erpnext.accounts.party import get_party_account
from frappe import _
from frappe.utils import flt, getdate, today


def resolve_party_account(party_type: str, party: str, company: str, currency: str) -> str:
	"""Wrap ERPNext get_party_account, then enforce that the account's currency
	matches the document's currency. If there's a mismatch, swap to the matching
	receivable/payable account for this company & currency.
	Throws a human-readable ValidationError if no matching account exists.
	"""
	# Get the default account (which could be the one from Party Account or Company default)
	account = get_party_account(party_type=party_type, party=party, company=company)

	account_type = "Receivable" if party_type == "Customer" else "Payable"

	if account:
		account_currency = frappe.get_cached_value("Account", account, "account_currency")
		# If account_currency is unassigned/blank, or matches document currency, return immediately.
		# If account_currency is explicitly assigned (e.g. USD) and differs from document currency (e.g. UZS),
		# it CANNOT be used even if USD is the company base currency.
		if not account_currency or account_currency == currency:
			return account

	# Mismatch or no account resolved! Swap/resolve to the matching receivable/payable account
	matching = frappe.get_all(
		"Account",
		filters={
			"account_type": account_type,
			"company": company,
			"account_currency": currency,
			"is_group": 0,
			"disabled": 0,
		},
		pluck="name",
		order_by="lft asc",
		limit=1,
	)
	if not matching:
		# Fallback: unassigned currency account
		matching = frappe.get_all(
			"Account",
			filters={
				"account_type": account_type,
				"company": company,
				"account_currency": ["in", ["", None]],
				"is_group": 0,
				"disabled": 0,
			},
			pluck="name",
			order_by="lft asc",
			limit=1,
		)
	if not matching:
		frappe.throw(
			_("No {0} {1} account exists for company {2}. Create one before using this currency.").format(
				currency, account_type.lower(), company
			),
			frappe.ValidationError,
		)
	return matching[0]


# Re-export, not a second copy: the body lives in `_fx_rates`, which does not
# import erpnext, so `crm_board` can reach the same reader from the frappe-free
# test path (moved 2026-09-02). Every existing caller keeps importing this name
# from here, and `validate_exchange_rate` below still measures documents against
# exactly the rate the Tender CRM's companion line shows.
from stabler.api._fx_rates import cbu_rate_on_or_before as _cbu_rate_on_or_before


def validate_exchange_rate(company: str, doc_currency: str, conversion_rate: float, posting_date) -> None:
	"""Validate that the exchange rate is within +/-20% CBU tolerance and not stale."""
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	if doc_currency == company_currency:
		return

	# Hard floor validation for USD -> UZS
	if doc_currency == "USD" and company_currency == "UZS" and flt(conversion_rate) <= 1000.0:
		frappe.throw(
			_("Conversion rate for USD to UZS cannot be less than 1000 (got {0}).").format(conversion_rate),
			frappe.ValidationError,
		)

	# Fetch CBU rate from Currency Exchange (CBU task stores daily rates there).
	# CBU publishes each pair in ONE direction only (e.g. USD -> UZS). If the direct
	# pair isn't stored, fall back to the inverse pair and invert the rate — so the
	# validation works regardless of which side is the company base currency
	# (e.g. a USD-base company converting a UZS leg needs 1 / (USD->UZS)).
	cbu_rate, cbu_date = _cbu_rate_on_or_before(doc_currency, company_currency, posting_date)
	if cbu_rate is None:
		frappe.throw(
			_("No CBU exchange rate found for {0} to {1} on or before {2}.").format(
				doc_currency, company_currency, posting_date
			),
			frappe.ValidationError,
		)

	# Staleness window is admin-configurable (Accounts Settings, set via the
	# Posting Window page): `allow_stale` bypasses the check entirely — needed for
	# back-dated corrections into periods the CBU feed never covered — and
	# `stale_days` widens the default 3-day window. The +/-20% band below still
	# guards against fat-finger rates regardless.
	allow_stale = 0
	stale_days = 3
	try:
		acc = frappe.get_cached_doc("Accounts Settings")
		allow_stale = int(getattr(acc, "allow_stale", 0) or 0)
		_sd = int(getattr(acc, "stale_days", 0) or 0)
		if _sd > 0:
			stale_days = _sd
	except Exception:
		pass

	days_diff = (getdate(posting_date) - getdate(cbu_date)).days
	if not allow_stale and days_diff > stale_days:
		frappe.throw(
			_(
				"Stale exchange rate: the nearest CBU rate for {0} to {1} is from {2} ({3} days old). "
				"Must be within {4} days (raise the window or enable 'allow stale' in "
				"Admin → Posting Window)."
			).format(doc_currency, company_currency, cbu_date, days_diff, stale_days),
			frappe.ValidationError,
		)

	# Check +/-20% tolerance band
	lower_limit = cbu_rate * 0.8
	upper_limit = cbu_rate * 1.2
	if not (lower_limit <= flt(conversion_rate) <= upper_limit):
		frappe.throw(
			_(
				"Conversion rate {0} is outside the allowed CBU tolerance band (+/-20%) for {1} to {2}. "
				"CBU rate on {3} is {4} (Allowed band: {5} - {6})."
			).format(
				conversion_rate,
				doc_currency,
				company_currency,
				cbu_date,
				cbu_rate,
				round(lower_limit, 2),
				round(upper_limit, 2),
			),
			frappe.ValidationError,
		)


def validate_sales_invoice(doc, method=None):
	if doc.customer:
		doc.debit_to = resolve_party_account("Customer", doc.customer, doc.company, doc.currency)
		validate_exchange_rate(doc.company, doc.currency, doc.conversion_rate, doc.posting_date)

	if frappe.db.get_single_value("Stabler Settings", "require_delivery_note") and doc.update_stock:
		frappe.throw(
			frappe._(
				"Direct stock updates via Sales Invoice are disabled by company policy. "
				"Please create a Delivery Note first and link it to this Sales Invoice (with Update Stock unchecked)."
			),
			frappe.ValidationError,
		)


def validate_purchase_invoice(doc, method=None):
	if doc.supplier:
		doc.credit_to = resolve_party_account("Supplier", doc.supplier, doc.company, doc.currency)
		validate_exchange_rate(doc.company, doc.currency, doc.conversion_rate, doc.posting_date)
	_three_way_match_check(doc)


def _three_way_match_check(doc) -> None:
	"""Three-way match (PO vs Receipt vs Bill). Opt-in via Stabler Settings.

	Does NOT re-implement ERPNext's native amount-based Over Billing Allowance —
	it adds rate-variance and billed-vs-received-qty exception surfacing. When
	enforcement is on, blocking exceptions stop submission; otherwise they are
	attached to the doc as a warning comment.
	"""
	if not frappe.db.exists("DocType", "Stabler Settings"):
		return
	enabled = frappe.db.get_single_value("Stabler Settings", "enable_three_way_match")
	if not (enabled and int(enabled or 0)):
		return

	from stabler.api._three_way_match import evaluate_invoice

	qty_tol = flt(frappe.db.get_single_value("Stabler Settings", "three_way_qty_tolerance_pct") or 0)
	rate_tol = flt(frappe.db.get_single_value("Stabler Settings", "three_way_rate_tolerance_pct") or 0)

	# Build PO-row and PR-row indices for the rows this invoice references.
	po_details = {r.po_detail for r in doc.get("items", []) if r.get("po_detail")}
	pr_details = {r.pr_detail for r in doc.get("items", []) if r.get("pr_detail")}
	po_rows = _rows_by_name("Purchase Order Item", po_details, ["qty", "rate"])
	pr_rows = _rows_by_name("Purchase Receipt Item", pr_details, ["qty", "received_qty"])

	lines = []
	for r in doc.get("items", []):
		po = po_rows.get(r.get("po_detail")) if r.get("po_detail") else None
		pr = pr_rows.get(r.get("pr_detail")) if r.get("pr_detail") else None
		lines.append(
			{
				"idx": r.idx,
				"item_code": r.get("item_code"),
				"bill_qty": flt(r.get("qty")),
				"bill_rate": flt(r.get("rate")),
				"po_qty": flt(po["qty"]) if po else None,
				"po_rate": flt(po["rate"]) if po else None,
				"received_qty": (flt(pr.get("received_qty") or pr.get("qty")) if pr else None),
			}
		)

	result = evaluate_invoice(lines, qty_tol_pct=qty_tol, rate_tol_pct=rate_tol)
	if not result["exceptions"]:
		return
	msg = "<br>".join(
		"Row {0} ({1}): {2}".format(e.get("idx"), e.get("item_code") or "", e.get("detail"))
		for e in result["exceptions"]
	)
	if result["has_block"]:
		frappe.throw(
			_("Three-way match failed:") + "<br>" + msg,
			title=_("Vendor bill does not match PO / receipt"),
		)
	else:
		# Advisory only — record so it shows on the document timeline.
		doc.add_comment("Comment", _("Three-way match warnings:") + "<br>" + msg)


def _rows_by_name(child_doctype: str, names: set, fields: list[str]) -> dict:
	"""Fetch child rows by name into {name: {field: value}} (parameterized)."""
	out: dict = {}
	if not names:
		return out
	for row in frappe.get_all(child_doctype, filters={"name": ["in", list(names)]}, fields=["name", *fields]):
		out[row["name"]] = row
	return out


def validate_payment_entry(doc, method=None):
	# EmployeePaymentEntry (ERPNext HR controller) reuses the "Payment Entry"
	# doctype for salary advances but lacks paid_from/to_currency fields.
	# Skip our validation for employee payments entirely.
	if getattr(doc, "party_type", None) == "Employee":
		return
	if doc.party_type and doc.party and doc.party_account and doc.party_account_currency:
		doc.party_account = resolve_party_account(
			doc.party_type, doc.party, doc.company, doc.party_account_currency
		)

		company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "UZS"

		paid_from_ccy = getattr(doc, "paid_from_currency", None)
		paid_to_ccy = getattr(doc, "paid_to_currency", None)

		# Check conversion rate for foreign payment
		if (
			paid_from_ccy
			and paid_from_ccy != company_currency
			and paid_from_ccy == doc.party_account_currency
		):
			rate = flt(doc.source_exchange_rate)
			if rate > 0:
				validate_exchange_rate(
					doc.company, paid_from_ccy, rate, doc.clearance_date or doc.posting_date
				)
		elif paid_to_ccy and paid_to_ccy != company_currency and paid_to_ccy == doc.party_account_currency:
			rate = flt(doc.target_exchange_rate)
			if rate > 0:
				validate_exchange_rate(doc.company, paid_to_ccy, rate, doc.clearance_date or doc.posting_date)


def validate_journal_entry(doc, method=None):
	if (doc.voucher_type or "").lower() == "exchange gain or loss" or getattr(
		doc, "is_system_generated", False
	):
		return

	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "UZS"
	for row in getattr(doc, "accounts", []):
		if not row.account:
			continue

		if row.party_type and row.party:
			# Verify account type matches party type
			expected_type = "Receivable" if row.party_type == "Customer" else "Payable"
			acc_type = frappe.get_cached_value("Account", row.account, "account_type")
			if acc_type != expected_type:
				frappe.throw(
					_("Account {0} is not a {1} account for party {2}.").format(
						row.account, expected_type.lower(), row.party
					),
					frappe.ValidationError,
				)

		account_currency = frappe.get_cached_value("Account", row.account, "account_currency")
		if not account_currency or account_currency == company_currency:
			continue

		# Non-base currency row validation
		debit = flt(row.debit)
		credit = flt(row.credit)
		debit_in_acc = flt(row.debit_in_account_currency)
		credit_in_acc = flt(row.credit_in_account_currency)

		if debit > 0:
			if abs(debit - debit_in_acc) < 0.01:
				frappe.throw(
					_(
						"Cannot post UZS 1:1 into non-base currency account {0}. "
						"Please provide a valid exchange rate and debit amount in {1}."
					).format(row.account, account_currency),
					frappe.ValidationError,
				)
			validate_exchange_rate(doc.company, account_currency, row.exchange_rate, doc.posting_date)
		elif credit > 0:
			if abs(credit - credit_in_acc) < 0.01:
				frappe.throw(
					_(
						"Cannot post UZS 1:1 into non-base currency account {0}. "
						"Please provide a valid exchange rate and credit amount in {1}."
					).format(row.account, account_currency),
					frappe.ValidationError,
				)
			validate_exchange_rate(doc.company, account_currency, row.exchange_rate, doc.posting_date)
