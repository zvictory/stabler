import json
import os

import frappe
from frappe.utils import flt, today


def setup_fixtures_and_run_smoke():
	sites_path = "/Users/zafar/frappe-bench-local/sites"
	frappe.init(site="stabler", sites_path=sites_path)
	frappe.connect()
	frappe.set_user("Administrator")

	print("=== PREPARING TEST FIXTURES ===")
	# Pick 3 CIs
	cis = frappe.get_all("Commercial Invoice", filters={"docstatus": ["<", 2]}, order_by="creation desc", limit=10, fields=["name", "company", "supplier", "total_kg", "agreed_total"])
	if len(cis) < 3:
		print("Insufficient CIs in database")
		return

	ci_a = cis[0]
	ci_b = cis[1]
	ci_c = cis[2]

	company_a = ci_a.company or "MSA"
	supplier = ci_a.supplier or frappe.get_all("Supplier", limit=1, pluck="name")[0]

	# Ensure containers exist for CI A and CI B
	cnt_a_names = frappe.get_all("Import Container", filters={"commercial_invoice": ci_a.name}, pluck="name")
	if not cnt_a_names:
		cnt_a = frappe.get_doc({
			"doctype": "Import Container",
			"commercial_invoice": ci_a.name,
			"container_number": "SMOKE-CNT-A-01",
			"total_boxes": 100,
			"total_kg": 2500,
			"status": "In Transit",
		}).insert(ignore_permissions=True)
		cnt_a_names = [cnt_a.name]

	cnt_b_names = frappe.get_all("Import Container", filters={"commercial_invoice": ci_b.name}, pluck="name")
	if not cnt_b_names:
		cnt_b = frappe.get_doc({
			"doctype": "Import Container",
			"commercial_invoice": ci_b.name,
			"container_number": "SMOKE-CNT-B-02",
			"total_boxes": 150,
			"total_kg": 3750,
			"status": "In Transit",
		}).insert(ignore_permissions=True)
		cnt_b_names = [cnt_b.name]

	# Create fixture Purchase Invoice linked to CI A
	pinv_a = frappe.db.get_value("Purchase Invoice", {"custom_commercial_invoice": ci_a.name}, "name")
	if not pinv_a:
		doc_pinv_a = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"supplier": supplier,
			"company": company_a,
			"posting_date": today(),
			"due_date": today(),
			"currency": "USD",
			"grand_total": 1200.0,
			"outstanding_amount": 400.0,
			"custom_commercial_invoice": ci_a.name,
			"items": [{
				"item_code": frappe.get_all("Item", limit=1, pluck="name")[0] if frappe.db.count("Item") else "TEST-ITEM",
				"qty": 1,
				"rate": 1200.0,
				"amount": 1200.0,
			}],
		}).insert(ignore_permissions=True)
		pinv_a = doc_pinv_a.name

	# Create fixture Import Expense for CI A linked to pinv_a
	exp_a = frappe.db.get_value("Import Expense", {"commercial_invoice": ci_a.name}, "name")
	if not exp_a:
		doc_exp_a = frappe.get_doc({
			"doctype": "Import Expense",
			"commercial_invoice": ci_a.name,
			"company": company_a,
			"category": "Transport",
			"expense_date": today(),
			"supplier": supplier,
			"amount": 1500.0,
			"bank_payment": 800.0,
			"cash_payment": 0.0,
			"status": "Draft",
			"purchase_invoice": pinv_a,
		}).insert(ignore_permissions=True)
		exp_a = doc_exp_a.name

	# Create fixture Purchase Invoice linked directly to container of CI B (Scenario b)
	company_b = ci_b.company
	pinv_b = frappe.db.get_value("Purchase Invoice", {"custom_import_container": cnt_b_names[0]}, "name")
	if not pinv_b:
		doc_pinv_b = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"supplier": supplier,
			"company": company_b,
			"posting_date": today(),
			"due_date": today(),
			"currency": "USD",
			"grand_total": 850.0,
			"outstanding_amount": 250.0,
			"custom_import_container": cnt_b_names[0],
			"items": [{
				"item_code": frappe.get_all("Item", limit=1, pluck="name")[0] if frappe.db.count("Item") else "TEST-ITEM",
				"qty": 1,
				"rate": 850.0,
				"amount": 850.0,
			}],
		}).insert(ignore_permissions=True)
		pinv_b = doc_pinv_b.name

	# Create fixture Import Expense for CI B
	exp_b = frappe.db.get_value("Import Expense", {"commercial_invoice": ci_b.name}, "name")
	if not exp_b:
		doc_exp_b = frappe.get_doc({
			"doctype": "Import Expense",
			"commercial_invoice": ci_b.name,
			"container": cnt_b_names[0],
			"company": company_b,
			"category": "Transport",
			"expense_date": today(),
			"supplier": supplier,
			"amount": 850.0,
			"bank_payment": 600.0,
			"cash_payment": 0.0,
			"status": "Draft",
			"purchase_invoice": pinv_b,
		}).insert(ignore_permissions=True)
		exp_b = doc_exp_b.name

	# Update CI weights & items for scenario (a) to test per_kg calculation
	ci_a_doc = frappe.get_doc("Commercial Invoice", ci_a.name)
	ci_a_doc.total_kg = 5000.0
	ci_a_doc.save(ignore_permissions=True)
	frappe.db.sql("UPDATE `tabImport Container` SET total_kg = 2500.0 WHERE commercial_invoice = %s", (ci_a.name,))
	frappe.db.sql("UPDATE `tabCommercial Invoice Item` SET qty = 2500.0, rate = 10.0, amount = 25000.0 WHERE parent = %s", (ci_a.name,))

	# Ensure PINV-A grand_total = 1500.0 to match exp_a amount = 1500.0
	pinv_a = frappe.db.get_value("Purchase Invoice", {"custom_commercial_invoice": ci_a.name}, "name")
	if pinv_a:
		frappe.db.sql("UPDATE `tabPurchase Invoice` SET grand_total = 1500.0, outstanding_amount = 1500.0 WHERE name = %s", (pinv_a,))

	# Add product bill to CI A to test accounting.billed_goods
	prod_pinv = frappe.db.get_value("Purchase Invoice", {"custom_commercial_invoice": ci_a.name, "supplier": supplier, "grand_total": 45000.0}, "name")
	if not prod_pinv:
		frappe.get_doc({
			"doctype": "Purchase Invoice",
			"supplier": supplier,
			"company": company_a,
			"posting_date": today(),
			"due_date": today(),
			"currency": "USD",
			"grand_total": 45000.0,
			"outstanding_amount": 45000.0,
			"custom_commercial_invoice": ci_a.name,
			"items": [{
				"item_code": frappe.get_all("Item", limit=1, pluck="name")[0] if frappe.db.count("Item") else "TEST-ITEM",
				"qty": 4500,
				"rate": 10.0,
				"amount": 45000.0,
			}],
		}).insert(ignore_permissions=True)

	frappe.db.commit()

	print("\n========================================================")
	print("SMOKE TEST 1 (a): CI with expenses AND purchase invoice bills")
	print(f"Testing CI: {ci_a.name}")
	print("========================================================")
	res_a = frappe.call("stabler.api.imports.ci_cost_overview", commercial_invoice=ci_a.name)
	print(json.dumps(res_a, indent=2, ensure_ascii=False))

	print("\n========================================================")
	print("SMOKE TEST 1 (b): CI with container-linked Purchase Invoice (custom_import_container)")
	print(f"Testing CI: {ci_b.name}, Container: {cnt_b_names[0]}")
	print("========================================================")
	res_b = frappe.call("stabler.api.imports.ci_cost_overview", commercial_invoice=ci_b.name)
	print(json.dumps(res_b, indent=2, ensure_ascii=False))

	print("\n========================================================")
	print("SMOKE TEST 1 (c): CI with NO expenses")
	print(f"Testing CI: {ci_c.name}")
	print("========================================================")
	res_c = frappe.call("stabler.api.imports.ci_cost_overview", commercial_invoice=ci_c.name)
	print(json.dumps(res_c, indent=2, ensure_ascii=False))

	print("\n========================================================")
	print("SMOKE TEST 2: container_cost_ledger Regression Check")
	print(f"Testing Container: {cnt_b_names[0]}")
	print("========================================================")
	res_ledger = frappe.call("stabler.api.imports.container_cost_ledger", container=cnt_b_names[0])
	print("Container Cost Ledger Result:")
	print(json.dumps(res_ledger, indent=2, ensure_ascii=False))

	print("\n========================================================")
	print("SMOKE TEST 3: Financial Masking Check (cost_visible=False)")
	print(f"Testing CI: {ci_b.name} with cost_visible=False")
	print("========================================================")

	# Mock _cost_visible to return False
	orig_cost_visible = frappe.get_attr("stabler.api.imports._cost_visible")
	try:
		frappe.flags.mock_cost_visible_false = True
		import stabler.api.imports as imp_mod
		imp_mod._cost_visible = lambda user=None: False
		res_masked = frappe.call("stabler.api.imports.ci_cost_overview", commercial_invoice=ci_b.name)
		print(json.dumps(res_masked, indent=2, ensure_ascii=False))
	finally:
		imp_mod._cost_visible = orig_cost_visible
		frappe.flags.mock_cost_visible_false = False

	# Verify reconciliation identity (totals.transport == totals.billed + totals.unbilled)
	for label, res in [("Scenario A", res_a), ("Scenario B", res_b), ("Scenario C", res_c)]:
		tot = res.get("totals", {})
		t_amt = float(tot.get("transport") or 0.0)
		b_amt = float(tot.get("billed") or 0.0)
		u_amt = float(tot.get("unbilled") or 0.0)
		assert abs(t_amt - (b_amt + u_amt)) <= 0.01, f"{label} reconciliation identity failed: {t_amt} != {b_amt} + {u_amt}"

	# Verify non-zero per_kg values on weighted CI A
	assert res_a["operational"]["per_kg"] > 0, "Scenario A operational per_kg should be > 0"
	assert res_a["accounting"]["per_kg"] > 0, "Scenario A accounting per_kg should be > 0"
	assert res_a["by_container"][0]["per_kg"] > 0, "Scenario A by_container per_kg should be > 0"

	# Verify accounting.billed_goods comes from product bills (not declaration docs)
	assert res_a["accounting"]["billed_goods"] > 0, "Scenario A accounting billed_goods should be > 0 from product bill"

	# Verify basic structures
	assert isinstance(res_a.get("expenses"), list), "res_a expenses missing"
	assert isinstance(res_a.get("bills"), list), "res_a bills missing"
	assert len(res_a.get("bills")) > 0, "res_a bills should not be empty"

	assert isinstance(res_b.get("bills"), list), "res_b bills missing"
	assert len(res_b.get("bills")) > 0, "res_b bills should contain container-linked bill"

	assert res_c.get("expenses") == [], "res_c expenses should be empty list"
	assert res_c.get("bills") == [], "res_c bills should be empty list"

	assert isinstance(res_ledger.get("bills"), list), "ledger bills missing"
	assert len(res_ledger.get("bills")) > 0, "ledger bills should contain container-linked bill"

	assert res_masked.get("totals", {}).get("transport") is None, "Masked transport should be None"
	assert res_masked.get("operational", {}).get("total") is None, "Masked operational total should be None"
	assert res_masked.get("accounting", {}).get("total") is None, "Masked accounting total should be None"
	assert res_masked.get("gap", {}).get("amount") is None, "Masked gap amount should be None"
	assert res_masked.get("expenses")[0]["amount"] is None, "Masked expense amount should be None"
	assert res_masked.get("bills")[0]["grand_total"] is None, "Masked bill grand_total should be None"
	print("\n=== ALL SMOKE TEST ASSERTIONS PASSED CLEANLY! ===")

if __name__ == "__main__":
	setup_fixtures_and_run_smoke()
