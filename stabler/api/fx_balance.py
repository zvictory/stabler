"""System-wide multi-currency rounding-residual auto-balancing.

A document that posts to the GL must balance in the company (reporting) currency.
When the transaction currency differs, translating the amount and its allocations
can leave a sub-unit base-currency residual — a realized exchange gain/loss
(IAS 21 §28 / ASC 830-20-35-1), not a user error. ERPNext blocks submit
("Difference Amount must be zero" / "Total Debit must equal Total Credit").

This module auto-books a *tiny* residual to the company Exchange Gain/Loss
account, leaving the transaction-currency amount (the user-typed amount)
untouched as ground truth — exactly how NetSuite/QuickBooks/Xero handle it.

Registered in hooks.py as a `before_validate` doc-event for Payment Entry and
Journal Entry, so it runs BEFORE ERPNext's own balance check, on every save and
submit, regardless of where the document was created (SPA, Desk, transfer,
expense, remittance, import). Idempotent: prior auto-rows are stripped and
recomputed each pass, so re-saving never stacks duplicate lines. A residual
larger than the rounding tolerance is left alone for ERPNext to reject loudly —
that's a real allocation error, not rounding.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from stabler.api._fx_residual import base_precision_for, residual_tolerance, within_tolerance

_PE_MARKER = "Exchange rounding (auto)"
_JE_MARKER = "fx-rounding-auto"


def auto_balance_fx_residual(doc, method=None):
	"""doc_event entrypoint (before_validate). Dispatches by doctype."""
	try:
		if doc.doctype == "Payment Entry":
			_balance_payment_entry(doc)
		elif doc.doctype == "Journal Entry":
			_balance_journal_entry(doc)
	except frappe.ValidationError:
		# A genuine document error raised by ERPNext while we were recomputing
		# totals (e.g. the same account debited and credited). Its own validate()
		# raises it again a moment later, so the user still sees it — logging it
		# here would only file the same complaint twice.
		pass
	except Exception:
		# Never let auto-balancing break a legitimate save/submit; ERPNext's own
		# balance validation remains the backstop.
		frappe.log_error(title="fx_balance: auto-balance failed", message=frappe.get_traceback())


def _gl_and_cost_center(company: str):
	gl = frappe.get_cached_value("Company", company, "exchange_gain_loss_account") or frappe.get_cached_value(
		"Company", company, "round_off_account"
	)
	cc = frappe.get_cached_value("Company", company, "round_off_cost_center") or frappe.get_cached_value(
		"Company", company, "cost_center"
	)
	return gl, cc


def _balance_payment_entry(doc) -> None:
	# Strip any prior auto deduction so we recompute cleanly (idempotent).
	deductions = doc.get("deductions") or []
	if any((d.description or "") == _PE_MARKER for d in deductions):
		doc.set("deductions", [d for d in deductions if (d.description or "") != _PE_MARKER])

	# We run at before_validate, so on a brand-new document ERPNext has not filled
	# the company-currency amounts yet (set_amounts_in_company_currency() does that
	# during validate). set_difference_amount() subtracts them without flt(), so
	# calling it now would raise TypeError on None. Nothing to balance on that pass
	# anyway — the residual only has to be gone by submit, and before_validate runs
	# again then, with the amounts populated.
	if doc.get("base_paid_amount") is None or doc.get("base_received_amount") is None:
		return

	if hasattr(doc, "set_difference_amount"):
		doc.set_difference_amount()
	diff = flt(getattr(doc, "difference_amount", 0))
	if not diff:
		return

	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "UZS"
	tol = residual_tolerance(len(doc.get("references") or []), base_precision_for(company_currency))
	if not within_tolerance(diff, tol):
		return  # real imbalance — let ERPNext reject it

	gl, cc = _gl_and_cost_center(doc.company)
	if not gl:
		return  # no account to book to — ERPNext will raise its standard error

	doc.append(
		"deductions",
		{
			"account": gl,
			"cost_center": cc,
			"amount": diff,
			"description": _PE_MARKER,
		},
	)
	if hasattr(doc, "set_difference_amount"):
		doc.set_difference_amount()


def _balance_journal_entry(doc) -> None:
	# WHICH SAVE THIS CAN ACT ON. We run at `before_validate`, which frappe calls
	# once per save and before `validate`
	# (frappe/model/document.py:run_before_save_methods). ERPNext fills the
	# company-currency columns `debit`/`credit` inside `validate`, in
	# `set_amounts_in_company_currency` (journal_entry.py:977). So on the FIRST
	# save of a document built the way the SPA builds one — only
	# `*_in_account_currency` set — `set_total_debit_credit()` below sums base
	# columns that are still empty, `diff` is 0, and we return without booking
	# anything. The residual can only appear from the second save on.
	#
	# That is safe rather than lucky: ERPNext enforces the balance in
	# `before_submit` (journal_entry.py:196-200), never in `validate`, so a draft
	# is allowed to carry the gap, and every Stabler path submits on a later save
	# (`doc.insert()` then `doc.submit()`), by which time the columns are
	# populated. `_balance_payment_entry` above records the same ordering for its
	# own doctype. Written down here because a bench test built a one-save draft,
	# found no residual, and the tolerance was blamed first — it was never
	# reached.
	#
	# Strip any prior auto row first (idempotent).
	accounts = doc.get("accounts") or []
	if any((a.user_remark or "") == _JE_MARKER for a in accounts):
		doc.set("accounts", [a for a in accounts if (a.user_remark or "") != _JE_MARKER])

	if hasattr(doc, "set_total_debit_credit"):
		doc.set_total_debit_credit()
	# Both sides rounded BEFORE they are subtracted, which is what ERPNext itself
	# does one line later (journal_entry.py:951). Its accumulator is not rounded as
	# it goes — only each addend is (:948) — so on a multi-leg entry that closes
	# exactly the two running sums still land an ulp apart. At UZS magnitudes that
	# is ~3e-08: inside every tolerance below, and it used to buy an Exchange
	# Gain/Loss row that `set_amounts_in_company_currency` promptly rounded to zero
	# and `validate_debit_credit_amount` then refused — "Row N: Both Debit and
	# Credit values cannot be zero" on a balanced document. A difference ERPNext
	# cannot see is not a residual; it is float noise, and booking it is worse than
	# ignoring it.
	places = doc.precision("total_debit")
	diff = flt(getattr(doc, "total_debit", 0), places) - flt(getattr(doc, "total_credit", 0), places)
	if not diff:
		return

	# TWO NOTIONS OF PRECISION MEET HERE, and they now agree. The difference above
	# is measured at the DOCUMENT's precision — 2 on a UZS company, because
	# `currency_precision` is unset and `get_field_precision` falls through to the
	# global "#,###.##" (frappe/model/meta.py:910-913). The tolerance below is sized
	# at `base_precision_for`, which used to call UZS a 0-decimal currency and hand
	# back whole units: a 3-leg UZS entry tolerated 4,99 — 499 units at the
	# precision the difference is actually measured at.
	#
	# Closed 2026-08-20 by taking UZS out of ZERO_DECIMAL_CURRENCIES, which is the
	# narrowing this comment used to defer. It was measured first: the three
	# UZS-base tenants (horeca, mikas, msa) carry zero auto-booked rounding rows,
	# so nothing that exists today would have been refused. The boundary tests in
	# test_fx_balance.py moved with it, and test_currency_precision_agreement now
	# checks the set against the live site rather than against prose.
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency") or "UZS"
	tol = residual_tolerance(len(doc.get("accounts") or []), base_precision_for(company_currency))
	if not within_tolerance(diff, tol):
		return

	gl, cc = _gl_and_cost_center(doc.company)
	if not gl:
		return

	row = {"account": gl, "cost_center": cc, "user_remark": _JE_MARKER}
	# total_debit > total_credit  → add a credit to balance; else add a debit.
	if diff > 0:
		row["credit_in_account_currency"] = abs(diff)
		row["credit"] = abs(diff)
	else:
		row["debit_in_account_currency"] = abs(diff)
		row["debit"] = abs(diff)
	doc.append("accounts", row)
	if hasattr(doc, "set_total_debit_credit"):
		doc.set_total_debit_credit()
