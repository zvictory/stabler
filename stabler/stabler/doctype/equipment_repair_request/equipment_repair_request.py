"""Equipment Repair Request controller.

Tracks the lifecycle of a service ticket against an Equipment asset:
Open -> InProgress -> Resolved, with Cancelled as an explicit terminal exit.
``resolved_at`` is stamped automatically when status transitions to Resolved.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class EquipmentRepairRequest(Document):
	def before_insert(self) -> None:
		if not self.reported_by:
			self.reported_by = frappe.session.user
		if not self.reported_at:
			self.reported_at = frappe.utils.now_datetime()

	def validate(self) -> None:
		if self.status == "Resolved" and not self.resolved_at:
			self.resolved_at = frappe.utils.now_datetime()
		elif self.status != "Resolved":
			# Clear the stamp if reopened, so re-resolution timestamps fresh.
			self.resolved_at = None
