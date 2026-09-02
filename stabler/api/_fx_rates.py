"""The CBU rate reader, in a module that does not drag ERPNext in.

The body moved here from `_accounts.py` on 2026-09-02 for one reason: that
module imports `erpnext.accounts.party` at module level, so anything importing
it is unavailable to the frappe-free test suite
(`.github/frappe-free-tests.txt`). `crm_board` needs this reader for the Tender
CRM's base-currency companion line, and `test_tender_dashboard_behavior` calls
`crm_board` directly with no erpnext on the path.

MOVED, not copied. `_accounts.py` re-exports the name it always had, so its six
existing callers -- imports.py, reports.py and two guard tests that assert the
name appears in a call site -- are untouched, and there is still exactly ONE
implementation. A screen hint computed from a second copy could drift away from
`validate_exchange_rate`, which is what every real document is measured against.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt


def cbu_rate_on_or_before(doc_currency: str, company_currency: str, posting_date):
	"""Latest CBU rate (doc_currency -> company_currency) on/before posting_date.
	CBU stores each pair one-way, so if the direct pair is missing we fall back to
	the inverse pair and return its reciprocal. Returns (rate, date) or (None, None).
	"""

	def _latest(frm, to):
		rows = frappe.get_all(
			"Currency Exchange",
			filters={"from_currency": frm, "to_currency": to, "date": ("<=", posting_date)},
			fields=["exchange_rate", "date"],
			order_by="date desc",
			limit=1,
		)
		return rows[0] if rows else None

	direct = _latest(doc_currency, company_currency)
	if direct and flt(direct.exchange_rate) > 0:
		return flt(direct.exchange_rate), direct.date
	inv = _latest(company_currency, doc_currency)
	if inv and flt(inv.exchange_rate) > 0:
		return 1.0 / flt(inv.exchange_rate), inv.date
	return None, None
