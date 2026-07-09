"""Commercial Invoice controller.

Enforces the customs-clearance lifecycle as a one-way status pipeline, with
"Cancelled" reachable as an explicit exit from any non-terminal status.
Terminal statuses (Reconciled, Cancelled) accept no further transition.
"""

import frappe
from frappe.model.document import Document

_ALLOWED_TRANSITIONS = {
	"Draft": {"Pending Documents", "Cancelled"},
	"Pending Documents": {"Submitted to Broker", "Cancelled"},
	"Submitted to Broker": {"Declaration Filed", "Cancelled"},
	"Declaration Filed": {"Under Customs Review", "Cancelled"},
	"Under Customs Review": {"Customs Cleared", "Cancelled"},
	"Customs Cleared": {"Goods Received", "Cancelled"},
	"Goods Received": {"Reconciled"},
	"Reconciled": set(),
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
