"""POS Payment Session — one Uzbek-gateway QR checkout attempt.

A session is created when the cashier picks an online payment mode (Payme /
Click / Uzum Bank) at the POS. It carries the merchant order reference, the
cart snapshot, and the provider transaction state. The provider webhook
finalizes the session (status = Paid) and materializes the POS Sales Invoice
from the snapshot.

Idempotency is enforced at the DB level by the UNIQUE index on `order_id`,
plus a guarded lookup on `provider_trans_id` inside the webhook handlers.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class POSPaymentSession(Document):
	# states the SPA poller treats as terminal
	TERMINAL = {"Paid", "Cancelled", "Failed", "Expired"}

	def is_terminal(self) -> bool:
		return self.status in self.TERMINAL
