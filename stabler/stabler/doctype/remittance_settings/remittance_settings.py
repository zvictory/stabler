"""Remittance configuration, one row per company, named after the company.

`autoname: field:company` plus `unique: 1` on the field makes the docname the company,
so a second row for the same company collides on the primary key. Following
`Vehicle Finance Settings` — no validate() check is needed for that, and adding one
would only be a second, weaker copy of a constraint the database already holds.

Three company accounts, not five: ADR-009 removed the FX margin account and its
counterpart, so the obligation is carried in the receive currency and valued at the
principal instead of being split across a margin line.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


def get_settings(company: str) -> Document | None:
	"""The settings row for a company, or None when it has never been configured."""
	if not company or not frappe.db.exists("Remittance Settings", company):
		return None
	return frappe.get_doc("Remittance Settings", company)


def get_desk_account(company: str, branch: str, currency: str) -> str:
	"""The cash account a desk uses for one currency.

	Throws instead of falling back to any other account. Registering against the
	wrong drawer is worse than not registering at all: the desk's book balance then
	stops matching the physical count, and nothing downstream notices until someone
	reconciles by hand.

	The message names what is missing and points at the settings screen. It does not
	explain how to fix it — that belongs on the screen itself, where the desk shows
	its own not-ready state.
	"""
	settings = get_settings(company)
	if not settings:
		frappe.throw(
			_("Remittance is not configured for {0}. Set it up in Remittance Settings.").format(company)
		)

	for row in settings.cash_desk_accounts or []:
		if row.branch == branch and row.currency == currency:
			return row.account

	frappe.throw(
		_("Desk {0} has no {1} cash account. Add it under Cash Desks in Remittance Settings for {2}.").format(
			branch, currency, company
		)
	)


class RemittanceSettings(Document):
	def validate(self) -> None:
		self._dedupe_desk_currency()

	def _dedupe_desk_currency(self) -> None:
		"""One account per (desk, currency).

		Frappe's `unique` flag is a single-column index and does nothing on a child
		table, so the pair is enforced here — same shape as
		`Route._dedupe_outlet_sequences`.
		"""
		seen: set[tuple[str, str]] = set()
		for row in self.cash_desk_accounts or []:
			pair = (row.branch, row.currency)
			if pair in seen:
				frappe.throw(
					_("Desk {0} already has a {1} account. One account per desk per currency.").format(
						row.branch, row.currency
					)
				)
			seen.add(pair)
