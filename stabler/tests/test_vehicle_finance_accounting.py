"""Vehicle Finance Phase 2 — accounting engine integration (bench).

Real ERPNext documents end to end: activation (stock + invoice with deferred
markup), FIFO collection Payment Entries, same-day cancellation reversals,
rescheduling with an unchanged legal total, FX-safe payment amounts and the
reconciliation report that surfaces — never silently repairs — a mismatch.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, flt, getdate, today

from stabler.api.vehicle_finance import v1
from stabler.tests.fixtures import TEST_COMPANY

COMPANY = TEST_COMPANY
USD_RATE = 12900.0


def _ensure(doctype: str, name: str, values: dict) -> str:
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.new_doc(doctype)
	doc.update({"doctype": doctype, **values})
	if not doc.get("name") and doctype != "Account":
		doc.name = name  # Account autonames from account_name + abbr
	doc.insert(ignore_permissions=True)
	return doc.name


class VehicleFinanceAccountingTest(FrappeTestCase):
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

		# Both masters autoname via naming_series — link by the returned name.
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
					"exchange_rate": USD_RATE,
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

	def _make_agreement(self, *, direction, settlement_mode="Installment", party=None, vin=None):
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
		# Dynamic-Link validation runs before any controller hook, so the
		# caller must seed party_type; validate() still derives/overwrites it
		# server-side as the authority.
		agreement.party_type = "Supplier" if direction == "Acquisition" else "Customer"
		agreement.currency = "USD"
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

	# --- activation ----------------------------------------------------------------

	def test_installment_acquisition_activation(self):
		name = self._make_agreement(direction="Acquisition")
		result = v1.activate_agreement(name)
		self.assertEqual(result["status"], "Active")
		pi = frappe.get_doc("Purchase Invoice", result["documents"]["invoice"])
		self.assertEqual(flt(pi.grand_total), 1000)
		self.assertEqual(pi.currency, "USD")
		self.assertEqual(pi.credit_to, self.payable)
		self.assertEqual(len(pi.payment_schedule), 4)  # row 0 + 3 installments
		markup_line = next(i for i in pi.items if not i.item_code)
		self.assertEqual(markup_line.enable_deferred_expense, 1)
		self.assertEqual(markup_line.deferred_expense_account, self.deferred_cost)
		# idempotent refusal on a second activation
		with self.assertRaises(frappe.ValidationError):
			v1.activate_agreement(name)

	def test_installment_disposition_activation(self):
		acq = v1.activate_agreement(self._make_agreement(direction="Acquisition"))
		vin = frappe.db.get_value(
			"Vehicle Unit",
			frappe.db.get_value("Vehicle Agreement", acq["agreement"], "vehicle_unit"),
			"serial_no",
		)
		# Same VIN, second leg: one inbound + one outbound is legal.
		name = self._make_agreement(direction="Disposition", vin=vin)
		result = v1.activate_agreement(name)
		si = frappe.get_doc("Sales Invoice", result["documents"]["invoice"])
		self.assertEqual(flt(si.grand_total), 1000)
		self.assertEqual(si.debit_to, self.receivable)
		markup_line = next(i for i in si.items if not i.item_code)
		self.assertEqual(markup_line.enable_deferred_revenue, 1)
		self.assertEqual(markup_line.deferred_revenue_account, self.deferred_income)
		serial = frappe.get_doc("Serial No", vin)
		self.assertEqual(serial.status, "Delivered")

	def test_cash_settlement_activation(self):
		result = v1.activate_agreement(self._make_agreement(direction="Disposition", settlement_mode="Cash"))
		si = frappe.get_doc("Sales Invoice", result["documents"]["invoice"])
		self.assertEqual(len(si.payment_schedule), 1)
		self.assertEqual(flt(si.payment_schedule[0].payment_amount), 980)

	def test_activation_blocked_when_field_missing(self):
		name = self._make_agreement(direction="Disposition")
		settings = frappe.get_doc("Vehicle Finance Settings", {"company": COMPANY})
		missing = settings.disposition_receivable_account
		settings.disposition_receivable_account = None
		settings.save(ignore_permissions=True)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				v1.activate_agreement(name)
			self.assertIn("disposition_receivable_account", str(ctx.exception))
		finally:
			settings.disposition_receivable_account = missing
			settings.save(ignore_permissions=True)

	# --- collection / FIFO / FX --------------------------------------------------------

	def test_collect_partial_fifo_and_invoice_outstanding(self):
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		result = v1.collect_customer_payment(name, 150, mode_of_payment="Cash", bank_account=self.bank)
		self.assertEqual(result["payment_entry"], result["payment_entry"])
		allocs = result["allocations"]
		self.assertEqual(allocs[0]["sequence"], 0)  # down payment first
		self.assertEqual(allocs[0]["allocated"], 100)
		self.assertEqual(allocs[1]["allocated"], 50)
		apps = frappe.get_all(
			"Vehicle Finance Payment Application",
			filters={"agreement": name, "docstatus": 1},
			pluck="allocated_amount",
		)
		self.assertEqual(flt(sum(apps)), 150)
		si_name = frappe.db.get_value("Vehicle Agreement", name, "sales_invoice")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si_name, "outstanding_amount")), 850)

	def test_collect_fx_usd_party_uzs_bank(self):
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		result = v1.collect_customer_payment(name, 100, mode_of_payment="Cash", bank_account=self.bank)
		pe = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(pe.payment_type, "Receive")
		self.assertEqual(flt(pe.paid_amount), 100)  # USD party account
		self.assertAlmostEqual(flt(pe.received_amount), 100 * USD_RATE)  # UZS bank
		self.assertEqual(flt(pe.source_exchange_rate), USD_RATE)

	def test_pay_supplier_uzs_bank(self):
		name = self._make_agreement(direction="Acquisition")
		v1.activate_agreement(name)
		result = v1.pay_supplier(name, 100, mode_of_payment="Cash", bank_account=self.bank)
		pe = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(pe.payment_type, "Pay")
		self.assertAlmostEqual(flt(pe.paid_amount), 100 * USD_RATE)  # UZS out of bank
		self.assertEqual(flt(pe.received_amount), 100)  # USD to supplier

	def test_missing_exchange_rate_refuses_to_post(self):
		"""A missing rate must stop the payment, never post it at 1:1.

		Why it matters: a 100 USD collection into the UZS bank account is worth
		1 290 000 UZS. Defaulting the rate to 1.0 posts 100 UZS — a silently
		wrong Payment Entry and a silently wrong GL, with no error anywhere.
		`money.py` already refuses on a missing rate; this engine must too.
		"""
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)  # activation itself needs the rate
		frappe.db.delete("Currency Exchange", {"from_currency": "USD", "to_currency": "UZS"})

		with self.assertRaises(frappe.ValidationError) as caught:
			v1.collect_customer_payment(name, 100, mode_of_payment="Cash", bank_account=self.bank)
		self.assertIn("USD", str(caught.exception))
		# nothing was posted
		self.assertFalse(frappe.get_all("Vehicle Finance Payment Application", filters={"agreement": name}))

	def test_fifo_override_requires_capability_and_reason(self):
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		rows = frappe.get_all(
			"Vehicle Finance Schedule Row",
			filters={"parent": frappe.db.get_value("Vehicle Agreement", name, "active_schedule_version")},
			order_by="sequence",
			pluck="name",
		)
		# Administrator holds every capability; reason is mandatory.
		with self.assertRaises(frappe.ValidationError):
			v1.collect_customer_payment(
				name,
				50,
				mode_of_payment="Cash",
				bank_account=self.bank,
				override_rows=[rows[2]],
			)
		result = v1.collect_customer_payment(
			name,
			50,
			mode_of_payment="Cash",
			bank_account=self.bank,
			override_rows=[rows[2]],
			override_reason="Customer instruction",
		)
		self.assertEqual(result["allocations"][0]["row_name"], rows[2])
		app = frappe.get_all(
			"Vehicle Finance Payment Application",
			filters={"agreement": name, "docstatus": 1},
			fields=["is_fifo_override", "override_reason"],
		)
		self.assertTrue(all(a.is_fifo_override for a in app))
		self.assertTrue(all(a.override_reason == "Customer instruction" for a in app))

	# --- same-day cancellation -----------------------------------------------------------

	def test_cancel_payment_reverses_newest_first(self):
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		result = v1.collect_customer_payment(
			name, 400, mode_of_payment="Cash", bank_account=self.bank
		)  # covers row 0 (100) + row 1 (300)
		pe_name = result["payment_entry"]
		cancelled = v1.cancel_payment(pe_name, reason="mistake")
		self.assertEqual(cancelled["reversed_applications"], 2)
		reversals = frappe.get_all(
			"Vehicle Finance Payment Application",
			filters={"payment_entry": pe_name, "is_reversal": 1, "docstatus": 1},
			fields=["row_sequence", "allocated_amount", "reverses"],
			order_by="creation",
		)
		# newest-covered first: sequence 1 before sequence 0
		self.assertEqual([r.row_sequence for r in reversals], [1, 0])
		self.assertTrue(all(flt(r.allocated_amount) < 0 for r in reversals))
		# originals untouched
		originals = frappe.get_all(
			"Vehicle Finance Payment Application",
			filters={"payment_entry": pe_name, "is_reversal": 0, "docstatus": 1},
			pluck="name",
		)
		self.assertEqual(len(originals), 2)
		# net is zero again
		net = frappe.db.sql(
			"""select sum(allocated_amount) from `tabVehicle Finance Payment Application`
			   where agreement=%s and docstatus=1""",
			name,
		)[0][0]
		self.assertEqual(flt(net), 0)
		self.assertEqual(frappe.db.get_value("Payment Entry", pe_name, "docstatus"), 2)

	# --- rescheduling ------------------------------------------------------------------------

	def test_reschedule_keeps_legal_total_and_applications(self):
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		v1.collect_customer_payment(name, 400, mode_of_payment="Cash", bank_account=self.bank)
		old_version = frappe.db.get_value("Vehicle Agreement", name, "active_schedule_version")

		preview = v1.reschedule_preview(
			name,
			{
				"plan_type": "Equal Monthly",
				"installment_count": 2,
				"first_installment_date": add_months(today(), 2),
			},
		)
		self.assertEqual(preview["legal_total"], 1000)
		self.assertEqual(preview["paid_total"], 400)

		result = v1.approve_reschedule(
			name,
			{
				"plan_type": "Equal Monthly",
				"installment_count": 2,
				"first_installment_date": add_months(today(), 2),
				"reschedule_reason": "Customer hardship",
			},
		)
		self.assertEqual(
			frappe.db.get_value("Vehicle Finance Schedule Version", old_version, "status"), "Superseded"
		)
		new_version = frappe.get_doc("Vehicle Finance Schedule Version", result["new_version"])
		self.assertEqual(int(new_version.version_number), 2)
		self.assertEqual(flt(new_version.total_amount), 1000)  # legal total unchanged
		# every prior application still visible
		apps = frappe.get_all(
			"Vehicle Finance Payment Application",
			filters={"agreement": name, "docstatus": 1, "is_reversal": 0},
			pluck="name",
		)
		self.assertEqual(len(apps), 2)
		self.assertEqual(frappe.db.get_value("Vehicle Agreement", name, "agreement_status"), "Restructured")

	def test_collection_continues_after_reschedule(self):
		"""A restructured agreement must keep collecting on its new schedule.

		Why it matters: rescheduling exists so a struggling customer can keep
		paying. If Restructured stopped collection, every reschedule would
		permanently freeze the receivable and the agreement could never reach
		Completed — the status model's own terminal state.
		"""
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		v1.collect_customer_payment(name, 400, mode_of_payment="Cash", bank_account=self.bank)
		v1.approve_reschedule(
			name,
			{
				"plan_type": "Equal Monthly",
				"installment_count": 2,
				"first_installment_date": add_months(today(), 2),
				"reschedule_reason": "Customer hardship",
			},
		)
		self.assertEqual(frappe.db.get_value("Vehicle Agreement", name, "agreement_status"), "Restructured")

		result = v1.collect_customer_payment(name, 200, mode_of_payment="Cash", bank_account=self.bank)
		self.assertTrue(result["payment_entry"])

		# the new money lands on the NEW version, leaving the old one immutable
		active_version = frappe.db.get_value("Vehicle Agreement", name, "active_schedule_version")
		versions = frappe.get_all(
			"Vehicle Finance Payment Application",
			filters={"payment_entry": result["payment_entry"], "docstatus": 1},
			pluck="schedule_version",
		)
		self.assertTrue(versions)
		self.assertEqual(set(versions), {active_version})

		si_name = frappe.db.get_value("Vehicle Agreement", name, "sales_invoice")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si_name, "outstanding_amount")), 400)

	# --- reconciliation ------------------------------------------------------------------------

	def test_reconciliation_reports_corruption_without_repair(self):
		name = self._make_agreement(direction="Disposition")
		v1.activate_agreement(name)
		v1.collect_customer_payment(name, 150, mode_of_payment="Cash", bank_account=self.bank)
		status = v1.reconciliation_status(COMPANY, agreement=name)
		self.assertEqual(status["issues"], [])

		app = frappe.get_all(
			"Vehicle Finance Payment Application",
			filters={"agreement": name, "docstatus": 1, "is_reversal": 0},
			pluck="name",
		)[0]
		# Deliberately corrupt the ledger behind the framework's back.
		frappe.db.set_value("Vehicle Finance Payment Application", app, "allocated_amount", 999)
		status = v1.reconciliation_status(COMPANY, agreement=name)
		self.assertTrue(any(i["blocking"] for i in status["issues"]))
		# and it must not have repaired anything
		self.assertEqual(
			flt(frappe.db.get_value("Vehicle Finance Payment Application", app, "allocated_amount")), 999
		)

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		# 1. Clean up Payment Entries referencing VFA-
		for pe in frappe.get_all("Payment Entry", filters={"reference_no": ("like", "VFA-%")}, pluck="name"):
			try:
				doc = frappe.get_doc("Payment Entry", pe)
				if doc.docstatus == 1:
					doc.flags.ignore_links = True
					doc.cancel()
				frappe.db.delete("Payment Entry", pe)
			except Exception:
				pass

		# 2. Clean up Sales Invoices & Purchase Invoices
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

		# 3. Clean up Delivery Notes & Purchase Receipts
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

		# 4. Clean up VF doctypes
		for dt in [
			"Vehicle Finance Payment Application",
			"Vehicle Finance Schedule Version",
			"Vehicle Agreement",
			"Vehicle Unit",
		]:
			frappe.db.delete(dt, {"company": COMPANY})

		# 5. Clean up master records
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
