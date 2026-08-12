"""Supplier-payment currency rule (Frappe-free, unit-testable).

A supplier is paid FROM a bank/cash account and the debt is cleared ON the
supplier's payable account. When those two accounts are in different currencies
the Payment Entry has to convert, and the conversion rate is whatever the person
typed — so the amount that lands on the supplier's ledger is a judgement call, not
a fact. Tenants that buy in a single foreign currency (msa: every supplier is USD,
`Creditors USD - M`) want that door closed: pay a USD supplier from a USD account
or not at all.

The rule is expressed in terms of the two ACCOUNT currencies, never a currency
literal and never a tenant name — on a company whose payable account is USD it
means "USD only", on one whose payable account is EUR it means "EUR only".

Scope is deliberately narrow: only outgoing supplier payments. A customer receipt
or an employee advance in a second currency is ordinary business and stays legal.

Whether the rule applies at all is a per-company policy decision — see
`supplier_payment_guard.guard_enabled`. This module only answers "would it be
violated", so the answer can be tested without booting a site.
"""

from __future__ import annotations


def supplier_payment_currency_mismatch(
	payment_type: str | None,
	party_type: str | None,
	paid_from_currency: str | None,
	paid_to_currency: str | None,
) -> bool:
	"""True when this payment breaks the same-currency rule for a supplier.

	Returns False — i.e. no violation — whenever either currency is unknown.
	Missing account metadata must never be turned into a rule violation: the
	guard would then block a payment on the strength of a blank field.
	"""
	if payment_type != "Pay" or party_type != "Supplier":
		return False
	if not paid_from_currency or not paid_to_currency:
		return False
	return paid_from_currency != paid_to_currency
