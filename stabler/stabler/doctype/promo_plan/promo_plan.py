from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class PromoPlan(Document):
	def validate(self) -> None:
		if self.start_date and self.end_date and self.end_date < self.start_date:
			frappe.throw(_("End Date must be on or after Start Date."))
