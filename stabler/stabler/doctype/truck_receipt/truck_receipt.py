"""Truck Receipt controller.

One record per truck that delivers against a GRN Checklist. SUBMITTABLE: the
submit is the physical stock event — before submit the expected packing is
frozen, then a partial Purchase Receipt is created + submitted (critique M7), the
parent GRN Checklist is recomputed, and the Import Truck is advanced to
GRN_CREATED. Those side effects are wired via doc_events in imports_module/hooks
so they self-gate on the migration flag + per-company imports toggle.

The controller stays thin: `validate` recomputes this truck's totals, runs the
cold-chain temperature check (frappe-free `receipt_math.temperature_ok`) — an
out-of-range reading requires a QC note before the receipt can be saved — and
names any line that would enter the Purchase Receipt with no price at all.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from stabler.stabler.imports_module import receipt_math


class TruckReceipt(Document):
	def validate(self) -> None:
		from stabler.stabler.imports_module.hooks import _validate_truck_receipt_scope

		grn, _truck = _validate_truck_receipt_scope(self)
		self._recompute_totals()
		self._check_temperature()
		self._warn_unpriced_lines(grn)

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

	def _warn_unpriced_lines(self, grn) -> None:
		"""Name, at edit time, every line that would enter the receipt with no price.

		The Purchase Receipt is priced from the linked Purchase Order, but Proforma
		Invoice and Purchase Order are unlinked parallel structures here and PO
		creation is manual, so `resolve_po_rate` routinely finds no match (or several
		with differing rates) and yields 0. The row's manual `rate` is the escape
		hatch; with neither, stock enters the warehouse valued at zero. The submit
		hook throws on exactly that — but by then the operator has clicked Submit and
		the truck's paperwork is behind them, so say it here while the lines are still
		in front of them.

		Deliberately a `msgprint`, never a `throw`. `validate` runs on every save, so
		a throw would make the DRAFT unsavable — and the draft is where the boxes,
		weights, temperature, seal and damage trail are captured, evidence that only
		exists while the truck is at the gate and cannot be reconstructed later. A
		draft posts nothing to stock or to the ledger, so there is no valuation to
		defend at this point; submit stays the hard block.

		The PO rates come from the same `_po_item_rows_for_ci` + `resolve_po_rate`
		pair the build path uses, so this warning and the submit block cannot
		disagree about which lines are unpriced.
		"""
		from stabler.stabler.imports_module.hooks import _po_item_rows_for_ci, _should_run

		# Only warn where a Purchase Receipt would actually be built: the same M6
		# gate the submit hook applies, so a company with imports automation off
		# never sees a warning about a document it will never create.
		if not _should_run(grn):
			return

		rows = []
		for it in self.items or []:
			# Damaged/rejected weight never reaches the Purchase Receipt, so its rate
			# is irrelevant — matching `_create_pr_for_truck_receipt` line for line.
			qty = receipt_math.good_qty(it.received_kg, it.condition)
			if qty <= 0:
				continue
			rows.append(
				{
					"idx": it.idx,
					"item_code": it.grn_item_code,
					"qty": qty,
					# Raw, exactly as `_create_pr_for_truck_receipt` passes it —
					# `effective_rate` does the blank/unreadable handling itself.
					"manual_rate": it.get("rate"),
					"po_rate": 0.0,
				}
			)
		if not rows:
			return

		po_item_rows = _po_item_rows_for_ci(grn.commercial_invoice)
		for row in rows:
			row["po_rate"] = receipt_math.resolve_po_rate(row["item_code"], po_item_rows)["rate"]

		unpriced = receipt_math.unpriced_lines(rows)
		if not unpriced:
			return

		listed = "<br>".join(
			frappe._("Row {0}: {1}").format(row.get("idx"), row.get("item_code")) for row in unpriced
		)
		frappe.msgprint(
			frappe._(
				"No Purchase Order price was found for these lines, and no rate was entered "
				"on them, so they would enter stock valued at zero:<br>{0}<br>"
				"Enter a Rate on each line, or link the Purchase Order that covers them. "
				"The receipt cannot be submitted until every line has a price."
			).format(listed),
			title=frappe._("Lines with no price"),
			indicator="orange",
		)
