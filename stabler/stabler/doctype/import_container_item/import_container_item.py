import frappe
from frappe.model.document import Document


class ImportContainerItem(Document):
	def validate(self) -> None:
		self._reject_direct_mutation()

	def on_trash(self) -> None:
		self._reject_direct_mutation()

	def _reject_direct_mutation(self) -> None:
		frappe.throw(frappe._("Packing-list rows must be changed through Import Container."))
