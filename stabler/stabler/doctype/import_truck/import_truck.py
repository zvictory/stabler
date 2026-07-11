"""Import Truck controller.

Non-submittable operational document (critique M5): the Iran -> Uzbekistan road
leg is enforced as a one-way status pipeline via the shared `assert_transition`
helper. A single-step backward correction is allowed for an Imports Manager who
supplies a `status_correction_reason`.

The CROSSED_BORDER side effect (create the DRAFT cross-border transport Purchase
Invoice) is wired through `doc_events` on_update in the app hooks.py — see
stabler/stabler/imports_module/hooks.py:on_truck_update.
"""

import frappe
from frappe.model.document import Document

from stabler.stabler.imports_module.status_pipeline import assert_transition

_ALLOWED_TRANSITIONS = {
	"PENDING": {"DEPARTED_IRAN", "Cancelled"},
	"DEPARTED_IRAN": {"AT_BORDER", "Cancelled"},
	"AT_BORDER": {"CROSSED_BORDER", "Cancelled"},
	"CROSSED_BORDER": {"IN_TRANSIT", "Cancelled"},
	"IN_TRANSIT": {"ARRIVED", "Cancelled"},
	"ARRIVED": {"UNLOADING", "Cancelled"},
	"UNLOADING": {"GRN_CREATED", "Cancelled"},
	"GRN_CREATED": {"COMPLETED", "Cancelled"},
	"COMPLETED": set(),
	"Cancelled": set(),
}


class ImportTruck(Document):
	def validate(self) -> None:
		if self.is_new():
			return
		previous_status = frappe.db.get_value("Import Truck", self.name, "status")
		assert_transition("Import Truck", previous_status, self.status, _ALLOWED_TRANSITIONS, self)
