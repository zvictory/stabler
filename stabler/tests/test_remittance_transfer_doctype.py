"""The master record and its trail.

The Journal Entry chain used to BE the record, which is why a concurrent double payout
was possible. These tests cover the invariants that must hold for any row regardless of
who wrote it — the row lock and replay handling belong to the command handlers
(stabler-4lc3) and are tested there.

Bench-free: the bench set is not part of `make check`, so a test needing one would not
gate a push.
"""

from __future__ import annotations

import importlib
import json
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TRANSFER = "stabler.stabler.doctype.remittance_transfer.remittance_transfer"
_EVENT = "stabler.stabler.doctype.remittance_event.remittance_event"

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _load_doctype(name: str) -> dict:
	path = os.path.join(_PKG, "stabler", "doctype", name, f"{name}.json")
	with open(path, encoding="utf-8") as fh:
		return json.load(fh)


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


class _Flags(dict):
	"""Stands in for `frappe._dict`: a dict that also answers to attribute access."""

	__getattr__ = dict.get
	__setattr__ = dict.__setitem__


def _load(module: str):
	_SANDBOX.evict(module, "frappe", "frappe.model", "frappe.model.document", "frappe.utils")

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	# The digest guard mirrors `validate_higher_perm_levels`, which reads both of
	# these before it resets anything. Defaults are the ordinary case: a real user,
	# a site that is not mid-install.
	frappe.flags = types.SimpleNamespace(in_install=False)
	frappe.session = types.SimpleNamespace(user="cashier@example.com")

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value, precision=None: (
		round(float(value or 0), precision) if precision is not None else float(value or 0)
	)
	utils.cint = lambda value, default=0: int(float(value)) if str(value or "").strip() else default
	frappe.utils = utils

	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")

	class Document:
		def is_new(self):
			return getattr(self, "_is_new", True)

		@property
		def flags(self):
			# A dict with attribute access, because that is what `frappe._dict` is and
			# the guard uses BOTH forms: `flags.ignore_permissions` and
			# `flags.get("ignore_permlevel_for_fields")`. A SimpleNamespace would pass
			# the first and blow up on the second.
			if not hasattr(self, "_flags"):
				self._flags = _Flags()
			return self._flags

		def get_permlevel_access(self, permission_type="write"):
			# Keyed by permission_type on purpose. The real doctype grants permlevel 1
			# for WRITE only — there is no permlevel-1 read row, and
			# test_nobody_is_granted_read_at_that_level keeps it that way. A fake that
			# ignored this argument would let the guard ask about "read", get False for
			# every user forever, and still show green.
			#
			# Default is the site the guard exists for: level 0 and nothing above it,
			# so `pickup_code_hash` gets reset on the way in. Tests that model a
			# patched site set `_permlevel_grants`.
			grants = getattr(self, "_permlevel_grants", {"write": [0]})
			return grants.get(permission_type, [0])

	document.Document = Document
	model.document = document
	frappe.model = model

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.model": model,
			"frappe.model.document": document,
			"frappe.utils": utils,
		}
	)
	return importlib.import_module(module)


def _transfer(api, **overrides):
	doc = api.RemittanceTransfer()
	doc.commission_mode = "Exclusive"
	doc.principal = 1000.00
	doc.commission = 10.00
	doc.tendered = 1010.00
	doc.operational_status = "Draft"
	doc.accounting_status = "Unposted"
	# Every registered row carries one, so the fixture does too. Nothing in this class
	# asserts anything ABOUT it any more: `_new_transfer` writes it with `db_set`,
	# below the permlevel layer, so it cannot be absent by the time validate runs.
	doc.pickup_code_hash = "s1$salt$digest"
	for key, value in overrides.items():
		setattr(doc, key, value)
	return doc


class StateAxes(unittest.TestCase):
	"""Four axes, shown separately. A single status field cannot express this."""

	def setUp(self):
		self.fields = {f["fieldname"]: f for f in _load_doctype("remittance_transfer")["fields"]}

	def test_the_four_axes_carry_exactly_the_documented_values(self):
		expected = {
			"operational_status": (
				["Draft", "Registered", "Paid Out", "Refunded", "Expired", "Exception"],
				"Draft",
			),
			"accounting_status": (["Unposted", "Posted", "Reversed", "Posting Error"], "Unposted"),
			"verification_status": (
				["Not Issued", "Active", "Locked", "Consumed", "Expired"],
				"Not Issued",
			),
			"refund_status": (["None", "Requested", "Approved", "Rejected", "Completed"], "None"),
		}
		for fieldname, (options, initial) in expected.items():
			field = self.fields[fieldname]
			self.assertEqual(field["options"].split("\n"), options, fieldname)
			self.assertEqual(field["default"], initial, fieldname)
			self.assertEqual(field.get("reqd"), 1, fieldname)

	def test_no_single_collapsed_status_field_exists(self):
		# A combined "status" would let two axes disagree silently — the reason the
		# design shows them separately in the first place.
		self.assertNotIn("status", self.fields)


class FrozenTriple(unittest.TestCase):
	"""Stored, never recomputed — so a row that does not close is not trustworthy."""

	def setUp(self):
		self.api = _load(_TRANSFER)

	def test_principal_plus_commission_must_equal_tendered(self):
		_transfer(self.api).validate()  # 1000 + 10 == 1010

	def test_a_triple_that_does_not_close_is_rejected(self):
		# Measured in the plan: round-tripping inclusive<->exclusive drifts exactly one
		# minor unit in ~1% of amounts. A drifted row must not reach the receipt.
		with self.assertRaises(_Thrown):
			_transfer(self.api, tendered=1010.01).validate()

	def test_inclusive_commission_may_not_swallow_the_principal(self):
		with self.assertRaises(_Thrown):
			_transfer(
				self.api, commission_mode="Inclusive", principal=0.00, commission=1000.00, tendered=1000.00
			).validate()

	def test_inclusive_is_fine_while_a_principal_remains(self):
		_transfer(
			self.api, commission_mode="Inclusive", principal=990.10, commission=9.90, tendered=1000.00
		).validate()

	def test_the_stored_values_are_all_required(self):
		fields = {f["fieldname"]: f for f in _load_doctype("remittance_transfer")["fields"]}
		for fieldname in ("principal", "commission", "tendered", "receiver_amount"):
			self.assertEqual(fields[fieldname].get("reqd"), 1, fieldname)


class RegisteredIsAlwaysPosted(unittest.TestCase):
	"""The transition and the JE submit share a transaction, so the pair is unreachable."""

	def setUp(self):
		self.api = _load(_TRANSFER)

	def test_registered_and_unposted_is_rejected(self):
		# Reaching it means the payout queue can debit an obligation that was never
		# created.
		with self.assertRaises(_Thrown):
			_transfer(self.api, operational_status="Registered", accounting_status="Unposted").validate()

	def test_registered_and_posted_is_fine(self):
		_transfer(self.api, operational_status="Registered", accounting_status="Posted").validate()

	def test_draft_and_unposted_is_fine(self):
		_transfer(self.api, operational_status="Draft", accounting_status="Unposted").validate()


class CodeAndReplayFields(unittest.TestCase):
	def setUp(self):
		self.fields = {f["fieldname"]: f for f in _load_doctype("remittance_transfer")["fields"]}

	def test_the_code_is_stored_hashed_and_never_offered_to_a_form(self):
		field = self.fields["pickup_code_hash"]
		self.assertEqual(field["hidden"], 1)
		self.assertEqual(field["read_only"], 1)
		self.assertEqual(field["no_copy"], 1)

	def test_there_is_no_plaintext_code_field(self):
		self.assertNotIn("pickup_code", self.fields)

	def test_the_digest_carries_no_default(self):
		# Load-bearing for the insert guard, and invisible from it. On a new document
		# `reset_values_if_no_permlevel_access` writes the field's DEFAULT, not an
		# empty string (frappe/model/base_document.py, `if self.is_new()`). Give this
		# field a default and a discarded digest comes back looking supplied — the
		# guard goes quiet and the unpayable transfer ships again.
		self.assertIsNone(self.fields["pickup_code_hash"].get("default"))

	def test_the_attempt_counter_and_lock_are_server_owned(self):
		for fieldname in ("code_attempts", "code_locked"):
			self.assertEqual(self.fields[fieldname]["read_only"], 1, fieldname)

	def test_a_replay_key_cannot_produce_a_second_transfer(self):
		# The database refuses the duplicate; the handler turns that into "return the
		# original result" rather than a second registration.
		field = self.fields["client_request_id"]
		self.assertEqual(field["unique"], 1)
		self.assertEqual(field["no_copy"], 1)

	def test_the_obligation_rate_is_frozen_at_register(self):
		# Payout and refund reuse it. If a form could edit it, the obligation would
		# close at a different rate than it opened and never balance to zero.
		self.assertEqual(self.fields["register_base_rate"]["read_only"], 1)


class PickupCodeDigestIsNotReadable(unittest.TestCase):
	"""`hidden` is a form-layout flag. It does not gate a field read.

	`frappe/model/meta.py:677 get_permitted_fieldnames` builds the readable set from
	permlevel access and never consults `hidden`, so at permlevel 0 any role holding
	`read` on the doctype — Remittance Viewer and Remittance Auditor, whose entire
	permission set is `{read: 1}` — could ask `/api/resource/Remittance Transfer` for
	`pickup_code_hash` and be given it. The digest is a salted SHA-256 over an
	8-character code from a 32-glyph alphabet: one record is a bounded offline crack,
	and what falls out is the bearer token for somebody's cash.

	The permlevel bump used to have a trap attached: `validate_higher_perm_levels`
	resets a permlevel field the saving user cannot WRITE, so bumping the level
	without granting write at that level made `_new_transfer` store NULL while
	`register_remittance` still handed the cashier a plaintext code. That is no longer
	how the digest is written — `_new_transfer` writes it with `db_set` after the
	insert, below the permlevel layer (stabler-tvvc), and
	`test_remittance_digest_below_permlevel_bench` proves on a live site that a role
	holding no permlevel-1 grant at all can still register.

	The grant is KEPT anyway, deliberately: revoking it would mean a permission
	migration across seven tenants to buy nothing, and it is what keeps a future move
	of the digest back into the insert payload from being silent data loss. The test
	below pins it as shipped, not as a gate registration still depends on.
	"""

	def setUp(self):
		self.dt = _load_doctype("remittance_transfer")
		self.fields = {f["fieldname"]: f for f in self.dt["fields"]}
		self.perms = self.dt["permissions"]

	def test_the_digest_is_above_permlevel_zero(self):
		self.assertGreaterEqual(self.fields["pickup_code_hash"].get("permlevel", 0), 1)

	def test_it_is_the_only_field_lifted_out_of_level_zero(self):
		# A second field arriving at permlevel 1 would inherit this grant without
		# anyone deciding it should.
		lifted = [f["fieldname"] for f in self.dt["fields"] if f.get("permlevel", 0) > 0]
		self.assertEqual(["pickup_code_hash"], lifted)

	def test_every_role_that_can_create_can_also_write_at_that_level(self):
		# Defence in depth, pinned as shipped. Registration no longer depends on this
		# grant (see the class docstring), but the grant is what would keep a move of
		# the digest back into the insert payload from being silent data loss.
		level = self.fields["pickup_code_hash"].get("permlevel", 0)
		creators = {p["role"] for p in self.perms if p.get("create") and not p.get("permlevel")}
		writers = {p["role"] for p in self.perms if p.get("permlevel") == level and p.get("write")}
		self.assertTrue(creators, "no role can create a transfer — the fixture is wrong")
		self.assertEqual(set(), creators - writers, "a role can register but cannot store the digest")

	def test_nobody_is_granted_read_at_that_level(self):
		# The whole point. A read grant here would undo the permlevel and be harder
		# to notice than the permlevel 0 it replaced.
		level = self.fields["pickup_code_hash"].get("permlevel", 0)
		readers = [p["role"] for p in self.perms if p.get("permlevel") == level and p.get("read")]
		self.assertEqual([], readers)

	def test_each_higher_level_role_also_holds_a_level_zero_row(self):
		# frappe/core/doctype/doctype/doctype.py:1829 `check_level_zero_is_set` throws
		# on migrate otherwise, which would take the whole doctype sync down.
		zero = {p["role"] for p in self.perms if not p.get("permlevel")}
		higher = {p["role"] for p in self.perms if p.get("permlevel")}
		self.assertEqual(set(), higher - zero)


class EventTrail(unittest.TestCase):
	def setUp(self):
		self.dt = _load_doctype("remittance_event")
		self.api = _load(_EVENT)

	def test_the_documented_event_types_and_no_others(self):
		options = {f["fieldname"]: f for f in self.dt["fields"]}["event_type"]["options"]
		self.assertEqual(
			options.split("\n"),
			[
				"Register",
				"Failed code attempt",
				"Lock",
				"Unlock",
				"Payout",
				"Refund request",
				"Refund approval",
				# A rejection is a fourth refund outcome, not an approval with a sad
				# note in `details`. `refund_status` has carried `Rejected` since
				# qzr9.7 and `reject_refund` is the transition that writes it; without
				# its own option, the one refund step that ends a request would be the
				# only transition with no entry in an append-only trail — or would be
				# filed under the opposite word.
				"Refund rejection",
				"Refund completion",
			],
		)

	def test_refund_approval_and_completion_are_separate_events(self):
		# Approval carries authority, completion moves cash. Collapsing them is how a
		# refund gets paid without anyone approving it.
		options = {f["fieldname"]: f for f in self.dt["fields"]}["event_type"]["options"].split("\n")
		self.assertIn("Refund approval", options)
		self.assertIn("Refund completion", options)

	def test_nobody_is_granted_write_or_delete(self):
		for row in self.dt["permissions"]:
			self.assertNotIn("write", row, row)
			self.assertNotIn("delete", row, row)

	def test_an_existing_event_cannot_be_edited(self):
		event = self.api.RemittanceEvent()
		event._is_new = False
		with self.assertRaises(_Thrown):
			event.validate()

	def test_a_new_event_saves(self):
		event = self.api.RemittanceEvent()
		event._is_new = True
		event.validate()

	def test_an_event_cannot_be_deleted(self):
		with self.assertRaises(_Thrown):
			self.api.RemittanceEvent().on_trash()


if __name__ == "__main__":
	unittest.main()
