"""ADR-609 P5b — the one query behind the tender's ledger P&L.

Everything that DECIDES anything lives in `_tender_gl`, which imports no frappe
and is measured without a bench. This module holds the parts that only a live
site can supply: the company gate, the dimension's real fieldname, the accounts
the settings nominate, and one grouped read of `tabGL Entry`.

Two things it deliberately does NOT do.

  * It never spells the dimension fieldname. `dimension_fieldname()` reads it
    from the enabled Accounting Dimension, so a site whose dimension was created
    by hand under another name still works, and a site that never ran v103 gets
    an `available: False` answer instead of a traceback.
  * It never changes `deal_bid_pricing`. The document-derived block stays exactly
    as it was and is READ here, because the transition period's whole point is
    that both sources are on screen at once and neither is hidden.
"""

from __future__ import annotations

import re

import frappe
from frappe import _

from stabler.api._tender_gl import reconcile, summarize
from stabler.api.tender import _actual_block, _bid_inputs, _compute_bid_pnl, _deal_scope
from stabler.api.tender_dimension import dimension_fieldname

#: A fieldname reaches the SQL by interpolation — it is a COLUMN, and no
#: placeholder can carry one. Frappe builds it from the dimension's label, so it
#: is an identifier in practice; this is what makes that a fact rather than a
#: hope. Values are always parameters.
_SAFE_FIELDNAME = re.compile(r"[a-z_][a-z0-9_]*")

#: Where a site may nominate the account its landed charges are booked to. Both
#: are read by `lcv.py` when it writes a Landed Cost Voucher, in this order, so
#: reading them here is reading the same declaration back.
_LANDED_SETTINGS = ("landed_cost_expense_account", "imports_lcv_expense_account")


def _landed_accounts() -> frozenset:
	"""The accounts `Stabler Settings` nominates as landed-cost expense.

	Empty on a site that configured neither — which is every site today, and why
	`classify_account`'s "Expenses Included In Valuation" rule is the one that
	actually carries the landed bucket in production.
	"""
	return frozenset(
		account
		for account in (frappe.db.get_single_value("Stabler Settings", field) for field in _LANDED_SETTINGS)
		if account
	)


def _ledger_rows(deal: str, company: str, fieldname: str) -> list[dict]:
	"""One grouped read: account x voucher type, for this tender, this company.

	`is_cancelled = 0` and nothing else. A cancelled voucher's reversal rows are
	cancelled too, so their net effect is already nil; the filter is there to keep
	the counts and the account list honest rather than to change a total.
	"""
	return frappe.db.sql(
		f"""
		SELECT g.account, a.account_name, a.report_type, a.root_type, a.account_type,
		       g.voucher_type, SUM(g.debit) AS debit, SUM(g.credit) AS credit, COUNT(*) AS `count`
		FROM `tabGL Entry` g
		JOIN `tabAccount` a ON a.name = g.account
		WHERE g.`{fieldname}` = %(deal)s
		  AND g.company = %(company)s
		  AND g.is_cancelled = 0
		GROUP BY g.account, g.voucher_type, a.account_name, a.report_type, a.root_type, a.account_type
		""",
		{"deal": deal, "company": company},
		as_dict=True,
	)


def _envelope(
	deal: str, company: str, currency: str, *, available: bool, reason: str, fieldname: str
) -> dict:
	"""The unavailable answer, shaped by `summarize` itself.

	Built from an empty row set rather than hand-written, so the screen indexes
	into exactly the same keys whether the dimension is there or not. A hand-made
	stub is how the empty state and the loaded state drift apart.
	"""
	return {
		"deal": deal,
		"company": company,
		"currency": currency,
		"available": available,
		"reason": reason,
		"fieldname": fieldname,
		**summarize([], frozenset()),
		"reconciliation": [],
	}


@frappe.whitelist()
def tender_gl_pnl(deal: str) -> dict:
	"""This tender's profit and loss as the GENERAL LEDGER holds it, reconciled.

	Gated by `_deal_scope` — the same gate `deal_bid_pricing` uses, so an unknown
	deal raises `DoesNotExistError` and a deal the user may not read raises
	`PermissionError`, here as there. Neither is swallowed: a screen that renders
	an empty ledger for a permission refusal tells the reader the tender has no
	postings, which is a different and much worse answer than "not permitted".
	"""
	company = _deal_scope(deal, write=False)
	currency = frappe.db.get_value("Company", company, "default_currency") or ""

	fieldname = dimension_fieldname()
	if not fieldname:
		return _envelope(deal, company, currency, available=False, reason="no_dimension", fieldname="")
	if not frappe.db.has_column("GL Entry", fieldname):
		# The dimension exists but its Custom Field never landed on GL Entry, so
		# nothing was ever stamped. Reporting zero would be a lie about the money.
		return _envelope(deal, company, currency, available=False, reason="no_column", fieldname=fieldname)
	if not _SAFE_FIELDNAME.fullmatch(fieldname):
		frappe.throw(_("Unsafe dimension fieldname"))

	gl = summarize(_ledger_rows(deal, company, fieldname), _landed_accounts())
	inputs, _refs = _bid_inputs(deal, company)
	actual = _actual_block(deal, company, inputs, _compute_bid_pnl(inputs))
	return {
		"deal": deal,
		"company": company,
		"currency": currency,
		"available": True,
		"reason": "",
		"fieldname": fieldname,
		**gl,
		"reconciliation": reconcile(actual, gl),
	}
