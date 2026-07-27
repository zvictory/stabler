"""Unit tests for the pure maker-checker decision logic.

These import only stabler.api._approval_rules (no Frappe), so they run under
plain `python -m unittest` as well as `bench run-tests`. They lock down the
rules the whole control depends on: when approval is required, and that a user
can never approve their own request.
"""

from __future__ import annotations

import unittest

from stabler.api._approval_rules import (
	approval_is_in_sequence,
	docstatus_kind,
	extract_field_changes,
	is_fully_approved,
	is_self_approval,
	next_required_level,
	resolve_required_tiers,
	summarize_version,
	threshold_requires,
	would_be_double_approve,
)


class ThresholdRequiresTest(unittest.TestCase):
	def test_disabled_never_requires(self):
		self.assertFalse(threshold_requires(10**9, enabled=False, threshold=0))
		self.assertFalse(threshold_requires(10**9, enabled=False, threshold=5))

	def test_zero_threshold_requires_everything(self):
		# Secure default: 0 / None / negative => every controlled doc.
		self.assertTrue(threshold_requires(0, enabled=True, threshold=0))
		self.assertTrue(threshold_requires(1, enabled=True, threshold=None))
		self.assertTrue(threshold_requires(1, enabled=True, threshold=-5))

	def test_threshold_boundary_is_inclusive(self):
		self.assertTrue(threshold_requires(1000, enabled=True, threshold=1000))
		self.assertTrue(threshold_requires(1001, enabled=True, threshold=1000))
		self.assertFalse(threshold_requires(999.99, enabled=True, threshold=1000))

	def test_string_amounts_are_coerced(self):
		self.assertTrue(threshold_requires("25000000", enabled=True, threshold="1000000"))
		self.assertFalse(threshold_requires("500", enabled=True, threshold="1000"))

	def test_garbage_amount_does_not_crash(self):
		self.assertFalse(threshold_requires("not-a-number", enabled=True, threshold=1000))


class SelfApprovalTest(unittest.TestCase):
	def test_same_user_is_self_approval(self):
		self.assertTrue(is_self_approval("a@x.uz", "a@x.uz"))

	def test_different_users_ok(self):
		self.assertFalse(is_self_approval("maker@x.uz", "checker@x.uz"))

	def test_missing_party_is_not_self_approval(self):
		# A not-yet-reviewed request must not read as a violation.
		self.assertFalse(is_self_approval("maker@x.uz", None))
		self.assertFalse(is_self_approval(None, "checker@x.uz"))
		self.assertFalse(is_self_approval("", ""))


class DocstatusKindTest(unittest.TestCase):
	def test_submit_detected(self):
		self.assertEqual(docstatus_kind([["docstatus", 0, 1]]), "submit")

	def test_cancel_detected(self):
		self.assertEqual(docstatus_kind([["docstatus", 1, 2]]), "cancel")

	def test_no_docstatus_change(self):
		self.assertIsNone(docstatus_kind([["status", "Draft", "Paid"]]))
		self.assertIsNone(docstatus_kind([]))
		self.assertIsNone(docstatus_kind(None))

	def test_non_integer_docstatus_ignored(self):
		self.assertIsNone(docstatus_kind([["docstatus", 0, "weird"]]))


class ExtractFieldChangesTest(unittest.TestCase):
	def test_drops_noise_and_docstatus(self):
		rows = [
			["modified", "t1", "t2"],
			["docstatus", 0, 1],
			["paid_amount", 100, 250],
		]
		out = extract_field_changes(rows)
		self.assertEqual(out, [{"field": "paid_amount", "old": 100, "new": 250}])

	def test_handles_short_rows(self):
		self.assertEqual(extract_field_changes([["only_one"]]), [])


class SummarizeVersionTest(unittest.TestCase):
	def test_submit_is_meaningful_without_field_changes(self):
		s = summarize_version({"changed": [["docstatus", 0, 1]]})
		self.assertEqual(s["kind"], "submit")
		self.assertTrue(s["meaningful"])
		self.assertEqual(s["field_changes"], [])

	def test_cancel_is_meaningful(self):
		s = summarize_version({"changed": [["docstatus", 1, 2]]})
		self.assertEqual(s["kind"], "cancel")
		self.assertTrue(s["meaningful"])

	def test_timestamp_only_edit_is_dropped(self):
		s = summarize_version({"changed": [["modified", "t1", "t2"]]})
		self.assertEqual(s["kind"], "edit")
		self.assertFalse(s["meaningful"])

	def test_field_edit_is_meaningful(self):
		s = summarize_version({"changed": [["remarks", "a", "b"]]})
		self.assertTrue(s["meaningful"])
		self.assertEqual(s["field_changes"], [{"field": "remarks", "old": "a", "new": "b"}])

	def test_child_row_change_counts(self):
		s = summarize_version({"row_changed": [["accounts", 1, "row1", [["debit", 0, 5]]]]})
		self.assertTrue(s["meaningful"])
		self.assertEqual(s["child_changes"], 1)

	def test_empty_version_is_not_meaningful(self):
		self.assertFalse(summarize_version({})["meaningful"])


# ---------------------------------------------------------------------------
# Tiered / multi-level approval pure tests
# ---------------------------------------------------------------------------

# A canonical two-tier config used across multiple tests:
#   level 1: Department Manager  threshold 0      (all docs)
#   level 2: Finance Director    threshold 5_000  (large docs only)
TWO_TIER = [
	{"threshold": 0, "approver_role": "Department Manager", "level": 1},
	{"threshold": 5000, "approver_role": "Finance Director", "level": 2},
]

THREE_TIER = [
	{"threshold": 0, "approver_role": "Team Lead", "level": 1},
	{"threshold": 10000, "approver_role": "Finance Manager", "level": 2},
	{"threshold": 100000, "approver_role": "CFO", "level": 3},
]


class ResolveRequiredTiersTest(unittest.TestCase):
	def test_empty_tiers_returns_empty(self):
		self.assertEqual(resolve_required_tiers(999, []), [])
		self.assertEqual(resolve_required_tiers(999, None), [])

	def test_zero_threshold_always_activates(self):
		tiers = [{"threshold": 0, "approver_role": "Manager", "level": 1}]
		self.assertEqual(len(resolve_required_tiers(0, tiers)), 1)
		self.assertEqual(len(resolve_required_tiers(1, tiers)), 1)

	def test_amount_below_second_tier_only_gets_first(self):
		result = resolve_required_tiers(1000, TWO_TIER)
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["level"], 1)

	def test_amount_at_second_tier_boundary_gets_both(self):
		result = resolve_required_tiers(5000, TWO_TIER)
		self.assertEqual(len(result), 2)
		self.assertEqual([t["level"] for t in result], [1, 2])

	def test_amount_above_second_tier_gets_both(self):
		result = resolve_required_tiers(9999, TWO_TIER)
		self.assertEqual(len(result), 2)

	def test_three_tier_partial_resolve(self):
		# 50_000 triggers levels 1 and 2 but not 3 (threshold 100_000).
		result = resolve_required_tiers(50000, THREE_TIER)
		self.assertEqual([t["level"] for t in result], [1, 2])

	def test_three_tier_full_resolve(self):
		result = resolve_required_tiers(200000, THREE_TIER)
		self.assertEqual([t["level"] for t in result], [1, 2, 3])

	def test_garbage_entries_are_dropped(self):
		bad_tiers = [
			None,
			"not-a-dict",
			{"threshold": 0},  # missing role and level
			{"threshold": 0, "approver_role": "", "level": 1},  # blank role → dropped
			{"threshold": 0, "approver_role": "Manager", "level": 0},  # level 0 → dropped
			{"threshold": 0, "approver_role": "Manager", "level": 1},  # good
		]
		result = resolve_required_tiers(100, bad_tiers)
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["approver_role"], "Manager")

	def test_returned_list_is_sorted_by_level(self):
		shuffled = [
			{"threshold": 0, "approver_role": "C", "level": 3},
			{"threshold": 0, "approver_role": "A", "level": 1},
			{"threshold": 0, "approver_role": "B", "level": 2},
		]
		result = resolve_required_tiers(1, shuffled)
		self.assertEqual([t["level"] for t in result], [1, 2, 3])

	def test_string_amounts_and_thresholds_coerced(self):
		tiers = [{"threshold": "5000", "approver_role": "CFO", "level": 1}]
		self.assertEqual(len(resolve_required_tiers("6000", tiers)), 1)
		self.assertEqual(len(resolve_required_tiers("4999", tiers)), 0)

	def test_mutating_result_does_not_affect_input(self):
		tiers = [{"threshold": 0, "approver_role": "Manager", "level": 1}]
		result = resolve_required_tiers(1, tiers)
		result[0]["level"] = 99
		fresh = resolve_required_tiers(1, tiers)
		self.assertEqual(fresh[0]["level"], 1)


class IsFullyApprovedTest(unittest.TestCase):
	def test_no_required_tiers_is_vacuously_true(self):
		self.assertTrue(is_fully_approved([], []))
		self.assertTrue(is_fully_approved([], None))

	def test_single_tier_not_yet_approved(self):
		req = [{"level": 1, "approver_role": "Manager"}]
		self.assertFalse(is_fully_approved(req, []))

	def test_single_tier_approved(self):
		req = [{"level": 1, "approver_role": "Manager"}]
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertTrue(is_fully_approved(req, approvals))

	def test_two_tiers_only_first_approved(self):
		req = [{"level": 1, "approver_role": "Mgr"}, {"level": 2, "approver_role": "Dir"}]
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertFalse(is_fully_approved(req, approvals))

	def test_two_tiers_both_approved(self):
		req = [{"level": 1, "approver_role": "Mgr"}, {"level": 2, "approver_role": "Dir"}]
		approvals = [
			{"level": 1, "approver": "alice@x.uz"},
			{"level": 2, "approver": "bob@x.uz"},
		]
		self.assertTrue(is_fully_approved(req, approvals))

	def test_extra_approvals_do_not_break(self):
		# Superset of approvals still satisfies.
		req = [{"level": 1, "approver_role": "Mgr"}]
		approvals = [
			{"level": 1, "approver": "alice@x.uz"},
			{"level": 2, "approver": "bob@x.uz"},  # not required, harmless
		]
		self.assertTrue(is_fully_approved(req, approvals))

	def test_malformed_approval_entries_ignored(self):
		req = [{"level": 1, "approver_role": "Mgr"}]
		approvals = [None, "bad", {"approver": "x"}, {"level": 1, "approver": "ok@x.uz"}]
		self.assertTrue(is_fully_approved(req, approvals))


class NextRequiredLevelTest(unittest.TestCase):
	def test_no_tiers_returns_none(self):
		self.assertIsNone(next_required_level([], []))

	def test_nothing_approved_yet(self):
		req = [{"level": 1, "approver_role": "A"}, {"level": 2, "approver_role": "B"}]
		self.assertEqual(next_required_level(req, []), 1)

	def test_first_done_returns_second(self):
		req = [{"level": 1, "approver_role": "A"}, {"level": 2, "approver_role": "B"}]
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertEqual(next_required_level(req, approvals), 2)

	def test_all_done_returns_none(self):
		req = [{"level": 1, "approver_role": "A"}, {"level": 2, "approver_role": "B"}]
		approvals = [
			{"level": 1, "approver": "alice@x.uz"},
			{"level": 2, "approver": "bob@x.uz"},
		]
		self.assertIsNone(next_required_level(req, approvals))


class ApprovalIsInSequenceTest(unittest.TestCase):
	def _tiers(self):
		return [
			{"level": 1, "approver_role": "A"},
			{"level": 2, "approver_role": "B"},
			{"level": 3, "approver_role": "C"},
		]

	def test_level_1_is_always_in_sequence(self):
		self.assertTrue(approval_is_in_sequence(1, self._tiers(), []))

	def test_level_2_blocked_when_level_1_not_done(self):
		self.assertFalse(approval_is_in_sequence(2, self._tiers(), []))

	def test_level_2_ok_when_level_1_done(self):
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertTrue(approval_is_in_sequence(2, self._tiers(), approvals))

	def test_level_3_blocked_when_level_2_not_done(self):
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertFalse(approval_is_in_sequence(3, self._tiers(), approvals))

	def test_level_3_ok_when_all_prior_done(self):
		approvals = [
			{"level": 1, "approver": "alice@x.uz"},
			{"level": 2, "approver": "bob@x.uz"},
		]
		self.assertTrue(approval_is_in_sequence(3, self._tiers(), approvals))

	def test_level_not_in_required_tiers_returns_false(self):
		# Level 99 is not in the required set — reject.
		self.assertFalse(approval_is_in_sequence(99, self._tiers(), []))

	def test_empty_tiers_any_level_returns_false(self):
		self.assertFalse(approval_is_in_sequence(1, [], []))

	def test_single_tier_config_level_1_always_ok(self):
		tiers = [{"level": 1, "approver_role": "Manager"}]
		self.assertTrue(approval_is_in_sequence(1, tiers, []))


class WouldBeDoubleApproveTest(unittest.TestCase):
	def test_no_prior_approvals_not_double(self):
		self.assertFalse(would_be_double_approve(1, "alice@x.uz", []))

	def test_same_user_same_level_is_double(self):
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertTrue(would_be_double_approve(1, "alice@x.uz", approvals))

	def test_different_level_not_double(self):
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertFalse(would_be_double_approve(2, "alice@x.uz", approvals))

	def test_different_user_same_level_not_double(self):
		approvals = [{"level": 1, "approver": "alice@x.uz"}]
		self.assertFalse(would_be_double_approve(1, "bob@x.uz", approvals))

	def test_empty_approver_never_double(self):
		approvals = [{"level": 1, "approver": ""}]
		self.assertFalse(would_be_double_approve(1, "", approvals))

	def test_malformed_entries_ignored(self):
		approvals = [None, "bad", {"level": 1}, {"level": 1, "approver": "alice@x.uz"}]
		self.assertTrue(would_be_double_approve(1, "alice@x.uz", approvals))


class MultiLevelIntegrationTest(unittest.TestCase):
	"""End-to-end simulation of the pure layer for a three-level PI flow."""

	def setUp(self):
		# 150_000 UZS purchase invoice — triggers all three tiers.
		self.tiers = resolve_required_tiers(150000, THREE_TIER)
		self.assertEqual([t["level"] for t in self.tiers], [1, 2, 3])

	def test_flow_level_by_level(self):
		approvals = []

		# Level 1 is next, in sequence, not double.
		self.assertEqual(next_required_level(self.tiers, approvals), 1)
		self.assertTrue(approval_is_in_sequence(1, self.tiers, approvals))
		self.assertFalse(would_be_double_approve(1, "teamlead@x.uz", approvals))
		self.assertFalse(is_fully_approved(self.tiers, approvals))

		approvals.append({"level": 1, "approver": "teamlead@x.uz"})

		# Level 2 is next; level 3 is blocked.
		self.assertEqual(next_required_level(self.tiers, approvals), 2)
		self.assertTrue(approval_is_in_sequence(2, self.tiers, approvals))
		self.assertFalse(approval_is_in_sequence(3, self.tiers, approvals))
		self.assertFalse(is_fully_approved(self.tiers, approvals))

		approvals.append({"level": 2, "approver": "finmgr@x.uz"})

		# Level 3 is next.
		self.assertEqual(next_required_level(self.tiers, approvals), 3)
		self.assertTrue(approval_is_in_sequence(3, self.tiers, approvals))
		self.assertFalse(is_fully_approved(self.tiers, approvals))

		approvals.append({"level": 3, "approver": "cfo@x.uz"})

		# Fully approved.
		self.assertIsNone(next_required_level(self.tiers, approvals))
		self.assertTrue(is_fully_approved(self.tiers, approvals))

	def test_small_amount_single_tier(self):
		# 500 only triggers level 1 (threshold 0), not 2 or 3.
		tiers = resolve_required_tiers(500, THREE_TIER)
		self.assertEqual([t["level"] for t in tiers], [1])
		approvals = [{"level": 1, "approver": "teamlead@x.uz"}]
		self.assertTrue(is_fully_approved(tiers, approvals))

	def test_medium_amount_two_tiers(self):
		# 50_000 triggers levels 1 and 2.
		tiers = resolve_required_tiers(50000, THREE_TIER)
		self.assertEqual([t["level"] for t in tiers], [1, 2])
		approvals = [
			{"level": 1, "approver": "teamlead@x.uz"},
			{"level": 2, "approver": "finmgr@x.uz"},
		]
		self.assertTrue(is_fully_approved(tiers, approvals))
		# Level 3 approval not needed.
		self.assertFalse(approval_is_in_sequence(3, tiers, approvals))

	def test_skip_prevention(self):
		# Attempt to approve level 2 before level 1 → blocked.
		approvals = []
		self.assertFalse(approval_is_in_sequence(2, self.tiers, approvals))
		self.assertFalse(approval_is_in_sequence(3, self.tiers, approvals))

	def test_double_approve_prevented_at_each_level(self):
		approvals = [{"level": 1, "approver": "teamlead@x.uz"}]
		self.assertTrue(would_be_double_approve(1, "teamlead@x.uz", approvals))
		# Different user OK.
		self.assertFalse(would_be_double_approve(1, "other@x.uz", approvals))

	def test_zero_amount_triggers_level_with_zero_threshold(self):
		# A zero-amount PI still needs level 1 (threshold 0 = all docs).
		tiers = resolve_required_tiers(0, THREE_TIER)
		self.assertEqual(tiers[0]["level"], 1)
		# But not level 2 or 3 (thresholds > 0, amount = 0).
		self.assertEqual(len(tiers), 1)


class PurchaseInvoiceTierConfigTest(unittest.TestCase):
	"""Tests that validate tier config scenarios specific to Purchase Invoice."""

	def _pi_tiers(self):
		# Typical PI tier config: every PI needs L1; large ones need L2.
		return [
			{"threshold": 0, "approver_role": "Purchase Manager", "level": 1},
			{"threshold": 50000, "approver_role": "Accounts Manager", "level": 2},
		]

	def test_small_pi_needs_only_purchase_manager(self):
		tiers = resolve_required_tiers(10000, self._pi_tiers())
		self.assertEqual(len(tiers), 1)
		self.assertEqual(tiers[0]["approver_role"], "Purchase Manager")

	def test_large_pi_needs_both_levels(self):
		tiers = resolve_required_tiers(100000, self._pi_tiers())
		self.assertEqual(len(tiers), 2)
		roles = [t["approver_role"] for t in tiers]
		self.assertIn("Purchase Manager", roles)
		self.assertIn("Accounts Manager", roles)

	def test_boundary_amount_exactly_at_l2_threshold(self):
		tiers = resolve_required_tiers(50000, self._pi_tiers())
		self.assertEqual(len(tiers), 2)

	def test_one_below_boundary_only_l1(self):
		tiers = resolve_required_tiers(49999.99, self._pi_tiers())
		self.assertEqual(len(tiers), 1)

	def test_empty_config_falls_through(self):
		# No tiers → no multi-level requirement; single-level threshold_requires handles it.
		self.assertEqual(resolve_required_tiers(999999, None), [])
		self.assertEqual(resolve_required_tiers(999999, []), [])

	def test_fully_approved_after_both_levels(self):
		tiers = resolve_required_tiers(80000, self._pi_tiers())
		approvals = [
			{"level": 1, "approver": "pm@x.uz"},
			{"level": 2, "approver": "am@x.uz"},
		]
		self.assertTrue(is_fully_approved(tiers, approvals))

	def test_not_fully_approved_after_only_l1(self):
		tiers = resolve_required_tiers(80000, self._pi_tiers())
		approvals = [{"level": 1, "approver": "pm@x.uz"}]
		self.assertFalse(is_fully_approved(tiers, approvals))

	def test_sequence_enforced_for_pi(self):
		tiers = resolve_required_tiers(80000, self._pi_tiers())
		# Cannot jump straight to level 2.
		self.assertFalse(approval_is_in_sequence(2, tiers, []))
		# After level 1, level 2 is OK.
		self.assertTrue(approval_is_in_sequence(2, tiers, [{"level": 1, "approver": "pm@x.uz"}]))


if __name__ == "__main__":
	unittest.main()
