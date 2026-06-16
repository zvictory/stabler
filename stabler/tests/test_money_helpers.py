from __future__ import annotations

import unittest
from types import SimpleNamespace

from stabler.api.money import (
	_invoice_payment_amount,
	_invoice_payment_can_allocate,
	_payment_entry_list_amount,
)


class MoneyHelperTest(unittest.TestCase):
	def test_invoice_payment_can_allocate_only_submitted_invoices(self):
		self.assertFalse(_invoice_payment_can_allocate(0))
		self.assertTrue(_invoice_payment_can_allocate(1))
		self.assertFalse(_invoice_payment_can_allocate(2))

	def test_invoice_payment_amount_uses_outstanding_for_submitted_invoice(self):
		doc = SimpleNamespace(docstatus=1, outstanding_amount="125000", grand_total="150000")

		self.assertEqual(_invoice_payment_amount(doc), 125000.0)

	def test_invoice_payment_amount_uses_grand_total_for_draft_advance(self):
		doc = SimpleNamespace(docstatus=0, outstanding_amount=0, grand_total="150000")

		self.assertEqual(_invoice_payment_amount(doc), 150000.0)

	def test_invoice_payment_amount_blocks_cancelled_invoice(self):
		doc = SimpleNamespace(docstatus=2, outstanding_amount="125000", grand_total="150000")

		self.assertEqual(_invoice_payment_amount(doc), 0.0)

	def test_payment_entry_list_amount_uses_original_receive_amount(self):
		row = {
			"payment_type": "Receive",
			"paid_amount": "125000",
			"received_amount": "124000",
			"paid_from_account_currency": "UZS",
			"paid_to_account_currency": "USD",
		}

		self.assertEqual(_payment_entry_list_amount(row), {"amount": 125000.0, "currency": "UZS"})

	def test_payment_entry_list_amount_uses_original_pay_amount(self):
		row = {
			"payment_type": "Pay",
			"paid_amount": "124000",
			"received_amount": "125000",
			"paid_from_account_currency": "USD",
			"paid_to_account_currency": "UZS",
		}

		self.assertEqual(_payment_entry_list_amount(row), {"amount": 125000.0, "currency": "UZS"})


if __name__ == "__main__":
	unittest.main()
