"""A single row of somebody's payment plan.

A plan row records an intention: this much, to or from this party, on this date,
at this level of confidence. It is not an accounting document and it posts
nothing — money still leaves through Payments / Kassa / Journal, and a row is
closed by hand. Everything here exists to make the row summable: `direction` so
totals split in from out, `base_amount` so a month is one GROUP BY, and a closed
reference set so a row cannot claim to settle a document that has no amount.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt

# Every kind resolves to exactly one side of the total. The two "Other" kinds are
# split by direction rather than left ambiguous: a single "Other" would need the
# user to also pick a direction, and a forecast row whose direction is a free
# choice is a row that lands on the wrong side the first time someone rushes.
DIRECTION_BY_KIND = {
	"Customer Receipt": "In",
	"Vendor Payment": "Out",
	"Item Purchase": "Out",
	"Expense": "Out",
	"Salary": "Out",
	"Tax": "Out",
	"Other Receipt": "In",
	"Other Payment": "Out",
}

# A plan row may only point at a document that carries an amount and a due date.
# Left open, a Dynamic Link accepts User or File, and the form would then try to
# read an outstanding balance off a record that has none.
ALLOWED_REFERENCE_DOCTYPES = (
	"Sales Invoice",
	"Sales Order",
	"Purchase Invoice",
	"Purchase Order",
	"Proforma Invoice",
)


class PaymentPlanEntry(Document):
	def validate(self):
		self._set_direction()
		self._check_amount()
		self._set_base_amount()
		self._check_reference()
		self._sync_realized_on()

	def _set_direction(self):
		kind = (self.kind or "").strip()
		direction = DIRECTION_BY_KIND.get(kind)
		if not direction:
			frappe.throw(frappe._("Unknown payment kind: {0}").format(kind or "-"))
		# Overwritten rather than trusted: a client that sends the wrong side
		# would move money across a director's in/out split.
		self.direction = direction

	def _check_amount(self):
		# Direction carries the sign. A negative amount would double-negate and
		# land on the opposite side of the total.
		if flt(self.amount) <= 0:
			frappe.throw(frappe._("Planned amount must be greater than zero."))

	def _set_base_amount(self):
		rate = flt(self.exchange_rate)
		if rate <= 0:
			# A base-currency row carries no rate. Reading that as 0 would drop
			# the row out of every total while it still shows on the calendar.
			rate = 1.0
			self.exchange_rate = rate
		self.base_amount = flt(flt(self.amount) * rate, 2)

	def _check_reference(self):
		doctype = (self.reference_doctype or "").strip()
		name = (self.reference_name or "").strip()
		if not doctype and not name:
			return
		if not doctype or not name:
			frappe.throw(frappe._("A linked document needs both a type and a document."))
		if doctype not in ALLOWED_REFERENCE_DOCTYPES:
			frappe.throw(frappe._("A payment plan cannot be linked to {0}.").format(doctype))

	def _sync_realized_on(self):
		if self.status == "Realized":
			# Without the date, the calendar cannot tell a plan that landed on
			# time from one that landed two months late.
			if not self.realized_on:
				frappe.throw(frappe._("Set the date this payment was realized."))
			return
		# Reopened or cancelled: drop the date, or the row reads as pending and
		# settled at the same time.
		self.realized_on = None
