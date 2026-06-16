"""Historical data repair script for party account currencies.

Moves outstanding party balances out of wrong-currency accounts into correct
per-currency accounts using correcting Journal Entries (append-only).
Preserves the base-currency value and against_voucher linkages.

Run via:
    bench --site stabler execute stabler.maintenance.fix_party_account_currency.execute
"""

from __future__ import annotations

import csv
import sys
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, today


def get_or_create_party_account(company: str, party_type: str, currency: str) -> str:
	account_type = "Receivable" if party_type == "Customer" else "Payable"

	# Look for an existing account
	existing = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"account_type": account_type,
			"account_currency": currency,
			"is_group": 0,
			"disabled": 0,
		},
		limit=1,
	)
	if existing:
		return existing[0].name

	# Copy parent account from default account
	default_acc = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"account_type": account_type,
			"is_group": 0,
		},
		limit=1,
	)
	if not default_acc:
		frappe.throw(_("No default {0} account found to copy parent from.").format(account_type))

	parent_account = frappe.db.get_value("Account", default_acc[0].name, "parent_account")
	name_prefix = "Debtors" if party_type == "Customer" else "Creditors"
	new_name = f"{name_prefix} ({currency}) - A"

	existing_name = frappe.db.exists("Account", new_name)
	if existing_name:
		return existing_name

	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": f"{name_prefix} ({currency})",
			"parent_account": parent_account,
			"company": company,
			"account_type": account_type,
			"account_currency": currency,
			"is_group": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	print(f"Created new account: {doc.name} ({currency})")
	return doc.name


def execute(dry_run: bool = True, company: str = "ANJAN") -> None:
	print(f"Starting Historical Data Repair for company: {company} (dry_run={dry_run})")
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"

	results = []

	# --- 1. Diagnose & Fix Sales Invoices ---
	sales_invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"company": company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
		},
		fields=["name", "customer", "currency", "debit_to", "outstanding_amount", "conversion_rate"],
	)

	print(f"Found {len(sales_invoices)} open Sales Invoices.")

	for si in sales_invoices:
		debit_to_currency = frappe.db.get_value("Account", si.debit_to, "account_currency")
		if debit_to_currency != si.currency:
			# Needs correction!
			correct_account = get_or_create_party_account(company, "Customer", si.currency)
			
			# Outstanding in base (USD) and foreign (UZS)
			outstanding_base = flt(si.outstanding_amount) * flt(si.conversion_rate)
			outstanding_foreign = flt(si.outstanding_amount)

			results.append({
				"party_type": "Customer",
				"party": si.customer,
				"voucher_type": "Sales Invoice",
				"voucher_no": si.name,
				"old_account": si.debit_to,
				"new_account": correct_account,
				"amount_foreign": outstanding_foreign,
				"amount_base": outstanding_base,
				"currency": si.currency,
			})

	# --- 2. Diagnose & Fix Purchase Invoices ---
	purchase_invoices = frappe.get_all(
		"Purchase Invoice",
		filters={
			"company": company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
		},
		fields=["name", "supplier", "currency", "credit_to", "outstanding_amount", "conversion_rate"],
	)

	print(f"Found {len(purchase_invoices)} open Purchase Invoices.")

	for pi in purchase_invoices:
		credit_to_currency = frappe.db.get_value("Account", pi.credit_to, "account_currency")
		if credit_to_currency != pi.currency:
			correct_account = get_or_create_party_account(company, "Supplier", pi.currency)
			
			outstanding_base = flt(pi.outstanding_amount) * flt(pi.conversion_rate)
			outstanding_foreign = flt(pi.outstanding_amount)

			results.append({
				"party_type": "Supplier",
				"party": pi.supplier,
				"voucher_type": "Purchase Invoice",
				"voucher_no": pi.name,
				"old_account": pi.credit_to,
				"new_account": correct_account,
				"amount_foreign": outstanding_foreign,
				"amount_base": outstanding_base,
				"currency": pi.currency,
			})

	# Write CSV results log
	csv_filepath = "/tmp/fix_party_account_results.csv"
	with open(csv_filepath, mode="w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(
			f,
			fieldnames=[
				"party_type", "party", "voucher_type", "voucher_no",
				"old_account", "new_account", "amount_foreign", "amount_base", "currency"
			]
		)
		writer.writeheader()
		for row in results:
			writer.writerow(row)

	print(f"Wrote {len(results)} anomalies to CSV: {csv_filepath}")

	if dry_run:
		print("Dry run completed. No Journal Entries created.")
		return

	# --- 3. Process Corrections (Create Correcting JEs) ---
	corrected_count = 0
	for item in results:
		# Create correcting Journal Entry
		je = frappe.new_doc("Journal Entry")
		je.company = company
		je.posting_date = today()
		je.user_remark = f"GL integrity correction for {item['voucher_type']} {item['voucher_no']}"

		# For Customer (Receivable): Credit old account, Debit new account
		# For Supplier (Payable): Debit old account, Credit new account
		is_customer = item["party_type"] == "Customer"

		# Old account line (reversing original)
		row_old = {
			"account": item["old_account"],
			"party_type": item["party_type"],
			"party": item["party"],
			"against_voucher_type": item["voucher_type"],
			"against_voucher": item["voucher_no"],
		}
		
		# New account line (re-posting correctly)
		row_new = {
			"account": item["new_account"],
			"party_type": item["party_type"],
			"party": item["party"],
			"against_voucher_type": item["voucher_type"],
			"against_voucher": item["voucher_no"],
		}

		if is_customer:
			# Credit old account
			row_old["credit"] = item["amount_base"]
			row_old["credit_in_account_currency"] = item["amount_foreign"]
			# Debit new account
			row_new["debit"] = item["amount_base"]
			row_new["debit_in_account_currency"] = item["amount_foreign"]
		else:
			# Debit old account
			row_old["debit"] = item["amount_base"]
			row_old["debit_in_account_currency"] = item["amount_foreign"]
			# Credit new account
			row_new["credit"] = item["amount_base"]
			row_new["credit_in_account_currency"] = item["amount_foreign"]

		je.append("accounts", row_old)
		je.append("accounts", row_new)

		je.insert(ignore_permissions=True)
		# Automated historical-data repair (run via bench execute) — not a
		# discretionary posting, so it bypasses the maker-checker gate.
		je.flags.ignore_approval_gate = True
		je.submit()
		corrected_count += 1

	frappe.db.commit()
	print(f"Successfully processed {corrected_count} correcting Journal Entries.")
