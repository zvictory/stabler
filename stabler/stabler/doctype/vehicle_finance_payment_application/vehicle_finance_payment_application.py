"""Payment Application — the append-only allocation ledger.

Links a Payment Entry to a schedule row. Cancellation is forbidden: a reversal
is a NEW record with `is_reversal = 1`, a `reverses` link and a negative
`allocated_amount`. History is never deleted or mutated.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now, nowdate


class VehicleFinancePaymentApplication(Document):
	def validate(self) -> None:
		if self.is_fifo_override and not self.override_reason:
			frappe.throw(_("An override reason is mandatory for a FIFO override."))
		if self.is_reversal:
			self._validate_reversal()
		elif flt(self.allocated_amount) <= 0:
			frappe.throw(_("Allocated amount must be greater than zero."))
		self._validate_agreement_scope()
		self.applied_by = self.applied_by or frappe.session.user
		self.applied_on = self.applied_on or now()

	def _validate_reversal(self) -> None:
		if not self.reverses:
			frappe.throw(_("A reversal must reference the application it reverses."))
		if flt(self.allocated_amount) >= 0:
			frappe.throw(_("A reversal's allocated amount must be negative."))
		original = frappe.db.get_value(
			"Vehicle Finance Payment Application",
			self.reverses,
			["agreement", "is_reversal"],
			as_dict=True,
		)
		if not original:
			frappe.throw(_("Reversed application {0} does not exist.").format(self.reverses))
		if original.is_reversal:
			frappe.throw(_("A reversal cannot reverse another reversal."))
		if original.agreement != self.agreement:
			frappe.throw(_("A reversal must stay on the same agreement as the original."))

	def _validate_agreement_scope(self) -> None:
		"""Invariant 7: a child record's company must equal its parent's."""
		agreement_company = frappe.db.get_value("Vehicle Agreement", self.agreement, "company")
		if agreement_company and agreement_company != self.company:
			frappe.throw(
				_("Agreement {0} belongs to company {1}, not {2}.").format(
					self.agreement, agreement_company, self.company
				)
			)
		if not frappe.db.exists("Payment Entry", self.payment_entry):
			frappe.throw(_("Payment Entry {0} does not exist.").format(self.payment_entry))

	def on_cancel(self) -> None:
		frappe.throw(
			_("Payment Applications are append-only. Reverse the allocation instead.")
		)

	def on_trash(self) -> None:
		frappe.throw(_("Payment Applications are append-only and cannot be deleted."))
