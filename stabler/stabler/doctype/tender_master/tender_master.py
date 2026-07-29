from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class TenderMaster(Document):
	def validate(self) -> None:
		if self.publication_date and self.submission_deadline:
			if getdate(self.submission_deadline) < getdate(self.publication_date):
				frappe.throw(_("Submission deadline cannot be before publication date."))
