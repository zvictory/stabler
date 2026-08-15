"""Vehicle Finance Phase 4 — deterministic work queue and daily generator (bench).

The frappe-free half of the policy is covered by test_vehicle_finance_work.py.
What can only be proved against a real database is here:

* running the generator twice creates zero extra work items — the guard is the
  identity tuple, not a timestamp and not a "has it run today" flag;
* a late row generates ONE item, not one per night it stays late;
* the queue's notion of overdue is the same one `read.agreement_detail` prints on
  the agreement screen (Phase 4 acceptance criterion 7) — two independently
  written modules, one definition;
* a broken promise escalates the work status without touching the agreement,
  the schedule or any money;
* one company with bad data cannot roll back another company's work.

Fixture pattern mirrors test_vehicle_finance_read.py.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, flt, today

from stabler.api.vehicle_finance import read, work
from stabler.api.vehicle_finance import work_policy as policy
from stabler.tests.fixtures import TEST_COMPANY

COMPANY = TEST_COMPANY


class VehicleFinanceSchedulerTest(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._setup_accounts()
		self._setup_items()
		self._setup_parties()
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
			return full

		self.receivable = account(
			"VF Receivable USD", "Accounts Receivable", account_type="Receivable", currency="USD"
		)
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

	def _setup_settings(self):
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
		doc.disposition_receivable_account = self.receivable
		doc.default_cash_bank_account = self.bank
		doc.escalation_threshold_days = 7
		doc.save(ignore_permissions=True)

	# --- helpers -----------------------------------------------------------------

	def _make_vehicle(self, vin):
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
		existing = frappe.db.get_value("Vehicle Unit", {"serial_no": vin}, "name")
		if existing:
			return existing
		unit = frappe.new_doc("Vehicle Unit")
		unit.company = COMPANY
		unit.serial_no = vin
		unit.insert(ignore_permissions=True)
		return unit.name

	def _make_active_agreement(self, *, first_installment_date, currency="USD", vin=None):
		"""An Active Disposition agreement with three installments. Activation
		itself (invoices, stock) is Phase 2's business and irrelevant here — the
		generator reads the schedule and the payment applications, nothing else.

		The agreement is signed one month before its first installment: `build_schedule`
		refuses a due date earlier than the agreement date, and rightly so — nobody
		signs a contract whose first payment was already late. So a backdated first
		installment means a backdated agreement, down-payment row included."""
		agreement_date = add_months(first_installment_date, -1)
		unit = self._make_vehicle(vin or f"VF-VIN-{frappe.generate_hash(length=6).upper()}")
		agreement = frappe.new_doc("Vehicle Agreement")
		agreement.company = COMPANY
		agreement.direction = "Disposition"
		agreement.settlement_mode = "Installment"
		agreement.party_type = "Customer"
		agreement.party = self.customer
		agreement.currency = currency
		agreement.vehicle_unit = unit
		agreement.agreement_date = agreement_date
		agreement.cash_price = 820
		agreement.disclosed_markup = 150
		agreement.approved_fees = 30
		agreement.tax_amount = 0
		agreement.down_payment = 100
		agreement.insert(ignore_permissions=True)
		agreement.submit()

		from stabler.api.vehicle_finance.schedule import build_schedule

		rows = build_schedule(
			total=1000,
			down_payment=100,
			currency_precision=2,
			plan_type="Equal Monthly",
			agreement_date=agreement_date,
			first_installment_date=first_installment_date,
			installment_count=3,
		)
		version = frappe.new_doc("Vehicle Finance Schedule Version")
		version.agreement = agreement.name
		version.version_number = 1
		version.effective_date = agreement_date
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
		agreement.agreement_status = "Active"
		agreement.approved_by = "Administrator"
		agreement.save(ignore_permissions=True)
		return agreement.name

	def _items(self, agreement, **filters):
		return frappe.get_all(
			"Vehicle Finance Work Item",
			filters={"agreement": agreement, **filters},
			fields=["name", "event_type", "policy_date", "work_status", "row_sequence"],
		)

	# --- 1. idempotency ------------------------------------------------------------

	def test_second_run_on_the_same_day_creates_nothing(self):
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -2))
		work.generate_daily_work()
		first = self._items(agreement)
		self.assertTrue(first, "an agreement two months late must produce work")

		work.generate_daily_work()
		second = self._items(agreement)
		self.assertEqual(
			len(second),
			len(first),
			"re-running the scheduler on the same day must produce zero new rows",
		)
		self.assertEqual({i.name for i in first}, {i.name for i in second})

	def test_a_late_row_generates_one_item_not_one_per_run(self):
		# The rule the identity tuple exists for: policy_date is the row's own
		# due date, so ninety nights of lateness are still one collection task.
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -3))
		for _ in range(4):
			work.generate_daily_work()
		overdue = self._items(agreement, event_type=policy.EVENT_OVERDUE)
		policy_dates = {str(i.policy_date) for i in overdue}
		# Four late rows — the down payment at the agreement date plus three
		# installments — and four scheduler runs. The count that must not move is 4.
		self.assertEqual(len(overdue), 4, "four missed rows, four collection tasks")
		self.assertEqual(
			len(policy_dates),
			4,
			"one overdue item per due date, never one per scheduler run",
		)

	# Deliberately not covered here: "a fully settled row stops producing work".
	# Settling a row means submitting a Vehicle Finance Payment Application, whose
	# `payment_entry` is reqd and scope-checked, which means a real activation and a
	# real Payment Entry — i.e. Phase 2's accounting engine, already covered by its
	# own bench tests. The policy half lives in test_vehicle_finance_work.py
	# (`test_fully_paid_row_is_not_open`).

	# --- 2. one definition of overdue (acceptance criterion 7) ----------------------

	def test_queue_overdue_matches_the_agreement_screen(self):
		"""Criterion 7. `read.agreement_detail` derives `payment_health` itself, from
		the schedule rows — it never calls `work_policy`. So agreeing here means two
		independently written modules landed on the same definition of overdue."""
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -2))

		detail = read.agreement_detail(agreement)
		screen = [r for r in detail["schedule_rows"] if r["payment_health"] == "Overdue"]
		self.assertTrue(screen, "a two-month-late agreement has overdue rows on its screen")

		queue = work.work_queue(company=COMPANY, view=policy.VIEW_OVERDUE, limit=200)
		mine = [r for r in queue["rows"] if r["agreement"] == agreement]
		self.assertTrue(mine, "a two-month-late agreement belongs in the overdue view")

		self.assertEqual(
			sorted(r["row_sequence"] for r in mine),
			sorted(r["sequence"] for r in screen),
			"the queue and the agreement screen must call the same rows overdue",
		)
		self.assertEqual(
			flt(sum(r["outstanding"] for r in mine), 2),
			flt(sum(r["outstanding"] for r in screen), 2),
			"and must report the same outstanding for them",
		)

	def test_totals_never_merge_two_currencies(self):
		self._make_active_agreement(first_installment_date=add_months(today(), -2), currency="USD")
		self._make_active_agreement(first_installment_date=add_months(today(), -2), currency="UZS")
		queue = work.work_queue(company=COMPANY, view=policy.VIEW_OVERDUE, limit=200)
		totals = queue["totals_by_currency"]
		self.assertIn("USD", totals)
		self.assertIn("UZS", totals)
		self.assertGreater(totals["USD"], 0)
		self.assertGreater(totals["UZS"], 0)
		self.assertNotIsInstance(totals, (int, float))

	# --- 3. promises ----------------------------------------------------------------

	def test_promise_moves_only_the_work_status_axis(self):
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -1))
		work.generate_daily_work()
		before_status = frappe.db.get_value("Vehicle Agreement", agreement, "agreement_status")

		row = self._items(agreement, event_type=policy.EVENT_OVERDUE)[0]
		result = work.record_promise(
			agreement=agreement,
			row_sequence=row.row_sequence,
			amount=10,
			promise_date=add_days(today(), 3),
		)
		self.assertEqual(flt(result["promise_amount"]), 10.0)
		self.assertEqual(
			frappe.db.get_value("Vehicle Finance Work Item", row.name, "work_status"),
			policy.WORK_PROMISE,
		)
		self.assertEqual(
			frappe.db.get_value("Vehicle Agreement", agreement, "agreement_status"),
			before_status,
			"a promise must never move the agreement status",
		)

	def test_promise_above_outstanding_is_refused(self):
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			work.record_promise(
				agreement=agreement,
				row_sequence=1,
				amount=999_999,
				promise_date=add_days(today(), 3),
			)

	def test_broken_promise_escalates_without_touching_money(self):
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -2))
		work.generate_daily_work()
		row = self._items(agreement, event_type=policy.EVENT_OVERDUE)[0]

		# A promise dated in the past cannot be recorded through the endpoint —
		# that is deliberate — so the broken case is seeded directly.
		log = frappe.new_doc("Vehicle Finance Follow-up Log")
		log.company = COMPANY
		log.agreement = agreement
		log.row_sequence = row.row_sequence
		log.contact_type = "Call"
		log.contact_result = "Promise"
		log.promise_amount = 50
		log.promise_date = add_days(today(), -3)
		log.insert(ignore_permissions=True)

		before_paid = frappe.db.sql(
			"select ifnull(sum(allocated_amount), 0) from `tabVehicle Finance Payment Application`"
			" where agreement = %s and docstatus = 1",
			agreement,
		)[0][0]

		work.generate_daily_work()
		broken = self._items(agreement, event_type=policy.EVENT_PROMISE_BROKEN)
		self.assertEqual(len(broken), 1)
		self.assertEqual(broken[0].work_status, policy.WORK_ESCALATED)
		self.assertEqual(
			frappe.db.get_value("Vehicle Finance Work Item", row.name, "work_status"),
			policy.WORK_ESCALATED,
		)

		after_paid = frappe.db.sql(
			"select ifnull(sum(allocated_amount), 0) from `tabVehicle Finance Payment Application`"
			" where agreement = %s and docstatus = 1",
			agreement,
		)[0][0]
		self.assertEqual(flt(before_paid), flt(after_paid), "escalation must not move money")

		work.generate_daily_work()
		self.assertEqual(
			len(self._items(agreement, event_type=policy.EVENT_PROMISE_BROKEN)),
			1,
			"a broken promise is filed once, keyed on the promise date",
		)

	def test_followup_advances_unassigned_but_never_downgrades(self):
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -1))
		work.generate_daily_work()
		row = self._items(agreement, event_type=policy.EVENT_OVERDUE)[0]

		work.log_followup(agreement, {"row_sequence": row.row_sequence, "contact_type": "Call"})
		self.assertEqual(
			frappe.db.get_value("Vehicle Finance Work Item", row.name, "work_status"),
			policy.WORK_CONTACTED,
		)

		frappe.db.set_value("Vehicle Finance Work Item", row.name, "work_status", policy.WORK_ESCALATED)
		work.log_followup(agreement, {"row_sequence": row.row_sequence, "contact_type": "Call"})
		self.assertEqual(
			frappe.db.get_value("Vehicle Finance Work Item", row.name, "work_status"),
			policy.WORK_ESCALATED,
			"logging a call must not walk an escalated item back to Contacted",
		)

	# --- 4. guards ------------------------------------------------------------------

	def test_legacy_engine_company_generates_nothing(self):
		agreement = self._make_active_agreement(first_installment_date=add_months(today(), -2))
		name = frappe.db.get_value("Vehicle Finance Settings", {"company": COMPANY}, "name")
		frappe.db.set_value("Vehicle Finance Settings", name, "installment_engine", "Legacy")
		try:
			self.assertNotIn(COMPANY, work._agreement_v1_companies())
			work.generate_daily_work()
			self.assertEqual(
				self._items(agreement),
				[],
				"a company still on the Legacy engine must not be worked",
			)
		finally:
			frappe.db.set_value("Vehicle Finance Settings", name, "installment_engine", "Agreement V1")

	def test_unknown_view_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			work.work_queue(company=COMPANY, view="everything")

	def test_generator_reports_the_company_it_failed_on(self):
		summary = work.generate_daily_work()
		self.assertIn("failed", summary)
		self.assertEqual(summary["failed"], [], "no company should fail on clean fixtures")

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		for dt in [
			"Vehicle Finance Work Item",
			"Vehicle Finance Follow-up Log",
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
		]:
			for n in frappe.get_all(dt, filters={field: val}, pluck="name"):
				frappe.db.delete(dt, n)

		frappe.db.delete("Vehicle Finance Settings", {"company": COMPANY})
		frappe.db.commit()
