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

from stabler.stabler.imports_module import packing_service
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
		before = self.get_doc_before_save()
		if not self.is_new():
			previous_status = frappe.db.get_value("Import Container", self.name, "status")
			assert_transition("Import Container", previous_status, self.status, _ALLOWED_TRANSITIONS, self)
		self._lock_packing_source(before)
		self._validate_commercial_invoice_company()
		self._check_packing_snapshot_lock(before)

	def _lock_packing_source(self, before) -> None:
		if before and (
			before.commercial_invoice == self.commercial_invoice
			and before.company == self.company
			and self._packing_signature(before.items) == self._packing_signature(self.items)
		):
			return
		packing_service.lock_commercial_invoices(
			[
				before.commercial_invoice if before else None,
				self.commercial_invoice,
			]
		)

	def _validate_commercial_invoice_company(self) -> None:
		if not self.commercial_invoice:
			return
		ci_company = frappe.db.get_value("Commercial Invoice", self.commercial_invoice, "company")
		if ci_company and self.company != ci_company:
			frappe.throw(frappe._("Import Container company must match Commercial Invoice company."))

	def _packing_signature(self, rows) -> tuple:
		# Container-row order is non-semantic: packing aggregation groups by item.
		return tuple(
			sorted(
				(
					# Normalise like GRNChecklist._expected_signature — a None
					# item_code must not sort-crash or compare unequal to "".
					row.item_code or "",
					row.category or "",
					cint(row.box_qty),
					flt(row.box_kg),
					flt(row.total_kg),
				)
				for row in rows or []
			)
		)

	def _immutable_grn_for_ci(self, commercial_invoice):
		if not commercial_invoice:
			return None
		grn = frappe.db.get_value(
			"GRN Checklist",
			{"commercial_invoice": commercial_invoice},
			["name", "docstatus", "expected_snapshot_locked"],
			as_dict=True,
			for_update=True,
		)
		if not grn:
			return None
		if cint(grn.docstatus) != 0 or cint(grn.expected_snapshot_locked):
			return grn.name
		if frappe.db.get_value(
			"Truck Receipt",
			{"grn_checklist": grn.name, "docstatus": 1},
			"name",
			for_update=True,
		):
			return grn.name
		return None

	def _reject_locked_packing_source(self, commercial_invoice) -> None:
		grn_name = self._immutable_grn_for_ci(commercial_invoice)
		if grn_name:
			frappe.throw(frappe._("Packing source is locked by GRN {0}.").format(grn_name))

	def _check_packing_snapshot_lock(self, before) -> None:
		if not before:
			self._reject_locked_packing_source(self.commercial_invoice)
			return
		if before.commercial_invoice != self.commercial_invoice:
			self._reject_locked_packing_source(before.commercial_invoice)
			self._reject_locked_packing_source(self.commercial_invoice)
			return
		if self._packing_signature(before.items) == self._packing_signature(self.items):
			return
		grn_name = self._immutable_grn_for_ci(self.commercial_invoice)
		if grn_name:
			frappe.throw(
				frappe._(
					"Packing-list quantities are locked by GRN {0} after the first submitted Truck Receipt."
				).format(grn_name)
			)

	def on_trash(self) -> None:
		packing_service.lock_commercial_invoices([self.commercial_invoice])
		self._reject_locked_packing_source(self.commercial_invoice)
