"""A remittance stage voucher cannot be cancelled out from under its transfer.

Registered as a `Journal Entry` `before_cancel` doc-event in hooks.py, next to
`desk_write_guard.assert_write_via_stabler`. That guard answers "may this caller
write here at all" and deliberately PERMITS anything arriving from `stabler.api.*`
— which is exactly what the Money screen's Cancel button is
(`api/money.py:cancel_journal_entry`, `pages/money/JournalEntries.vue:503`). So
until this module existed, one click on a row the operator was merely browsing
un-posted a paid-out transfer: `operational_status` stayed `Paid Out` while the
obligation re-opened and the destination drawer was credited back. Cancelling the
register entry is worse — `accounting_status` stays `Posted` pointing at a
cancelled voucher, and `_amounts_from_register_entry` then mirrors a cancelled row
into every later stage.

Nothing else caught it: `Remittance Transfer` is not submittable, so Frappe's link
protection (`delete_doc.py:356`, which only holds a cancel back for *submitted*
linking documents) never fires; the imports hook returns early unless the voucher
is a Bank Entry; and the doctype's own checks are validate-time only.

**The decision: refuse, and name the reversal that already exists.**

The alternative the bead offered — let the cancel through but move the transfer's
state with it — was rejected on three counts:

1. *There is already a reversal, and it is not cancellation.* The Refund stage
   (`api/remittance.py:refund_remittance`) returns the cash to the sender, claws
   back the commission and moves the transfer to Refunded, leaving both vouchers
   on the ledger. A cancel-plus-state-move would be a second answer to the same
   question, and the only one of the two that destroys the evidence. Two reversal
   paths is how the books and the trail drift apart.
2. *It would encode a physical impossibility.* Reversing a payout means the cash
   has left the drawer and the receiver has it. No state transition makes them
   hand it back, so "cancel the payout entry" would silently assert a refund that
   never happened.
3. *It cannot cover the legacy transfers.* The JE-only model in `api/remittance.py`
   has no master row to move — a state-carrying reversal would guard the new
   `Remittance Transfer` rows and leave the hole open for every transfer booked
   before them. This refusal keys on `stabler_remittance_id`, which both models
   write, so it closes both.

**The way out for a genuine mistake is in the message**, and it is Refund: the
operator is told what to press, not merely that they may not press this. An
operator who mis-keyed a registration refunds it and registers again — the wrong
figure stays visible, reversed, which is what an audit trail is for.

**The ops door is an explicit flag, not an exemption.** `desk_write_guard` exempts
System Managers and headless contexts because it is a UX layer. Both exemptions
would gut this rule instead: every operator with the Money screen is a System
Manager on these tenants, and "headless" is every background job and scheduler
tick — a door standing open for code nobody reviewed as a cancel path. So neither
the session user nor the request is consulted here (a test asserts that), and the
single door is `doc.flags.ignore_remittance_cancel_guard = True`, which has to be
typed at the call site, greps in one command, and reads as a decision. Same idiom
as `ignore_approval_gate` (`api/approvals.py:309`) and the `ignore_exchange_rate`
flag `remittance_accounting._build_entry` sets.
"""

from __future__ import annotations

import frappe
from frappe import _

# The escape hatch, named once so `rg` finds every use of it.
BYPASS_FLAG = "ignore_remittance_cancel_guard"


def assert_not_a_remittance_stage(doc, method=None) -> None:
	"""Doc-event hook: raise ValidationError when the voucher belongs to a transfer."""
	# Cheapest and most selective first: almost every Journal Entry in the app
	# carries no remittance id and leaves here without touching anything else.
	remittance_id = (doc.get("stabler_remittance_id") or "").strip()
	if not remittance_id:
		return
	if getattr(doc, "flags", None) is not None and doc.flags.get(BYPASS_FLAG):
		return

	stage = (doc.get("stabler_remittance_stage") or "").strip()
	frappe.throw(
		_(
			"Journal Entry {0} is the {1} entry of remittance {2} and cannot be "
			"cancelled — the ledger would move and the transfer's status would not. "
			"To reverse this transfer, post a Refund from the Remittance screen: it "
			"returns the cash to the sender, claws back the commission and moves the "
			"transfer to Refunded, with both vouchers kept on the ledger."
		).format(doc.name, stage or _("stage"), remittance_id),
		frappe.ValidationError,
	)


__all__ = ["BYPASS_FLAG", "assert_not_a_remittance_stage"]
