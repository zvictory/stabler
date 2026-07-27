"""Vendor import-exposure math (WP-I4, Frappe-free, unit-testable).

Vendor Center shows a supplier's import position on top of the standard GL A/P:
  * open commitment  — agreed_total of Commercial Invoices not yet delivered
                       (i.e. not yet turned into a Purchase Invoice / GL A/P);
  * cash vs bank paid — every payment to the supplier IS in GL; the split is
                       just which asset account it came from (Cash vs Bank,
                       read from the Payment Entry's paid_from account_type).

Nothing here is off-book: `cash_paid + bank_paid (+ other) == GL total paid`,
which the reconciliation helper asserts to the kuruş. `docs_total` is a
customs-declaration figure and NEVER enters these numbers.

The Frappe layer (api/purchasing.supplier_import_exposure) hydrates the rows and
applies the enable_imports tenant gate; this module only does arithmetic.
"""

from __future__ import annotations

# Commercial Invoice statuses that have left the "owed / in-flight" state.
_TERMINAL_CI_STATUS = frozenset({"DELIVERED_TO_UZBEKISTAN", "Cancelled"})


def classify_method(account_type: str | None) -> str:
	"""Map an ERPNext Account.account_type to a payment method bucket."""
	t = (account_type or "").strip().lower()
	if t == "cash":
		return "cash"
	if t == "bank":
		return "bank"
	return "other"


def _amt(v) -> float:
	try:
		return float(v or 0)
	except TypeError, ValueError:
		return 0.0


def split_by_method(payment_rows) -> dict:
	"""Sum payment amounts into {cash, bank, other} by source account_type.

	``payment_rows`` = iterable of {amount, account_type}.
	"""
	out = {"cash": 0.0, "bank": 0.0, "other": 0.0}
	for r in payment_rows or []:
		out[classify_method((r or {}).get("account_type"))] += _amt((r or {}).get("amount"))
	return out


def reconciles_gl(by_method: dict, gl_total_paid, eps: float = 0.5) -> bool:
	"""True when cash+bank+other equals the GL total paid (kuruş-level check)."""
	total = _amt(by_method.get("cash")) + _amt(by_method.get("bank")) + _amt(by_method.get("other"))
	return abs(total - _amt(gl_total_paid)) <= eps


def _ci_closed(row) -> bool:
	"""A Commercial Invoice has left virtual import exposure when it is
	delivered/cancelled OR has been converted to a Purchase Invoice (WP-I5).

	Once a PInv exists (draft = pending A/P, submitted = GL A/P) the agreed_total
	lives on that invoice, so counting it here too would double-count the same
	money. ``has_purchase_invoice`` defaults False, so rows that predate the
	conversion wiring behave exactly as before.
	"""
	r = row or {}
	if (r.get("status") or "") in _TERMINAL_CI_STATUS:
		return True
	return bool(r.get("has_purchase_invoice"))


def _open_sum(ci_rows, field: str) -> float:
	"""Σ of ``field`` over Commercial Invoices still open (not delivered/cancelled
	and not yet converted to a Purchase Invoice)."""
	return sum(_amt((r or {}).get(field)) for r in (ci_rows or []) if not _ci_closed(r))


def open_commitment(ci_rows) -> float:
	"""Σ agreed_total of Commercial Invoices still open (not delivered/cancelled)."""
	return _open_sum(ci_rows, "agreed_total")


def earmark_reconciles(bank_agreed, cash_agreed, agreed_total, eps: float = 0.5) -> bool:
	"""True when bank_agreed + cash_agreed equals agreed_total (earmark identity)."""
	return abs((_amt(bank_agreed) + _amt(cash_agreed)) - _amt(agreed_total)) <= eps


def _pct(paid, committed) -> float:
	c = _amt(committed)
	if c <= 0:
		return 0.0
	return round(100.0 * _amt(paid) / c, 1)


def exposure_summary(ci_rows, payment_rows, gl_total_paid) -> dict:
	"""Full supplier import-exposure summary for the Vendor Center.

	Adds the cash/bank EARMARK view when the Commercial Invoice rows carry
	``custom_bank_agreed`` / ``custom_cash_agreed`` (WP-I3b): committed-per-method
	over open CIs, remaining balance per method, and % paid. Everything is GL:
	``cash_paid + bank_paid + other == GL total paid``.
	"""
	by_method = split_by_method(payment_rows)
	total_paid = by_method["cash"] + by_method["bank"] + by_method["other"]

	bank_committed = _open_sum(ci_rows, "custom_bank_agreed")
	cash_committed = _open_sum(ci_rows, "custom_cash_agreed")

	return {
		"open_commitment": round(open_commitment(ci_rows), 2),
		"cash_paid": round(by_method["cash"], 2),
		"bank_paid": round(by_method["bank"], 2),
		"other_paid": round(by_method["other"], 2),
		"total_paid": round(total_paid, 2),
		"reconciles_gl": reconciles_gl(by_method, gl_total_paid),
		# Cash/bank earmark (WP-I3b): committed vs paid, per method.
		"bank_committed": round(bank_committed, 2),
		"cash_committed": round(cash_committed, 2),
		"bank_balance": round(bank_committed - by_method["bank"], 2),
		"cash_balance": round(cash_committed - by_method["cash"], 2),
		"bank_pct_paid": _pct(by_method["bank"], bank_committed),
		"cash_pct_paid": _pct(by_method["cash"], cash_committed),
	}
