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
4. A new row carries its pickup-code digest. `pickup_code_hash` is permlevel 1, and
   Frappe silently RESETS a permlevel field the saving user cannot write
   (`Document.validate_higher_perm_levels`, which runs immediately before this
   method at insert). Without this check a missing permlevel-1 DocPerm row would
   store NULL instead of the digest, `register_remittance` would return the
   plaintext to the cashier as if all were well, and the failure would surface days
   later at the counter as "Transfer {0} has no usable pickup code on file" — with
   the cash already taken and no way to pay it out. Loud here, at insert, or silent
   until it is somebody's money.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class RemittanceTransfer(Document):
	def validate(self) -> None:
		self._assert_triple_closes()
		self._assert_inclusive_leaves_a_principal()
		self._assert_registered_is_posted()
		self._assert_new_rows_carry_the_code_digest()

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

	def _assert_new_rows_carry_the_code_digest(self) -> None:
		"""Only on insert: catch a `pickup_code_hash` that Frappe silently discarded.

		The failure this exists for is specific. `pickup_code_hash` is permlevel 1, so
		on a site that never got the permlevel-1 write grant
		`Document.validate_higher_perm_levels` RESETS it on the way in — no error, no
		warning — and the register command stores a transfer that can never be paid
		out. Discovered days later, at the counter.

		It is NOT "every new row must carry a digest". A `Remittance Transfer` is not
		created only by `_new_transfer`; a Draft row built directly carries no code
		and needs none, because a Draft cannot be paid out. Reading an empty field as
		proof of a missing grant was wrong in exactly that case, and the message it
		threw named a cause that was not there.

		So the guard mirrors `validate_higher_perm_levels`'s own exits: where Frappe
		cannot have reset anything, an empty digest is the caller's choice and this
		says nothing. Restricted to new rows because every later write goes through
		`db_set`, which does not run validation, and because rows that predate the
		field must stay saveable.
		"""
		# `getattr` and not attribute access: a permlevel reset removes the value,
		# and a row built without the field never had the attribute at all. Both
		# are the same fact here and only one of them has an attribute to read.
		if not self.is_new() or getattr(self, "pickup_code_hash", None):
			return
		# The paths on which frappe returns before it can reset a single field: three
		# in `validate_higher_perm_levels` (frappe/model/document.py) and a fourth one
		# level down, below. Kept in frappe's order and with frappe's names so the
		# mirror stays checkable against it.
		if self.flags.ignore_permissions or frappe.flags.in_install:
			return
		if frappe.session.user == "Administrator":
			return
		# The fourth exit, one level down in `reset_values_if_no_permlevel_access`
		# (frappe/model/base_document.py:1481): a caller may name fields the reset must
		# leave alone. Named here too, or this throws about a field nothing touched.
		if "pickup_code_hash" in (self.flags.get("ignore_permlevel_for_fields") or []):
			return
		# The grant itself, asked the way Frappe asks it. Present means nothing was
		# discarded and the caller simply supplied no code.
		#
		# `cint` and not `1 in ...`: `get_permlevel_access` returns `perm.permlevel`
		# straight off the DocPerm rows, and frappe's own permission check wraps that
		# same value in `cint` (frappe/permissions.py:315). If it ever arrives as
		# "1", a bare membership test reads False and this throws at the one user who
		# DOES hold the grant — refusing the registration it was written to protect.
		if any(cint(level) == 1 for level in (self.get_permlevel_access("write") or [])):
			return
		frappe.throw(
			_(
				"This transfer was saved without its pickup-code digest. The field is "
				"permlevel 1 and your roles have no write grant at that level, so it was "
				"discarded. Run the remittance role patch on this site before registering."
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
