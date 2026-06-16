"""Unit tests for the pure segregation-of-duties logic (no Frappe, no I/O)."""
from __future__ import annotations

import unittest

from stabler.api._sod_rules import (
	ACTOR_CONFLICT_RULES,
	capabilities_for,
	conflicting_actor,
	evaluate_user,
	scan_users,
	would_conflict,
)


class EvaluateUserTest(unittest.TestCase):
	def test_vendor_and_pay_flagged(self):
		ev = evaluate_user(["Purchase User", "Accounts User"])
		ids = {v["id"] for v in ev}
		self.assertIn("vendor_and_pay", ids)

	def test_pure_accounts_user_not_flagged_for_vendor_pay(self):
		ev = evaluate_user(["Accounts User"])
		self.assertNotIn("vendor_and_pay", {v["id"] for v in ev})

	def test_superadmin_operator_is_critical(self):
		ev = evaluate_user(["System Manager", "Accounts User"])
		crit = [v for v in ev if v["id"] == "superadmin_and_operator"]
		self.assertTrue(crit)
		self.assertEqual(crit[0]["severity"], "critical")

	def test_lone_system_manager_not_self_flagged(self):
		# System Manager alone (no operator role) must not violate superadmin_and_operator.
		ev = evaluate_user(["System Manager"])
		self.assertNotIn("superadmin_and_operator", {v["id"] for v in ev})

	def test_no_roles_no_violations(self):
		self.assertEqual(evaluate_user([]), [])
		self.assertEqual(evaluate_user(None), [])

	def test_matched_roles_reported(self):
		ev = evaluate_user(["Purchase Manager", "Accounts Manager"])
		v = next(v for v in ev if v["id"] == "vendor_and_pay")
		self.assertIn("Purchase Manager", v["matched_a"])
		self.assertIn("Accounts Manager", v["matched_b"])


class ScanUsersTest(unittest.TestCase):
	def test_summary_counts_and_flagged(self):
		users = [
			{"user": "a@x", "full_name": "A", "roles": ["System Manager", "Accounts User"]},  # critical
			{"user": "b@x", "full_name": "B", "roles": ["Purchase User", "Accounts User"]},  # high
			{"user": "c@x", "full_name": "C", "roles": ["Sales User"]},  # clean
		]
		res = scan_users(users)
		self.assertEqual(res["summary"]["users_flagged"], 2)
		self.assertGreaterEqual(res["summary"]["critical"], 1)
		# Critical sorts first.
		self.assertEqual(res["violations"][0]["severity"], "critical")

	def test_clean_org_has_no_violations(self):
		users = [{"user": "a@x", "full_name": "A", "roles": ["Sales User"]}]
		res = scan_users(users)
		self.assertEqual(res["summary"]["total"], 0)
		self.assertEqual(res["summary"]["users_flagged"], 0)


class WouldConflictTest(unittest.TestCase):
	def test_adding_payments_to_vendor_manager_warns(self):
		new = would_conflict(["Purchase User"], "Accounts User")
		self.assertIn("vendor_and_pay", {c["id"] for c in new})

	def test_no_warning_when_already_conflicting(self):
		# Already has the conflict; adding an unrelated role introduces nothing new.
		new = would_conflict(["Purchase User", "Accounts User"], "Sales User")
		self.assertNotIn("vendor_and_pay", {c["id"] for c in new})

	def test_safe_addition_no_warning(self):
		self.assertEqual(would_conflict(["Sales User"], "Sales Manager"), [])


class CapabilitiesTest(unittest.TestCase):
	def test_capability_flags(self):
		caps = capabilities_for(["Accounts User"])
		self.assertTrue(caps["make_payments"])
		self.assertFalse(caps["manage_suppliers"])

	def test_admin_has_user_admin(self):
		caps = capabilities_for(["System Manager"])
		self.assertTrue(caps["administer_users"])


class ConflictingActorTest(unittest.TestCase):
	"""Tests for the per-document enforcement decision engine."""

	# ------------------------------------------------------------------
	# Basic blocking
	# ------------------------------------------------------------------

	def test_creator_blocked_from_approving(self):
		"""alice created the doc → she cannot approve it."""
		hits = conflicting_actor(
			"approve",
			"Payment Entry",
			"alice@x",
			{"create": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("creator_cannot_approve", rule_ids)

	def test_submitter_blocked_from_approving(self):
		hits = conflicting_actor(
			"approve",
			"Purchase Order",
			"alice@x",
			{"submit": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("submitter_cannot_approve", rule_ids)

	def test_po_creator_blocked_from_receiving(self):
		"""alice created the PO → she cannot receive goods on the linked Receipt."""
		hits = conflicting_actor(
			"receive",
			"Purchase Receipt",
			"alice@x",
			{"create": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("po_creator_cannot_receive", rule_ids)

	def test_requester_blocked_from_approving(self):
		hits = conflicting_actor(
			"approve",
			"Purchase Order",
			"alice@x",
			{"request": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("requester_cannot_approve", rule_ids)

	def test_requester_blocked_from_paying(self):
		hits = conflicting_actor(
			"pay",
			"Payment Entry",
			"alice@x",
			{"request": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("requester_cannot_pay", rule_ids)

	def test_creator_blocked_from_paying_payment_entry(self):
		hits = conflicting_actor(
			"pay",
			"Payment Entry",
			"alice@x",
			{"create": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("creator_cannot_pay", rule_ids)

	def test_creator_blocked_from_paying_journal_entry(self):
		hits = conflicting_actor(
			"pay",
			"Journal Entry",
			"alice@x",
			{"create": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("creator_cannot_pay", rule_ids)

	def test_supplier_creator_blocked_from_paying(self):
		hits = conflicting_actor(
			"pay",
			"Payment Entry",
			"alice@x",
			{"create_supplier": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("supplier_creator_cannot_pay", rule_ids)

	def test_creator_blocked_from_amending(self):
		hits = conflicting_actor(
			"amend",
			"Sales Invoice",
			"alice@x",
			{"create": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("creator_cannot_amend", rule_ids)

	# ------------------------------------------------------------------
	# Different actor — must NOT be blocked
	# ------------------------------------------------------------------

	def test_different_approver_not_blocked(self):
		"""bob approves what alice created — no conflict."""
		hits = conflicting_actor(
			"approve",
			"Payment Entry",
			"bob@x",
			{"create": ["alice@x"]},
		)
		self.assertEqual(hits, [])

	def test_different_receiver_not_blocked(self):
		hits = conflicting_actor(
			"receive",
			"Purchase Receipt",
			"bob@x",
			{"create": ["alice@x"]},
		)
		self.assertEqual(hits, [])

	def test_different_payer_not_blocked(self):
		hits = conflicting_actor(
			"pay",
			"Payment Entry",
			"bob@x",
			{"create": ["alice@x"]},
		)
		self.assertEqual(hits, [])

	# ------------------------------------------------------------------
	# Doctype scoping
	# ------------------------------------------------------------------

	def test_po_creator_cannot_receive_only_on_purchase_receipt(self):
		"""po_creator_cannot_receive must NOT fire for doctypes outside its set."""
		hits = conflicting_actor(
			"receive",
			"Stock Entry",  # not in rule's doctypes
			"alice@x",
			{"create": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertNotIn("po_creator_cannot_receive", rule_ids)

	def test_supplier_pay_rule_scoped_to_payment_doctypes(self):
		"""supplier_creator_cannot_pay must not fire on a doctype outside its set."""
		hits = conflicting_actor(
			"pay",
			"Stock Entry",
			"alice@x",
			{"create_supplier": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertNotIn("supplier_creator_cannot_pay", rule_ids)

	def test_creator_cannot_pay_not_on_purchase_order(self):
		"""creator_cannot_pay is scoped to Payment Entry and Journal Entry."""
		hits = conflicting_actor(
			"pay",
			"Purchase Order",  # not in rule's doctypes
			"alice@x",
			{"create": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertNotIn("creator_cannot_pay", rule_ids)

	# ------------------------------------------------------------------
	# Universal rules (empty doctypes frozenset = applies everywhere)
	# ------------------------------------------------------------------

	def test_creator_cannot_approve_is_universal(self):
		"""creator_cannot_approve fires on any doctype."""
		for dt in ("Sales Invoice", "Quotation", "Expense Claim", "Custom DocType"):
			with self.subTest(doctype=dt):
				hits = conflicting_actor("approve", dt, "alice@x", {"create": ["alice@x"]})
				rule_ids = {h["rule_id"] for h in hits}
				self.assertIn("creator_cannot_approve", rule_ids)

	# ------------------------------------------------------------------
	# Edge / safety cases
	# ------------------------------------------------------------------

	def test_empty_prior_actors_no_conflict(self):
		hits = conflicting_actor("approve", "Payment Entry", "alice@x", {})
		self.assertEqual(hits, [])

	def test_none_prior_actors_no_conflict(self):
		hits = conflicting_actor("approve", "Payment Entry", "alice@x", {"create": None})
		self.assertEqual(hits, [])

	def test_empty_actor_no_conflict(self):
		hits = conflicting_actor("approve", "Payment Entry", "", {"create": ["alice@x"]})
		self.assertEqual(hits, [])

	def test_none_actor_no_conflict(self):
		hits = conflicting_actor("approve", "Payment Entry", None, {"create": ["alice@x"]})
		self.assertEqual(hits, [])

	def test_empty_action_no_conflict(self):
		hits = conflicting_actor("", "Payment Entry", "alice@x", {"create": ["alice@x"]})
		self.assertEqual(hits, [])

	def test_unrelated_action_no_conflict(self):
		"""An action not matched by any rule's action_b returns nothing."""
		hits = conflicting_actor(
			"view",
			"Payment Entry",
			"alice@x",
			{"create": ["alice@x"], "submit": ["alice@x"]},
		)
		self.assertEqual(hits, [])

	def test_multiple_prior_actors_only_matching_triggers(self):
		"""Prior list has multiple users; only the current actor triggers."""
		hits = conflicting_actor(
			"approve",
			"Payment Entry",
			"alice@x",
			{"create": ["alice@x", "bob@x"]},
		)
		self.assertTrue(hits)  # alice is in the prior list → blocked

		hits2 = conflicting_actor(
			"approve",
			"Payment Entry",
			"carol@x",
			{"create": ["alice@x", "bob@x"]},
		)
		self.assertEqual(hits2, [])  # carol is not in the prior list → ok

	def test_violation_dict_shape(self):
		"""Each returned violation carries the expected keys."""
		hits = conflicting_actor(
			"approve",
			"Payment Entry",
			"alice@x",
			{"create": ["alice@x"]},
		)
		self.assertTrue(hits)
		v = hits[0]
		for key in ("rule_id", "action_a", "action_b", "conflict_actor", "severity", "message"):
			self.assertIn(key, v, f"Missing key: {key}")
		self.assertEqual(v["conflict_actor"], "alice@x")
		self.assertEqual(v["action_b"], "approve")

	def test_severity_values_are_valid(self):
		"""All rules declare a known severity."""
		valid = {"critical", "high", "medium", "info"}
		for rule in ACTOR_CONFLICT_RULES:
			self.assertIn(rule["severity"], valid, f"Bad severity in rule {rule['id']}")

	def test_custom_rules_override(self):
		"""Caller can pass custom rules; built-in rules are not applied."""
		custom = [
			{
				"id": "test_only_rule",
				"doctypes": frozenset({"Foo"}),
				"action_a": "create",
				"action_b": "delete",
				"severity": "info",
				"message": "Test rule.",
			}
		]
		hits = conflicting_actor("delete", "Foo", "alice@x", {"create": ["alice@x"]}, rules=custom)
		self.assertEqual(len(hits), 1)
		self.assertEqual(hits[0]["rule_id"], "test_only_rule")

		# Built-in rules must NOT fire when custom rules supplied.
		hits2 = conflicting_actor("approve", "Payment Entry", "alice@x", {"create": ["alice@x"]}, rules=custom)
		self.assertEqual(hits2, [])

	def test_multiple_rules_can_fire_simultaneously(self):
		"""creator_cannot_approve and submitter_cannot_approve both fire when actor
		both created and submitted before trying to approve."""
		hits = conflicting_actor(
			"approve",
			"Payment Entry",
			"alice@x",
			{"create": ["alice@x"], "submit": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("creator_cannot_approve", rule_ids)
		self.assertIn("submitter_cannot_approve", rule_ids)

	def test_requester_cannot_approve_not_on_payment_entry(self):
		"""requester_cannot_approve is scoped to Material Request and Purchase Order."""
		hits = conflicting_actor(
			"approve",
			"Payment Entry",
			"alice@x",
			{"request": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		# creator_cannot_approve is universal but requester_cannot_approve is scoped
		self.assertNotIn("requester_cannot_approve", rule_ids)

	def test_requester_cannot_approve_fires_on_material_request(self):
		hits = conflicting_actor(
			"approve",
			"Material Request",
			"alice@x",
			{"request": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("requester_cannot_approve", rule_ids)

	def test_requester_cannot_pay_fires_on_purchase_invoice(self):
		hits = conflicting_actor(
			"pay",
			"Purchase Invoice",
			"alice@x",
			{"request": ["alice@x"]},
		)
		rule_ids = {h["rule_id"] for h in hits}
		self.assertIn("requester_cannot_pay", rule_ids)


if __name__ == "__main__":
	unittest.main()
