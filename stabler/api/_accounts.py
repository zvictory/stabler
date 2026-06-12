from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today
from erpnext.accounts.party import get_party_account

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
		# If currency matches, return immediately
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
		frappe.throw(
			_("No {0} {1} account exists for company {2}. "
			  "Create one before using this currency.").format(currency, account_type.lower(), company),
			frappe.ValidationError
		)
	return matching[0]


def validate_exchange_rate(company: str, doc_currency: str, conversion_rate: float, posting_date) -> None:
	"""Validate that the exchange rate is within +/-20% CBU tolerance and not stale."""
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	if doc_currency == company_currency:
		return

	# Hard floor validation for USD -> UZS
	if doc_currency == "USD" and company_currency == "UZS" and flt(conversion_rate) <= 1000.0:
		frappe.throw(
			_("Conversion rate for USD to UZS cannot be less than 1000 (got {0}).").format(conversion_rate),
			frappe.ValidationError
		)

	# Fetch CBU rate from Currency Exchange (CBU task stores daily rates there)
	cbu_rate_doc = frappe.get_all(
		"Currency Exchange",
		filters={"from_currency": doc_currency, "to_currency": company_currency, "date": ("<=", posting_date)},
		fields=["exchange_rate", "date"],
		order_by="date desc",
		limit=1
	)
	if not cbu_rate_doc:
		frappe.throw(
			_("No CBU exchange rate found for {0} to {1} on or before {2}.").format(doc_currency, company_currency, posting_date),
			frappe.ValidationError
		)

	cbu_rate = flt(cbu_rate_doc[0].exchange_rate)
	cbu_date = cbu_rate_doc[0].date

	# Check for stale rate (older than 3 days)
	days_diff = (getdate(posting_date) - getdate(cbu_date)).days
	if days_diff > 3:
		frappe.throw(
			_("Stale exchange rate: the nearest CBU rate for {0} to {1} is from {2} ({3} days old). "
			  "Must be within 3 days.").format(doc_currency, company_currency, cbu_date, days_diff),
			frappe.ValidationError
		)

	# Check +/-20% tolerance band
	lower_limit = cbu_rate * 0.8
	upper_limit = cbu_rate * 1.2
	if not (lower_limit <= flt(conversion_rate) <= upper_limit):
		frappe.throw(
			_("Conversion rate {0} is outside the allowed CBU tolerance band (+/-20%) for {1} to {2}. "
			  "CBU rate on {3} is {4} (Allowed band: {5} - {6}).").format(
				  conversion_rate, doc_currency, company_currency, cbu_date, cbu_rate, round(lower_limit, 2), round(upper_limit, 2)
			  ),
			frappe.ValidationError
		)


def validate_sales_invoice(doc, method=None):
	if doc.customer:
		doc.debit_to = resolve_party_account("Customer", doc.customer, doc.company, doc.currency)
		validate_exchange_rate(doc.company, doc.currency, doc.conversion_rate, doc.posting_date)


def validate_purchase_invoice(doc, method=None):
	if doc.supplier:
		doc.credit_to = resolve_party_account("Supplier", doc.supplier, doc.company, doc.currency)
		validate_exchange_rate(doc.company, doc.currency, doc.conversion_rate, doc.posting_date)


def validate_payment_entry(doc, method=None):
	# EmployeePaymentEntry (ERPNext HR controller) reuses the "Payment Entry"
	# doctype for salary advances but lacks paid_from/to_currency fields.
	# Skip our validation for employee payments entirely.
	if getattr(doc, "party_type", None) == "Employee":
		return
	if doc.party_type and doc.party and doc.party_account and doc.party_account_currency:
		doc.party_account = resolve_party_account(doc.party_type, doc.party, doc.company, doc.party_account_currency)

		company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "UZS"

		paid_from_ccy = getattr(doc, "paid_from_currency", None)
		paid_to_ccy = getattr(doc, "paid_to_currency", None)

		# Check conversion rate for foreign payment
		if paid_from_ccy and paid_from_ccy != company_currency and paid_from_ccy == doc.party_account_currency:
			rate = flt(doc.source_exchange_rate)
			if rate > 0:
				validate_exchange_rate(doc.company, paid_from_ccy, rate, doc.clearance_date or doc.posting_date)
		elif paid_to_ccy and paid_to_ccy != company_currency and paid_to_ccy == doc.party_account_currency:
			rate = flt(doc.target_exchange_rate)
			if rate > 0:
				validate_exchange_rate(doc.company, paid_to_ccy, rate, doc.clearance_date or doc.posting_date)


def validate_journal_entry(doc, method=None):
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
					_("Account {0} is not a {1} account for party {2}.").format(row.account, expected_type.lower(), row.party),
					frappe.ValidationError
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
					_("Cannot post UZS 1:1 into non-base currency account {0}. "
					  "Please provide a valid exchange rate and debit amount in {1}.").format(row.account, account_currency),
					frappe.ValidationError
				)
			validate_exchange_rate(doc.company, account_currency, row.exchange_rate, doc.posting_date)
		elif credit > 0:
			if abs(credit - credit_in_acc) < 0.01:
				frappe.throw(
					_("Cannot post UZS 1:1 into non-base currency account {0}. "
					  "Please provide a valid exchange rate and credit amount in {1}.").format(row.account, account_currency),
					frappe.ValidationError
				)
			validate_exchange_rate(doc.company, account_currency, row.exchange_rate, doc.posting_date)
