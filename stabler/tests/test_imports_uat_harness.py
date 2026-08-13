"""Fast, frappe-free tests for the imports UAT fixture.

The fixture inserts and deletes documents. `_guard()` is the only thing standing
between it and a real tenant's data, so that is the first thing these tests pin:
not that the guard exists, but that it actually refuses.

The second thing they pin is that the fixture sets up the situation it claims to,
so the harness cannot report a false pass — see `ImportsUatExactlyOnceFixtureTest`.
"""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from unittest.mock import MagicMock

# Setup frappe mock as a package with utilities
frappe_mock = MagicMock()
frappe_mock.utils = MagicMock()
frappe_mock.utils.nowdate = MagicMock(return_value="2026-08-13")

sys.modules["frappe"] = frappe_mock
sys.modules["frappe.utils"] = frappe_mock.utils

import frappe

from stabler.api._imports_rules import bill_cost_component, derive_bill_category
from stabler.maintenance import seed_imports_uat
from stabler.maintenance.seed_imports_uat import DEMO_SUFFIX, _guard


class _Refused(Exception):
	"""Stands in for frappe.throw, which aborts rather than returns."""


class ImportsUatGuardTest(unittest.TestCase):
	def setUp(self):
		frappe.throw.side_effect = _Refused
		frappe.local = MagicMock()
		frappe.local.site = "genesis-test.local"
		frappe.conf = {"developer_mode": 1}

	def test_the_sandbox_site_is_let_through(self):
		# Without this the harness could never run at all.
		_guard()

	def test_any_other_site_is_refused(self):
		# The failure this prevents: seeding UAT fixtures into a live tenant.
		frappe.local.site = "msa.erpstable.com"
		with self.assertRaises(_Refused):
			_guard()

	def test_the_site_name_is_matched_exactly_not_by_prefix(self):
		frappe.local.site = "genesis-test.local.erpstable.com"
		with self.assertRaises(_Refused):
			_guard()

	def test_developer_mode_off_is_refused_even_on_the_sandbox_site(self):
		# A site restored from a production dump keeps its name but loses
		# developer_mode; the second condition is what catches that.
		frappe.conf = {}
		with self.assertRaises(_Refused):
			_guard()


class ImportsUatMarkerTest(unittest.TestCase):
	def test_seeded_records_carry_a_distinctive_marker(self):
		# seed() names its records with this suffix and unseed() finds them by it.
		# If it ever became empty or generic, unseed would match site-owned data.
		self.assertEqual(DEMO_SUFFIX, " [UAT]")


def _string_keyed_dict_literals(source: str) -> list[dict]:
	"""Every dict literal in *source* whose keys are all plain string constants.

	Reading the fixture as data instead of running it keeps this test frappe-free
	while still measuring the fixture that actually ships.
	"""
	found = []
	for node in ast.walk(ast.parse(source)):
		if not isinstance(node, ast.Dict):
			continue
		pairs = {}
		for key, value in zip(node.keys, node.values, strict=True):
			if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
				pairs = None
				break
			pairs[key.value] = value.value if isinstance(value, ast.Constant) else None
		if pairs is not None:
			found.append(pairs)
	return found


class ImportsUatExactlyOnceFixtureTest(unittest.TestCase):
	"""The fixture must stage a real exactly-once situation, not a lookalike.

	Container B carries a hand-typed transport cost AND the carrier's own bill for
	the same leg. The chain only demonstrates that this money is capitalized once
	if both sides name the *same* cost component: `lcv_math.vouchered_hand_line`
	matches the component exactly, deliberately (widening it would trade a visible
	over-capitalization for a silent, permanent under-capitalization).

	When the two drift apart the failure is invisible: the link path writes a
	second cost line, a second voucher capitalizes the same 150 USD under the other
	name, and the harness still records "one tax row for this component" — a false
	pass. That is the bug this test exists to prevent from coming back.
	"""

	def setUp(self):
		self.source = inspect.getsource(seed_imports_uat)
		self.dicts = _string_keyed_dict_literals(self.source)

	def test_the_hand_typed_transport_line_names_the_component_its_bill_derives(self):
		hand_lines = [d for d in self.dicts if "cost_component" in d and d.get("amount") == 150]
		# Loud rather than vacuous: if the fixture is restructured so this no longer
		# matches, the test must fail instead of silently checking nothing.
		self.assertEqual(len(hand_lines), 1, f"expected one 150-unit cost line, got {hand_lines!r}")

		bill_items = [d for d in self.dicts if "item_name" in d]
		self.assertEqual(len(bill_items), 1, f"expected one bill item, got {bill_items!r}")
		# The trap: the carrier bill's item carries `item_name`, never `item_code`,
		# and derive_bill_category only inspects item codes — so the "Import Service"
		# expense branch cannot fire and the supplier group decides the category.
		item = bill_items[0]
		item_codes = (item["item_code"],) if item.get("item_code") else ()

		# `transport_supplier=True` is not an assumption: the fixture puts the carrier
		# in the "Services" group and configures that same group as a transport group.
		self.assertIn('doc.supplier_group = "Services"', self.source)
		self.assertIn('imports_transport_supplier_groups = "Services', self.source)

		expected = bill_cost_component(
			derive_bill_category(
				item_codes=item_codes,
				bill_no=f"UAT-PI{DEMO_SUFFIX}",
				transport_supplier=True,
			)
		)
		self.assertEqual(expected, "Cross-Border Transport")
		self.assertEqual(hand_lines[0]["cost_component"], expected)
