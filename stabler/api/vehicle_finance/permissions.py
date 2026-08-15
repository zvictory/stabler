"""Capability, module and engine gates for the Vehicle Finance Center.

Authorization reuses real Frappe roles created by ``v84_vehicle_finance_roles``
— no parallel auth system. System Manager and Stabler Admin pass every
capability, mirroring ``stabler.api.organization._can_access_module``.

The real safety gate is the ENGINE, not the module flag: ``v13`` backfilled
``enable_installment = 1`` on pre-existing companies, so a company can have the
module visible while ``installment_engine`` is still ``Legacy``. V1 behaviour
must check both.
"""

from __future__ import annotations

import frappe
from frappe import _

VIEWER = "Vehicle Finance Viewer"
CONTRACT_CLERK = "Vehicle Finance Contract Clerk"
COLLECTOR = "Vehicle Finance Collector"
PAYABLES_CLERK = "Vehicle Finance Payables Clerk"
REVIEWER = "Vehicle Finance Reviewer"
CASHIER = "Vehicle Finance Cashier"
MANAGER = "Vehicle Finance Manager"

ALL_ROLES = (VIEWER, CONTRACT_CLERK, COLLECTOR, PAYABLES_CLERK, REVIEWER, CASHIER, MANAGER)

_ADMIN_ROLES = ("System Manager", "Stabler Admin")

CAPABILITY_ROLES: dict[str, frozenset[str]] = {
	"view": frozenset(ALL_ROLES),
	"view_cost_margin": frozenset({MANAGER, REVIEWER}),
	"draft_write": frozenset({CONTRACT_CLERK, MANAGER}),
	"approve": frozenset({REVIEWER, MANAGER}),
	"activate": frozenset({REVIEWER, MANAGER}),
	"collect": frozenset({CASHIER, COLLECTOR, MANAGER}),
	"pay_supplier": frozenset({PAYABLES_CLERK, MANAGER}),
	"fifo_override": frozenset({MANAGER}),
	"cancel_same_day": frozenset({MANAGER}),
	"reschedule": frozenset({MANAGER}),
	"title_override": frozenset({MANAGER}),
	"settlement_writeoff": frozenset({MANAGER}),
}


def _assert_capability(user: str, company: str | None, capability: str) -> None:
	"""Throw PermissionError unless `user` holds `capability` (admins pass)."""
	allowed = CAPABILITY_ROLES.get(capability)
	if allowed is None:
		frappe.throw(_("Unknown capability: {0}").format(capability), frappe.PermissionError)
	roles = set(frappe.get_roles(user))
	if roles & set(_ADMIN_ROLES):
		return
	if not (roles & allowed):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _vehicle_finance_module_enabled(company: str | None) -> bool:
	"""Company-level installment switch as a boolean, without throwing."""
	if not company:
		return False
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	return bool(module_map_for(company).get("installment"))


def _require_vehicle_finance_module(company: str | None = None) -> None:
	"""Role gate (module key `installment`) plus, when given, the company flag."""
	from stabler.api.organization import _can_access_module

	if not _can_access_module(frappe.session.user, "installment"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if company and not _vehicle_finance_module_enabled(company):
		frappe.throw(
			_("The installment module is not enabled for company {0}.").format(company),
			frappe.PermissionError,
		)


def _require_agreement_v1(company: str) -> None:
	"""Module gate + engine gate. The engine default is Legacy, so a company
	with the module flag on still gets a clear "not enabled" error, not a
	permission error."""
	_require_vehicle_finance_module(company)
	from stabler.stabler.doctype.vehicle_finance_settings.vehicle_finance_settings import (
		get_engine,
	)

	if get_engine(company) != "Agreement V1":
		frappe.throw(_("Agreement V1 is not enabled for this company."))
