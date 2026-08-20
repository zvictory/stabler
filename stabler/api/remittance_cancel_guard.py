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

**The decision: refuse, and say what is actually available today.**

The alternative the bead offered — let the cancel through but move the transfer's
state with it — was rejected on two counts:

1. *It would encode a physical impossibility.* Reversing a payout means the cash
   has left the drawer and the receiver has it. No state transition makes them
   hand it back, so "cancel the payout entry" would silently assert a refund that
   never happened.
2. *It cannot cover the legacy transfers.* The JE-only model in `api/remittance.py`
   has no master row to move — a state-carrying reversal would guard the new
   `Remittance Transfer` rows and leave the hole open for every transfer booked
   before them. This refusal keys on `stabler_remittance_id`, which both models
   write, so it closes both.

**What the message may promise, measured rather than assumed — and it has been
wrong in both directions.** The first draft sent the operator to "post a Refund
from the Remittance screen" when no such screen existed, which was a worse
regression than the bug: before the guard, the (unsafe) Cancel button was at
least *a* recourse. The correction said no screen reverses a remittance at all —
and then slice 4 of `stabler-yf1w` shipped `RemittanceRefund.vue`, which works
the three-signature refund and reaches all four commands. The correction stayed
in the tree anyway, because `RemittanceReversalReachabilityTest` scanned
`public/js` for a contiguous `stabler.api.remittance_commands.request_refund`
and `api/remittance.js:182` writes ``call(`${CMD}.request_refund`)`` — so the two
tests written expressly to go red that day never saw the call. Naming no recourse
when one exists is not the safe direction; it is the same defect facing the other
way, and it sends an operator to a person when a button would have done.

**So the branch is keyed on what can actually be reversed, not on the stage
alone.** Both engines stamp all three stages (`api/remittance.py:399/520/637`;
`remittance_accounting.py:220`), so the stage does not say which model a voucher
belongs to. `_is_refundable_from_a_screen` asks the transfer row instead, using
`_assert_refundable`'s own precondition (`remittance_commands.py:941`) — still
`Registered`, still `Posted`. A paid-out transfer, an already-refunded one, and a
legacy JE-only remittance with no master row all fail it, and all three get the
escalation message, which is true for each of them.
`RemittanceReversalReachabilityTest` asserts every fact these branches rest on
and goes red the day one changes — including, now, a canary for the scanner
itself, because a blind scanner made the whole class agree with the wrong answer.

**Building that reversal here was rejected, deliberately.** A whitelisted refund
command for `Remittance Transfer` is slice 3 of the parent epic (`stabler-yf1w`,
two-step Requested → Approved → Completed) and has since landed there, where the
row lock and the approval separation live; its SPA action is slice 4. Writing it
here would have collided with that slice and pre-empted a design decision that was
not this bead's to make. So this module fixes the promise, not the product.

**The exit named is escalation, and it exists.** Nothing an operator can click
reverses a transfer, so the message says that plainly and sends them to someone
who has a server-side route: `refund_remittance` for the legacy model,
`post_refund` for the new one, and — where a cancel really is the right answer —
the `BYPASS_FLAG` below. The message is **branched by stage** because the two
cases differ in kind: for a Register-stage voucher a refund is the correct
reversal and merely has no button yet, while for a Payout-stage voucher no
reversal exists at any layer, so that branch must not hint at one.

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

# The value both writers put in `stabler_remittance_stage` for a payout leg, and
# they do not write it the same way: the legacy model stamps the literal inline
# (`api/remittance.py:519`), while the new one stamps `_build_entry`'s `stage`
# argument (`api/remittance_accounting.py:220`), which `post_payout` (`:287`)
# feeds from the module constant `PAYOUT` (`:57`). A test walks both paths — get
# this string wrong and the payout branch silently degrades to the milder message.
PAYOUT_STAGE = "Payout"


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
	# One literal per branch, never implicit concatenation: `translations/harvest.py`
	# matches `_(` followed by a single quoted string, so a split literal harvests
	# only its first fragment and the catalogs end up keyed on a string nobody throws.
	if stage == PAYOUT_STAGE:
		message = _(
			"Journal Entry {0} is the payout of remittance {1} and cannot be cancelled here — the cash has already left the drawer, and a paid-out transfer cannot be refunded either. Escalate it: only an administrator can reverse remittance {1}, on the server."
		).format(doc.name, remittance_id)
	elif _is_refundable_from_a_screen(remittance_id):
		message = _(
			"Journal Entry {0} is the {2} entry of remittance {1} and cannot be cancelled here — the ledger would move and the transfer's status would not. Open a refund on remittance {1} instead: a manager approves it, and the ledger and the status move together."
		).format(doc.name, remittance_id, stage or _("Unknown"))
	else:
		message = _(
			"Journal Entry {0} is the {2} entry of remittance {1} and cannot be cancelled here — the ledger would move and the transfer's status would not. No screen can reverse this remittance, so escalate it: only an administrator can reverse remittance {1}, on the server."
		).format(doc.name, remittance_id, stage or _("Unknown"))
	frappe.throw(message, frappe.ValidationError)


def _is_refundable_from_a_screen(remittance_id: str) -> bool:
	"""True only when `RemittanceRefund.vue` could actually reverse this remittance.

	The two fields are `_assert_refundable`'s own preconditions
	(`remittance_commands.py:941-951`), read off the same row — get them out of
	step and the message promises a screen that throws. A refusal that names a
	button which refuses the operator is the first draft's bug again.

	Three cases return False and all three want the escalation branch: a
	paid-out transfer, an already-refunded one, and a legacy JE-only remittance,
	which has no master row for any screen to work from.

	The table probe is not defensive padding. This runs inside `before_cancel`,
	so an exception here does not fail the refusal politely — it replaces every
	remittance voucher cancel on that site with a traceback. `frappe.db` raises
	`TableMissingError` rather than returning falsy when a doctype's table is
	absent (`.claude/rules/20-backend-migrations.md`), which is the state of any
	site carrying legacy remittance JEs from before this doctype shipped. Same
	reasoning, same shape as `api/crm.py:clear_deal_activities`.
	"""
	if not frappe.db.table_exists("Remittance Transfer"):
		return False
	row = frappe.db.get_value(
		"Remittance Transfer",
		remittance_id,
		["operational_status", "accounting_status"],
		as_dict=True,
	)
	return bool(row) and row.operational_status == "Registered" and row.accounting_status == "Posted"


__all__ = ["BYPASS_FLAG", "PAYOUT_STAGE", "assert_not_a_remittance_stage"]
