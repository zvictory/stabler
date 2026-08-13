"""Fast, frappe-free tests for the imports UAT fixture's safety guard.

The fixture inserts and deletes documents. `_guard()` is the only thing standing
between it and a real tenant's data, so that is what these tests pin: not that the
guard exists, but that it actually refuses.
"""

from __future__ import annotations

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
