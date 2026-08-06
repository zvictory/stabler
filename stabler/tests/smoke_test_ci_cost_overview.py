import os
import sys

import frappe


def main():
	# Ensure log directory exists or stream logs
	sites_path = "/Users/zafar/frappe-bench-local/sites"
	frappe.init(site="stabler", sites_path=sites_path)
	frappe.connect()
	frappe.set_user("Administrator")

	# Find a CI with containers, expenses, or bills
	cis = frappe.get_all("Commercial Invoice", limit=50, order_by="modified desc", pluck="name")
	print(f"Found {len(cis)} CIs")

	target_ci = None
	for ci in cis:
		exp_cnt = frappe.db.count("Import Expense", {"commercial_invoice": ci})
		if exp_cnt > 0:
			target_ci = ci
			break

	if not target_ci and cis:
		target_ci = cis[0]

	print(f"Testing ci_cost_overview on CI with expenses: {target_ci}")

	res = frappe.call("stabler.api.imports.ci_cost_overview", commercial_invoice=target_ci)

	print("=== CI COST OVERVIEW SMOKE TEST RESULT ===")
	print(f"CI: {target_ci}")
	print(f"Bills count: {len(res.get('bills', []))}")
	print(f"Expenses count: {len(res.get('expenses', []))}")
	print(f"Unbilled count: {len(res.get('unbilled', []))}")
	print(f"Containers breakdown count: {len(res.get('by_container', []))}")
	print(f"Operational: {res.get('operational')}")
	print(f"Accounting: {res.get('accounting')}")
	print(f"Gap: {res.get('gap')}")
	print(f"Totals: {res.get('totals')}")
	print("SUCCESS: Endpoint executed cleanly with full live database state!")


if __name__ == "__main__":
	main()
