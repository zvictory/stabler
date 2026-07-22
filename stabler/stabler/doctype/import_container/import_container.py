"""Import Container controller.

Non-submittable operational document (critique M5): the shipping/logistics
lifecycle is enforced as a one-way status pipeline via the shared
`assert_transition` helper, matching the Commercial Invoice pipeline. Once goods
have physically arrived (ARRIVED_AT_IRAN) the deal cannot be walked back, so
that status has no Cancelled exit.

The ARRIVED_AT_IRAN side effect (enqueue the DRAFT 70% advance Payment Entry) is
wired through `doc_events` on_update in the app hooks.py, not here — see
stabler/stabler/imports_module/hooks.py:on_container_update.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

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


class ImportContainer(Document):
	def validate(self) -> None:
		if not self.is_new():
			previous_status = frappe.db.get_value("Import Container", self.name, "status")
			assert_transition(
				"Import Container", previous_status, self.status, _ALLOWED_TRANSITIONS, self
			)
		self._check_packing_snapshot_lock()

	def _packing_signature(self, rows) -> tuple:
		return tuple(
			sorted(
				(row.item_code, cint(row.box_qty), flt(row.box_kg), flt(row.total_kg))
				for row in rows or []
			)
		)

	def _check_packing_snapshot_lock(self) -> None:
		before = self.get_doc_before_save()
		if not before or self._packing_signature(before.items) == self._packing_signature(
			self.items
		):
			return
		grn = frappe.db.get_value(
			"GRN Checklist",
			{"commercial_invoice": self.commercial_invoice},
			["name", "expected_snapshot_locked"],
			as_dict=True,
		)
		if grn and grn.expected_snapshot_locked:
			frappe.throw(
				frappe._(
					"Packing-list quantities are locked by GRN {0} after the first submitted "
					"Truck Receipt."
				).format(grn.name)
			)
