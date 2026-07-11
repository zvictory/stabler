"""Freight Booking controller.

Non-submittable operational document for cross-border land freight. Enforces the
XOR rule (exactly one of Commercial Invoice / Container) and a one-way status
pipeline (Pending -> Booked -> In Transit -> Delivered, Cancelled as an exit
from any non-terminal status) via the shared ``assert_transition`` helper.
"""

import frappe
from frappe.model.document import Document

from stabler.stabler.imports_module.status_pipeline import assert_transition

_ALLOWED_TRANSITIONS = {
	"Pending": {"Booked", "Cancelled"},
	"Booked": {"In Transit", "Cancelled"},
	"In Transit": {"Delivered", "Cancelled"},
	"Delivered": set(),
	"Cancelled": set(),
}


class FreightBooking(Document):
	def validate(self) -> None:
		self._validate_xor()
		if self.is_new():
			return
		previous_status = frappe.db.get_value("Freight Booking", self.name, "status")
		assert_transition("Freight Booking", previous_status, self.status, _ALLOWED_TRANSITIONS, self)

	def _validate_xor(self) -> None:
		has_ci = bool(self.commercial_invoice)
		has_container = bool(self.container)
		if has_ci == has_container:
			frappe.throw(
				frappe._("Set exactly one of Commercial Invoice or Container on a Freight Booking.")
			)
