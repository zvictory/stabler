"""One recorded loss on one Work Order, and the draft stock movement that keeps
it honest.

Measured on anjan 2026-08-27, read-only: this floor already moves scrap through
the stock ledger by hand — 25 Stock Entries, 35 037 units, $3 941, into two
scrap warehouses, filed by three people, latest 2026-08-22. The pattern is always
the same: a Material Transfer into the scrap warehouse, then a Material Issue to
write it off, with the reason surviving only as a free-text Uzbek paragraph in
`remarks`. So this record does not invent a flow. It gives the existing one a
keyboard and a reason code.

**Option B, chosen by Zafar:** the record writes a **DRAFT** Material Transfer.
Accounting submits it in the Desk, exactly as they do today. An operator never
submits stock movement — that would be a new authority, not a faster one.

Why the draft is a plain `Material Transfer` and not `Material Transfer for
Manufacture`: the second one increments `Work Order Item.transferred_qty`, which
tells ERPNext that *more* material arrived in WIP. The opposite of what happened.
The price of the plain transfer is that ERPNext's own `transferred_qty -
consumed_qty` does not fall when scrap leaves, which is why this log keeps its own
subtraction — see `available_to_scrap`.

Every refusal below lives in `validate` rather than in the endpoint, so a Desk
write is refused the same way an API write is. That is not theoretical here:
3856 of 3856 production entries on this site came from two Desk accounts.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from stabler.api._scrap import available_to_scrap, validate_scrap
from stabler.stabler.doctype.stabler_manufacturing_settings.stabler_manufacturing_settings import (
	get_scrap_warehouse,
)

#: The message shown for each refusal `validate_scrap` can return. Kept here
#: rather than in the frappe-free helper so that module stays importable without
#: a bench, and so the wording is translated in one place. Same split as
#: `Stabler Line Stop._REFUSALS`.
_REFUSALS = {
	"missing_qty": "A scrap record needs a quantity.",
	"zero_qty": "A scrap record with no quantity is a double-tap, not a loss.",
	"negative_qty": "A negative quantity would move stock back onto the line. Record what was lost.",
}

#: ERPNext matches this string exactly to decide what a Stock Entry is. Spelled
#: once because it is read from two places in this file.
_SE_TRANSFER = "Material Transfer"


class StablerLineScrap(Document):
	def validate(self) -> None:
		self._require_work_order()
		order = self._order()
		self._assert_order_belongs_to_this_company(order)
		self.line = order.wip_warehouse
		self._assert_frozen_once_transferred()
		self._assert_rejects_were_not_already_reported()
		# Read before the quantity is checked, so "nothing configured" is answered
		# before "too much" — an operator whose site was never set up should be
		# sent to the setting, not told their number is wrong.
		get_scrap_warehouse(self.company)
		self._check_quantity_against_wip()
		self.reported_by = self.reported_by or frappe.session.user

	def after_insert(self) -> None:
		self._write_the_draft_transfer()

	def on_trash(self) -> None:
		self._refuse_to_orphan_a_submitted_transfer()

	# ----- refusals ---------------------------------------------------------

	def _require_work_order(self) -> None:
		"""Required, unlike a line stop, and the difference is deliberate.

		A line stops between orders as often as during one, so `Stabler Line Stop`
		leaves the order optional. Lost material is not like that: it came out of
		a specific WIP warehouse, it was carried there by a specific order, and
		every check below — which items may be named, how much of one is standing
		there — is relative to that order. Without it there is no defensible
		source warehouse for the transfer and no way to tell a real loss from a
		typo.

		Raw material spoiling in the store is a real thing and is deliberately NOT
		this record: it never entered production, and the Desk's own Material
		Issue already handles it. Widening this doctype to cover it would mean
		dropping every guard in this file.
		"""
		if not self.work_order:
			frappe.throw(_("A scrap record needs a Work Order."))

	def _order(self):
		return frappe.db.get_value(
			"Work Order",
			self.work_order,
			["name", "company", "wip_warehouse"],
			as_dict=True,
		)

	def _assert_order_belongs_to_this_company(self, order) -> None:
		"""`company` and `work_order` arrive as two independent values with
		nothing in the pair saying they belong together — the same hole
		`log_line_stop` closed. Checked here rather than only in the endpoint so
		a Desk write cannot walk around it."""
		if not order:
			frappe.throw(_("Unknown Work Order: {0}").format(self.work_order))
		if order.company != self.company:
			frappe.throw(_("That Work Order belongs to another company."), frappe.PermissionError)
		if not order.wip_warehouse:
			frappe.throw(_("{0} has no WIP warehouse to scrap from.").format(self.work_order))

	def _assert_frozen_once_transferred(self) -> None:
		"""What the record says and what its draft says must not be able to drift.

		The draft is written once, at insert. Editing the quantity or the item
		afterwards would leave a record reading 5 kg beside a stock document
		moving 3 kg, and the two would be filed together, under one name, saying
		different things. Cancelling the transfer and filing again costs one
		minute and leaves both numbers true.
		"""
		if self.is_new() or not self.stock_entry:
			return
		for field in ("work_order", "item_code", "qty"):
			if self.has_value_changed(field):
				frappe.throw(
					_(
						"A scrap record cannot be changed once its stock transfer exists. Cancel that transfer and file a new record."
					)
				)

	def _assert_rejects_were_not_already_reported(self) -> None:
		"""The double count, closed from this side.

		A finished-goods reject path shipped on 2026-06-08 (`410f2ba`) and has
		never been used: `process_loss_qty > 0` on 0 of 3757 Manufacture entries.
		It takes a bare `scrap_qty` at Finish and inflates `fg_completed_qty` to
		good+loss so ERPNext's own equality check passes. That draws the raw
		material for the lost units and receives none of it anywhere — the cost is
		absorbed into the good output's unit cost.

		Which is the same loss this record moves into the scrap warehouse. Both,
		for one order, charges the material twice: once inside the good units'
		cost, once as stock standing in the scrap warehouse. Nothing throws; each
		number is individually correct and their sum is wrong.

		So the two are mutually exclusive per Work Order and the refusal runs in
		both directions. The other half lives in
		`manufacturing._assert_no_scrap_record`.
		"""
		if not self.is_new():
			return
		if frappe.db.exists(
			"Stock Entry",
			{
				"work_order": self.work_order,
				"purpose": "Manufacture",
				"docstatus": 1,
				"process_loss_qty": [">", 0],
			},
		):
			frappe.throw(
				_(
					"Rejects were already entered when this order was finished. Record the loss in one place, not two."
				)
			)

	def _check_quantity_against_wip(self) -> None:
		row = frappe.db.get_value(
			"Work Order Item",
			{"parent": self.work_order, "item_code": self.item_code},
			["transferred_qty", "consumed_qty", "stock_uom"],
			as_dict=True,
		)
		if not row:
			# Not merely an unknown item: naming one the order never carried would
			# draft a transfer of somebody else's material out of a WIP warehouse
			# shared by five departments' worth of orders.
			frappe.throw(_("{0} is not one of this order's materials.").format(self.item_code))

		self.uom = self.uom or row.stock_uom or frappe.db.get_value("Item", self.item_code, "stock_uom")
		available = available_to_scrap(row.transferred_qty, row.consumed_qty, self._already_scrapped())
		allowed, refusal = validate_scrap(self.qty, available)
		if allowed:
			return
		if refusal == "nothing_in_wip":
			frappe.throw(_("{0} has nothing in WIP on this order to scrap.").format(self.item_code))
		if refusal == "more_than_wip_holds":
			frappe.throw(
				_("{0} holds only {1} of {2} in WIP on this order.").format(
					self.work_order, available, self.item_code
				)
			)
		frappe.throw(_(_REFUSALS.get(refusal, "That quantity cannot be recorded.")))

	def _already_scrapped(self) -> float:
		"""What this log has itself sent to scrap for this order and item.

		Cancelled transfers are excluded — a cancelled entry moved nothing, and
		counting it would lock away stock that is still standing in WIP. Records
		whose draft is still unsubmitted ARE counted: the operator has already
		said those kilograms are gone, and letting a second record claim them
		would simply move the collision to the Desk, where it becomes a negative
		stock throw in front of somebody who cannot know the right number.
		"""
		rows = frappe.get_all(
			"Stabler Line Scrap",
			filters={
				"work_order": self.work_order,
				"item_code": self.item_code,
				"name": ["!=", self.name or ""],
			},
			fields=["qty", "stock_entry"],
		)
		total = 0.0
		for row in rows:
			if row.stock_entry and frappe.db.get_value("Stock Entry", row.stock_entry, "docstatus") == 2:
				continue
			total += flt(row.qty)
		return total

	def _refuse_to_orphan_a_submitted_transfer(self) -> None:
		"""Deleting the measurement must not leave the movement unexplained.

		Three states, three answers. A submitted transfer has already moved stock
		and its only written reason is this record, so the delete is refused. A
		draft transfer exists only because this record does, so it goes with it —
		otherwise the Desk fills with drafts nobody can account for. A cancelled
		transfer is left alone; it is an audit trace and it moved nothing.

		The other direction needs no code: `stock_entry` is a Link field, so
		Frappe's own link check refuses to delete the Stock Entry while this
		record still points at it.
		"""
		if not self.stock_entry:
			return
		docstatus = frappe.db.get_value("Stock Entry", self.stock_entry, "docstatus")
		if docstatus == 1:
			frappe.throw(_("That scrap record's stock transfer was already submitted. It cannot be deleted."))
		if docstatus == 0:
			# The link has to be cleared BEFORE the entry is deleted, and the reason
			# is the guard described just above: Frappe refuses to delete a document
			# while anything still points at it, and until this column is cleared
			# this row is one of those things. Both halves are correct on their own
			# and only this order lets them both run — written out because the
			# obvious edit (delete first, it is being deleted anyway) restores a
			# `LinkExistsError` that surfaces as a failed delete, not as a bug.
			entry = self.stock_entry
			self.db_set("stock_entry", None, update_modified=False)
			frappe.delete_doc("Stock Entry", entry, ignore_permissions=True)

	# ----- the draft --------------------------------------------------------

	def _write_the_draft_transfer(self) -> None:
		"""The whole point of option B: the number and the ledger, together.

		Inserted, never submitted. `after_insert` rather than `validate` because
		`validate` runs again on every later save and would write a second draft;
		and because a failure here rolls the whole transaction back, so a scrap
		record without its draft cannot exist even for one commit.

		`remarks` carries the reason in words as well as in a link. The three
		people filing these by hand today already read that field — it is where
		the reason lives on all 25 of their entries — so the habit keeps working
		on the day this ships, before anybody has been shown the new screen.
		"""
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": self.company,
				"stock_entry_type": _SE_TRANSFER,
				"purpose": _SE_TRANSFER,
				"from_warehouse": self.line,
				"to_warehouse": get_scrap_warehouse(self.company),
				"remarks": _("Scrap {0}: {1} — {2}, reported by {3}").format(
					self.name, self.reason, self.work_order, self.reported_by
				),
				"items": [
					{
						"item_code": self.item_code,
						"qty": flt(self.qty),
						"uom": self.uom,
						"stock_uom": self.uom,
						"conversion_factor": 1.0,
						"s_warehouse": self.line,
						"t_warehouse": get_scrap_warehouse(self.company),
					}
				],
			}
		)
		# Not `ignore_permissions`: the same operators already post Manufacture and
		# consumption entries through `make_work_order_stock_entry`, which inserts
		# with permissions on. Bypassing the check here would hand a scrap record
		# the authority to write a stock document that its author could not write
		# directly — a privilege escalation dressed as a convenience, and one the
		# sibling path deliberately does not take.
		entry.insert(ignore_permissions=False)
		self.db_set("stock_entry", entry.name, update_modified=False)
