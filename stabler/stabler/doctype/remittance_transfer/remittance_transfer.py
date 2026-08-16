"""The master record. Today the Journal Entry chain IS the record, which is why a
concurrent double payout is possible at all.

This class owns the SCHEMA invariants only — the ones that must hold for any row,
whoever wrote it. The row lock and `client_request_id` replay handling belong to the
command handlers (`stabler-4lc3`), because a document cannot serialise or de-duplicate
its own callers.

Three invariants live here:

1. The frozen triple closes. `principal + commission == tendered`, to the cent. Only
   one of the three is ever rounded and the third is a plug, so a row where they do not
   close was not produced by the pricing rule and must not be trusted by the receipt,
   the refund or the reconciliation — all of which read the stored values and never
   recompute them.
2. Inclusive commission cannot swallow the principal.
3. `Registered + Unposted` is unreachable. The state transition and the JE submit share
   a transaction, so a registered transfer always has its obligation posted. Reaching
   that pair means the payout queue could debit an obligation that was never created.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class RemittanceTransfer(Document):
	def validate(self) -> None:
		self._assert_triple_closes()
		self._assert_inclusive_leaves_a_principal()
		self._assert_registered_is_posted()

	def _assert_triple_closes(self) -> None:
		principal = flt(self.principal, 2)
		commission = flt(self.commission, 2)
		tendered = flt(self.tendered, 2)
		if flt(principal + commission, 2) != tendered:
			frappe.throw(
				_("Principal {0} plus commission {1} must equal {2}, not {3}.").format(
					principal, commission, flt(principal + commission, 2), tendered
				)
			)

	def _assert_inclusive_leaves_a_principal(self) -> None:
		if self.commission_mode != "Inclusive":
			return
		if flt(self.commission, 2) >= flt(self.tendered, 2):
			frappe.throw(
				_("Inclusive commission {0} cannot be the whole amount tendered {1}.").format(
					flt(self.commission, 2), flt(self.tendered, 2)
				)
			)

	def _assert_registered_is_posted(self) -> None:
		if self.operational_status == "Registered" and self.accounting_status == "Unposted":
			frappe.throw(
				_(
					"A registered transfer cannot be unposted — the obligation must exist "
					"before it can be paid out."
				)
			)
