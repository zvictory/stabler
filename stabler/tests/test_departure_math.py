"""Port-transfer departure gate rules — pure, no site required."""

import unittest

from stabler.stabler.imports_module import departure_math as dm


def D(gtd="GTD-1", status="Approved", cleared="2026-07-01", required=1):
	return {
		"gtd_number": gtd,
		"status": status,
		"cleared_date": cleared,
		"required_for_departure": required,
	}


def codes(blockers):
	return [b["code"] for b in blockers]


class IsClearedTest(unittest.TestCase):
	def test_approved_with_date(self):
		self.assertTrue(dm.is_cleared(D()))

	def test_approved_without_date_is_not_cleared(self):
		# Paperwork accepted, goods not released — the exact state the gate exists for.
		self.assertFalse(dm.is_cleared(D(cleared=None)))

	def test_other_statuses_are_not_cleared(self):
		for s in ("Draft", "Submitted", "Under Review", "Rejected"):
			with self.subTest(status=s):
				self.assertFalse(dm.is_cleared(D(status=s)))

	def test_none(self):
		self.assertFalse(dm.is_cleared(None))


class BlockersTest(unittest.TestCase):
	def test_all_clear(self):
		self.assertEqual(dm.departure_blockers([D()], vet_valid=True), [])

	def test_no_declarations_is_a_blocker_not_a_pass(self):
		self.assertEqual(codes(dm.departure_blockers([], vet_valid=True)), ["no_required_declaration"])

	def test_declarations_exist_but_none_required(self):
		self.assertEqual(
			codes(dm.departure_blockers([D(required=0)], vet_valid=True)),
			["no_required_declaration"],
		)

	def test_optional_declarations_are_ignored(self):
		rows = [D("REQ"), D("OPT", status="Draft", cleared=None, required=0)]
		self.assertEqual(dm.departure_blockers(rows, vet_valid=True), [])

	def test_uncleared_required_declaration_is_named(self):
		rows = [D("GTD-A"), D("GTD-B", status="Under Review", cleared=None)]
		b = dm.departure_blockers(rows, vet_valid=True)
		self.assertEqual(codes(b), ["declaration_not_cleared"])
		self.assertEqual(b[0]["gtd_number"], "GTD-B")

	def test_every_uncleared_declaration_is_reported(self):
		rows = [D("A", status="Draft", cleared=None), D("B", status="Rejected", cleared=None)]
		b = dm.departure_blockers(rows, vet_valid=True)
		self.assertEqual([x["gtd_number"] for x in b], ["A", "B"])

	def test_missing_vet_certificate(self):
		self.assertEqual(codes(dm.departure_blockers([D()], vet_valid=False)), ["vet_certificate_missing"])

	def test_blockers_accumulate(self):
		b = dm.departure_blockers([D(status="Draft", cleared=None)], vet_valid=False)
		self.assertEqual(codes(b), ["declaration_not_cleared", "vet_certificate_missing"])


class MayDepartTest(unittest.TestCase):
	def test_clear(self):
		r = dm.may_depart([D()], vet_valid=True)
		self.assertTrue(r["allowed"])
		self.assertFalse(r["via_override"])

	def test_blocked(self):
		r = dm.may_depart([D(status="Draft", cleared=None)], vet_valid=True)
		self.assertFalse(r["allowed"])
		self.assertEqual(codes(r["blockers"]), ["declaration_not_cleared"])

	def test_override_with_reason_allows_and_still_reports(self):
		r = dm.may_depart([], vet_valid=False, override=True, override_reason="port strike, DG approved")
		self.assertTrue(r["allowed"])
		self.assertTrue(r["via_override"])
		# The blockers stay in the payload — an override records what was
		# overridden, it does not erase it.
		self.assertEqual(codes(r["blockers"]), ["no_required_declaration", "vet_certificate_missing"])

	def test_override_without_reason_is_not_an_override(self):
		for reason in ("", "   ", None):
			with self.subTest(reason=repr(reason)):
				r = dm.may_depart([], vet_valid=True, override=True, override_reason=reason)
				self.assertFalse(r["allowed"])

	def test_override_flag_off_with_reason_present_still_blocks(self):
		r = dm.may_depart([], vet_valid=True, override=False, override_reason="whatever")
		self.assertFalse(r["allowed"])


class TransitionScopeTest(unittest.TestCase):
	def test_only_pending_to_departed_is_gated(self):
		self.assertTrue(dm.gates_this_transition("PENDING", "DEPARTED_IRAN"))

	def test_later_steps_are_not_gated(self):
		for a, b in [
			("DEPARTED_IRAN", "AT_BORDER"),
			("AT_BORDER", "CROSSED_BORDER"),
			("ARRIVED", "UNLOADING"),
			("UNLOADING", "GRN_CREATED"),
		]:
			with self.subTest(t=(a, b)):
				self.assertFalse(dm.gates_this_transition(a, b))

	def test_cancellation_is_not_gated(self):
		self.assertFalse(dm.gates_this_transition("PENDING", "Cancelled"))

	def test_backward_correction_is_not_gated(self):
		self.assertFalse(dm.gates_this_transition("DEPARTED_IRAN", "PENDING"))

	def test_no_previous_status_is_not_gated(self):
		# A brand-new truck saved straight into PENDING is not a departure.
		self.assertFalse(dm.gates_this_transition(None, "PENDING"))


if __name__ == "__main__":
	unittest.main()
