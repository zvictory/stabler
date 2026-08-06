"""GRN Checklist controller.

Umbrella progressive-acceptance document (critique M6/M7): one per Commercial
Invoice, it tracks cumulative receipt across many Truck Receipts and is the
financially-binding completion doc, so it is SUBMITTABLE. On submit it triggers
the DRAFT Landed Cost Voucher build (wired via doc_events on_submit ->
imports_module/hooks.grn_on_submit).

The controller stays thin: `validate` recomputes every derived total/variance
field from the child rows, delegating all arithmetic to the frappe-free
`grn_math` module. The received quantities on the child rows are maintained by
the Truck Receipt submit/cancel flow (imports_module/hooks.recompute_grn_from_
receipts); this controller only turns expected-vs-received into pending /
variance / category / status.

Submit-time gates (received-kg present, valid Vet Certificate unless an Imports
Manager set the override) live in imports_module/hooks.grn_before_submit so they
self-gate on the migration flag + per-company imports toggle.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from stabler.stabler.imports_module import grn_math


class GRNChecklist(Document):
	def validate(self) -> None:
		self._validate_locked_snapshot()
		self.update_totals()

	def _validate_locked_snapshot(self) -> None:
		"""Snapshot-managed fields may only change through the receipt workflow.

		The guard used to arm itself only once ``expected_snapshot_locked`` was already
		set, which left two holes: an unlocked-but-saved GRN's expected rows could be
		rewritten by any direct save, and ``expected_snapshot_locked`` /
		``expected_snapshot_locked_at`` could be forged 0 -> 1 so a snapshot that was
		never derived from the packing lists looked frozen. Both matter because the
		expected quantities are what the Landed Cost Voucher and the variance report are
		measured against. Every legitimate writer (``hooks._lock_grn_expected_snapshot``,
		``imports.refresh_grn_expected_quantities``) already runs inside
		``packing_service.allow_expected_snapshot_update()``, so the guard is now
		unconditional and the ``frappe.flags`` gate is the only way through.
		"""
		before = self.get_doc_before_save()
		if not before:
			return
		if frappe.flags.get("in_grn_snapshot_update"):
			return
		if (
			self.company != before.company
			or self.commercial_invoice != before.commercial_invoice
			or cint(self.expected_snapshot_locked) != cint(before.expected_snapshot_locked)
			or self.expected_snapshot_locked_at != before.expected_snapshot_locked_at
			or self._expected_signature(self.grn_items) != self._expected_signature(before.grn_items)
		):
			frappe.throw(
				frappe._(
					"GRN snapshot is locked against direct edits; snapshot-managed fields "
					"can only be changed by the receipt workflow."
				)
			)

	@staticmethod
	def _expected_signature(rows) -> tuple:
		return tuple(
			sorted(
				(
					row.name or "",
					row.item_code or "",
					row.item_name or "",
					cint(row.expected_boxes),
					flt(row.expected_box_kg),
					flt(row.expected_total_kg),
				)
				for row in rows or []
			)
		)

	def update_totals(self) -> None:
		"""Recompute expected/received/pending/variance from the child rows."""
		expected_boxes = 0
		expected_kg = 0.0
		received_boxes = 0
		received_kg = 0.0

		for row in self.grn_items or []:
			line = grn_math.compute_line(
				row.expected_boxes, row.expected_total_kg, row.received_boxes, row.received_kg
			)
			row.pending_boxes = line["pending_boxes"]
			row.pending_kg = line["pending_kg"]
			row.variance_kg = line["variance_kg"]
			row.variance_percentage = line["variance_pct"]
			row.status = line["status"]

			expected_boxes += cint(row.expected_boxes)
			expected_kg += flt(row.expected_total_kg)
			received_boxes += cint(row.received_boxes)
			received_kg += flt(row.received_kg)

		self.expected_total_boxes = expected_boxes
		self.expected_total_kg = round(expected_kg, 2)
		self.received_total_boxes = received_boxes
		self.received_total_kg = round(received_kg, 2)

		header = grn_math.compute_header(expected_boxes, expected_kg, received_boxes, received_kg)
		self.pending_total_boxes = header["pending_boxes"]
		self.pending_total_kg = header["pending_kg"]
		self.variance_boxes = header["variance_boxes"]
		self.variance_kg = header["variance_kg"]
		self.variance_percentage = header["variance_pct"]
		self.variance_category = header["category"]
		self.completion_percentage = header["completion_pct"]
		self.receipt_status = header["receipt_status"]
		if header["claim_required"]:
			self.claim_required = 1
