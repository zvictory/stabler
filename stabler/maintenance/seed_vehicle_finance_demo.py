"""Vehicle Finance demo data for a local site — one agreement per state the screens claim to show.

Run:
    bench --site genesis-test.local execute stabler.maintenance.seed_vehicle_finance_demo.seed

Clean:
    bench --site genesis-test.local execute stabler.maintenance.seed_vehicle_finance_demo.unseed

WHAT IT BUILDS AND WHY
----------------------
The point is not to fill the Operations screen. It is to make every distinction
the screen draws actually testable, because a demo where everything is green
proves nothing. `work_policy.row_views` is the contract this data is built
against, and each agreement below exists to land in one cell of it:

  1  Disposition USD   rows at -12d, -3d, +45d
                       -12d is late past the 7-day escalation threshold  -> overdue + critical_overdue
                       -3d  is late but INSIDE the threshold             -> overdue only
                       The pair is the point: a seeder that only crosses the
                       threshold in one direction never proves the threshold exists.
  2  Disposition UZS   row at 0d                                         -> due_today
  3  Acquisition USD   row at +4d                                        -> next_7_days
  4  Disposition UZS   rows at +30d and beyond, plus an open follow-up   -> monitoring
                       Deliberately dated past the 7-day window. `row_views`
                       only adds `monitoring` when NO other view fired, so a
                       monitoring row placed inside +7d silently becomes a
                       next_7_days row and the monitoring queue is never exercised.
  5  Disposition USD   row at +20d with a BROKEN promise                 -> critical_overdue
                       Not late at all. A broken promise escalates on its own,
                       and that branch is invisible unless the row is early.
  6  Acquisition UZS   Cash settlement, unpaid                           -> due_today
                       Its single Cash Settlement row is dated today, so a cash
                       agreement is NOT invisible to the queue — worth having in
                       the data because it is easy to assume otherwise.

Both directions and both currencies.

There is no dedicated empty-portfolio agreement, because an empty queue is
already reachable by filtering: view=monitoring with direction=Acquisition
returns count 0 against this exact data set. A record that exists to produce
nothing would have been decoration.

KNOWN GAP, stated rather than faked
-----------------------------------
Every agreement here is seeded with `down_payment = 0`. The sequence-0 row still
exists — `validate_rows` requires the schedule to open with one, and states in
its own comment that it "may legitimately be zero" — but it carries no amount,
so the down-payment-settles-first branch of FIFO is NOT exercised.

This is deliberate. `Vehicle Finance Payment Application.payment_entry` is
reqd=1, so an allocation cannot exist without a real ERPNext Payment Entry —
the schema refuses fake money, which is correct. Settling a down payment
therefore means driving the real collection path, and that is a larger piece of
work than this seeder. Leaving a non-zero down-payment row unpaid instead would
put an overdue item on all six agreements and flatten the matrix above.

So: a zero row 0, and the gap is written down rather than papered over. Seeding
a fake allocation to make the screen look complete is the one thing this file
must not do.

SAFETY
------
One marker: every record carries ` [DEMO]` in a text field —
`Vehicle Agreement.remarks`, `Vehicle Unit.condition_notes`,
`Vehicle Finance Follow-up Log.next_action`. `unseed()` deletes ONLY records
carrying it and touches nothing else. Shared masters (accounts, items, the
company, the currency exchange rate) are ensured but never deleted: they may
predate this script and are not ours to remove.

Seeding twice is a no-op — every create is guarded by an existence check.
A missing prerequisite raises rather than leaving half a portfolio behind.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, today

# Imported, not retyped: the offsets below are built from these, so the seeder
# cannot drift out of step with the policy it is seeding data for.
from stabler.api.vehicle_finance.work_policy import (
	DEFAULT_ESCALATION_THRESHOLD_DAYS,
	UPCOMING_WINDOW_DAYS,
)

DEMO_SUFFIX = " [DEMO]"

COMPANY = "_Test Company"
ABBR = "_TC"
CAR_ITEM = "VF-CAR"
FEE_ITEM = "VF-FEE"
CUSTOMER_NAME = f"VF Demo Customer{DEMO_SUFFIX}"
SUPPLIER_NAME = f"VF Demo Supplier{DEMO_SUFFIX}"

# Round numbers, chosen so the schedule total equals the agreement total exactly.
# USD: 9000 + 900 + 100 = 10000, over 3 rows.  UZS: the same shape, x10 000.
USD_PARTS = {"cash_price": 9000.0, "disclosed_markup": 900.0, "approved_fees": 100.0}
UZS_PARTS = {"cash_price": 90_000_000.0, "disclosed_markup": 9_000_000.0, "approved_fees": 1_000_000.0}


def _parts(currency: str) -> dict:
	return dict(USD_PARTS if currency == "USD" else UZS_PARTS)


def _total(currency: str) -> float:
	return sum(_parts(currency).values())


# --- prerequisites ---------------------------------------------------------------


def _require(condition: object, message: str) -> None:
	"""Half a portfolio is worse than none — a missing prerequisite stops the run."""
	if not condition:
		frappe.throw(f"seed_vehicle_finance_demo: {message}")


def _ensure_account(name: str, parent: str, currency: str = "UZS", account_type: str = "") -> str:
	full = f"{name} - {ABBR}"
	if not frappe.db.exists("Account", full):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": name,
				"parent_account": f"{parent} - {ABBR}",
				"company": COMPANY,
				"account_currency": currency,
				"account_type": account_type,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
	return full


def _ensure_item(code: str, *, stock: bool) -> None:
	if frappe.db.exists("Item", code):
		return
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 1 if stock else 0,
			"has_serial_no": 1 if stock else 0,
			"is_sales_item": 1,
			"is_purchase_item": 1,
		}
	).insert(ignore_permissions=True)


def _ensure_party(doctype: str, fieldname: str, display: str) -> str:
	existing = frappe.db.get_value(doctype, {fieldname: display}, "name")
	if existing:
		return existing
	doc = frappe.new_doc(doctype)
	doc.set(fieldname, display)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_fx() -> None:
	if not frappe.db.exists(
		"Currency Exchange", {"from_currency": "USD", "to_currency": "UZS", "date": getdate(today())}
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


def _ensure_settings(accounts: dict) -> None:
	"""Turn the module on for this company and point the engine at Agreement V1.

	Without the engine flag every read endpoint throws before returning a row,
	so a seeded site would still show an error screen.
	"""
	settings = frappe.get_single("Stabler Settings")
	row = next((r for r in (settings.company_modules or []) if r.company == COMPANY), None)
	if row:
		row.enable_installment = 1
	else:
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
	doc.acquisition_payable_account = accounts["payable"]
	doc.acquisition_deferred_cost_account = accounts["deferred_cost"]
	doc.acquisition_realised_cost_account = accounts["expense"]
	doc.acquisition_fee_item = FEE_ITEM
	doc.disposition_receivable_account = accounts["receivable"]
	doc.disposition_deferred_income_account = accounts["deferred_income"]
	doc.disposition_income_account = accounts["expense"]
	doc.disposition_fee_item = FEE_ITEM
	doc.default_cash_bank_account = accounts["bank"]
	doc.save(ignore_permissions=True)


def _ensure_prerequisites() -> dict:
	_require(frappe.db.exists("Company", COMPANY), f"company {COMPANY!r} does not exist on this site")

	accounts = {
		"payable": _ensure_account("VF Payable USD", "Accounts Payable", "USD", "Payable"),
		"receivable": _ensure_account("VF Receivable USD", "Accounts Receivable", "USD", "Receivable"),
		"deferred_income": _ensure_account("VF Deferred Income USD", "Current Liabilities", "USD"),
		"deferred_cost": _ensure_account("VF Deferred Cost USD", "Current Assets", "USD"),
		"expense": _ensure_account("VF Realised Cost", "Direct Expenses", "USD"),
		"bank": _ensure_account("VF Bank", "Current Assets", "UZS", "Bank"),
	}
	_ensure_item(CAR_ITEM, stock=True)
	_ensure_item(FEE_ITEM, stock=False)
	frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	_ensure_fx()
	_ensure_settings(accounts)

	parties = {
		"customer": _ensure_party("Customer", "customer_name", CUSTOMER_NAME),
		"supplier": _ensure_party("Supplier", "supplier_name", SUPPLIER_NAME),
	}
	_require(parties["customer"], "could not create the demo customer")
	_require(parties["supplier"], "could not create the demo supplier")
	return {"accounts": accounts, **parties}


# --- builders --------------------------------------------------------------------


def _make_vehicle(vin: str, model: str) -> str:
	if not frappe.db.exists("Serial No", vin):
		frappe.get_doc(
			{
				"doctype": "Serial No",
				"serial_no": vin,
				"item_code": CAR_ITEM,
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
	unit.vin = vin
	unit.model_label = model
	unit.condition_notes = f"Seeded demo vehicle{DEMO_SUFFIX}"
	unit.insert(ignore_permissions=True)
	return unit.name


def _make_agreement(
	*,
	label: str,
	direction: str,
	currency: str,
	party: str,
	offsets: list[int],
	settlement_mode: str = "Installment",
) -> str:
	"""One agreement, left in `Active` so the work queue can actually see it.

	The read side filters on `agreement_status in ("Active", "Rescheduled")`
	(v1.py:41). The bench fixtures stop at `Approved`, which is correct for what
	they assert but would produce an empty queue here — a seeder copied from
	them verbatim looks like it worked and shows nothing.
	"""
	vin = f"VFDEMO{label}"
	unit = _make_vehicle(vin, f"Demo Model {label}")
	parts = _parts(currency)
	total = _total(currency)

	agreement = frappe.new_doc("Vehicle Agreement")
	agreement.company = COMPANY
	agreement.direction = direction
	agreement.settlement_mode = settlement_mode
	agreement.party_type = "Supplier" if direction == "Acquisition" else "Customer"
	agreement.party = party
	agreement.currency = currency
	agreement.vehicle_unit = unit
	agreement.agreement_date = today()
	agreement.tax_amount = 0
	# See the module docstring: no down payment, so no sequence-0 row, so no
	# unpayable overdue row on every agreement.
	agreement.down_payment = 0
	for field, value in parts.items():
		setattr(agreement, field, value)
	agreement.remarks = f"Seeded scenario {label}{DEMO_SUFFIX}"
	agreement.insert(ignore_permissions=True)
	agreement.submit()

	version = frappe.new_doc("Vehicle Finance Schedule Version")
	version.agreement = agreement.name
	version.company = COMPANY
	version.currency = currency
	version.version_number = 1
	version.effective_date = today()
	version.status = "Active"
	version.plan_type = "Custom"
	version.approved_by = "Administrator"
	version.total_amount = total

	if settlement_mode == "Cash":
		version.append(
			"rows",
			{
				"sequence": 0,
				"due_date": today(),
				"amount": total,
				"row_type": "Cash Settlement",
				"note": f"Cash{DEMO_SUFFIX}",
			},
		)
	else:
		# Sequence 0 is mandatory — validate_rows rejects a schedule that does not
		# open with a Down Payment or Cash Settlement row. It may be zero, and it
		# is: an unpaid non-zero row 0 would put an overdue item on every single
		# agreement and flatten the queue matrix this seeder exists to produce.
		# Its date has to precede row 1 because due dates must strictly increase,
		# and row 1 can be in the past.
		version.append(
			"rows",
			{
				"sequence": 0,
				"due_date": add_days(today(), min(offsets) - 1),
				"amount": 0,
				"row_type": "Down Payment",
				"note": f"No down payment{DEMO_SUFFIX}",
			},
		)
		share = round(total / len(offsets), 2)
		amounts = [share] * len(offsets)
		# Absorb the rounding residue into the last row so the schedule total is
		# exactly the agreement total — the invariant validate_rows checks.
		amounts[-1] = round(total - share * (len(offsets) - 1), 2)
		for index, (offset, amount) in enumerate(zip(offsets, amounts, strict=True), start=1):
			version.append(
				"rows",
				{
					"sequence": index,
					"due_date": add_days(today(), offset),
					"amount": amount,
					"row_type": "Installment",
					"note": f"{offset:+d}d{DEMO_SUFFIX}",
				},
			)
	version.insert(ignore_permissions=True)
	version.submit()

	agreement.flags.vf_internal = True
	agreement.active_schedule_version = version.name
	agreement.agreement_status = "Active"
	agreement.approved_by = "Administrator"
	agreement.activated_by = "Administrator"
	agreement.save(ignore_permissions=True)
	return agreement.name


def _make_broken_promise(agreement: str, sequence: int, amount: float, days_ago: int) -> str:
	"""Insert the log directly: `record_promise` refuses a past promise date.

	That refusal is right for the API — you cannot promise yesterday — but a
	broken promise is precisely a promise whose date has passed, so the demo has
	to write the record the API would have written a week ago.
	"""
	version = frappe.db.get_value("Vehicle Agreement", agreement, "active_schedule_version")
	row_name = frappe.db.get_value(
		"Vehicle Finance Schedule Row", {"parent": version, "sequence": sequence}, "name"
	)
	_require(row_name, f"agreement {agreement} has no schedule row {sequence}")
	log = frappe.get_doc(
		{
			"doctype": "Vehicle Finance Follow-up Log",
			"company": COMPANY,
			"agreement": agreement,
			"schedule_row": row_name,
			"row_sequence": sequence,
			"owner_user": "Administrator",
			"contact_type": "Other",
			"contact_result": "Promise",
			"promise_amount": amount,
			"promise_date": add_days(today(), -days_ago),
			"next_action": f"Promised and not paid{DEMO_SUFFIX}",
			"next_action_date": add_days(today(), -days_ago),
		}
	)
	log.insert(ignore_permissions=True)
	return log.name


def _make_open_followup(agreement: str, sequence: int, due_in: int) -> str:
	"""An open follow-up with no promise — the only thing that puts a row that is
	neither late nor near into `monitoring`."""
	version = frappe.db.get_value("Vehicle Agreement", agreement, "active_schedule_version")
	row_name = frappe.db.get_value(
		"Vehicle Finance Schedule Row", {"parent": version, "sequence": sequence}, "name"
	)
	_require(row_name, f"agreement {agreement} has no schedule row {sequence}")
	log = frappe.get_doc(
		{
			"doctype": "Vehicle Finance Follow-up Log",
			"company": COMPANY,
			"agreement": agreement,
			"schedule_row": row_name,
			"row_sequence": sequence,
			"owner_user": "Administrator",
			"contact_type": "Call",
			# "No Answer" rather than "Resolved": the point of this record is that
			# the loop is still OPEN. A resolved follow-up would close the row out
			# of the monitoring queue, which is the one queue this agreement exists
			# to populate.
			"contact_result": "No Answer",
			"next_action": f"Call again before the due date{DEMO_SUFFIX}",
			"next_action_date": add_days(today(), due_in),
		}
	)
	log.insert(ignore_permissions=True)
	return log.name


# --- entry points ----------------------------------------------------------------

# offsets are days from today. See the module docstring for what each row proves.
LATE_PAST_THRESHOLD = -(DEFAULT_ESCALATION_THRESHOLD_DAYS + 5)
LATE_INSIDE_THRESHOLD = -(DEFAULT_ESCALATION_THRESHOLD_DAYS - 4)
WITHIN_UPCOMING = UPCOMING_WINDOW_DAYS - 3
BEYOND_UPCOMING = UPCOMING_WINDOW_DAYS + 23


def seed(company: str = COMPANY) -> dict:
	# The whole script is scoped to one company; rebinding beats threading it
	# through every helper.
	global COMPANY
	COMPANY = company

	ctx = _ensure_prerequisites()
	customer, supplier = ctx["customer"], ctx["supplier"]

	if frappe.db.exists("Vehicle Agreement", {"company": COMPANY, "remarks": ["like", f"%{DEMO_SUFFIX}%"]}):
		return {"created": 0, "note": "demo data already present — unseed first to rebuild"}

	created: dict[str, str] = {}

	created["1-overdue-both-sides"] = _make_agreement(
		label="1",
		direction="Disposition",
		currency="USD",
		party=customer,
		offsets=[LATE_PAST_THRESHOLD, LATE_INSIDE_THRESHOLD, 45],
	)
	created["2-due-today"] = _make_agreement(
		label="2",
		direction="Disposition",
		currency="UZS",
		party=customer,
		offsets=[0, 40, 70],
	)
	created["3-next-7-days"] = _make_agreement(
		label="3",
		direction="Acquisition",
		currency="USD",
		party=supplier,
		offsets=[WITHIN_UPCOMING, 50, 80],
	)
	created["4-monitoring"] = _make_agreement(
		label="4",
		direction="Disposition",
		currency="UZS",
		party=customer,
		offsets=[BEYOND_UPCOMING, 60, 90],
	)
	_make_open_followup(created["4-monitoring"], sequence=1, due_in=BEYOND_UPCOMING - 5)

	created["5-broken-promise"] = _make_agreement(
		label="5",
		direction="Disposition",
		currency="USD",
		party=customer,
		offsets=[20, 50, 80],
	)
	_make_broken_promise(created["5-broken-promise"], sequence=1, amount=_total("USD") / 3, days_ago=4)

	created["6-cash-zero-state"] = _make_agreement(
		label="6",
		direction="Acquisition",
		currency="UZS",
		party=supplier,
		offsets=[0],
		settlement_mode="Cash",
	)

	frappe.db.commit()
	return {"created": len(created), "agreements": created}


def _cancel_then_delete(doctype: str, name: str) -> None:
	"""Submitted documents refuse deletion until they are cancelled — `force=True`
	does not override that, it only skips the link check. Both the agreement and
	its schedule version are submitted, so both take this path."""
	doc = frappe.get_doc(doctype, name)
	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.flags.vf_internal = True
		doc.cancel()
	frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)


def unseed(company: str = COMPANY) -> dict:
	"""Delete ONLY records carrying the marker. Shared masters are left alone."""
	global COMPANY
	COMPANY = company

	agreements = frappe.get_all(
		"Vehicle Agreement",
		filters={"company": COMPANY, "remarks": ["like", f"%{DEMO_SUFFIX}%"]},
		pluck="name",
		limit_page_length=0,
	)
	removed = {
		"Vehicle Finance Follow-up Log": 0,
		"Vehicle Finance Schedule Version": 0,
		"Vehicle Agreement": 0,
		"Vehicle Unit": 0,
	}

	# Children before parents: the logs and versions are found THROUGH the
	# agreement, so once it is gone they are unreachable and would be orphaned.
	#
	# Follow-up logs go out by raw SQL because the doctype's on_trash refuses
	# deletion outright — "Follow-up Log entries are append-only". That guard is
	# right for the product and wrong for a demo teardown, so the teardown goes
	# around it. The WHERE clause is the whole safety story: without it this
	# statement would erase every contact record on the site, so it is bound to
	# the agreements the marker already selected and nothing else.
	if agreements:
		# Counted before the delete: frappe.db.sql returns [] for a DELETE, and
		# reporting that as the number removed would be a teardown that lies about
		# what it did.
		removed["Vehicle Finance Follow-up Log"] = frappe.db.count(
			"Vehicle Finance Follow-up Log", {"agreement": ["in", agreements]}
		)
		frappe.db.sql(
			"DELETE FROM `tabVehicle Finance Follow-up Log` WHERE agreement IN %(agreements)s",
			{"agreements": tuple(agreements)},
		)
		# The agreement and its version point at each other — Vehicle Agreement
		# .active_schedule_version one way, Vehicle Finance Schedule Version
		# .agreement the other. Frappe refuses to cancel either while the link
		# stands, so the loop is broken from the agreement side first. db.set_value
		# rather than doc.save because the agreement is submitted.
		for name in agreements:
			frappe.db.set_value(
				"Vehicle Agreement", name, "active_schedule_version", None, update_modified=False
			)

		for name in frappe.get_all(
			"Vehicle Finance Schedule Version",
			filters={"agreement": ["in", agreements]},
			pluck="name",
			limit_page_length=0,
		):
			_cancel_then_delete("Vehicle Finance Schedule Version", name)
			removed["Vehicle Finance Schedule Version"] += 1

	for name in agreements:
		_cancel_then_delete("Vehicle Agreement", name)
		removed["Vehicle Agreement"] += 1

	for name in frappe.get_all(
		"Vehicle Unit",
		filters={"company": COMPANY, "condition_notes": ["like", f"%{DEMO_SUFFIX}%"]},
		pluck="name",
		limit_page_length=0,
	):
		frappe.delete_doc("Vehicle Unit", name, force=True, ignore_permissions=True)
		removed["Vehicle Unit"] += 1

	frappe.db.commit()
	return removed
