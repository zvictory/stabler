"""Vehicle Agreement — one vehicle, one commercial leg (Acquisition or
Disposition), one transaction currency, with frozen contract components.

docstatus 0 = Draft/Review, docstatus 1 = Approved onward. No commercial field
carries allow_on_submit, so native Frappe immutability enforces "approved
terms are immutable". Terminated is a status, never a cancellation.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

PARTY_TYPE_BY_DIRECTION = {"Disposition": "Customer", "Acquisition": "Supplier"}


def compute_total_contract_price(
	cash_price: float, disclosed_markup: float, approved_fees: float, tax_amount: float
) -> float:
	"""Invariant 1: components must sum to the contract total at currency precision."""
	return flt(cash_price) + flt(disclosed_markup) + flt(approved_fees) + flt(tax_amount)


def validate_down_payment(down_payment: float, total: float) -> None:
	"""Invariant 3: 0 <= down payment <= total contract price."""
	if flt(down_payment) < 0:
		raise ValueError("Down payment cannot be negative.")
	if flt(down_payment) > flt(total):
		raise ValueError("Down payment cannot exceed the total contract price.")


def validate_financed_amount(financed_amount: float) -> None:
	"""Invariant 4: the financed balance is never negative."""
	if flt(financed_amount) < 0:
		raise ValueError("Financed amount cannot be negative.")


class VehicleAgreement(Document):
	def validate(self) -> None:
		self.party_type = PARTY_TYPE_BY_DIRECTION[self.direction]
		self._set_party_name()
		self.total_contract_price = compute_total_contract_price(
			self.cash_price, self.disclosed_markup, self.approved_fees, self.tax_amount
		)
		self.financed_amount = flt(self.total_contract_price) - flt(self.down_payment)
		try:
			validate_down_payment(self.down_payment, self.total_contract_price)
			validate_financed_amount(self.financed_amount)
		except ValueError as exc:
			frappe.throw(_(str(exc)))
		if flt(self.cash_price) <= 0:
			frappe.throw(_("Cash price must be greater than zero."))

	def _set_party_name(self) -> None:
		name_field = "customer_name" if self.party_type == "Customer" else "supplier_name"
		self.party_name = frappe.db.get_value(self.party_type, self.party, name_field) or ""

	def on_submit(self) -> None:
		"""Invariant 6: at most one inbound and one outbound agreement per vehicle."""
		self._assert_single_direction_per_unit()

	def _assert_single_direction_per_unit(self) -> None:
		others = frappe.db.count(
			"Vehicle Agreement",
			{
				"vehicle_unit": self.vehicle_unit,
				"direction": self.direction,
				"docstatus": ("<", 2),
				"name": ("!=", self.name or ""),
			},
		)
		if others:
			frappe.throw(
				_("Vehicle Unit {0} already has a {1} agreement.").format(self.vehicle_unit, self.direction)
			)
