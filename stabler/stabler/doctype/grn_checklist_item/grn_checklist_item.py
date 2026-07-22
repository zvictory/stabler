import frappe
from frappe.model.document import Document


class GRNChecklistItem(Document):
	def validate(self) -> None:
		self._reject_direct_mutation()

	def on_trash(self) -> None:
		self._reject_direct_mutation()

	def _reject_direct_mutation(self) -> None:
		frappe.throw(
			frappe._("GRN rows must be changed through GRN Checklist.")
		)
