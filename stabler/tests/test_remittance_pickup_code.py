"""The pickup code is what collects the cash — so what we store must not be usable.

Two defects shipped in the July remittance API and ran on seven tenants:

1. `create_remittance()` wrote the code in plaintext into the hidden
   `stabler_pickup_code` Journal Entry field. Anyone who could open the register
   entry could read the code and collect someone else's money — no forgery, no
   privilege escalation, just reading a field.
2. The same endpoint accepted `pickup_code` from the caller, so nothing
   guaranteed the code was server-generated. A caller could pre-agree a code with
   a receiver.
3. Hashing it fixed WHAT is stored and not WHO may read it. The v33 Custom Field
   stayed at permlevel 0 behind `hidden: 1`, and `hidden` is a form hint — Frappe
   builds the permitted field list from permlevel access alone. So the digest
   stayed one `/api/resource/Journal Entry?fields=[...]` away from any role with
   `read` on Journal Entry, which on this bench means core ERPNext accounting
   roles that are not remittance roles at all. An 8-character draw from a
   32-glyph alphabet is a bounded offline crack, so "only the digest leaked" is
   not a defence.

These tests hold all three doors shut. The helpers under test are pure stdlib, so
the module is imported against stubs and stays in the frappe-free set — a
bench-only test would never run in `make check` and would not gate a push. The
permlevel is asserted against the patch SOURCE for the same reason: the field is a
Custom Field, so there is no doctype JSON to read, and a bench test would not gate.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATCHES_DIR = os.path.join(_PKG, "patches")
_PATCHES_TXT = os.path.join(_PKG, "patches.txt")
_V33 = os.path.join(_PATCHES_DIR, "v33_remittance_stage_fields.py")

_SANDBOX = ModuleSandbox()

_CRYPTO = "stabler.api._remittance_pickup_code"

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


def _load_crypto():
	"""The pickup-code helpers, imported directly.

	No stubs: since the move out of `stabler.api.remittance` this module imports
	nothing but the standard library, so the whole fake-frappe apparatus above is
	needed only by the two tests that read the legacy endpoints' signatures.
	"""
	_SANDBOX.evict(_CRYPTO)
	return importlib.import_module(_CRYPTO)


class PickupCodeStorage(unittest.TestCase):
	"""What lands in the Journal Entry field must not let anyone collect the cash."""

	def setUp(self):
		self.api = _load_crypto()

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

	def test_a_lowercase_legacy_code_still_opens_the_drawer_after_migration(self):
		"""`hash_pickup_code` folds case, and v86 is the only caller that needs it to.

		The other two callers hand it something already uppercase — a
		server-generated code from `store_pickup_code`, or a receiver's input that
		`_pickup_code_matches` has already folded — so the `.upper()` reads as dead
		and the test above cannot see it either, because it passes an uppercase
		literal on both sides.

		The caller that needs it is the migration. v86 hashes whatever plaintext
		the tenant already had in `stabler_pickup_code`, and nothing ever forced
		that value to be uppercase. Drop the fold and every migrated lowercase code
		is hashed one way and verified the other — the transfer stays payable in
		the database and unpayable at the counter, with no error to trace it by.

		Measured 2026-08-20: removing `.upper()` from `hash_pickup_code` left the
		whole remittance suite green until this test existed.
		"""
		salt = "0123456789abcdef0123456789abcdef"
		migrated = self.api.hash_pickup_code("abcd2345", salt)
		self.assertTrue(self.api._pickup_code_matches(migrated, "ABCD2345"))
		self.assertTrue(self.api._pickup_code_matches(migrated, "abcd2345"))


class PickupCodeGeneration(unittest.TestCase):
	"""The server chooses the code. Always."""

	def setUp(self):
		self.api = _load_api()
		self.crypto = _load_crypto()

	def test_register_does_not_accept_a_caller_supplied_code(self):
		# A caller who can choose the code can agree it with a receiver in
		# advance, which makes verification at payout meaningless.
		params = inspect.signature(self.api.create_remittance).parameters
		self.assertNotIn("pickup_code", params)

	def test_payout_still_takes_the_code_the_receiver_presents(self):
		params = inspect.signature(self.api.payout_remittance).parameters
		self.assertIn("pickup_code", params)

	def test_generated_codes_avoid_ambiguous_glyphs_and_repeat(self):
		codes = {self.crypto._gen_pickup_code() for _ in range(50)}
		self.assertGreater(len(codes), 1)
		for code in codes:
			self.assertEqual(len(code), 8)
			self.assertTrue(set(code) <= set(self.crypto._CODE_ALPHABET))
			# 0/O and 1/I are the pairs a receiver reads back wrongly over the phone.
			self.assertFalse(set(code) & set("01OI"))


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def _v33_fields() -> list[dict]:
	"""The `_FIELDS` list out of patch v33, read without importing frappe."""
	tree = ast.parse(_read(_V33))
	for node in tree.body:
		if isinstance(node, ast.Assign) and any(
			isinstance(t, ast.Name) and t.id == "_FIELDS" for t in node.targets
		):
			return ast.literal_eval(node.value)
	raise AssertionError("patch v33 no longer defines _FIELDS")


class JournalEntryDigestIsNotReadable(unittest.TestCase):
	"""The third name for the same secret, closed the same way v89 closed the second.

	`Remittance Transfer.pickup_code_hash` is at permlevel 1 and pinned by
	`test_remittance_transfer_doctype`. This is the other field holding the same
	digest — written by the LEGACY register path, which is the path every company
	runs while `remittance_engine` defaults to Legacy.
	"""

	def test_the_custom_field_is_defined_at_permlevel_1(self):
		field = next(f for f in _v33_fields() if f["fieldname"] == "stabler_pickup_code")
		# Not `hidden`. frappe/model/meta.py get_permitted_fieldnames filters on
		# `df.permlevel in permlevel_access` and the candidate list it filters
		# (get_fieldnames_with_value) never consults `hidden`, so a hidden field at
		# permlevel 0 is a readable field.
		self.assertEqual(
			field.get("permlevel"),
			1,
			"stabler_pickup_code holds `scheme$salt$digest`; at permlevel 0 any role "
			"with read on Journal Entry can pull it off /api/resource.",
		)

	def test_the_other_je_remittance_fields_stay_readable(self):
		# The gate is on the secret, not on the module. Raising the whole set would
		# blind the legacy Transfers list, which reads sender/receiver/stage.
		others = [f for f in _v33_fields() if f["fieldname"] != "stabler_pickup_code"]
		self.assertTrue(others)
		for field in others:
			self.assertFalse(field.get("permlevel"), field["fieldname"])

	def test_a_registered_patch_raises_it_on_sites_that_already_have_the_field(self):
		# v33's execute() skips fields that already exist, so its dict is dead letter
		# on every site that has ever migrated. Without a patch the fix ships only to
		# sites that do not exist yet.
		registered = {
			line.strip().rsplit(".", 1)[-1]
			for line in _read(_PATCHES_TXT).splitlines()
			if line.strip() and not line.strip().startswith(("#", "["))
		}
		movers = []
		for entry in sorted(os.listdir(_PATCHES_DIR)):
			if not entry.endswith(".py") or entry == os.path.basename(_V33):
				continue
			src = _read(os.path.join(_PATCHES_DIR, entry))
			if "stabler_pickup_code" in src and "permlevel" in src and "Journal Entry" in src:
				movers.append(entry[:-3])
		self.assertTrue(movers, "no patch raises the permlevel of Journal Entry.stabler_pickup_code")
		self.assertTrue(
			registered & set(movers),
			f"{movers} exists but is not listed in patches.txt, so migrate never runs it",
		)


if __name__ == "__main__":
	unittest.main()
