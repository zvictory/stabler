"""FX Revaluation — thin Frappe layer surfacing ERPNext Exchange Rate Revaluation.

Endpoints:
  list_fx_accounts       — accounts with foreign-currency GL balances needing revaluation
  get_fx_revaluation     — fetch one Exchange Rate Revaluation doc (read)
  list_fx_revaluations   — list Exchange Rate Revaluation docs for a company
  create_fx_revaluation  — create (and optionally submit) an ERPNext Exchange Rate
                           Revaluation doc; ERPNext's own controller posts the GL

Design principle: ERPNext is the source of truth for all GL posting. We surface
its doctype; we never hand-roll revaluation journal entries ourselves.

Guest is rejected at the whitelist level (no_guest_login decorator pattern used
here via explicit frappe.session.user check — consistent with other api modules).
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from stabler.api._common import _assert_can_read, _require_company
from stabler.api._fx_revaluation import compute_fx_delta, summarize_revaluation


def _reject_guest() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _base_currency(company: str) -> str:
	return frappe.get_cached_value("Company", company, "default_currency") or ""


# ---------------------------------------------------------------------------
# list_fx_accounts — accounts with a non-base-currency balance
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_fx_accounts(company: str, posting_date: str = "") -> dict:
	"""Return accounts that hold a non-base-currency balance together with a
	preview unrealised delta using the latest available Currency Exchange rate.

	Response shape:
	  {
	    "accounts": [{
	      account, account_currency, balance_in_account_ccy,
	      balance_base, book_rate, new_rate, delta, gain_loss
	    }],
	    "base_currency": str,
	    "posting_date": str,
	  }
	"""
	_reject_guest()
	_require_company(company)
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("Not permitted to read GL entries."), frappe.PermissionError)

	pdate = str(getdate(posting_date)) if posting_date else str(getdate(today()))
	base_ccy = _base_currency(company)

	# Fetch GL balances per account where account_currency != base
	# Parameterised query; no f-string interpolation of user input.
	rows = frappe.db.sql(
		"""
		SELECT
			gl.account,
			gl.account_currency,
			SUM(gl.debit_in_account_currency - gl.credit_in_account_currency) AS balance_in_account_ccy,
			SUM(gl.debit - gl.credit) AS balance_base
		FROM `tabGL Entry` gl
		WHERE gl.company = %(company)s
			AND gl.is_cancelled = 0
			AND gl.posting_date <= %(pdate)s
			AND gl.account_currency != %(base_ccy)s
		GROUP BY gl.account, gl.account_currency
		HAVING ABS(SUM(gl.debit_in_account_currency - gl.credit_in_account_currency)) > 0.0001
		ORDER BY gl.account ASC
		""",
		{"company": company, "pdate": pdate, "base_ccy": base_ccy},
		as_dict=True,
	)

	accounts = []
	for r in rows:
		# Derive book rate from base / account-ccy balance (safe against zero)
		bal_acc = flt(r.balance_in_account_ccy)
		bal_base = flt(r.balance_base)
		book_rate = (bal_base / bal_acc) if abs(bal_acc) > 1e-9 else 0.0

		# Latest market rate from Currency Exchange
		ce = frappe.db.get_all(
			"Currency Exchange",
			filters={
				"from_currency": r.account_currency,
				"to_currency": base_ccy,
				"date": ("<=", pdate),
			},
			fields=["exchange_rate", "date"],
			order_by="date desc",
			limit=1,
		)
		new_rate = flt(ce[0].exchange_rate) if ce else 0.0

		result = compute_fx_delta(
			balance_in_account_ccy=bal_acc,
			new_rate=new_rate,
			book_rate=book_rate,
		)

		accounts.append({
			"account": r.account,
			"account_currency": r.account_currency,
			"balance_in_account_ccy": float(result["balance_in_account_ccy"]),
			"balance_base": bal_base,
			"book_rate": float(result["book_rate"]),
			"new_rate": float(result["new_rate"]),
			"rate_diff": float(result["rate_diff"]),
			"delta": float(result["delta"]),
			"gain_loss": result["gain_loss"],
		})

	return {
		"accounts": accounts,
		"base_currency": base_ccy,
		"posting_date": pdate,
	}


# ---------------------------------------------------------------------------
# list_fx_revaluations — browse existing docs
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_fx_revaluations(
	company: str,
	from_date: str = "",
	to_date: str = "",
	limit: int = 100,
) -> list:
	"""List Exchange Rate Revaluation docs for a company (newest first)."""
	_reject_guest()
	_require_company(company)
	if not frappe.has_permission("Exchange Rate Revaluation", "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters = {"company": company}
	if from_date:
		filters["posting_date"] = (">=", str(getdate(from_date)))
	if to_date:
		existing = filters.get("posting_date")
		if existing:
			# both from and to: convert to a list condition
			filters["posting_date"] = ["between", [str(getdate(from_date)), str(getdate(to_date))]]
		else:
			filters["posting_date"] = ("<=", str(getdate(to_date)))

	docs = frappe.get_all(
		"Exchange Rate Revaluation",
		filters=filters,
		fields=["name", "company", "posting_date", "docstatus"],
		order_by="posting_date desc, name desc",
		limit=int(limit),
	)
	return docs


# ---------------------------------------------------------------------------
# get_fx_revaluation — fetch one doc
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_fx_revaluation(name: str) -> dict:
	"""Fetch one Exchange Rate Revaluation doc by name."""
	_reject_guest()
	if not name:
		frappe.throw(_("Name is required."), frappe.ValidationError)
	_assert_can_read("Exchange Rate Revaluation", name)
	doc = frappe.get_doc("Exchange Rate Revaluation", name)
	return doc.as_dict()


# ---------------------------------------------------------------------------
# create_fx_revaluation — delegate fully to ERPNext
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_fx_revaluation(
	company: str,
	posting_date: str = "",
	submit: int = 0,
) -> dict:
	"""Create an Exchange Rate Revaluation doc via ERPNext's controller.

	ERPNext's Exchange Rate Revaluation controller (erpnext/accounts/doctype/
	exchange_rate_revaluation/) reads the live GL balances and populates the
	account rows automatically when we call `doc.get_accounts()`. We do not
	hand-roll the GL entries — ERPNext posts them on submit.

	Parameters
	----------
	company:
		Target company (validated to exist).
	posting_date:
		Revaluation date (defaults to today).
	submit:
		Pass 1 to save + submit in one call.  Caller must have Submit permission.

	Returns the saved/submitted doc as dict.
	"""
	_reject_guest()
	_require_company(company)
	if not frappe.has_permission("Exchange Rate Revaluation", "create"):
		frappe.throw(_("Not permitted to create Exchange Rate Revaluation."), frappe.PermissionError)

	pdate = str(getdate(posting_date)) if posting_date else str(getdate(today()))

	doc = frappe.new_doc("Exchange Rate Revaluation")
	doc.company = company
	doc.posting_date = pdate

	# Let ERPNext populate the account rows from GL (its own method)
	try:
		doc.get_accounts()
	except AttributeError:
		# Older ERPNext versions may expose the same logic differently
		pass

	doc.insert(ignore_permissions=False)

	if int(submit or 0):
		if not frappe.has_permission("Exchange Rate Revaluation", "submit", doc=doc.name):
			frappe.throw(_("Not permitted to submit Exchange Rate Revaluation."), frappe.PermissionError)
		doc.submit()

	return doc.as_dict()
