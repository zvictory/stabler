"""Vehicle Finance Phase 2.5 — read/query API surface (bench).

Real ERPNext documents end to end, mirroring test_vehicle_finance_accounting.py's
fixture pattern. Focus: currency totals are never summed across currencies,
cost/margin is genuinely absent (not hidden) without the capability, the
module/engine guards fire before any row is read, and outstanding is the same
number wherever it is derived from — never two competing definitions.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, getdate, today

from stabler.api.vehicle_finance import read, v1
from stabler.tests.fixtures import TEST_COMPANY

COMPANY = TEST_COMPANY
VIEWER_EMAIL = "vf-read-viewer-test@example.com"


class VehicleFinanceReadTest(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls every test's transaction back, so the shared
		# masters are (re-)created inside each test's own transaction.
		self._setup_accounts()
		self._setup_items()
		self._setup_parties()
		self._setup_fx()
		self._setup_settings()

	def _setup_accounts(self):
		def account(name, parent, **kw):
			full = f"{name} - _TC"
			curr = kw.pop("currency", "UZS")
			acc_type = kw.pop("account_type", "")
			if not frappe.db.exists("Account", full):
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": name,
						"parent_account": f"{parent} - _TC",
						"company": COMPANY,
						"account_currency": curr,
						"account_type": acc_type,
						"is_group": 0,
					}
				).insert(ignore_permissions=True)
			else:
				frappe.db.set_value("Account", full, "account_currency", curr)
				if acc_type:
					frappe.db.set_value("Account", full, "account_type", acc_type)
			return full

		self.payable = account("VF Payable USD", "Accounts Payable", account_type="Payable", currency="USD")
		self.receivable = account(
			"VF Receivable USD", "Accounts Receivable", account_type="Receivable", currency="USD"
		)
		self.deferred_income = account("VF Deferred Income USD", "Current Liabilities", currency="USD")
		self.deferred_cost = account("VF Deferred Cost USD", "Current Assets", currency="USD")
		self.expense = account("VF Realised Cost", "Direct Expenses", currency="USD")
		self.bank = account("VF Bank", "Current Assets", account_type="Bank")

	def _setup_items(self):
		if not frappe.db.exists("Item", "VF-CAR"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "VF-CAR",
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"has_serial_no": 1,
					"is_sales_item": 1,
					"is_purchase_item": 1,
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Item", "VF-FEE"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "VF-FEE",
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"is_sales_item": 1,
					"is_purchase_item": 1,
				}
			).insert(ignore_permissions=True)

	def _setup_parties(self):
		def ensure(doctype, fieldname, display):
			name = frappe.db.get_value(doctype, {fieldname: display}, "name")
			if name:
				return name
			doc = frappe.new_doc(doctype)
			doc.set(fieldname, display)
			doc.insert(ignore_permissions=True)
			return doc.name

		self.customer = ensure("Customer", "customer_name", "VF Test Customer")
		self.supplier = ensure("Supplier", "supplier_name", "VF Test Supplier")

	def _setup_fx(self):
		if not frappe.db.exists(
			"Currency Exchange",
			{"from_currency": "USD", "to_currency": "UZS", "date": getdate(today())},
		):
			frappe.get_doc(
				{
					"doctype": "Currency Exchange",
					"from_currency": "USD",
					"to_currency": "UZS",
					"exchange_rate": 12900.0,
					"date": getdate(today()),
				}
			).insert(ignore_permissions=True)

	def _setup_settings(self):
		frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		settings = frappe.get_single("Stabler Settings")
		found = False
		for row in settings.company_modules or []:
			if row.company == COMPANY:
				row.enable_installment = 1
				found = True
				break
		if not found:
			settings.append("company_modules", {"company": COMPANY, "enable_installment": 1})
		settings.save(ignore_permissions=True)

		name = frappe.db.get_value("Vehicle Finance Settings", {"company": COMPANY}, "name")
		doc = (
			frappe.get_doc("Vehicle Finance Settings", name)
			if name
			else frappe.new_doc("Vehicle Finance Settings")
		)
		doc.company = COMPANY
		doc.installment_engine = "Agreement V1"
		doc.accounting_policy_approved = 1
		doc.acquisition_payable_account = self.payable
		doc.acquisition_deferred_cost_account = self.deferred_cost
		doc.acquisition_realised_cost_account = self.expense
		doc.acquisition_fee_item = "VF-FEE"
		doc.disposition_receivable_account = self.receivable
		doc.disposition_deferred_income_account = self.deferred_income
		doc.disposition_income_account = self.expense
		doc.disposition_fee_item = "VF-FEE"
		doc.default_cash_bank_account = self.bank
		doc.save(ignore_permissions=True)

	# --- helpers -----------------------------------------------------------------

	def _make_vehicle(self, vin, warehouse=None):
		if not frappe.db.exists("Serial No", vin):
			frappe.get_doc(
				{
					"doctype": "Serial No",
					"serial_no": vin,
					"item_code": "VF-CAR",
					"company": COMPANY,
					"status": "Active",
				}
			).insert(ignore_permissions=True)
		if warehouse:
			frappe.db.set_value("Serial No", vin, "warehouse", warehouse)
			frappe.db.set_value("Serial No", vin, "status", "Active")
		if frappe.db.exists("Vehicle Unit", {"serial_no": vin}):
			return frappe.db.get_value("Vehicle Unit", {"serial_no": vin}, "name")
		unit = frappe.new_doc("Vehicle Unit")
		unit.company = COMPANY
		unit.serial_no = vin
		unit.insert(ignore_permissions=True)
		return unit.name

	def _make_agreement(self, *, direction, settlement_mode="Installment", currency="USD", party=None, vin=None):
		wh = (
			"Stores - _TC"
			if direction == "Disposition" and not frappe.db.get_value("Serial No", vin, "warehouse")
			else None
		)
		unit = self._make_vehicle(vin or f"VF-VIN-{frappe.generate_hash(length=6).upper()}", warehouse=wh)
		agreement = frappe.new_doc("Vehicle Agreement")
		agreement.company = COMPANY
		agreement.direction = direction
		agreement.settlement_mode = settlement_mode
		agreement.party = party or (self.supplier if direction == "Acquisition" else self.customer)
		agreement.party_type = "Supplier" if direction == "Acquisition" else "Customer"
		agreement.currency = currency
		agreement.vehicle_unit = unit
		agreement.agreement_date = today()
		agreement.cash_price = 820 if settlement_mode == "Installment" else 800
		agreement.disclosed_markup = 150
		agreement.approved_fees = 30
		agreement.tax_amount = 0
		agreement.down_payment = 100 if settlement_mode == "Installment" else 980
		agreement.insert(ignore_permissions=True)
		agreement.submit()

		from stabler.api.vehicle_finance.schedule import build_schedule

		if settlement_mode == "Cash":
			rows = build_schedule(
				total=980,
				down_payment=980,
				currency_precision=2,
				plan_type="Equal Monthly",
				agreement_date=today(),
				settlement_mode="Cash",
			)
		else:
			rows = build_schedule(
				total=1000,
				down_payment=100,
				currency_precision=2,
				plan_type="Equal Monthly",
				agreement_date=today(),
				first_installment_date=add_months(today(), 1),
				installment_count=3,
			)
		version = frappe.new_doc("Vehicle Finance Schedule Version")
		version.agreement = agreement.name
		version.version_number = 1
		version.effective_date = today()
		version.status = "Active"
		version.plan_type = "Equal Monthly"
		version.approved_by = "Administrator"
		for row in rows:
			version.append(
				"rows",
				{
					"sequence": row["sequence"],
					"due_date": row["due_date"],
					"amount": row["amount"],
					"row_type": row["row_type"],
				},
			)
		version.insert(ignore_permissions=True)
		version.submit()
		agreement.flags.vf_internal = True
		agreement.active_schedule_version = version.name
		agreement.agreement_status = "Approved"
		agreement.approved_by = "Administrator"
		agreement.save(ignore_permissions=True)
		return agreement.name

	def _make_viewer_only_user(self):
		if not frappe.db.exists("User", VIEWER_EMAIL):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": VIEWER_EMAIL,
					"first_name": "VF Read Viewer Test",
					"send_welcome_email": 0,
				}
			)
			user.insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", VIEWER_EMAIL)
		user.add_roles("Vehicle Finance Viewer")
		return VIEWER_EMAIL

	# --- 1. multi-currency totals are never summed across currencies -------------

	def test_agreement_list_and_operations_summary_keep_currencies_separate(self):
		# FrappeTestCase in this environment shares one class-level transaction
		# across test methods (no per-test rollback), so other tests in this
		# class may already have their own agreements sitting in the same
		# company/currency buckets. Measure deltas, not absolute totals, so
		# this test proves "currencies are never summed together" regardless
		# of test execution order or what siblings left behind.
		before_list = read.agreement_list(company=COMPANY)["totals_by_currency"]
		before_summary = read.operations_summary(company=COMPANY)["totals_by_currency"]

		self._make_agreement(direction="Disposition", currency="USD", vin="VF-VIN-USD1")
		self._make_agreement(direction="Disposition", currency="UZS", vin="VF-VIN-UZS1")

		listing = read.agreement_list(company=COMPANY)["totals_by_currency"]
		usd_delta = listing["USD"]["total"] - before_list.get("USD", {}).get("total", 0)
		uzs_delta = listing["UZS"]["total"] - before_list.get("UZS", {}).get("total", 0)
		self.assertEqual(usd_delta, 1000)
		self.assertEqual(uzs_delta, 1000)

		summary = read.operations_summary(company=COMPANY)["totals_by_currency"]
		usd_summary_delta = summary["USD"]["total_contract_price"] - before_summary.get("USD", {}).get(
			"total_contract_price", 0
		)
		uzs_summary_delta = summary["UZS"]["total_contract_price"] - before_summary.get("UZS", {}).get(
			"total_contract_price", 0
		)
		self.assertEqual(usd_summary_delta, 1000)
		self.assertEqual(uzs_summary_delta, 1000)

	# --- 2. cost/margin key is genuinely absent without the capability -----------

	def test_vehicle_detail_hides_cost_margin_key_without_capability(self):
		unit = self._make_vehicle("VF-VIN-COSTMARGIN")

		as_admin = read.vehicle_detail(unit)
		self.assertIn("cost_margin", as_admin)

		viewer_email = self._make_viewer_only_user()
		frappe.set_user(viewer_email)
		try:
			as_viewer = read.vehicle_detail(unit)
			self.assertNotIn("cost_margin", as_viewer)
		finally:
			frappe.set_user("Administrator")

	# --- 3. module disabled / unknown company refuse before any row is read ------

	def test_unknown_company_refuses_before_reading_rows(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			read.agreement_list(company="Definitely Not A Real Company")
		self.assertIn("Unknown company", str(ctx.exception))

	def test_module_disabled_company_refuses_before_reading_rows(self):
		settings = frappe.get_single("Stabler Settings")
		for row in settings.company_modules or []:
			if row.company == COMPANY:
				row.enable_installment = 0
		settings.save(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError) as ctx:
			read.agreement_list(company=COMPANY)
		self.assertIn("installment module is not enabled", str(ctx.exception))

	# --- 4. Legacy engine is a clear "not enabled" error, not a permission error -

	def test_legacy_engine_company_gets_clear_not_enabled_error(self):
		vf_settings = frappe.get_doc("Vehicle Finance Settings", {"company": COMPANY})
		vf_settings.installment_engine = "Legacy"
		vf_settings.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError) as ctx:
			read.agreement_list(company=COMPANY)
		self.assertIn("Agreement V1 is not enabled", str(ctx.exception))

	# --- 5. outstanding has exactly one definition, everywhere it is read --------

	def test_agreement_detail_outstanding_matches_allocation_preview_open_total(self):
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		v1.collect_customer_payment(name, 150, mode_of_payment="Cash", bank_account=self.bank)

		detail = read.agreement_detail(name)
		preview = v1.allocation_preview(name, amount=50)
		self.assertEqual(detail["outstanding"], preview["open_total"])

	# --- 6. schedule_preview reports a row-sum/total mismatch as a failure -------

	def test_schedule_preview_reports_row_sum_mismatch_as_failure(self):
		payload = {
			"company": COMPANY,
			"currency": "USD",
			"currency_precision": 2,
			"total": 1000,
			"down_payment": 100,
			"agreement_date": today(),
			"custom_rows": [
				{"sequence": 0, "due_date": today(), "amount": 100, "row_type": "Down Payment"},
				{"sequence": 1, "due_date": add_months(today(), 1), "amount": 500, "row_type": "Installment"},
			],
		}
		result = read.schedule_preview(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["rows"], [])
		invariant = result["invariants"][0]
		self.assertEqual(invariant["name"], "schedule_builds")
		self.assertFalse(invariant["passed"])
		self.assertIn("600", invariant["message"])
		self.assertIn("1000", invariant["message"])

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		frappe.db.delete("User", VIEWER_EMAIL)

		for pe in frappe.get_all("Payment Entry", filters={"reference_no": ("like", "VFA-%")}, pluck="name"):
			try:
				doc = frappe.get_doc("Payment Entry", pe)
				if doc.docstatus == 1:
					doc.flags.ignore_links = True
					doc.cancel()
				frappe.db.delete("Payment Entry", pe)
			except Exception:
				pass

		for dt in ["Sales Invoice", "Purchase Invoice"]:
			for inv in frappe.get_all(dt, filters={"remarks": ("like", "%Vehicle Finance%")}, pluck="name"):
				try:
					doc = frappe.get_doc(dt, inv)
					if doc.docstatus == 1:
						doc.flags.ignore_links = True
						doc.cancel()
					frappe.db.delete(dt, inv)
				except Exception:
					pass

		for dt in ["Delivery Note", "Purchase Receipt"]:
			for st in frappe.get_all(dt, filters={"company": COMPANY}, pluck="name"):
				items = frappe.get_all(f"{dt} Item", filters={"parent": st, "item_code": "VF-CAR"})
				if items:
					try:
						doc = frappe.get_doc(dt, st)
						if doc.docstatus == 1:
							doc.flags.ignore_links = True
							doc.cancel()
						frappe.db.delete(dt, st)
					except Exception:
						pass

		for dt in [
			"Vehicle Finance Payment Application",
			"Vehicle Finance Schedule Version",
			"Vehicle Agreement",
			"Vehicle Unit",
		]:
			frappe.db.delete(dt, {"company": COMPANY})

		for dt, field, val in [
			("Customer", "customer_name", "VF Test Customer"),
			("Supplier", "supplier_name", "VF Test Supplier"),
			("Item", "item_code", "VF-CAR"),
			("Item", "item_code", "VF-FEE"),
		]:
			names = frappe.get_all(dt, filters={field: val}, pluck="name")
			for n in names:
				frappe.db.delete(dt, n)

		frappe.db.delete("Vehicle Finance Settings", {"company": COMPANY})
		frappe.db.commit()
