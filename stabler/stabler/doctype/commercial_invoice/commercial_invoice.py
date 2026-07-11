"""Commercial Invoice controller.

Enforces the shipping/logistics lifecycle as a one-way status pipeline, with
"Cancelled" reachable as an explicit exit from any non-terminal status except
ARRIVED_AT_IRAN — once goods have physically arrived in-country the deal
cannot be walked back. Customs-clearance statuses (declaration filed, under
review, cleared, ...) belong to the separate Customs Declaration doctype, not
here. Terminal statuses (DELIVERED_TO_UZBEKISTAN, Cancelled) accept no
further transition.
"""

import frappe
from frappe.model.document import Document

from stabler.stabler.imports_module.status_pipeline import assert_transition

_ALLOWED_TRANSITIONS = {
	"BOOKED": {"STUFFED", "Cancelled"},
	"STUFFED": {"GATE_IN", "Cancelled"},
	"GATE_IN": {"ON_BOARD", "Cancelled"},
	"ON_BOARD": {"IN_TRANSIT", "Cancelled"},
	"IN_TRANSIT": {"DISCHARGED", "Cancelled"},
	"DISCHARGED": {"AVAILABLE", "Cancelled"},
	"AVAILABLE": {"ARRIVED_AT_IRAN", "Cancelled"},
	"ARRIVED_AT_IRAN": {"DELIVERED_TO_UZBEKISTAN"},
	"DELIVERED_TO_UZBEKISTAN": set(),
	"Cancelled": set(),
}


class CommercialInvoice(Document):
	def validate(self) -> None:
		# The migration-flag and per-company imports-module bypasses now live in
		# the shared assert_transition helper (imports_module/status_pipeline.py),
		# which also adds the privileged single-step backward-correction path.
		if self.is_new():
			return
		previous_status = frappe.db.get_value("Commercial Invoice", self.name, "status")
		assert_transition(
			"Commercial Invoice", previous_status, self.status, _ALLOWED_TRANSITIONS, self
		)
