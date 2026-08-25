"""Assigning both operators to many Work Orders in one gesture.

A shift lead opening thirty orders to type the same two names is the reason this
exists. The risk it introduces is the same one every sweep introduces: the caller
sends thirty ids and gets a success back, and nothing says that four of them were
never touched.

So the partition is a pure function with one invariant — every id the caller sent
comes back exactly once, either as done or as refused with a reason. That is what
makes "nothing was silently dropped" a property a test can hold rather than a
promise in a docstring.

The refusals themselves are the second decision. A finished order is skipped: a
bulk gesture is a sweep, not a per-order judgement, and rewriting the operator on
a closed order moves the credit for a shift that already happened. The single-order
endpoint still allows it, which is where a manager deliberately correcting one
record should be doing it anyway.

No bench and no DB, which is why this file is in the push gate.
"""

from __future__ import annotations

import unittest

from stabler.api.manufacturing import _bulk_pair_after, _partition_bulk_assign

COMPANY = "Anjan"


class TestBulkAssignPartition(unittest.TestCase):
	@staticmethod
	def _row(name, status="In Process", company=COMPANY, docstatus=1):
		return {"name": name, "status": status, "company": company, "docstatus": docstatus}

	def test_an_order_still_running_is_assigned(self):
		ok, skipped = _partition_bulk_assign(["WO-1"], [self._row("WO-1")], COMPANY)
		self.assertEqual(ok, ["WO-1"])
		self.assertEqual(skipped, [])

	def test_a_paused_order_is_still_assigned(self):
		"""A shift change is exactly when the two names need swapping, and a stopped
		order is the one most likely to be sitting there when it happens."""
		ok, _ = _partition_bulk_assign(["WO-1"], [self._row("WO-1", status="Stopped")], COMPANY)
		self.assertEqual(ok, ["WO-1"])

	def test_a_finished_order_is_refused_and_says_so(self):
		"""Not skipped quietly. Changing the operator here moves the credit for a
		shift that is already over, and the manager needs to know it did not happen.
		"""
		ok, skipped = _partition_bulk_assign(["WO-1"], [self._row("WO-1", status="Completed")], COMPANY)
		self.assertEqual(ok, [])
		self.assertEqual(skipped[0]["name"], "WO-1")
		self.assertIn("Completed", skipped[0]["reason"])

	def test_closed_and_cancelled_are_refused_too(self):
		for status in ("Closed", "Cancelled"):
			ok, skipped = _partition_bulk_assign(["WO-1"], [self._row("WO-1", status=status)], COMPANY)
			self.assertEqual(ok, [], status)
			self.assertIn(status, skipped[0]["reason"])

	def test_a_cancelled_document_is_refused_whatever_its_status_says(self):
		"""`docstatus` is the truth about a cancelled document; `status` is a field
		somebody can leave stale."""
		ok, skipped = _partition_bulk_assign(
			["WO-1"], [self._row("WO-1", status="In Process", docstatus=2)], COMPANY
		)
		self.assertEqual(ok, [])
		self.assertTrue(skipped)

	def test_an_order_from_another_company_is_refused_by_name(self):
		"""Tenant isolation. One shared app, seven businesses — an id from another
		company reaching this list is either a bug or an attempt, and either way the
		answer is to name it, not to drop it."""
		ok, skipped = _partition_bulk_assign(["WO-1"], [self._row("WO-1", company="MSA")], COMPANY)
		self.assertEqual(ok, [])
		self.assertIn("WO-1", skipped[0]["name"])

	def test_an_id_that_does_not_exist_comes_back_as_a_refusal(self):
		"""It never appears in the query result, so nothing else would ever mention
		it. Thirty sent, twenty-eight assigned, and the two typos silent."""
		ok, skipped = _partition_bulk_assign(["WO-1", "WO-GHOST"], [self._row("WO-1")], COMPANY)
		self.assertEqual(ok, ["WO-1"])
		self.assertEqual([s["name"] for s in skipped], ["WO-GHOST"])

	def test_every_id_sent_comes_back_exactly_once(self):
		"""The invariant the whole thing rests on. Anything that changes the rules
		later still has to satisfy this, or the caller is being told less than the
		truth about what happened."""
		names = ["WO-1", "WO-2", "WO-3", "WO-4", "WO-GHOST"]
		rows = [
			self._row("WO-1"),
			self._row("WO-2", status="Completed"),
			self._row("WO-3", company="MSA"),
			self._row("WO-4", status="Stopped"),
		]
		ok, skipped = _partition_bulk_assign(names, rows, COMPANY)
		self.assertEqual(sorted(ok + [s["name"] for s in skipped]), sorted(names))
		self.assertEqual(len(ok) + len(skipped), len(names))

	def test_a_repeated_id_is_not_assigned_twice(self):
		"""A double-click on a checkbox row should not turn into two writes."""
		ok, skipped = _partition_bulk_assign(["WO-1", "WO-1"], [self._row("WO-1")], COMPANY)
		self.assertEqual(ok, ["WO-1"])
		self.assertEqual(skipped, [])


class TestAnEmptyBoxIsNotAnInstructionToClear(unittest.TestCase):
	"""The single-order endpoint clears a role when its box is left empty — that is
	how "— Remove operator —" works there, and on one order it is unambiguous.

	In a sweep it is the opposite of unambiguous. A shift lead who opens the dialog
	to put one pouring operator on fifteen orders has said nothing at all about the
	packers, and reading that silence as "remove them" would strip fifteen packing
	assignments in one click. So bulk fills only the roles that were chosen.
	"""

	def test_a_role_left_empty_keeps_whoever_is_already_there(self):
		after = _bulk_pair_after(
			{"operator": "old.pour@x", "packaging_operator": "old.pack@x"},
			{"operator": "new.pour@x", "packaging_operator": None},
		)
		self.assertEqual(after["operator"], "new.pour@x")
		self.assertEqual(after["packaging_operator"], "old.pack@x")

	def test_a_role_that_was_chosen_overwrites_what_was_there(self):
		after = _bulk_pair_after(
			{"operator": "old.pour@x", "packaging_operator": "old.pack@x"},
			{"operator": None, "packaging_operator": "new.pack@x"},
		)
		self.assertEqual(after["operator"], "old.pour@x")
		self.assertEqual(after["packaging_operator"], "new.pack@x")

	def test_an_unassigned_order_stays_half_assigned_rather_than_inventing_a_name(self):
		"""Half-assigned is a state the list already shows in red and the Start button
		already refuses. Better that than guessing the second name."""
		after = _bulk_pair_after(
			{"operator": None, "packaging_operator": None},
			{"operator": "new.pour@x", "packaging_operator": None},
		)
		self.assertEqual(after, {"operator": "new.pour@x", "packaging_operator": None})

	def test_it_reveals_the_clash_the_manager_could_not_see(self):
		"""Assigning one role in bulk can put the same person in both roles on an
		order the manager never opened — v97 split the roles precisely so their
		output stays countable apart, so this pair has to be caught per order and
		not just between the two boxes in the dialog."""
		after = _bulk_pair_after(
			{"operator": None, "packaging_operator": "same@x"},
			{"operator": "same@x", "packaging_operator": None},
		)
		self.assertEqual(after["operator"], after["packaging_operator"])
