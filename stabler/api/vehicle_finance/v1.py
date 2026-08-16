"""Vehicle Finance Center — Agreement V1 whitelisted endpoints.

Money truth is native ERPNext: Delivery Note/Purchase Receipt are stock truth,
Sales/Purchase Invoice are accounting truth, Payment Entry is cash truth.
The Payment Application ledger only answers "which schedule row did this
payment settle" — it never mutates ERPNext documents and never competes with
the invoice outstanding.

Gate order on every endpoint: company → tenant scope → module → engine →
capability → document permission. Frontend totals are never trusted; every
number is recomputed from stored documents.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today
from frappe.utils.data import now

from stabler.api._accounts import resolve_party_account
from stabler.api._common import _assert_can_read, _assert_can_write, _require_company
from stabler.api.approvals import _assert_company_scope
from stabler.api.money import payment_defaults_for_invoice
from stabler.api.supplier_payment_guard import assert_supplier_payment_currency
from stabler.api.vehicle_finance import activation as activation_mod
from stabler.api.vehicle_finance import allocation as allocation_mod
from stabler.api.vehicle_finance.permissions import (
	_assert_capability,
	_require_agreement_v1,
	_require_vehicle_finance_module,
)
from stabler.api.vehicle_finance.schedule import build_schedule

_ADVANCE_PREFIX = "VFA-ADV-"

# Rescheduling exists so a struggling party keeps paying, so Rescheduled must
# stay collectible — otherwise a reschedule freezes the balance forever and the
# agreement can never reach Completed. Draft/Review/Approved have no invoice yet;
# Restructured/Completed/Terminated are terminal. Restructured is NOT a synonym
# for Rescheduled: it is stamped on the ORIGINAL agreement when a restructure
# closes it and opens a successor, so it must never be collectible
# (docs/decisions/2026-08-16-restructure-closes-and-reopens.md).
_COLLECTIBLE_STATUSES = ("Active", "Rescheduled")


# --- shared loaders -----------------------------------------------------------


def _settings(company: str) -> dict:
	name = frappe.db.get_value("Vehicle Finance Settings", {"company": company}, "name")
	if not name:
		frappe.throw(_("Vehicle Finance Settings is not configured for company {0}.").format(company))
	return frappe.get_doc("Vehicle Finance Settings", name)


def _load_agreement(agreement: str) -> object:
	_assert_can_read("Vehicle Agreement", agreement)
	doc = frappe.get_doc("Vehicle Agreement", agreement)
	_require_company(doc.company)
	_assert_company_scope(doc.company)
	_require_agreement_v1(doc.company)
	return doc


def _active_version(agreement_doc) -> object:
	name = agreement_doc.active_schedule_version or frappe.db.get_value(
		"Vehicle Finance Schedule Version",
		{"agreement": agreement_doc.name, "status": "Active", "docstatus": 1},
		"name",
	)
	if not name:
		frappe.throw(_("Agreement {0} has no active schedule version.").format(agreement_doc.name))
	return frappe.get_doc("Vehicle Finance Schedule Version", name)


def _paid_by_sequence(agreement: str) -> dict[int, float]:
	"""Net allocated per row sequence — reversal rows are negative amounts, so
	the plain sum is already net."""
	rows = frappe.db.sql(
		"""
		select row_sequence, sum(allocated_amount) as total
		from `tabVehicle Finance Payment Application`
		where agreement = %s and docstatus = 1
		group by row_sequence
		""",
		agreement,
		as_dict=True,
	)
	return {int(r.row_sequence): flt(r.total) for r in rows}


def _row_states(version_doc) -> list[dict]:
	paid = _paid_by_sequence(version_doc.agreement)
	return [
		{
			"row_name": row.name,
			"sequence": row.sequence,
			"due_date": str(row.due_date),
			"amount": flt(row.amount),
			"paid": paid.get(int(row.sequence), 0),
		}
		for row in version_doc.rows
	]


def _open_total(row_states: list[dict]) -> float:
	return flt(sum(max(0.0, flt(r["amount"]) - flt(r["paid"])) for r in row_states))


def _to_base_rates(currencies: set[str], company: str) -> dict[str, float]:
	"""Currency → company-base multipliers via the CBU Currency Exchange table
	(latest rate with date <= today), mirroring the money module's lookup."""
	base = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	rates = {base: 1.0}
	for currency in currencies:
		if not currency or currency == base or currency in rates:
			continue
		row = frappe.get_all(
			"Currency Exchange",
			filters={"from_currency": currency, "to_currency": base, "date": ("<=", today())},
			fields=["exchange_rate"],
			order_by="date desc",
			limit=1,
		)
		rate = flt(row[0].exchange_rate) if row else 0.0
		if rate <= 0:
			# Never fall back to 1.0: compute_payment_fx treats a 1.0 as a valid
			# rate, so a missing row would silently post 100 USD as 100 UZS.
			# money.py refuses the same way — a missing rate stops the document.
			frappe.throw(
				_("No exchange rate available from {0} to {1} on {2}.").format(currency, base, today())
			)
		rates[currency] = rate
	return rates


def _currency_precision(currency: str) -> int:
	# Currency.fraction stores a UOM *name* ("Cent"), not a digit count — the
	# usable metadata is the system-wide currency_precision default.
	from frappe.utils import cint

	return cint(frappe.db.get_default("currency_precision")) or 2


# --- activation ---------------------------------------------------------------


def _activation_checks(agreement_doc, settings_doc) -> list[dict]:
	configured = {}
	for field in activation_mod.SETTINGS_FIELDS_BY_DIRECTION.get(agreement_doc.direction, []):
		value = settings_doc.get(field)
		if value and not field.endswith("_item") and "tax_template" not in field:
			# Only Accounts are company-scoped; items and tax templates are not.
			configured[field] = {"company": frappe.db.get_value("Account", value, "company")}
	version = _active_version(agreement_doc)
	return activation_mod.check_activation_gates(
		agreement_doc.as_dict(),
		settings_doc.as_dict(),
		configured_records=configured,
		schedule_rows_total=flt(version.total_amount),
		precision=_currency_precision(agreement_doc.currency),
	)


@frappe.whitelist()
def activation_preview(agreement: str) -> dict:
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, "activate")
	checks = _activation_checks(doc, _settings(doc.company))
	return {
		"agreement": doc.name,
		"status": doc.agreement_status,
		"checks": checks,
		"documents": activation_mod.planned_documents(doc.as_dict()),
		"ready": all(c["passed"] for c in checks),
	}


def _markup_line(agreement_doc, settings_doc) -> dict:
	"""The fixed disclosed markup as a deferred line. Recognition dates run
	from the accounting recognition date to the final contractual due date and
	ERPNext's native deferred engine does the straight-line posting."""
	version = _active_version(agreement_doc)
	final_due = max(str(r.due_date) for r in version.rows)
	deferred = {
		"Disposition": settings_doc.disposition_deferred_income_account,
		"Acquisition": settings_doc.acquisition_deferred_cost_account,
	}[agreement_doc.direction]
	line = {
		"item_name": _("Deferred Murabaha Markup"),
		"qty": 1,
		"uom": "Nos",
		"conversion_factor": 1.0,
		"rate": flt(agreement_doc.disclosed_markup),
		"amount": flt(agreement_doc.disclosed_markup),
		"description": _("Fixed disclosed markup (Murabaha)"),
	}
	if agreement_doc.direction == "Disposition":
		line["income_account"] = settings_doc.disposition_income_account
		line["enable_deferred_revenue"] = 1
		line["deferred_revenue_account"] = deferred
	else:
		line["expense_account"] = settings_doc.acquisition_realised_cost_account
		line["enable_deferred_expense"] = 1
		line["deferred_expense_account"] = deferred
	line["service_start_date"] = getdate(agreement_doc.agreement_date)
	line["service_end_date"] = getdate(final_due)
	return line


def _invoice_payload(agreement_doc, settings_doc, stock_doc) -> dict:
	"""Mirror SI/PI payload: vehicle line at cash price, deferred markup line,
	fee line from Settings; payment_schedule from the active version."""
	version = _active_version(agreement_doc)
	is_disp = agreement_doc.direction == "Disposition"
	party_account = (
		settings_doc.disposition_receivable_account if is_disp else settings_doc.acquisition_payable_account
	)
	acc_key = "income_account" if is_disp else "expense_account"
	acc_val = (
		settings_doc.disposition_income_account if is_disp else settings_doc.acquisition_realised_cost_account
	)

	vehicle_item = {
		"item_code": agreement_doc.item_code,
		"qty": 1,
		"rate": flt(agreement_doc.cash_price),
		"amount": flt(agreement_doc.cash_price),
	}
	if acc_val:
		vehicle_item[acc_key] = acc_val

	payload = {
		"company": agreement_doc.company,
		"currency": agreement_doc.currency,
		"set_posting_time": 1,
		"posting_date": getdate(agreement_doc.agreement_date),
		"remarks": f"Vehicle Finance ({agreement_doc.direction}): {agreement_doc.name}",
		"items": [
			vehicle_item,
			_markup_line(agreement_doc, settings_doc),
		],
		"payment_schedule": [
			{
				"due_date": getdate(r.due_date),
				"invoice_portion": (flt(r.amount) / flt(agreement_doc.total_contract_price)) * 100,
				"payment_amount": flt(r.amount),
				"outstanding": flt(r.amount),
				"paid_amount": 0,
				"description": r.row_type,
			}
			for r in version.rows
		],
	}
	fee_item = {
		"Disposition": settings_doc.disposition_fee_item,
		"Acquisition": settings_doc.acquisition_fee_item,
	}[agreement_doc.direction]
	if flt(agreement_doc.approved_fees) > 0:
		fee_row = {
			"item_code": fee_item,
			"qty": 1,
			"rate": flt(agreement_doc.approved_fees),
			"amount": flt(agreement_doc.approved_fees),
		}
		if acc_val:
			fee_row[acc_key] = acc_val
		payload["items"].append(fee_row)
	if agreement_doc.direction == "Disposition":
		payload.update(
			{
				"doctype": "Sales Invoice",
				"customer": agreement_doc.party,
				"debit_to": party_account,
			}
		)
		if settings_doc.disposition_tax_template:
			payload["taxes_and_charges"] = settings_doc.disposition_tax_template
	else:
		payload.update(
			{
				"doctype": "Purchase Invoice",
				"supplier": agreement_doc.party,
				"credit_to": party_account,
			}
		)
		if settings_doc.acquisition_tax_template:
			payload["taxes_and_charges"] = settings_doc.acquisition_tax_template
	return payload


def _stock_payload(agreement_doc) -> dict:
	"""Delivery Note (Disposition, consumes the Serial No) or Purchase Receipt
	(Acquisition, receives it)."""
	warehouse = (
		frappe.db.get_value("Serial No", agreement_doc.serial_no, "warehouse")
		or frappe.db.get_value(
			"Item Default",
			{"parent": agreement_doc.item_code, "company": agreement_doc.company},
			"default_warehouse",
		)
		or frappe.db.get_value("Stock Settings", None, "default_warehouse")
		or frappe.db.get_value("Warehouse", {"company": agreement_doc.company, "is_group": 0}, "name")
	)
	rates = _to_base_rates({agreement_doc.currency}, agreement_doc.company)
	conv_rate = rates.get(agreement_doc.currency, 1.0)

	if agreement_doc.direction == "Disposition":
		return {
			"doctype": "Delivery Note",
			"company": agreement_doc.company,
			"customer": agreement_doc.party,
			"currency": agreement_doc.currency,
			"conversion_rate": conv_rate,
			"set_posting_time": 1,
			"posting_date": getdate(agreement_doc.agreement_date),
			"items": [
				{
					"item_code": agreement_doc.item_code,
					"qty": 1,
					"rate": flt(agreement_doc.cash_price),
					"serial_no": agreement_doc.serial_no,
					"warehouse": warehouse,
				}
			],
		}
	return {
		"doctype": "Purchase Receipt",
		"company": agreement_doc.company,
		"supplier": agreement_doc.party,
		"currency": agreement_doc.currency,
		"conversion_rate": conv_rate,
		"set_posting_time": 1,
		"posting_date": getdate(agreement_doc.agreement_date),
		"items": [
			{
				"item_code": agreement_doc.item_code,
				"qty": 1,
				"received_qty": 1,
				"rate": flt(agreement_doc.cash_price),
				"serial_no": agreement_doc.serial_no,
				"warehouse": warehouse,
			}
		],
	}


def _submit(doc) -> object:
	doc.insert(ignore_permissions=False)
	doc.flags.ignore_approval_gate = True
	doc.submit()
	return doc


def _assert_invoice_total(invoice_doc, agreement_doc) -> None:
	precision = _currency_precision(agreement_doc.currency)
	if round(flt(invoice_doc.grand_total), precision) != round(
		flt(agreement_doc.total_contract_price), precision
	):
		frappe.throw(
			_(
				"Generated invoice total {0} does not match the agreement total {1}. "
				"Check the configured tax template."
			).format(
				round(flt(invoice_doc.grand_total), precision),
				round(flt(agreement_doc.total_contract_price), precision),
			)
		)


def _reconcile_advances(agreement_doc, version_doc) -> int:
	"""Pre-invoice down-payment advances (PEs tagged VFA-ADV-<agreement>) are
	reconciled to row 0 once the invoice posts."""
	advances = frappe.get_all(
		"Payment Entry",
		filters={
			"reference_no": _ADVANCE_PREFIX + agreement_doc.name,
			"docstatus": 1,
		},
		pluck="name",
	)
	created = 0
	row0 = next((r for r in version_doc.rows if r.sequence == 0), None)
	if not row0 or not advances:
		return created
	paid = flt(_paid_by_sequence(agreement_doc.name).get(0, 0))
	open_amount = flt(row0.amount) - paid
	for pe_name in advances:
		if open_amount <= 0:
			break
		pe_amount = flt(
			frappe.db.get_value("Payment Entry", pe_name, "received_amount")
			if agreement_doc.direction == "Disposition"
			else frappe.db.get_value("Payment Entry", pe_name, "paid_amount")
		)
		applied = min(open_amount, pe_amount)
		if applied <= 0:
			continue
		_write_application(
			agreement_doc=agreement_doc,
			version_doc=version_doc,
			row=row0,
			payment_entry=pe_name,
			amount=applied,
		)
		open_amount = flt(open_amount - applied)
		created += 1
	return created


def _write_application(
	*,
	agreement_doc,
	version_doc,
	row,
	payment_entry: str,
	amount: float,
	is_reversal: int = 0,
	reverses: str | None = None,
	is_fifo_override: int = 0,
	override_reason: str | None = None,
) -> object:
	app = frappe.new_doc("Vehicle Finance Payment Application")
	app.company = agreement_doc.company
	app.agreement = agreement_doc.name
	app.schedule_version = version_doc.name
	app.schedule_row = row.name
	app.row_sequence = row.sequence
	app.payment_entry = payment_entry
	app.allocated_amount = flt(amount)
	app.currency = agreement_doc.currency
	app.is_reversal = is_reversal
	app.reverses = reverses
	app.is_fifo_override = is_fifo_override
	app.override_reason = override_reason
	app.flags.ignore_links = True
	app.insert(ignore_permissions=False, ignore_links=True)
	app.submit()
	return app


@frappe.whitelist()
def activate_agreement(agreement: str) -> dict:
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, "activate")
	if doc.agreement_status == "Active":
		frappe.throw(_("Agreement {0} is already active.").format(doc.name))
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted agreement can be activated."))

	settings_doc = _settings(doc.company)
	checks = _activation_checks(doc, settings_doc)
	failed = next((c for c in checks if not c["passed"]), None)
	if failed:
		frappe.throw(_("Activation blocked: {0}").format(failed["message"]))

	version = _active_version(doc)
	try:
		stock = _submit(frappe.new_doc(**_stock_payload(doc)))
		invoice_payload = _invoice_payload(doc, settings_doc, stock)
		invoice = frappe.get_doc(invoice_payload)
		invoice.set_missing_values()
		invoice.insert(ignore_permissions=False)
		_assert_invoice_total(invoice, doc)
		invoice.flags.ignore_approval_gate = True
		invoice.submit()

		doc.flags.vf_internal = True
		doc.agreement_status = "Active"
		doc.activated_by = frappe.session.user
		doc.activated_on = now()
		doc.active_schedule_version = version.name
		if doc.direction == "Disposition":
			doc.delivery_note = stock.name
			doc.sales_invoice = invoice.name
		else:
			doc.purchase_receipt = stock.name
			doc.purchase_invoice = invoice.name
		doc.save(ignore_permissions=False)

		unit = frappe.get_doc("Vehicle Unit", doc.vehicle_unit)
		unit.flags.vf_internal = True
		if doc.direction == "Disposition":
			unit.disposition_agreement = doc.name
			unit.operational_status = "Delivered"
		else:
			unit.acquisition_agreement = doc.name
			unit.operational_status = "Received"
		unit.save(ignore_permissions=False)

		advanced = _reconcile_advances(doc, version)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	return {
		"agreement": doc.name,
		"status": doc.agreement_status,
		"documents": {
			"stock": stock.name,
			"invoice": invoice.name,
		},
		"advance_applications": advanced,
	}


# --- FIFO allocation / collect / pay ------------------------------------------


def _allocation_payload(agreement_doc, version_doc, row_states, amount, allocations) -> dict:
	return {
		"agreement": agreement_doc.name,
		"currency": agreement_doc.currency,
		"amount": flt(amount),
		"open_total": _open_total(row_states),
		"allocations": allocations,
	}


@frappe.whitelist()
def allocation_preview(agreement: str, amount: float | str, override_rows=None) -> dict:
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, "view")
	version = _active_version(doc)
	states = _row_states(version)
	precision = _currency_precision(doc.currency)
	allocations = allocation_mod.allocate(
		states, flt(amount), override_rows=override_rows, precision=precision
	)
	return _allocation_payload(doc, version, states, flt(amount), allocations)


def _collect_or_pay(
	agreement: str,
	amount,
	mode_of_payment,
	bank_account,
	posting_date,
	override_rows,
	override_reason,
	dry_run,
	capability: str,
) -> dict:
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, capability)
	if doc.agreement_status not in _COLLECTIBLE_STATUSES:
		frappe.throw(_("Agreement {0} is not open for payment.").format(doc.name))
	invoice_doctype = "Sales Invoice" if doc.direction == "Disposition" else "Purchase Invoice"
	invoice_name = doc.sales_invoice or doc.purchase_invoice
	if not invoice_name:
		frappe.throw(_("Agreement {0} has no invoice yet.").format(doc.name))
	_assert_can_read(invoice_doctype, invoice_name)
	invoice = frappe.get_doc(invoice_doctype, invoice_name)

	precision = _currency_precision(doc.currency)
	paid = flt(amount)
	if paid <= 0:
		frappe.throw(_("Payment amount must be greater than zero."))
	if paid > flt(invoice.outstanding_amount) + 1e-9:
		frappe.throw(
			_("Payment amount exceeds the invoice outstanding ({0} {1}).").format(
				flt(invoice.outstanding_amount), doc.currency
			)
		)

	version = _active_version(doc)
	states = _row_states(version)
	is_override = bool(override_rows)
	if is_override:
		settings_doc = _settings(doc.company)
		if not settings_doc.allow_fifo_override:
			frappe.throw(_("FIFO override is disabled for this company."))
		if not override_reason:
			frappe.throw(_("An override reason is mandatory."))
		_assert_capability(frappe.session.user, doc.company, "fifo_override")

	allocations = allocation_mod.allocate(states, paid, override_rows=override_rows, precision=precision)

	if int(dry_run or 0):
		return _allocation_payload(doc, version, states, paid, allocations)

	if not mode_of_payment:
		frappe.throw(_("Mode of payment is required."))
	if not bank_account:
		frappe.throw(_("Cash/bank account is required."))

	defaults = payment_defaults_for_invoice(doc.company, invoice_doctype, invoice_name)
	payment_type = defaults["payment_type"]
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "UZS"
	bank_currency = frappe.db.get_value("Account", bank_account, "account_currency") or company_currency
	rates = _to_base_rates({doc.currency, bank_currency}, doc.company)
	fx = allocation_mod.compute_payment_fx(
		amount=paid,
		party_currency=doc.currency,
		bank_currency=bank_currency,
		to_base_rates=rates,
		payment_type=payment_type,
	)
	assert_supplier_payment_currency(
		doc.company,
		payment_type,
		defaults["party_type"],
		frappe.db.get_value("Account", defaults["party_account"], "account_currency"),
		bank_currency,
	)

	pe = frappe.new_doc("Payment Entry")
	pe.company = doc.company
	pe.posting_date = getdate(posting_date or today())
	pe.payment_type = payment_type
	pe.party_type = defaults["party_type"]
	pe.party = defaults["party"]
	if payment_type == "Receive":
		pe.paid_from = defaults["party_account"]
		pe.paid_to = bank_account
	else:
		pe.paid_from = bank_account
		pe.paid_to = defaults["party_account"]
	pe.paid_amount = flt(fx["paid_amount"])
	pe.received_amount = flt(fx["received_amount"])
	pe.source_exchange_rate = flt(fx["source_exchange_rate"])
	pe.target_exchange_rate = flt(fx["target_exchange_rate"])
	pe.mode_of_payment = mode_of_payment
	pe.reference_no = f"VFA-{doc.name}"
	pe.reference_date = pe.posting_date
	pe.append(
		"references",
		{
			"reference_doctype": invoice_doctype,
			"reference_name": invoice_name,
			"total_amount": flt(invoice.grand_total),
			"outstanding_amount": flt(invoice.outstanding_amount),
			"allocated_amount": min(paid, flt(invoice.outstanding_amount)),
		},
	)
	pe.setup_party_account_field()
	pe.set_missing_values()

	try:
		pe.insert(ignore_permissions=False)
		pe.flags.ignore_approval_gate = True
		pe.submit()
		for alloc in allocations:
			row = next(r for r in version.rows if r.name == alloc["row_name"])
			_write_application(
				agreement_doc=doc,
				version_doc=version,
				row=row,
				payment_entry=pe.name,
				amount=alloc["allocated"],
				is_fifo_override=1 if is_override else 0,
				override_reason=override_reason if is_override else None,
			)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	return {
		**_allocation_payload(doc, version, states, paid, allocations),
		"payment_entry": pe.name,
		"invoice_outstanding": flt(frappe.db.get_value(invoice_doctype, invoice_name, "outstanding_amount")),
	}


@frappe.whitelist()
def collect_customer_payment(
	agreement: str,
	amount: float | str,
	mode_of_payment: str | None = None,
	bank_account: str | None = None,
	posting_date: str | None = None,
	override_rows=None,
	override_reason: str | None = None,
	dry_run: int | str = 0,
) -> dict:
	return _collect_or_pay(
		agreement,
		amount,
		mode_of_payment,
		bank_account,
		posting_date,
		override_rows,
		override_reason,
		dry_run,
		capability="collect",
	)


@frappe.whitelist()
def pay_supplier(
	agreement: str,
	amount: float | str,
	mode_of_payment: str | None = None,
	bank_account: str | None = None,
	posting_date: str | None = None,
	override_rows=None,
	override_reason: str | None = None,
	dry_run: int | str = 0,
) -> dict:
	return _collect_or_pay(
		agreement,
		amount,
		mode_of_payment,
		bank_account,
		posting_date,
		override_rows,
		override_reason,
		dry_run,
		capability="pay_supplier",
	)


# --- same-day cancellation ----------------------------------------------------


@frappe.whitelist()
def cancel_payment(payment_entry: str, reason: str | None = None) -> dict:
	if not payment_entry:
		frappe.throw(_("Payment Entry is required."))
	_assert_can_write("Payment Entry", payment_entry, "cancel")
	pe = frappe.get_doc("Payment Entry", payment_entry)
	_require_company(pe.company)
	_assert_company_scope(pe.company)
	_require_agreement_v1(pe.company)
	_assert_capability(frappe.session.user, pe.company, "cancel_same_day")
	settings_doc = _settings(pe.company)
	if not settings_doc.allow_same_day_payment_cancel:
		frappe.throw(_("Same-day payment cancellation is disabled for this company."))
	if pe.docstatus == 2:
		frappe.throw(_("This payment is already cancelled."))
	if pe.docstatus != 1:
		frappe.throw(_("Only a submitted payment can be cancelled."))
	reference = pe.reference_no or ""
	if not reference.startswith("VFA-"):
		frappe.throw(_("This payment is not a Vehicle Finance payment."))
	if getdate(pe.posting_date) != getdate(today()):
		frappe.throw(_("Only same-day payments can be cancelled."))

	agreement_name = (
		reference[len(_ADVANCE_PREFIX) :]
		if reference.startswith(_ADVANCE_PREFIX)
		else reference[len("VFA-") :]
	)
	originals = frappe.get_all(
		"Vehicle Finance Payment Application",
		filters={"payment_entry": pe.name, "docstatus": 1, "is_reversal": 0},
		fields=["name", "schedule_row", "row_sequence", "allocated_amount", "schedule_version"],
	)
	already_reversed = frappe.db.exists(
		"Vehicle Finance Payment Application",
		{"payment_entry": pe.name, "is_reversal": 1},
	)
	if already_reversed:
		frappe.throw(_("This payment's allocations are already reversed."))

	try:
		if originals and agreement_name:
			agreement_doc = frappe.get_doc("Vehicle Agreement", agreement_name)
			for original in allocation_mod.reversal_plan(originals):
				version_doc = frappe.get_doc("Vehicle Finance Schedule Version", original.schedule_version)
				row = next((r for r in version_doc.rows if r.name == original.schedule_row), None)
				if row is None:
					continue
				_write_application(
					agreement_doc=agreement_doc,
					version_doc=version_doc,
					row=row,
					payment_entry=pe.name,
					amount=-flt(original.allocated_amount),
					is_reversal=1,
					reverses=original.name,
				)
		pe.flags.ignore_approval_gate = True
		pe.flags.ignore_links = True
		pe.cancel()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	return {
		"payment_entry": pe.name,
		"docstatus": pe.docstatus,
		"reversed_applications": len(originals),
		"reason": reason or "",
	}


# --- rescheduling ---------------------------------------------------------------


def _reschedule_rows(agreement_doc, version_doc, payload: dict) -> list[dict]:
	"""Row 0 keeps its FULL original amount (its outstanding is naturally the
	unpaid remainder). Settled portions of later rows travel as closed rows;
	the open remainder is re-planned by the shared builder."""
	paid = _paid_by_sequence(agreement_doc.name)
	rows = sorted(version_doc.rows, key=lambda r: int(r.sequence))
	row0 = rows[0]
	closed: list[dict] = []
	pool = 0.0
	for row in rows[1:]:
		row_paid = flt(paid.get(int(row.sequence), 0))
		closed_amount = min(row_paid, flt(row.amount))
		if closed_amount > 0:
			closed.append(
				{
					"sequence": int(row.sequence),
					"due_date": str(row.due_date),
					"amount": closed_amount,
					"row_type": row.row_type,
					"note": _("settled portion carried into this version"),
				}
			)
		pool += flt(row.amount) - closed_amount

	new_rows: list[dict] = []
	precision = _currency_precision(agreement_doc.currency)
	if pool > 0:
		built = build_schedule(
			total=pool,
			down_payment=0,
			currency_precision=precision,
			plan_type=payload.get("plan_type") or "Equal Monthly",
			agreement_date=str(row0.due_date),
			first_installment_date=payload.get("first_installment_date"),
			installment_count=payload.get("installment_count"),
			balloon_amount=flt(payload.get("balloon_amount") or 0),
		)
		# Row 0 of the built plan is a zero down payment — the agreement's own
		# row 0 already exists; keep only the generated installment rows.
		next_sequence = max([int(r.sequence) for r in rows]) + 1
		for i, built_row in enumerate([r for r in built if r["sequence"] > 0]):
			new_rows.append({**built_row, "sequence": next_sequence + i})
	elif payload.get("custom_rows"):
		raise ValueError("Nothing remains to re-plan; custom rows are not expected.")

	result = [
		{
			"sequence": int(row0.sequence),
			"due_date": str(row0.due_date),
			"amount": flt(row0.amount),
			"row_type": row0.row_type,
			"note": row0.note or "",
		},
		*closed,
		*new_rows,
	]
	# validate via the frozen Phase 1 rules (sum must equal the fixed total)
	from stabler.stabler.doctype.vehicle_finance_schedule_version.vehicle_finance_schedule_version import (
		validate_rows,
	)

	validate_rows(
		result,
		agreement_total=flt(agreement_doc.total_contract_price),
		settlement_mode=agreement_doc.settlement_mode,
		precision=precision,
	)
	return result


def _reschedule_payload(agreement, payload: dict) -> dict:
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, "reschedule")
	version = _active_version(doc)
	rows = _reschedule_rows(doc, version, payload or {})
	paid = _paid_by_sequence(doc.name)
	return {
		"agreement": doc.name,
		"current_version": version.name,
		"new_version_number": int(version.version_number) + 1,
		"legal_total": flt(doc.total_contract_price),
		"paid_total": flt(sum(paid.values())),
		"rows": rows,
	}


@frappe.whitelist()
def reschedule_preview(agreement: str, payload: dict | None = None) -> dict:
	return _reschedule_payload(agreement, payload or {})


@frappe.whitelist()
def approve_reschedule(agreement: str, payload: dict | None = None) -> dict:
	payload = payload or {}
	doc = _load_agreement(agreement)
	_assert_capability(frappe.session.user, doc.company, "reschedule")
	version = _active_version(doc)
	reason = payload.get("reschedule_reason")
	if not reason:
		frappe.throw(_("A reschedule reason is mandatory."))
	rows = _reschedule_rows(doc, version, payload)

	try:
		new_version = frappe.new_doc("Vehicle Finance Schedule Version")
		new_version.agreement = doc.name
		new_version.version_number = int(version.version_number) + 1
		new_version.effective_date = getdate(payload.get("effective_date") or today())
		new_version.status = "Active"
		new_version.plan_type = payload.get("plan_type") or "Equal Monthly"
		new_version.first_installment_date = payload.get("first_installment_date")
		new_version.installment_count = payload.get("installment_count")
		new_version.balloon_amount = flt(payload.get("balloon_amount") or 0)
		new_version.reschedule_reason = reason
		new_version.approved_by = frappe.session.user
		new_version.approved_on = now()
		for row in rows:
			new_version.append(
				"rows",
				{
					"sequence": row["sequence"],
					"due_date": getdate(row["due_date"]),
					"amount": flt(row["amount"]),
					"row_type": row["row_type"],
					"note": row.get("note") or "",
				},
			)
		# Phase 1's single-Active invariant blocks a second Active version, so
		# supersede the prior one first — immutably, by status only.
		frappe.db.set_value("Vehicle Finance Schedule Version", version.name, "status", "Superseded")
		new_version.flags.ignore_approval_gate = True
		new_version.insert(ignore_permissions=False)
		new_version.submit()

		doc.flags.vf_internal = True
		doc.agreement_status = "Rescheduled"
		doc.active_schedule_version = new_version.name
		doc.save(ignore_permissions=False)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	return {
		"agreement": doc.name,
		"superseded_version": version.name,
		"new_version": new_version.name,
		"status": doc.agreement_status,
	}


# --- reconciliation -------------------------------------------------------------


def _reconcile_agreement(doc) -> list[dict]:
	issues: list[dict] = []
	precision = _currency_precision(doc.currency)
	total = flt(doc.total_contract_price)
	component_sum = (
		flt(doc.cash_price) + flt(doc.disclosed_markup) + flt(doc.approved_fees) + flt(doc.tax_amount)
	)
	if round(component_sum, precision) != round(total, precision):
		issues.append(
			{
				"check": "components_equal_total",
				"message": "Components sum to {0} but the agreement total is {1}.".format(
					component_sum, total
				),
			}
		)

	version = None
	if doc.active_schedule_version:
		version = frappe.get_doc("Vehicle Finance Schedule Version", doc.active_schedule_version)
	if version is None:
		issues.append({"check": "active_schedule_exists", "message": "No active schedule version."})
	else:
		row_sum = flt(version.total_amount)
		if round(row_sum, precision) != round(total, precision):
			issues.append(
				{
					"check": "rows_equal_total",
					"message": "Active schedule rows sum to {0} but the agreement total is {1}.".format(
						row_sum, total
					),
				}
			)

	apps = frappe.get_all(
		"Vehicle Finance Payment Application",
		filters={"agreement": doc.name, "docstatus": 1},
		fields=["name", "payment_entry", "allocated_amount", "is_reversal", "reverses", "row_sequence"],
	)
	net = flt(sum(flt(a.allocated_amount) for a in apps))
	positive = flt(sum(flt(a.allocated_amount) for a in apps if not a.is_reversal))

	invoice_doctype = "Sales Invoice" if doc.direction == "Disposition" else "Purchase Invoice"
	invoice_name = doc.sales_invoice or doc.purchase_invoice
	if invoice_name:
		invoice = frappe.get_doc(invoice_doctype, invoice_name)
		moved = flt(invoice.grand_total) - flt(invoice.outstanding_amount)
		if round(net, precision) != round(moved, precision):
			issues.append(
				{
					"check": "allocated_equals_accounting_movement",
					"message": "Allocated payments total {0} but accounting movement is {1}.".format(
						net, moved
					),
				}
			)
		schedule_outstanding = flt(row_sum if version else 0) - net
		if round(schedule_outstanding, precision) != round(flt(invoice.outstanding_amount), precision):
			issues.append(
				{
					"check": "schedule_outstanding_equals_invoice",
					"message": "Schedule outstanding {0} but invoice outstanding is {1}.".format(
						schedule_outstanding, flt(invoice.outstanding_amount)
					),
				}
			)
		if positive > flt(invoice.grand_total) + 10**-precision:
			issues.append(
				{
					"check": "allocation_within_invoice",
					"message": "Allocations exceed the invoice grand total.",
				}
			)

	for app in apps:
		if app.is_reversal:
			original = frappe.db.get_value(
				"Vehicle Finance Payment Application",
				app.reverses,
				"allocated_amount",
			)
			if original is None or round(flt(original) + flt(app.allocated_amount), precision) != 0:
				issues.append(
					{
						"check": "reversal_negates_original",
						"message": "Reversal {0} does not negate its original.".format(app.name),
					}
				)

	return [{"agreement": doc.name, **issue, "blocking": True} for issue in issues]


@frappe.whitelist()
def reconciliation_status(company: str, agreement: str | None = None) -> dict:
	company = _require_company(company)
	_assert_company_scope(company)
	_require_agreement_v1(company)
	_assert_capability(frappe.session.user, company, "view")

	filters = {"company": company, "docstatus": 1}
	if agreement:
		filters["name"] = agreement
	names = frappe.get_all("Vehicle Agreement", filters=filters, pluck="name")
	issues: list[dict] = []
	for name in names:
		_assert_can_read("Vehicle Agreement", name)
		issues.extend(_reconcile_agreement(frappe.get_doc("Vehicle Agreement", name)))
	return {"company": company, "agreements": len(names), "issues": issues}
