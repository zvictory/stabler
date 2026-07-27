import frappe
from frappe.model.document import Document


class StablerVendorCategory(Document):
	def validate(self):
		# Validate unique categories per vendor
		existing = frappe.db.exists(
			"Stabler Vendor Category",
			{"vendor": self.vendor, "category_name": self.category_name, "name": ["!=", self.name]},
		)
		if existing:
			frappe.throw(
				frappe._("Vendor category '{0}' already exists for this vendor.").format(self.category_name)
			)
