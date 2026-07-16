import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ProformaInvoice(Document):
	def validate(self):
		self._compute_lines()
		self._default_and_check_earmark()

	def _compute_lines(self):
		"""Line amount = qty × rate; agreed_total defaults to the line sum."""
		total = 0.0
		for row in self.items or []:
			row.amount = flt(row.qty) * flt(row.rate)
			total += flt(row.amount)
		if not flt(self.agreed_total):
			self.agreed_total = total

	def _default_and_check_earmark(self):
		"""bank_agreed + cash_agreed must equal agreed_total (both fully in GL).

		When neither is set the whole amount defaults to the bank leg, so a PI is
		never blocked for an unspecified split.
		"""
		agreed = flt(self.agreed_total)
		bank, cash = flt(self.bank_agreed), flt(self.cash_agreed)
		if bank == 0 and cash == 0:
			self.bank_agreed = bank = agreed
		if abs((bank + flt(self.cash_agreed)) - agreed) > 0.5:
			frappe.throw(
				_("Bank Agreed + Cash Agreed ({0}) must equal Agreed Total ({1}).").format(
					flt(self.bank_agreed) + flt(self.cash_agreed), agreed
				)
			)
