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
		if frappe.flags.in_msaerp_migration:
			return
		from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

		if not module_map_for(self.company).get("imports"):
			return
		if self.is_new():
			return
		previous_status = frappe.db.get_value("Commercial Invoice", self.name, "status")
		if not previous_status or previous_status == self.status:
			return
		if self.status not in _ALLOWED_TRANSITIONS.get(previous_status, set()):
			frappe.throw(
				frappe._(
					"Cannot change Commercial Invoice status from {0} to {1}."
				).format(previous_status, self.status)
			)
