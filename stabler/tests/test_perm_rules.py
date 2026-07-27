"""Unit tests for the pure permission-scoping rules (no Frappe)."""
from __future__ import annotations

import unittest

from stabler.api._perm_rules import (
	COST_FIELDS,
	is_company_allowed,
	mask_fields,
	master_allowed,
	needs_company_restriction,
	needs_owner_restriction,
	needs_territory_restriction,
	owner_allowed,
	territory_allowed,
)

# ---------------------------------------------------------------------------
# Existing tests — company scoping (must not regress)
# ---------------------------------------------------------------------------

class NeedsRestrictionTest(unittest.TestCase):
	def test_empty_means_no_restriction(self):
		self.assertFalse(needs_company_restriction([]))
		self.assertFalse(needs_company_restriction(None))

	def test_nonempty_restricts(self):
		self.assertTrue(needs_company_restriction(["A Co"]))


class IsAllowedTest(unittest.TestCase):
	def test_no_restriction_allows_all(self):
		self.assertTrue(is_company_allowed("Anything", []))
		self.assertTrue(is_company_allowed("Anything", None))

	def test_in_list_allowed(self):
		self.assertTrue(is_company_allowed("A Co", ["A Co", "B Co"]))

	def test_not_in_list_denied(self):
		self.assertFalse(is_company_allowed("C Co", ["A Co", "B Co"]))

	def test_record_without_company_not_hidden(self):
		# A record that itself has no company can't be company-scoped.
		self.assertTrue(is_company_allowed("", ["A Co"]))
		self.assertTrue(is_company_allowed(None, ["A Co"]))


# ---------------------------------------------------------------------------
# Gap #46 — owner scoping
# ---------------------------------------------------------------------------

class NeedsOwnerRestrictionTest(unittest.TestCase):
	def test_empty_no_restriction(self):
		self.assertFalse(needs_owner_restriction([]))
		self.assertFalse(needs_owner_restriction(None))

	def test_nonempty_restricts(self):
		self.assertTrue(needs_owner_restriction(["alice@example.com"]))


class OwnerAllowedTest(unittest.TestCase):
	def test_no_restriction_allows_all(self):
		self.assertTrue(owner_allowed("alice@example.com", []))
		self.assertTrue(owner_allowed("alice@example.com", None))

	def test_in_list_allowed(self):
		self.assertTrue(owner_allowed("alice@example.com", ["alice@example.com", "bob@example.com"]))

	def test_not_in_list_denied(self):
		self.assertFalse(owner_allowed("carol@example.com", ["alice@example.com", "bob@example.com"]))

	def test_blank_owner_never_hidden(self):
		# Records with no owner are not scoped.
		self.assertTrue(owner_allowed("", ["alice@example.com"]))
		self.assertTrue(owner_allowed(None, ["alice@example.com"]))

	def test_tuple_allowed_list(self):
		# Allow-list may be any iterable, not just a list.
		self.assertTrue(owner_allowed("alice@example.com", ("alice@example.com",)))
		self.assertFalse(owner_allowed("carol@example.com", ("alice@example.com",)))


# ---------------------------------------------------------------------------
# Gap #46 — territory scoping
# ---------------------------------------------------------------------------

class NeedsTerritoryRestrictionTest(unittest.TestCase):
	def test_empty_no_restriction(self):
		self.assertFalse(needs_territory_restriction([]))
		self.assertFalse(needs_territory_restriction(None))

	def test_nonempty_restricts(self):
		self.assertTrue(needs_territory_restriction(["North"]))


class TerritoryAllowedTest(unittest.TestCase):
	def test_no_restriction_allows_all(self):
		self.assertTrue(territory_allowed("North", []))
		self.assertTrue(territory_allowed("North", None))

	def test_in_list_allowed(self):
		self.assertTrue(territory_allowed("North", ["North", "South"]))

	def test_not_in_list_denied(self):
		self.assertFalse(territory_allowed("East", ["North", "South"]))

	def test_blank_territory_never_hidden(self):
		self.assertTrue(territory_allowed("", ["North"]))
		self.assertTrue(territory_allowed(None, ["North"]))

	def test_set_allowed_list(self):
		self.assertTrue(territory_allowed("North", {"North", "South"}))
		self.assertFalse(territory_allowed("East", {"North", "South"}))


# ---------------------------------------------------------------------------
# Gap #46 — combined master_allowed gate
# ---------------------------------------------------------------------------

class MasterAllowedTest(unittest.TestCase):
	"""master_allowed must pass BOTH active restrictions independently."""

	def test_no_restrictions_always_passes(self):
		self.assertTrue(master_allowed("alice@example.com", "North", None, None))
		self.assertTrue(master_allowed("alice@example.com", "North", [], []))

	def test_owner_restriction_only_allow(self):
		self.assertTrue(
			master_allowed("alice@example.com", "North", ["alice@example.com"], None)
		)

	def test_owner_restriction_only_deny(self):
		self.assertFalse(
			master_allowed("carol@example.com", "North", ["alice@example.com"], None)
		)

	def test_territory_restriction_only_allow(self):
		self.assertTrue(
			master_allowed("alice@example.com", "North", None, ["North", "South"])
		)

	def test_territory_restriction_only_deny(self):
		self.assertFalse(
			master_allowed("alice@example.com", "East", None, ["North", "South"])
		)

	def test_both_restrictions_both_pass(self):
		self.assertTrue(
			master_allowed(
				"alice@example.com", "North",
				["alice@example.com", "bob@example.com"],
				["North", "South"],
			)
		)

	def test_both_restrictions_owner_fails(self):
		self.assertFalse(
			master_allowed(
				"carol@example.com", "North",
				["alice@example.com"],
				["North"],
			)
		)

	def test_both_restrictions_territory_fails(self):
		self.assertFalse(
			master_allowed(
				"alice@example.com", "East",
				["alice@example.com"],
				["North"],
			)
		)

	def test_both_restrictions_both_fail(self):
		self.assertFalse(
			master_allowed(
				"carol@example.com", "East",
				["alice@example.com"],
				["North"],
			)
		)

	def test_blank_owner_passes_owner_restriction(self):
		# Records with no owner are never hidden even under owner restriction.
		self.assertTrue(
			master_allowed(None, "North", ["alice@example.com"], ["North"])
		)

	def test_blank_territory_passes_territory_restriction(self):
		# Records with no territory are never hidden even under territory restriction.
		self.assertTrue(
			master_allowed("alice@example.com", None, ["alice@example.com"], ["North"])
		)

	def test_both_blank_passes_both_restrictions(self):
		self.assertTrue(
			master_allowed(None, None, ["alice@example.com"], ["North"])
		)


# ---------------------------------------------------------------------------
# Gap #45 — cost / margin field masking
# ---------------------------------------------------------------------------

class CostFieldsConstantTest(unittest.TestCase):
	def test_key_fields_present(self):
		for field in ("valuation_rate", "last_purchase_rate", "margin_type", "gross_profit"):
			self.assertIn(field, COST_FIELDS, f"{field!r} missing from COST_FIELDS")

	def test_is_frozenset(self):
		self.assertIsInstance(COST_FIELDS, frozenset)


class MaskFieldsTest(unittest.TestCase):
	"""mask_fields strips cost keys when user lacks visibility, no-ops otherwise."""

	_SAMPLE: dict = {
		"name": "ITEM-001",
		"item_name": "Widget",
		"valuation_rate": 100.0,
		"last_purchase_rate": 95.0,
		"margin_type": "Percentage",
		"margin_rate_or_amount": 20.0,
		"gross_profit": 5.0,
		"description": "A nice widget",
	}
	_NON_COST_KEYS = {"name", "item_name", "description"}

	def _sample(self):
		"""Fresh copy of the sample dict for each test."""
		return dict(self._SAMPLE)

	def test_visible_user_no_change(self):
		rec = self._sample()
		result = mask_fields(rec, role_has_cost_visibility=True)
		self.assertIs(result, rec)
		self.assertEqual(rec["valuation_rate"], 100.0)
		self.assertEqual(rec["margin_type"], "Percentage")

	def test_hidden_user_cost_fields_nulled(self):
		rec = self._sample()
		mask_fields(rec, role_has_cost_visibility=False)
		for field in COST_FIELDS:
			if field in rec:
				self.assertIsNone(rec[field], f"{field!r} should be None after masking")

	def test_hidden_user_non_cost_fields_preserved(self):
		rec = self._sample()
		mask_fields(rec, role_has_cost_visibility=False)
		for key in self._NON_COST_KEYS:
			self.assertEqual(rec[key], self._SAMPLE[key], f"{key!r} should be unchanged")

	def test_list_of_records_all_masked(self):
		recs = [self._sample(), self._sample()]
		mask_fields(recs, role_has_cost_visibility=False)
		for rec in recs:
			self.assertIsNone(rec.get("valuation_rate"))
			self.assertIsNone(rec.get("last_purchase_rate"))

	def test_list_visible_user_no_change(self):
		recs = [self._sample(), self._sample()]
		mask_fields(recs, role_has_cost_visibility=True)
		for rec in recs:
			self.assertEqual(rec["valuation_rate"], 100.0)

	def test_empty_dict_safe(self):
		rec: dict = {}
		mask_fields(rec, role_has_cost_visibility=False)
		self.assertEqual(rec, {})

	def test_empty_list_safe(self):
		result = mask_fields([], role_has_cost_visibility=False)
		self.assertEqual(result, [])

	def test_none_items_in_list_skipped(self):
		# Lists may contain non-dict items (e.g. None); should not raise.
		payload = [self._sample(), None, self._sample()]
		mask_fields(payload, role_has_cost_visibility=False)
		self.assertIsNone(payload[0].get("valuation_rate"))
		self.assertIsNone(payload[1])

	def test_returns_same_object_dict(self):
		rec = self._sample()
		self.assertIs(mask_fields(rec, False), rec)

	def test_returns_same_object_list(self):
		recs = [self._sample()]
		self.assertIs(mask_fields(recs, False), recs)

	def test_non_cost_only_record_unchanged(self):
		rec = {"name": "X", "item_name": "Y"}
		mask_fields(rec, role_has_cost_visibility=False)
		self.assertEqual(rec, {"name": "X", "item_name": "Y"})

	def test_garbage_values_safe(self):
		# Cost fields present but with odd types — should not raise.
		rec = {"valuation_rate": "N/A", "last_purchase_rate": [], "name": "X"}
		mask_fields(rec, role_has_cost_visibility=False)
		self.assertIsNone(rec["valuation_rate"])
		self.assertIsNone(rec["last_purchase_rate"])
		self.assertEqual(rec["name"], "X")


if __name__ == "__main__":
	unittest.main()
