"""Import Expense controller.

Plain-Link operational document (critique m1 — commercial_invoice / container /
truck are plain Links, never a Dynamic Link). Payment status (Pending / Partial
/ Paid) is derived in ``validate`` from the bank + cash split vs the amount,
matching Django ``CIExpense.clean``.

The DRAFT service Purchase Invoice side effect is wired through ``doc_events``
on_update in the app hooks.py (imports_module/hooks.import_expense_on_update) —
transport-category expenses are billed by the truck CROSSED_BORDER hook instead
(the 3-tier lookup), so they are excluded there to avoid a double bill.
"""

from frappe.model.document import Document

from stabler.stabler.imports_module import payment_math as pm


class ImportExpense(Document):
	def validate(self) -> None:
		self.status = pm.expense_status(self.amount, self.bank_payment, self.cash_payment)
