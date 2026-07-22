"""Truck Receipt controller.

One record per truck that delivers against a GRN Checklist. SUBMITTABLE: the
submit is the physical stock event — on submit a partial Purchase Receipt is
created + submitted (critique M7), the parent GRN Checklist is recomputed, and
the Import Truck is advanced to GRN_CREATED. Those side effects are wired via
doc_events (imports_module/hooks.truck_receipt_on_submit / _on_cancel) so they
self-gate on the migration flag + per-company imports toggle.

The controller stays thin: `validate` recomputes this truck's totals and runs
the cold-chain temperature check (frappe-free `receipt_math.temperature_ok`) —
an out-of-range reading requires a QC note before the receipt can be saved.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from stabler.stabler.imports_module import receipt_math


class TruckReceipt(Document):
	def validate(self) -> None:
		from stabler.stabler.imports_module.hooks import _validate_truck_receipt_scope

		_validate_truck_receipt_scope(self)
		self._recompute_totals()
		self._check_temperature()

	def _recompute_totals(self) -> None:
		self.total_boxes_this_truck = sum(cint(r.received_boxes) for r in self.items or [])
		self.total_kg_this_truck = round(sum(flt(r.received_kg) for r in self.items or []), 2)

	def _check_temperature(self) -> None:
		if self.temperature_at_arrival in (None, ""):
			return
		target_min = target_max = None
		if self.truck:
			target_min, target_max = frappe.db.get_value(
				"Import Truck", self.truck, ["target_temp_min", "target_temp_max"]
			) or (None, None)
		if receipt_math.temperature_ok(self.temperature_at_arrival, target_min, target_max):
			return
		if not (self.qc_notes or "").strip():
			frappe.throw(
				frappe._(
					"Truck temperature {0} C is outside the target range {1} C to {2} C; "
					"record a QC note to save."
				).format(self.temperature_at_arrival, target_min, target_max)
			)
		# Out of range but explained — flag it and let the receipt through.
		self.temperature_check_passed = 0
