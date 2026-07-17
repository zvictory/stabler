import frappe
from frappe.model.document import Document


class HSDutyRate(Document):
	def validate(self):
		if (self.duty_pct or 0) < 0 or (self.vat_pct or 0) < 0 or (self.excise_pct or 0) < 0:
			frappe.throw("Rates cannot be negative.")
