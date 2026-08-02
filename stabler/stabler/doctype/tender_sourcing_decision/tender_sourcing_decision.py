"""The auditable award: which quotation we picked, and why.

"Cheapest" and "selected" are two different facts. The comparison already knew
the first; nothing recorded the second, so an award existed only as a highlighted
row on a screen that recomputes itself every time it loads. This document is the
missing half — the selection, its reason, the approver, the timestamp, and a
snapshot of the numbers as they stood at the moment of the decision.

Three rules live here rather than in the endpoint, because a document that can
only be trusted when it is written through one particular function is not
trustworthy:

  * The approval stamp is the server's to write. A payload that carries its own
    `approved_by` is asserting a fact about a person; accepting it would let the
    record name an approver who never saw it.
  * Status moves one way. An approved award that can quietly return to draft is
    not an audit record, it is a form.
  * An award made on an incomplete quote set requires a written exception. The
    procurement rule (five quotations from two countries) has a legitimate escape
    hatch; a silent one is how the rule stops meaning anything.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

#: The procurement policy the sourcing screens count against. Same numbers as
#: `purchasing.tender_quotations`, named here so the exception rule and the badge
#: can never drift apart.
MIN_QUOTATIONS = 5
MIN_COUNTRIES = 2


class TenderSourcingDecision(Document):
	def validate(self) -> None:
		previous = self._committed_state()
		self._reject_client_written_approval(previous)
		self._enforce_one_way_status(previous)
		self._require_exception_when_the_quote_set_is_short()

	# ── helpers ──────────────────────────────────────────────────────────────
	def _committed_state(self):
		"""The committed state, or None for a new document.

		NOT named `_previous`: a helper whose name can collide with a field name
		gets shadowed by the document's own data, and the method silently becomes
		whatever was stored under that key."""
		getter = getattr(self, "get_doc_before_save", None)
		return getter() if callable(getter) else None

	def _approving(self) -> bool:
		"""Set only by `approve_sourcing_decision`. Named for the trusted source
		it comes from, the way `set_tender_go_no_go_from_trusted_source` is."""
		return bool(getattr(self.flags, "stabler_approving", False))

	# ── rules ────────────────────────────────────────────────────────────────
	def _reject_client_written_approval(self, previous) -> None:
		if self._approving():
			return
		was_by = (previous.approved_by if previous else "") or ""
		was_at = str(previous.approved_at if previous else "") or ""
		if ((self.approved_by or "") != was_by) or (str(self.approved_at or "") != was_at):
			frappe.throw(
				_("The approval stamp is written by the server, not by the caller."),
				frappe.PermissionError,
			)

	def _enforce_one_way_status(self, previous) -> None:
		status = self.status or "Draft"
		if previous is None:
			# A decision cannot be born approved: approval is an act by a second
			# person, and an insert has no first state for them to have reviewed.
			if status != "Draft":
				frappe.throw(_("A new sourcing decision starts as a draft."))
			return
		if (previous.status or "Draft") == "Approved":
			frappe.throw(_("An approved sourcing decision cannot be changed. Record a new one."))
		if status == "Approved" and not self._approving():
			frappe.throw(_("Approve the decision through its approval action."), frappe.PermissionError)

	def _require_exception_when_the_quote_set_is_short(self) -> None:
		short = (
			int(self.quotation_count or 0) < MIN_QUOTATIONS or int(self.country_count or 0) < MIN_COUNTRIES
		)
		if not short:
			return
		if not self.policy_exception:
			frappe.throw(
				_(
					"This award sits below the {0}-quotation / {1}-country rule. Record a policy exception to proceed."
				).format(MIN_QUOTATIONS, MIN_COUNTRIES)
			)
		if not (self.exception_reason or "").strip():
			frappe.throw(_("A policy exception needs a written reason."))
