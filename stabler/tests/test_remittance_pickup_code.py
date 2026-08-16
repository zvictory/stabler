"""The pickup code is what collects the cash — so what we store must not be usable.

Two defects shipped in the July remittance API and ran on seven tenants:

1. `create_remittance()` wrote the code in plaintext into the hidden
   `stabler_pickup_code` Journal Entry field. Anyone who could open the register
   entry could read the code and collect someone else's money — no forgery, no
   privilege escalation, just reading a field.
2. The same endpoint accepted `pickup_code` from the caller, so nothing
   guaranteed the code was server-generated. A caller could pre-agree a code with
   a receiver.

These tests hold both doors shut. The helpers under test are pure stdlib, so the
module is imported against stubs and stays in the frappe-free set — a bench-only
test would never run in `make check` and would not gate a push.
"""

from __future__ import annotations

import importlib
import inspect
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()

_FAKED = (
	"stabler.api.remittance",
	"frappe",
	"frappe.model",
	"frappe.model.naming",
	"frappe.utils",
	"stabler.api._common",
	"stabler.api.approvals",
	"stabler.api.money",
)


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _load_api():
	"""Import the remittance API against stubs.

	Only the pickup-code helpers are exercised and they touch nothing but the
	standard library, so every stub below exists purely to satisfy the module's
	import line.
	"""
	_SANDBOX.evict(*_FAKED)

	frappe = types.ModuleType("frappe")
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn

	model = types.ModuleType("frappe.model")
	naming = types.ModuleType("frappe.model.naming")
	naming.make_autoname = lambda *_a, **_k: ""
	model.naming = naming
	frappe.model = model

	utils = types.ModuleType("frappe.utils")
	utils.flt = float
	utils.getdate = lambda value=None: value
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_a, **_k: None
	common._require_company = lambda *_a, **_k: None

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda *_a, **_k: None

	money = types.ModuleType("stabler.api.money")
	for name in (
		"_date_filters",
		"_round2",
		"_validate_account",
		"bank_cash_accounts",
		"get_exchange_rate_for_currencies",
		"journal_entry_detail",
	):
		setattr(money, name, lambda *_a, **_k: None)

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.model": model,
			"frappe.model.naming": naming,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.api.money": money,
		}
	)
	return importlib.import_module("stabler.api.remittance")


class PickupCodeStorage(unittest.TestCase):
	"""What lands in the Journal Entry field must not let anyone collect the cash."""

	def setUp(self):
		self.api = _load_api()

	def test_stored_value_does_not_contain_the_code(self):
		# The original defect in one line: the field held the code itself.
		code = "ABCD2345"
		stored = self.api.store_pickup_code(code)
		self.assertNotIn(code, stored)
		self.assertTrue(stored.startswith("s1$"))

	def test_the_same_code_stores_differently_every_time(self):
		# Per-record salt: one leaked digest must not identify every other
		# transfer that happens to carry the same code.
		code = "ABCD2345"
		self.assertNotEqual(self.api.store_pickup_code(code), self.api.store_pickup_code(code))

	def test_a_stored_code_still_verifies(self):
		# Hashing is worthless if the receiver can no longer be paid.
		code = self.api._gen_pickup_code()
		self.assertTrue(self.api._pickup_code_matches(self.api.store_pickup_code(code), code))

	def test_a_different_code_is_rejected(self):
		stored = self.api.store_pickup_code("ABCD2345")
		self.assertFalse(self.api._pickup_code_matches(stored, "ABCD2346"))

	def test_the_receiver_may_type_it_loosely(self):
		# Existing behaviour: the code is normalised before comparison, so a
		# lowercase or padded entry is the same code, not a failed attempt.
		stored = self.api.store_pickup_code("ABCD2345")
		self.assertTrue(self.api._pickup_code_matches(stored, "  abcd2345 "))

	def test_an_empty_code_never_matches(self):
		stored = self.api.store_pickup_code("ABCD2345")
		self.assertFalse(self.api._pickup_code_matches(stored, ""))
		self.assertFalse(self.api._pickup_code_matches("", "ABCD2345"))

	def test_a_legacy_plaintext_row_never_authorises_a_payout(self):
		# The point of patch v86. If a row that still holds plaintext could be
		# matched against that plaintext, the fix would be cosmetic: reading the
		# field would still be enough to collect the cash.
		self.assertFalse(self.api._pickup_code_matches("ABCD2345", "ABCD2345"))

	def test_hashed_form_is_told_apart_from_plaintext(self):
		# Both the payout guard and the migration branch on this.
		self.assertTrue(self.api.is_hashed_pickup_code(self.api.store_pickup_code("ABCD2345")))
		self.assertFalse(self.api.is_hashed_pickup_code("ABCD2345"))
		self.assertFalse(self.api.is_hashed_pickup_code(""))
		self.assertFalse(self.api.is_hashed_pickup_code("s1$onlyonepart"))

	def test_migration_and_api_derive_the_same_digest(self):
		# The patch hashes existing values with hash_pickup_code and payout
		# verifies with _pickup_code_matches. If the two ever drift, every
		# migrated transfer silently becomes unpayable.
		salt = "0123456789abcdef0123456789abcdef"
		self.assertTrue(
			self.api._pickup_code_matches(self.api.hash_pickup_code("ABCD2345", salt), "ABCD2345")
		)


class PickupCodeGeneration(unittest.TestCase):
	"""The server chooses the code. Always."""

	def setUp(self):
		self.api = _load_api()

	def test_register_does_not_accept_a_caller_supplied_code(self):
		# A caller who can choose the code can agree it with a receiver in
		# advance, which makes verification at payout meaningless.
		params = inspect.signature(self.api.create_remittance).parameters
		self.assertNotIn("pickup_code", params)

	def test_payout_still_takes_the_code_the_receiver_presents(self):
		params = inspect.signature(self.api.payout_remittance).parameters
		self.assertIn("pickup_code", params)

	def test_generated_codes_avoid_ambiguous_glyphs_and_repeat(self):
		codes = {self.api._gen_pickup_code() for _ in range(50)}
		self.assertGreater(len(codes), 1)
		for code in codes:
			self.assertEqual(len(code), 8)
			self.assertTrue(set(code) <= set(self.api._CODE_ALPHABET))
			# 0/O and 1/I are the pairs a receiver reads back wrongly over the phone.
			self.assertFalse(set(code) & set("01OI"))


if __name__ == "__main__":
	unittest.main()
