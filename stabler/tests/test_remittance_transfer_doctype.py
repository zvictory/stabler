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


def _load(module: str):
	_SANDBOX.evict(module, "frappe", "frappe.model", "frappe.model.document", "frappe.utils")

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value, precision=None: (
		round(float(value or 0), precision) if precision is not None else float(value or 0)
	)
	frappe.utils = utils

	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")

	class Document:
		def is_new(self):
			return getattr(self, "_is_new", True)

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
