"""The action table: who is offered what, in which state — and never the pickup code.

Three failures this file exists to catch, and each one is tested in BOTH
directions, because a one-directional assertion passes on code where the guard is
missing entirely:

1. **A Cashier offered a manager's action.** "A Cashier is never offered Approve
   refund, Reject or Unlock" is the acceptance sentence of stabler-qzr9.10. It is
   asserted over the FULL cross-product of the four state axes plus the lock flag
   (1,200 states), not over one hand-picked row, because the interesting failure
   is a state nobody thought to write down. Its mirror — a Finance Manager IS
   offered them where the state permits — is asserted too: a table that offers
   nothing to anybody also passes the first half.

2. **An action offered in a state that forbids it.** Each predicate mirrors the
   refusal its endpoint already raises, so the two can drift. Where they can, the
   test reads both.

3. **A read path handing out the pickup code.** Asserted three ways: the guard
   itself raises, the field-list constants contain none of the three names the
   secret goes by, and every read path's source calls the guard. The first alone
   would pass on a guard nobody calls; the third alone would pass on a guard that
   returns True unconditionally.

`Registered` + not-`Posted` gets its own class. The obligation was never posted,
so a payout there would debit a ledger entry that does not exist — the module
refuses it in three places already and this is the fourth, stated as "no action
at all" rather than "not this action".

Bench-free: the action table imports nothing, so it needs no sandbox and no
site. What it cannot prove — that a REAL Frappe user holding a REAL
`Remittance Cashier` role gets this list back over HTTP — is
`test_remittance_allowed_actions_bench.py`.
"""

from __future__ import annotations

import ast
import itertools
import os
import unittest

from stabler.api import _remittance_actions as actions

_API = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api")
_COMMANDS_SRC = os.path.join(_API, "remittance_commands.py")
_REMITTANCE_SRC = os.path.join(_API, "remittance.py")
_APPROVALS_SRC = os.path.join(_API, "approvals.py")

# The four axes, verbatim from remittance_transfer.json. Duplicated here on
# purpose: this list is the contract the table is written against, and a Select
# option added to the doctype without a decision here should surface as a failing
# test rather than as an action silently offered or silently withheld.
OPERATIONAL = ("Draft", "Registered", "Paid Out", "Refunded", "Expired", "Exception")
ACCOUNTING = ("Unposted", "Posted", "Reversed", "Posting Error")
VERIFICATION = ("Not Issued", "Active", "Locked", "Consumed", "Expired")
REFUND = ("None", "Requested", "Approved", "Rejected", "Completed")

MANAGER_ONLY = (actions.APPROVE_REFUND, actions.REJECT_REFUND, actions.UNLOCK_PICKUP_CODE)


def _state(**overrides) -> dict:
	"""A payable transfer, which every other state is a departure from."""
	return {
		"name": "REM-2026-00001",
		"operational_status": "Registered",
		"accounting_status": "Posted",
		"verification_status": "Active",
		"refund_status": "None",
		**overrides,
	}


def _every_state():
	for operational, accounting, verification, refund in itertools.product(
		OPERATIONAL, ACCOUNTING, VERIFICATION, REFUND
	):
		yield _state(
			operational_status=operational,
			accounting_status=accounting,
			verification_status=verification,
			refund_status=refund,
		)


def _source(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def _literal(path: str, name: str):
	"""A module-level constant, read out of the source without importing frappe."""
	tree = ast.parse(_source(path))
	for node in ast.walk(tree):
		targets = getattr(node, "targets", None) or ([node.target] if hasattr(node, "target") else [])
		for target in targets:
			if isinstance(target, ast.Name) and target.id == name:
				return ast.literal_eval(node.value)
	raise AssertionError(f"{name} not found in {os.path.basename(path)}")


def _func_body(src: str, name: str) -> str:
	start = src.index(f"def {name}(")
	rest = src[start:]
	ends = [pos for pos in (rest.find("\ndef ", 1), rest.find("\n__all__", 1)) if pos != -1]
	return rest[: min(ends)] if ends else rest


class RoleMatrixTest(unittest.TestCase):
	"""Both directions, per role, per action."""

	def test_a_cashier_is_never_offered_a_managers_action(self):
		"""The acceptance sentence of the parent bead, over every reachable state."""
		for state in _every_state():
			offered = actions.allowed_actions(state, [actions.CASHIER])
			for action in MANAGER_ONLY:
				self.assertNotIn(action, offered, f"{action} offered to a Cashier in {state}")

	def test_a_finance_manager_is_offered_each_of_them_where_the_state_permits(self):
		"""The mirror. Without it, a table that offers nothing passes the test above."""
		manager = [actions.FINANCE_MANAGER]
		self.assertIn(
			actions.UNLOCK_PICKUP_CODE, actions.allowed_actions(_state(verification_status="Locked"), manager)
		)
		requested = _state(refund_status="Requested")
		self.assertIn(actions.APPROVE_REFUND, actions.allowed_actions(requested, manager))
		self.assertIn(actions.REJECT_REFUND, actions.allowed_actions(requested, manager))

	def test_a_cashier_is_offered_the_counter_actions(self):
		"""The Cashier half of the mirror: withholding everything is not the answer."""
		cashier = [actions.CASHIER]
		self.assertIn(actions.PAYOUT, actions.allowed_actions(_state(), cashier))
		self.assertIn(actions.REQUEST_REFUND, actions.allowed_actions(_state(), cashier))
		self.assertIn(
			actions.COMPLETE_REFUND,
			actions.allowed_actions(_state(refund_status="Approved"), cashier),
		)

	def test_a_viewer_is_offered_nothing_anywhere(self):
		for state in _every_state():
			self.assertEqual([], actions.allowed_actions(state, [actions.VIEWER]))

	def test_an_auditor_is_offered_nothing_anywhere(self):
		"""Read the trail, touch nothing. An Auditor who can act is not an auditor."""
		for state in _every_state():
			self.assertEqual([], actions.allowed_actions(state, [actions.AUDITOR]))

	def test_a_caller_with_no_role_at_all_is_offered_nothing(self):
		for state in _every_state():
			self.assertEqual([], actions.allowed_actions(state, []))

	def test_an_unrelated_role_is_offered_nothing(self):
		"""Holding Sales User is not holding a remittance role."""
		for state in _every_state():
			self.assertEqual([], actions.allowed_actions(state, ["Sales User", "Employee"]))

	def test_every_action_has_a_role_that_holds_it_and_a_role_that_does_not(self):
		"""No action may be universal, and none may be unreachable."""
		for action in actions.ACTIONS:
			self.assertTrue(actions.holds(action, actions.DESK_ROLES), action)
			self.assertFalse(actions.holds(action, [actions.VIEWER, actions.AUDITOR]), action)

	def test_the_manager_set_covers_the_legacy_approver_roles(self):
		"""`unlock_pickup_code` shipped gated on `approvals._APPROVER_ROLES`.

		The tuple is copied into `_remittance_actions` so the table stays
		Frappe-free; this is the copy's leash. An Accounts Manager who could
		unlock before the remittance roles existed must still be able to.
		"""
		approver_roles = _literal(_APPROVALS_SRC, "_APPROVER_ROLES")
		self.assertTrue(approver_roles, "approvals._APPROVER_ROLES is empty")
		for role in approver_roles:
			self.assertIn(role, actions.MANAGER_ROLES)

	def test_the_manager_set_is_a_subset_of_the_desk_set(self):
		"""A manager standing at the counter is still allowed to serve."""
		self.assertTrue(set(actions.MANAGER_ROLES) <= set(actions.DESK_ROLES))
		self.assertIn(actions.CASHIER, actions.DESK_ROLES)
		self.assertNotIn(actions.CASHIER, actions.MANAGER_ROLES)


class StateGateTest(unittest.TestCase):
	"""An action is offered only where the endpoint would actually accept it."""

	def setUp(self):
		# The widest role set there is: whatever is withheld below is withheld by
		# the STATE, never by the role. Testing state gates with a narrow role
		# would pass on a table whose state predicates all return False.
		self.roles = list(actions.DESK_ROLES)

	def offered(self, **overrides):
		return actions.allowed_actions(_state(**overrides), self.roles)

	def test_payout_is_offered_on_a_registered_posted_unlocked_transfer(self):
		self.assertIn(actions.PAYOUT, self.offered())

	def test_a_locked_code_withdraws_the_payout(self):
		self.assertNotIn(actions.PAYOUT, self.offered(verification_status="Locked"))

	def test_only_the_word_Locked_withdraws_the_payout(self):
		"""The axis is a Select, so the comparison is a string one — not truthiness.

		This is the whole reason the `code_locked` Check could go: it needed
		`_truthy` to read 1, "1", True and None as one another, because a Check
		arrives as an int off a Document and as a string off a SQL row. A Select
		arrives as its own word either way, and every word that is not "Locked"
		means the code is usable — including the blank one, which v93 backfilled
		and `reqd` now prevents.
		"""
		for unlocked in ("Not Issued", "Active", "Consumed", "Expired", "", None):
			self.assertIn(actions.PAYOUT, self.offered(verification_status=unlocked), repr(unlocked))
		self.assertNotIn(actions.PAYOUT, self.offered(verification_status="Locked"))

	def test_an_approved_or_completed_refund_withdraws_the_payout(self):
		"""Mirrors `_assert_payable`: the cash is committed back to the sender."""
		self.assertNotIn(actions.PAYOUT, self.offered(refund_status="Approved"))
		self.assertNotIn(actions.PAYOUT, self.offered(refund_status="Completed"))

	def test_a_requested_refund_does_not_withdraw_the_payout(self):
		"""Also `_assert_payable`: a request is not yet a commitment, and letting
		one freeze the receiver's cash makes the request a denial of service on
		the person standing at the counter."""
		self.assertIn(actions.PAYOUT, self.offered(refund_status="Requested"))

	def test_payout_is_not_offered_once_the_transfer_has_left_registered(self):
		for operational in ("Draft", "Paid Out", "Refunded", "Expired", "Exception"):
			self.assertNotIn(actions.PAYOUT, self.offered(operational_status=operational), operational)

	def test_unlock_is_offered_only_on_a_locked_registered_transfer(self):
		self.assertIn(actions.UNLOCK_PICKUP_CODE, self.offered(verification_status="Locked"))
		self.assertNotIn(actions.UNLOCK_PICKUP_CODE, self.offered(verification_status="Active"))
		self.assertNotIn(
			actions.UNLOCK_PICKUP_CODE,
			self.offered(operational_status="Paid Out", verification_status="Locked"),
		)

	def test_a_refund_can_only_be_requested_once(self):
		self.assertIn(actions.REQUEST_REFUND, self.offered(refund_status="None"))
		for refund in ("Requested", "Approved", "Rejected", "Completed"):
			self.assertNotIn(actions.REQUEST_REFUND, self.offered(refund_status=refund), refund)

	def test_a_refund_cannot_be_requested_on_a_transfer_already_paid_out(self):
		"""The cash is gone; what the sender wants back is at the other counter."""
		self.assertNotIn(actions.REQUEST_REFUND, self.offered(operational_status="Paid Out"))

	def test_approve_and_reject_need_an_open_request(self):
		for action in (actions.APPROVE_REFUND, actions.REJECT_REFUND):
			self.assertIn(action, self.offered(refund_status="Requested"))
			for refund in ("None", "Approved", "Rejected", "Completed"):
				self.assertNotIn(action, self.offered(refund_status=refund), f"{action}/{refund}")

	def test_only_an_approved_refund_can_be_completed(self):
		self.assertIn(actions.COMPLETE_REFUND, self.offered(refund_status="Approved"))
		for refund in ("None", "Requested", "Rejected", "Completed"):
			self.assertNotIn(actions.COMPLETE_REFUND, self.offered(refund_status=refund), refund)

	def test_approving_and_completing_are_not_the_same_gate(self):
		"""Approving must not move cash, so the two must never be open together —
		otherwise one screen can do both and the two-step refund is one step."""
		for state in _every_state():
			offered = actions.allowed_actions(state, self.roles)
			self.assertFalse(
				actions.APPROVE_REFUND in offered and actions.COMPLETE_REFUND in offered,
				f"approve and complete offered together in {state}",
			)

	def test_an_empty_refund_status_reads_as_None(self):
		"""A row written before the Select had a default carries "" — that is the
		same state as "None", and a refund must still be requestable on it."""
		for empty in ("", None):
			self.assertIn(actions.REQUEST_REFUND, self.offered(refund_status=empty), repr(empty))

	def test_the_offered_list_is_ordered_and_stable(self):
		"""A response a client diffs must not reshuffle between requests."""
		state = _state(refund_status="Requested", verification_status="Locked")
		first = actions.allowed_actions(state, self.roles)
		self.assertEqual(first, actions.allowed_actions(state, list(reversed(self.roles))))
		self.assertEqual(first, [a for a in actions.ACTIONS if a in first])


class UnpostedObligationTest(unittest.TestCase):
	"""Registered + not-Posted is the combination that must not be actionable."""

	def test_no_role_is_offered_anything_on_a_registered_unposted_transfer(self):
		for accounting in ("Unposted", "Reversed", "Posting Error"):
			for verification, refund in itertools.product(VERIFICATION, REFUND):
				state = _state(
					accounting_status=accounting, verification_status=verification, refund_status=refund
				)
				self.assertEqual(
					[],
					actions.allowed_actions(state, list(actions.DESK_ROLES)),
					f"actionable at Registered/{accounting}",
				)

	def test_the_same_transfer_becomes_actionable_once_it_is_posted(self):
		"""The mirror: the rule above must be about Posted, not about everything."""
		self.assertIn(actions.PAYOUT, actions.allowed_actions(_state(), list(actions.DESK_ROLES)))

	def test_the_queue_selects_the_columns_the_table_needs(self):
		"""`payout_queue` cannot answer with columns it did not select — a missing
		`refund_status` reads as None and would offer Pay out on a refunded row."""
		queue_fields = _literal(_COMMANDS_SRC, "_QUEUE_FIELDS")
		for field in actions.STATE_FIELDS:
			self.assertIn(field, queue_fields)


class PickupCodeNeverOnAReadTest(unittest.TestCase):
	"""The absence is enforced, not observed."""

	def test_the_field_guard_refuses_every_name_the_secret_goes_by(self):
		for field in actions.FORBIDDEN_READ_FIELDS:
			with self.assertRaises(actions.PickupCodeLeak):
				actions.assert_safe_fields(("name", field, "company"))

	def test_the_field_guard_passes_an_honest_projection(self):
		fields = ("name", "company", *actions.STATE_FIELDS)
		self.assertEqual(fields, actions.assert_safe_fields(fields))

	def test_the_response_guard_refuses_a_leak_at_the_top_level(self):
		for field in actions.FORBIDDEN_READ_FIELDS:
			with self.assertRaises(actions.PickupCodeLeak):
				actions.assert_no_pickup_code({"name": "REM-1", field: "s1$abc$def"})

	def test_the_response_guard_refuses_a_leak_nested_in_a_list(self):
		"""A leak arrives inside `stages` at least as easily as at the top level."""
		with self.assertRaises(actions.PickupCodeLeak):
			actions.assert_no_pickup_code(
				{"name": "REM-1", "stages": [{"name": "JE-1", "stabler_pickup_code": "s1$a$b"}]}
			)

	def test_the_response_guard_refuses_a_leak_nested_in_a_dict(self):
		with self.assertRaises(actions.PickupCodeLeak):
			actions.assert_no_pickup_code({"transfer": {"pickup_code_hash": "s1$a$b"}})

	def test_the_response_guard_refuses_a_null_valued_leak(self):
		"""The KEY is the leak: a client that sees the field knows to ask for it,
		and a null today is a value after the next refactor."""
		with self.assertRaises(actions.PickupCodeLeak):
			actions.assert_no_pickup_code({"name": "REM-1", "pickup_code": None})

	def test_the_response_guard_passes_a_clean_response_through(self):
		payload = [{"name": "REM-1", "receiver_name": "ABCD2345", "allowed_actions": ["payout"]}]
		self.assertIs(payload, actions.assert_no_pickup_code(payload))

	def test_the_response_guard_does_not_refuse_a_value_that_looks_like_a_code(self):
		"""Refusing values rather than keys would make a receiver named like a
		code un-listable — a denial of service with no security story."""
		actions.assert_no_pickup_code({"receiver_name": "s1$salt$digest"})

	def test_the_queue_field_list_carries_no_secret(self):
		actions.assert_safe_fields(_literal(_COMMANDS_SRC, "_QUEUE_FIELDS"))

	def test_the_queue_search_fields_carry_no_secret(self):
		"""A searchable digest is an oracle, even when it is never displayed."""
		actions.assert_safe_fields(_literal(_COMMANDS_SRC, "_QUEUE_SEARCH_FIELDS"))


# Every read path in the module, and the function that serves it. Adding a read
# endpoint means adding a line here — the list is the contract, and a read path
# that is not on it is a read path nobody proved anything about.
READ_PATHS = (
	(_COMMANDS_SRC, "payout_queue"),
	(_REMITTANCE_SRC, "list_remittances"),
	(_REMITTANCE_SRC, "remittance_detail"),
)


class ReadPathSourceTest(unittest.TestCase):
	"""What a reader can see, asserted where they can see it."""

	@classmethod
	def setUpClass(cls):
		cls.bodies = {name: _func_body(_source(path), name) for path, name in READ_PATHS}

	def test_every_read_path_runs_the_pickup_code_guard(self):
		for name, body in self.bodies.items():
			self.assertIn("assert_no_pickup_code", body, name)

	def test_every_read_path_returns_allowed_actions(self):
		for name, body in self.bodies.items():
			self.assertTrue(
				"annotate(" in body or "_annotate_actions(" in body,
				f"{name} returns no allowed_actions",
			)

	def test_no_read_path_selects_a_forbidden_field(self):
		for name, body in self.bodies.items():
			for field in actions.FORBIDDEN_READ_FIELDS:
				self.assertNotIn(f'"{field}"', body, f"{name} selects {field}")

	def test_the_role_read_happens_once_per_read_path(self):
		"""`allowed_actions` is computed once with the caller's role. A
		`get_roles()` inside the row loop is N queries to answer one question,
		and a role set that can change mid-response."""
		for name, body in self.bodies.items():
			self.assertLessEqual(body.count("frappe.get_roles()"), 1, name)

	def test_the_unlock_gate_and_the_offer_come_from_the_same_table(self):
		"""Otherwise the button and the endpoint can disagree, which is the exact
		failure the whole slice exists to close."""
		unlock = _func_body(_source(_COMMANDS_SRC), "unlock_pickup_code")
		self.assertIn("actions.holds(actions.UNLOCK_PICKUP_CODE", unlock)


class AnnotateTest(unittest.TestCase):
	def test_every_row_gets_a_list_even_when_it_is_empty(self):
		"""A missing key makes a client distinguish "no actions" from "this
		endpoint forgot" — and clients get that wrong in the permissive direction."""
		rows = [_state(), _state(operational_status="Paid Out")]
		actions.annotate(rows, [actions.VIEWER])
		for row in rows:
			self.assertEqual([], row["allowed_actions"])

	def test_the_same_role_list_serves_every_row(self):
		rows = [_state(), _state(verification_status="Locked")]
		actions.annotate(rows, [actions.FINANCE_MANAGER])
		self.assertIn(actions.PAYOUT, rows[0]["allowed_actions"])
		self.assertIn(actions.UNLOCK_PICKUP_CODE, rows[1]["allowed_actions"])
		self.assertNotIn(actions.PAYOUT, rows[1]["allowed_actions"])


class StateShapeTest(unittest.TestCase):
	"""The same row arrives as a dict, a `frappe._dict` and a Document."""

	def test_a_document_like_object_is_read_by_attribute(self):
		class _Doc:
			operational_status = "Registered"
			accounting_status = "Posted"
			verification_status = "Active"
			refund_status = "None"

		self.assertIn(actions.PAYOUT, actions.allowed_actions(_Doc(), [actions.CASHIER]))

	def test_an_object_with_a_get_method_is_read_through_it(self):
		class _Dict(dict):
			pass

		self.assertIn(actions.PAYOUT, actions.allowed_actions(_Dict(_state()), [actions.CASHIER]))
