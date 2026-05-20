from frappe.model.document import Document


class OSAAudit(Document):
	def validate(self) -> None:
		lines = list(self.lines or [])
		self.total_skus = len(lines)
		self.present_skus = sum(1 for line in lines if line.present)
		self.osa_pct = (self.present_skus / self.total_skus * 100.0) if self.total_skus else 0.0
