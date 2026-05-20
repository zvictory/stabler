import frappe
from frappe import _
from frappe.model.document import Document


class Visit(Document):
	def validate(self):
		if self.status == "Skipped" and not (self.skip_reason or "").strip():
			frappe.throw(_("Skip reason is required when status is Skipped."))
		if self.check_out_at and not self.check_in_at:
			frappe.throw(_("Cannot check out before checking in."))
