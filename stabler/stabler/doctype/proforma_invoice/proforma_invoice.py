import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ProformaInvoice(Document):
	def validate(self):
		self._compute_lines()
		self._compute_docs_totals()
		self._default_and_check_earmark()

	def _compute_lines(self):
		"""MSA line math: qty defaults to boxes × box_weight_kg; amount = qty × rate
		(agreed price); docs_amount = qty × docs_price. agreed_total defaults to
		the line sum when unset."""
		total = 0.0
		for row in self.items or []:
			if not flt(row.qty) and flt(row.get("boxes")) and flt(row.get("box_weight_kg")):
				row.qty = flt(row.boxes) * flt(row.box_weight_kg)
			row.amount = flt(row.qty) * flt(row.rate)
			row.docs_amount = flt(row.qty) * flt(row.get("docs_price"))
			total += flt(row.amount)
		if not flt(self.agreed_total):
			self.agreed_total = total

	def _compute_docs_totals(self):
		"""docs_total = Σ line docs_amount (customs-declaration value, never GL);
		cash_difference = agreed_total − docs_total (MSA identity)."""
		docs = sum(flt(r.get("docs_amount")) for r in (self.items or []))
		if docs or self.items:
			self.docs_total = docs
		self.cash_difference = flt(self.agreed_total) - flt(self.docs_total)

	def _default_and_check_earmark(self):
		"""bank_agreed + cash_agreed must equal agreed_total (both fully in GL).

		Default split follows the MSA suggestion: the bank/official leg carries
		the docs (declared) value, cash carries the difference. Without a docs
		total the whole amount defaults to the bank leg — a PI is never blocked
		for an unspecified split.
		"""
		agreed = flt(self.agreed_total)
		bank, cash = flt(self.bank_agreed), flt(self.cash_agreed)
		if bank == 0 and cash == 0:
			docs = flt(self.docs_total)
			if 0 < docs <= agreed:
				self.bank_agreed = docs
				self.cash_agreed = agreed - docs
			else:
				self.bank_agreed = agreed
			bank = flt(self.bank_agreed)
		if abs((bank + flt(self.cash_agreed)) - agreed) > 0.5:
			frappe.throw(
				_("Bank Agreed + Cash Agreed ({0}) must equal Agreed Total ({1}).").format(
					flt(self.bank_agreed) + flt(self.cash_agreed), agreed
				)
			)
