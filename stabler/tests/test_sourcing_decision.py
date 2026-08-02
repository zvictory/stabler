"""Schema and controller contracts for the auditable award (Faz 2 · Task 3).

`Tender Sourcing Decision` is the record that turns "the cheapest row is
highlighted" into "this quotation was selected, for this reason, by this person,
at this time, against these numbers". Every rule below is one that has to hold
even when the document is written by something other than our own endpoint —
a bench console, a data import, a future screen. A rule that only holds inside
one function is not an audit guarantee.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_sourcing_decision -v
"""

from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = _ROOT / "stabler" / "doctype" / "tender_sourcing_decision" / "tender_sourcing_decision.json"
CONTROLLER = _ROOT / "stabler" / "doctype" / "tender_sourcing_decision" / "tender_sourcing_decision.py"
HOOKS = _ROOT / "hooks.py"


class _Flags(types.SimpleNamespace):
	pass


class _Document:
	"""Minimal stand-in for frappe's Document.

	`get_doc_before_save` is modelled because the one-way status rule turns on
	exactly that call: without a committed previous state the controller cannot
	tell an insert from an edit, and every rule about transitions collapses.
	"""

	def __init__(self, **values):
		before = values.pop("_before_save", None)
		self.__dict__.update(values)
		self.flags = _Flags()
		# Stored under a name no field uses: a fixture attribute that shadows a
		# controller helper turns a rule failure into an AttributeError, and the
		# rule stops being tested at all.
		self.__dict__["_before_save"] = before

	def get_doc_before_save(self):
		return self.__dict__.get("_before_save")


def _load_controller():
	for name in (
		"stabler.stabler.doctype.tender_sourcing_decision.tender_sourcing_decision",
		"frappe",
		"frappe.model",
		"frappe.model.document",
	):
		sys.modules.pop(name, None)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))
	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")
	document.Document = _Document
	sys.modules.update({"frappe": frappe, "frappe.model": model, "frappe.model.document": document})
	module = importlib.import_module(
		"stabler.stabler.doctype.tender_sourcing_decision.tender_sourcing_decision"
	)
	return module


def _complete(**overrides):
	"""A decision whose quote set satisfies the policy, so the exception rule is
	out of the way and the test can be about the rule it names."""
	values = {
		"company": "ACME",
		"deal": "LOT-A",
		"status": "Draft",
		"selected_quotation": "SQ-2",
		"cheapest_quotation": "SQ-1",
		"selection_reason": "Delivery window fits the tender deadline.",
		"technical_result": "Compliant",
		"quotation_count": 6,
		"country_count": 3,
		"policy_exception": 0,
		"exception_reason": "",
		"approved_by": "",
		"approved_at": "",
	}
	values.update(overrides)
	return values


class TestSchema(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.schema = json.loads(SCHEMA.read_text())
		cls.fields = {f["fieldname"]: f for f in cls.schema["fields"]}

	def test_the_decision_is_scoped_and_named(self):
		self.assertEqual(self.schema["autoname"], "naming_series:")
		self.assertEqual(self.fields["company"]["options"], "Company")
		self.assertEqual(self.fields["company"]["reqd"], 1)
		self.assertEqual(self.fields["deal"]["options"], "CRM Deal")
		self.assertEqual(self.fields["deal"]["reqd"], 1)

	def test_cheapest_and_selected_are_separate_fields(self):
		"""They are separate FACTS. Collapsing them into one link would erase the
		only interesting case: the time we knowingly did not take the cheapest."""
		self.assertEqual(self.fields["selected_quotation"]["options"], "Supplier Quotation")
		self.assertEqual(self.fields["selected_quotation"]["reqd"], 1)
		self.assertEqual(self.fields["cheapest_quotation"]["options"], "Supplier Quotation")

	def test_a_reason_is_mandatory(self):
		"""An award with no reason is a click, not a decision."""
		self.assertEqual(self.fields["selection_reason"]["reqd"], 1)

	def test_the_derived_and_stamped_fields_are_read_only(self):
		"""Anything the server computes must be un-typeable in the Desk form, or
		the audit record acquires a second, editable version of the truth."""
		for field in (
			"status",
			"cheapest_quotation",
			"quotation_count",
			"country_count",
			"comparison_snapshot",
			"approved_by",
			"approved_at",
		):
			with self.subTest(field=field):
				self.assertEqual(self.fields[field].get("read_only"), 1)

	def test_status_has_exactly_two_states(self):
		self.assertEqual(self.fields["status"]["options"], "Draft\nApproved")
		self.assertEqual(self.fields["status"]["default"], "Draft")

	def test_changes_are_tracked(self):
		"""The point of the record is the audit trail around it."""
		self.assertEqual(self.schema["track_changes"], 1)

	def test_nobody_but_an_administrator_may_delete_an_award(self):
		by_role = {p["role"]: p for p in self.schema["permissions"]}
		self.assertEqual(by_role["Sales User"].get("delete", 0), 0)
		self.assertEqual(by_role["Sales Manager"].get("delete", 0), 0)

	def test_the_doctype_is_company_scoped_by_hooks(self):
		hooks = HOOKS.read_text()
		self.assertIn('"Tender Sourcing Decision"', hooks)


class TestApprovalStampIsTheServers(unittest.TestCase):
	def setUp(self):
		self.module = _load_controller()

	def _doc(self, previous=None, **overrides):
		doc = self.module.TenderSourcingDecision(**_complete(**overrides))
		doc.__dict__["_before_save"] = previous
		return doc

	def test_a_payload_cannot_name_its_own_approver(self):
		"""Accepting it would let the record name a person who never saw it."""
		doc = self._doc(approved_by="ceo@example.com")
		with self.assertRaises(PermissionError):
			doc.validate()

	def test_a_payload_cannot_set_its_own_timestamp(self):
		doc = self._doc(approved_at="2020-01-01 00:00:00")
		with self.assertRaises(PermissionError):
			doc.validate()

	def test_the_approval_path_may_stamp(self):
		previous = self.module.TenderSourcingDecision(**_complete())
		doc = self._doc(
			previous=previous,
			status="Approved",
			approved_by="dir@example.com",
			approved_at="2026-08-02 10:00:00",
		)
		doc.flags.stabler_approving = True
		doc.validate()

	def test_an_unchanged_stamp_passes_on_a_later_edit(self):
		"""Re-saving an already stamped document must not read as forging one."""
		previous = self.module.TenderSourcingDecision(
			**_complete(approved_by="dir@example.com", approved_at="2026-08-02 10:00:00")
		)
		doc = self._doc(
			previous=previous,
			approved_by="dir@example.com",
			approved_at="2026-08-02 10:00:00",
			selection_reason="Reworded.",
		)
		doc.validate()


class TestStatusMovesOneWay(unittest.TestCase):
	def setUp(self):
		self.module = _load_controller()

	def _doc(self, previous=None, **overrides):
		doc = self.module.TenderSourcingDecision(**_complete(**overrides))
		doc.__dict__["_before_save"] = previous
		return doc

	def test_a_decision_cannot_be_born_approved(self):
		"""Approval is an act by a second person; an insert has no first state
		for them to have reviewed."""
		with self.assertRaises(Exception):
			self._doc(status="Approved").validate()

	def test_a_draft_cannot_approve_itself_through_an_ordinary_save(self):
		previous = self.module.TenderSourcingDecision(**_complete())
		doc = self._doc(previous=previous, status="Approved")
		with self.assertRaises(PermissionError):
			doc.validate()

	def test_an_approved_decision_is_frozen(self):
		"""An award that can quietly return to draft is a form, not a record."""
		previous = self.module.TenderSourcingDecision(**_complete(status="Approved"))
		for attempt in ({"status": "Draft"}, {"status": "Approved", "selected_quotation": "SQ-9"}):
			with self.subTest(attempt=attempt):
				doc = self._doc(previous=previous, **attempt)
				with self.assertRaises(Exception):
					doc.validate()

	def test_editing_a_draft_stays_allowed(self):
		previous = self.module.TenderSourcingDecision(**_complete())
		self._doc(previous=previous, selection_reason="Better wording.").validate()


class TestPolicyExceptionIsWritten(unittest.TestCase):
	def setUp(self):
		self.module = _load_controller()

	def _validate(self, **overrides):
		doc = self.module.TenderSourcingDecision(**_complete(**overrides))
		doc.__dict__["_before_save"] = None
		doc.validate()

	def test_a_complete_quote_set_needs_no_exception(self):
		self._validate(quotation_count=5, country_count=2)

	def test_too_few_quotations_demands_an_exception(self):
		with self.assertRaises(Exception):
			self._validate(quotation_count=4, country_count=3)

	def test_a_single_country_demands_an_exception_even_with_many_bids(self):
		"""Five bids from one country is the exact case the two-country half of
		the rule exists to catch."""
		with self.assertRaises(Exception):
			self._validate(quotation_count=9, country_count=1)

	def test_the_exception_must_carry_a_reason(self):
		with self.assertRaises(Exception):
			self._validate(quotation_count=2, country_count=1, policy_exception=1, exception_reason="  ")

	def test_a_written_exception_lets_the_award_through(self):
		self._validate(
			quotation_count=2,
			country_count=1,
			policy_exception=1,
			exception_reason="Sole distributor for this HS code in the region.",
		)

	def test_the_thresholds_match_the_procurement_rule_the_screens_count(self):
		self.assertEqual(self.module.MIN_QUOTATIONS, 5)
		self.assertEqual(self.module.MIN_COUNTRIES, 2)


if __name__ == "__main__":
	unittest.main()
