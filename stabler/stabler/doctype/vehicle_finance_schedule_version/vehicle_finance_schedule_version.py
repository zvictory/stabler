"""Schedule Version — immutable once submitted; exactly one Active per agreement.

Row 0 is the down payment (or the complete cash-settlement row) and IS part of
the schedule total. Previous versions are never edited; a reschedule creates a
new version for the remaining legal balance.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

ROW_0_TYPES = ("Down Payment", "Cash Settlement")


def validate_rows(rows: list, *, agreement_total: float, settlement_mode: str, precision: int = 2) -> None:
	"""Pure row-set validation shared by the controller and the builder tests.

	Raises ValueError with a message stating both numbers on a sum mismatch.
	"""
	if not rows:
		raise ValueError("Schedule must have at least one row.")
	if flt(agreement_total) <= 0:
		raise ValueError("Agreement total must be greater than zero.")
	amount_sum = 0.0
	previous_date = None
	previous_sequence = None
	for row in rows:
		# Row 0 carries the down payment, which may legitimately be zero.
		if int(row.get("sequence")) != 0 and flt(row.get("amount")) <= 0:
			raise ValueError("Schedule row amounts must be greater than zero.")
		due = getdate(row.get("due_date"))
		if previous_date is not None and due <= previous_date:
			raise ValueError("Schedule due dates must be strictly increasing.")
		if previous_sequence is not None and int(row.get("sequence")) <= previous_sequence:
			raise ValueError("Schedule sequence numbers must be strictly increasing.")
		previous_date = due
		previous_sequence = int(row.get("sequence"))
		amount_sum += flt(row.get("amount"))
	if int(rows[0].get("sequence")) != 0 or rows[0].get("row_type") not in ROW_0_TYPES:
		raise ValueError("Row 0 must be the down payment (or cash settlement) row.")
	if settlement_mode == "Cash":
		if len(rows) != 1 or rows[0].get("row_type") != "Cash Settlement":
			raise ValueError("A cash agreement has exactly one cash-settlement row.")
	if round(amount_sum, precision) != round(flt(agreement_total), precision):
		raise ValueError(
			"Schedule rows sum to {0} but the agreement total is {1}.".format(
				round(amount_sum, precision), round(flt(agreement_total), precision)
			)
		)


class VehicleFinanceScheduleVersion(Document):
	def validate(self) -> None:
		self._validate_version_rules()
		agreement = frappe.get_doc("Vehicle Agreement", self.agreement)
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		try:
			validate_rows(
				[r.as_dict() for r in self.rows],
				agreement_total=agreement.total_contract_price,
				settlement_mode=agreement.settlement_mode,
				precision=precision,
			)
		except ValueError as exc:
			frappe.throw(_(str(exc)))
		self.company = agreement.company
		self.currency = agreement.currency
		self.total_amount = sum(flt(r.amount) for r in self.rows)
		if self.status == "Active":
			self._assert_only_active_version()

	def _validate_version_rules(self) -> None:
		if int(self.version_number) < 1:
			frappe.throw(_("Version number must be at least 1."))
		if int(self.version_number) > 1 and not self.reschedule_reason:
			frappe.throw(_("A reschedule reason is mandatory from version 2 onward."))

	def _assert_only_active_version(self) -> None:
		others = frappe.db.count(
			"Vehicle Finance Schedule Version",
			{
				"agreement": self.agreement,
				"status": "Active",
				"docstatus": ("<", 2),
				"name": ("!=", self.name or ""),
			},
		)
		if others:
			frappe.throw(_("Agreement {0} already has an active schedule version.").format(self.agreement))
