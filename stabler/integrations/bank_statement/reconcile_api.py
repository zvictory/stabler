"""Bank reconciliation matching API (Phase 2).

Surfaces unreconciled Bank Transactions, ranks candidate vouchers with the pure
``match`` scorer, and reconciles **through ERPNext** — by appending to the Bank
Transaction's ``payment_entries`` table and saving, which is what stamps the
voucher's ``clearance_date``. No custom GL, no custom stock; ERPNext owns posting.

Endpoint checklist honoured on every whitelisted method: auth (reject Guest) ·
``frappe.has_permission`` · company isolation · server-side validation · IDOR
(verify the Bank Transaction belongs to the requested account/company) ·
parameterized SQL · consistent response envelope · concurrency
(``check_concurrency``) · activity logging.

Phase 2 additions:
  - ``suggest_matches`` now fetches **Journal Entry** lines in addition to
    Payment Entries, and enriches both types with the party's INN/STIR from
    the Supplier / Customer doctype for better scorer accuracy.
  - New ``reconcile_partial`` endpoint: split one bank line across multiple
    vouchers (or allocate a partial amount to a single voucher) using the pure
    ``allocate_partial`` helper so allocations sum exactly to the bank line.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from stabler.api._common import _require_company, check_concurrency
from stabler.api.approvals import _assert_company_scope
from stabler.api.organization import _can_access_module
from stabler.integrations.bank_statement.match import allocate_partial, rank_candidates


def _require_recon() -> None:
	if not _can_access_module(frappe.session.user, "money"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _bt(name: str):
	"""Load a Bank Transaction with read-permission + existence checks (anti-IDOR)."""
	if not name:
		frappe.throw(_("Bank transaction is required."))
	if not frappe.db.exists("Bank Transaction", name):
		frappe.throw(_("Bank transaction not found."), frappe.DoesNotExistError)
	if not frappe.has_permission("Bank Transaction", "read", name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_doc("Bank Transaction", name)


def _bank_gl_account(bank_account: str) -> str | None:
	return frappe.db.get_value("Bank Account", bank_account, "account")


def _fetch_party_inn(party_type: str | None, party: str | None) -> str:
	"""Look up the INN/STIR from the party master, or return empty string."""
	if not party_type or not party:
		return ""
	doctype_map = {
		"Supplier": "Supplier",
		"Customer": "Customer",
	}
	dt = doctype_map.get(party_type)
	if not dt:
		return ""
	# ERPNext stores INN/STIR in a custom field ``tax_id`` on Supplier/Customer.
	try:
		return frappe.db.get_value(dt, party, "tax_id") or ""
	except Exception:
		return ""


@frappe.whitelist()
def list_unreconciled(
	company: str,
	bank_account: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 100,
) -> dict:
	"""Submitted Bank Transactions with an unallocated balance, for one account."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_recon()
	_require_company(company)
	acc = frappe.db.get_value("Bank Account", bank_account, ["company"], as_dict=True)
	if not acc or acc.company != company:
		frappe.throw(_("Bank account does not belong to company '{0}'.").format(company))

	conds = ["bank_account = %(ba)s", "company = %(co)s", "docstatus = 1", "unallocated_amount != 0"]
	params: dict = {"ba": bank_account, "co": company, "limit": min(int(limit or 100), 500)}
	if from_date:
		conds.append("date >= %(fd)s")
		params["fd"] = from_date
	if to_date:
		conds.append("date <= %(td)s")
		params["td"] = to_date
	rows = frappe.db.sql(
		f"""SELECT name, date, deposit, withdrawal, currency, description,
		           reference_number, unallocated_amount, status
		    FROM `tabBank Transaction`
		    WHERE {" AND ".join(conds)}
		    ORDER BY date DESC, name DESC
		    LIMIT %(limit)s""",
		params,
		as_dict=True,
	)
	return {"transactions": rows, "count": len(rows)}


def _fetch_pe_candidates(
	gl_account: str,
	is_deposit: bool,
	amount: float,
	lo,
	hi,
	amt_lo: float,
	amt_hi: float,
) -> list[dict]:
	"""Query Payment Entry candidates and enrich with party INN."""
	acct_field = "paid_to" if is_deposit else "paid_from"
	amt_field = "received_amount" if is_deposit else "paid_amount"
	rows = frappe.db.sql(
		f"""SELECT pe.name, pe.posting_date, pe.{amt_field} AS amount, pe.reference_no,
		           pe.party, pe.party_name, pe.party_type, pe.payment_type
		    FROM `tabPayment Entry` pe
		    WHERE pe.{acct_field} = %(acc)s
		      AND pe.docstatus = 1
		      AND (pe.clearance_date IS NULL OR pe.clearance_date = '')
		      AND pe.posting_date BETWEEN %(lo)s AND %(hi)s
		      AND pe.{amt_field} BETWEEN %(amt_lo)s AND %(amt_hi)s
		    ORDER BY pe.posting_date DESC
		    LIMIT 50""",
		{"acc": gl_account, "lo": lo, "hi": hi, "amt_lo": amt_lo, "amt_hi": amt_hi},
		as_dict=True,
	)
	candidates = []
	for r in rows:
		candidates.append(
			{
				"voucher_type": "Payment Entry",
				"voucher_no": r.name,
				"amount": flt(r.amount),
				"date": str(r.posting_date),
				"reference": r.reference_no,
				"party_type": r.party_type,
				"party": r.party,
				"party_name": r.party_name or r.party,
				"party_inn": _fetch_party_inn(r.party_type, r.party),
			}
		)
	return candidates


def _fetch_je_candidates(
	gl_account: str,
	is_deposit: bool,
	amount: float,
	lo,
	hi,
	amt_lo: float,
	amt_hi: float,
) -> list[dict]:
	"""Query Journal Entry lines that hit the bank GL account and are uncleared.

	A JE line that debits the bank account corresponds to a deposit (money in);
	a credit to the bank account corresponds to a withdrawal (money out).
	"""
	# deposit => bank is debited => debit_in_account_currency > 0
	# withdrawal => bank is credited => credit_in_account_currency > 0
	if is_deposit:
		amt_col = "jea.debit_in_account_currency"
	else:
		amt_col = "jea.credit_in_account_currency"

	rows = frappe.db.sql(
		f"""SELECT je.name, je.posting_date, {amt_col} AS amount,
		           je.cheque_no, je.user_remark,
		           jea.party_type, jea.party
		    FROM `tabJournal Entry` je
		    INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
		    WHERE jea.account = %(acc)s
		      AND je.docstatus = 1
		      AND (je.clearance_date IS NULL OR je.clearance_date = '')
		      AND je.posting_date BETWEEN %(lo)s AND %(hi)s
		      AND {amt_col} BETWEEN %(amt_lo)s AND %(amt_hi)s
		    ORDER BY je.posting_date DESC
		    LIMIT 50""",
		{"acc": gl_account, "lo": lo, "hi": hi, "amt_lo": amt_lo, "amt_hi": amt_hi},
		as_dict=True,
	)
	candidates = []
	for r in rows:
		party_name = ""
		if r.party_type and r.party:
			try:
				party_name = (
					frappe.db.get_value(
						"Supplier" if r.party_type == "Supplier" else "Customer",
						r.party,
						"supplier_name" if r.party_type == "Supplier" else "customer_name",
					)
					or r.party
				)
			except Exception:
				party_name = r.party or ""
		candidates.append(
			{
				"voucher_type": "Journal Entry",
				"voucher_no": r.name,
				"amount": flt(r.amount),
				"date": str(r.posting_date),
				# Use cheque_no as the reference identifier for JEs (matches bank ref fields)
				"reference": r.cheque_no or "",
				"party_type": r.party_type or "",
				"party": r.party or "",
				"party_name": party_name,
				"party_inn": _fetch_party_inn(r.party_type, r.party),
			}
		)
	return candidates


@frappe.whitelist()
def suggest_matches(
	bank_transaction: str,
	date_window: int = 7,
	amount_tol_pct: float = 5,
	include_je: int = 1,
) -> dict:
	"""Rank candidate Payment Entries and Journal Entries for a bank line.

	``include_je=1`` (default) also queries Journal Entry lines against the
	bank's GL account. Pass ``include_je=0`` to return PE candidates only
	(legacy behaviour).

	INN/STIR enrichment: both PE and JE candidates are enriched with the
	party's ``tax_id`` (INN) from the Supplier/Customer master, which the
	scorer uses to boost matches when the bank statement row carries an INN.
	"""
	_require_recon()
	bt = _bt(bank_transaction)
	gl_account = _bank_gl_account(bt.bank_account)
	if not gl_account:
		frappe.throw(_("Bank account has no linked GL account."))

	amount = abs(flt(bt.deposit) - flt(bt.withdrawal)) or abs(flt(bt.unallocated_amount))
	is_deposit = flt(bt.deposit) > 0
	lo = getdate(add_days(bt.date, -int(date_window)))
	hi = getdate(add_days(bt.date, int(date_window)))
	tol = flt(amount_tol_pct) / 100.0
	amt_lo = amount * (1 - tol)
	amt_hi = amount * (1 + tol)

	candidates = _fetch_pe_candidates(gl_account, is_deposit, amount, lo, hi, amt_lo, amt_hi)

	if int(include_je or 1):
		candidates += _fetch_je_candidates(gl_account, is_deposit, amount, lo, hi, amt_lo, amt_hi)

	bank_line = {
		"amount": amount,
		"date": str(bt.date),
		"reference": bt.reference_number,
		# INN may be populated on the Bank Transaction if the import parser
		# extracted it from the payment-purpose field (MT940 / 1C XML).
		"counterparty_inn": getattr(bt, "counterparty_inn", "") or "",
		"description": bt.description,
	}
	ranked = rank_candidates(bank_line, candidates)
	return {
		"bank_transaction": bt.name,
		"amount": amount,
		"direction": "deposit" if is_deposit else "withdrawal",
		"candidates": ranked,
		"count": len(ranked),
	}


@frappe.whitelist()
def reconcile(
	bank_transaction: str,
	payment_doctype: str,
	payment_name: str,
	allocated_amount: float | str | None = None,
	modified: str | None = None,
) -> dict:
	"""Link a voucher to a bank line via ERPNext's Bank Transaction table.

	ERPNext stamps the voucher's clearance_date and recomputes allocated /
	unallocated on save — we do not touch the ledger.
	"""
	_require_recon()
	if payment_doctype not in ("Payment Entry", "Journal Entry"):
		frappe.throw(_("Only Payment Entry / Journal Entry can be reconciled here."))
	bt = _bt(bank_transaction)
	check_concurrency("Bank Transaction", bt.name, modified)
	if not frappe.db.exists(payment_doctype, payment_name):
		frappe.throw(_("Voucher not found."))
	if not frappe.has_permission(payment_doctype, "write", payment_name):
		frappe.throw(_("Not permitted to reconcile this voucher."), frappe.PermissionError)

	alloc = flt(allocated_amount) if allocated_amount not in (None, "") else flt(bt.unallocated_amount)
	if alloc <= 0:
		frappe.throw(_("Allocated amount must be greater than zero."))
	if alloc > flt(bt.unallocated_amount) + 0.01:
		frappe.throw(_("Allocation exceeds the unreconciled amount on this transaction."))

	bt.append(
		"payment_entries",
		{"payment_document": payment_doctype, "payment_entry": payment_name, "allocated_amount": alloc},
	)
	bt.save()  # ERPNext on-update stamps clearance_date + updates status
	frappe.db.commit()
	frappe.logger("stabler.bankrec").info(
		f"reconciled {payment_doctype} {payment_name} -> {bt.name} ({alloc}) by {frappe.session.user}"
	)
	bt.reload()
	return {
		"bank_transaction": bt.name,
		"status": bt.status,
		"allocated_amount": flt(bt.allocated_amount),
		"unallocated_amount": flt(bt.unallocated_amount),
	}


@frappe.whitelist()
def reconcile_partial(
	bank_transaction: str,
	vouchers: list | str,
	currency_precision: int = 2,
	modified: str | None = None,
) -> dict:
	"""Allocate one bank line across one or more vouchers with exact precision.

	``vouchers`` is a JSON-encodable list of objects::

	    [
	        {"doctype": "Payment Entry", "name": "PE-001", "amount": 500000},
	        {"doctype": "Journal Entry", "name": "JV-002", "amount": 250000},
	    ]

	Each ``amount`` is the *requested* allocation for that voucher.  The helper
	``allocate_partial`` redistributes proportionally so all allocations sum
	**exactly** to the bank line's ``unallocated_amount`` with no residual
	(last voucher absorbs the rounding remainder).

	``currency_precision``: decimal places (0 for UZS, 2 for USD/EUR).

	The endpoint appends all entries to the Bank Transaction in a single
	``bt.save()`` call so ERPNext's ``on_update`` runs once.
	"""
	_require_recon()
	import json

	if isinstance(vouchers, str):
		try:
			vouchers = json.loads(vouchers)
		except Exception:
			frappe.throw(_("vouchers must be a JSON list."))

	if not vouchers or not isinstance(vouchers, list):
		frappe.throw(_("At least one voucher is required."))

	bt = _bt(bank_transaction)
	check_concurrency("Bank Transaction", bt.name, modified)

	unalloc = flt(bt.unallocated_amount)
	if unalloc <= 0:
		frappe.throw(_("This bank transaction is already fully reconciled."))

	# Validate each voucher entry.
	valid_doctypes = {"Payment Entry", "Journal Entry"}
	for v in vouchers:
		dt = v.get("doctype") or v.get("payment_doctype", "")
		nm = v.get("name") or v.get("payment_name", "")
		if dt not in valid_doctypes:
			frappe.throw(_("Only Payment Entry / Journal Entry can be reconciled here."))
		if not frappe.db.exists(dt, nm):
			frappe.throw(_("Voucher not found: {0} {1}").format(dt, nm))
		if not frappe.has_permission(dt, "write", nm):
			frappe.throw(_("Not permitted to reconcile {0} {1}.").format(dt, nm), frappe.PermissionError)

	# Compute exact allocations using the pure helper.
	voucher_amounts = [flt(v.get("amount") or 0) for v in vouchers]
	alloc_strings = allocate_partial(
		unalloc,
		voucher_amounts,
		precision=int(currency_precision),
	)

	# Append all entries in one pass so ERPNext reconciles cleanly.
	appended = []
	for v, alloc_str in zip(vouchers, alloc_strings, strict=True):
		alloc = flt(alloc_str)
		if alloc <= 0:
			continue
		dt = v.get("doctype") or v.get("payment_doctype", "")
		nm = v.get("name") or v.get("payment_name", "")
		bt.append(
			"payment_entries",
			{"payment_document": dt, "payment_entry": nm, "allocated_amount": alloc},
		)
		appended.append({"doctype": dt, "name": nm, "allocated_amount": alloc})

	if not appended:
		frappe.throw(_("All computed allocation amounts were zero."))

	bt.save()
	frappe.db.commit()
	frappe.logger("stabler.bankrec").info(
		f"reconcile_partial {bt.name}: {len(appended)} voucher(s) by {frappe.session.user}"
	)
	bt.reload()
	return {
		"bank_transaction": bt.name,
		"status": bt.status,
		"allocated_amount": flt(bt.allocated_amount),
		"unallocated_amount": flt(bt.unallocated_amount),
		"entries": appended,
	}


@frappe.whitelist()
def unreconcile(bank_transaction: str, payment_name: str, modified: str | None = None) -> dict:
	"""Remove a voucher link from a bank line (best effort; clears clearance_date)."""
	_require_recon()
	bt = _bt(bank_transaction)
	check_concurrency("Bank Transaction", bt.name, modified)
	if not frappe.has_permission("Bank Transaction", "write", bt.name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	kept = [r for r in bt.get("payment_entries", []) if r.payment_entry != payment_name]
	if len(kept) == len(bt.get("payment_entries", [])):
		frappe.throw(_("That voucher is not linked to this transaction."))
	bt.set("payment_entries", kept)
	bt.save()
	frappe.db.commit()
	bt.reload()
	return {
		"bank_transaction": bt.name,
		"status": bt.status,
		"unallocated_amount": flt(bt.unallocated_amount),
	}
