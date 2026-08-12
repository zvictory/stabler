"""Company policy: pay a supplier only from an account in the supplier's currency.

The rule itself lives in `_supplier_payment.py` (pure, tested without a site).
This module owns the two things that need Frappe: reading the per-company opt-in
flag, and raising the translated rejection.

Opt-in per company via `enable_supplier_payment_currency_guard` on Stabler Company
Modules, OFF by default — measured on production 2026-08-13: anjan has 211
submitted supplier payments whose bank currency differs from the payable account
(206 of them UZS -> USD). That is anjan's normal way of working, so the rule
cannot be unconditional. msa, whose suppliers are all USD, has 0 such payments and
is the tenant that asked for the rule. Config decides, never a tenant name.
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.api._supplier_payment import supplier_payment_currency_mismatch

_GATE_FIELD = "enable_supplier_payment_currency_guard"


def guard_enabled(company: str | None) -> bool:
	"""True when this company opted into the supplier-payment currency rule.

	Reads the child row directly rather than through `module_map_for()`, which
	*creates and commits* a missing row — a payment endpoint must not write
	settings as a side effect of validating. Any failure (pre-migrate site,
	missing column) resolves to OFF: a policy the tenant never asked for must
	never be the reason a payment cannot be recorded.
	"""
	if not company:
		return False
	try:
		val = frappe.db.get_value(
			"Stabler Company Modules",
			{"parent": "Stabler Settings", "parenttype": "Stabler Settings", "company": company},
			_GATE_FIELD,
		)
	except Exception:
		return False
	return bool(int(val or 0))


def assert_supplier_payment_currency(
	company: str | None,
	payment_type: str | None,
	party_type: str | None,
	paid_from_currency: str | None,
	paid_to_currency: str | None,
) -> None:
	"""Reject an outgoing supplier payment whose source account is in another currency."""
	if not guard_enabled(company):
		return
	if not supplier_payment_currency_mismatch(payment_type, party_type, paid_from_currency, paid_to_currency):
		return
	frappe.throw(
		_(
			"This supplier is paid in {0}. Select a {0} account: the selected payment account is in {1}."
		).format(paid_to_currency, paid_from_currency)
	)
