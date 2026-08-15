"""Unit tests for the customs-declaration (GTD) precedence in the LCV build.

A cleared GTD's duty + excise REPLACE any cost-line "Uzbekistan Customs Duty"
(no double count); VAT is never added; Iran-side duty is untouched; a warning is
raised only when both a cost-line Uzbek duty and a cleared GTD are present.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_lcv_gtd_precedence -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import lcv_math


class TestIsUzbekistanCustomsDuty(unittest.TestCase):
	def test_matches_uzbek_duty(self):
		self.assertTrue(lcv_math.is_uzbekistan_customs_duty("Uzbekistan Customs Duty"))
		self.assertTrue(lcv_math.is_uzbekistan_customs_duty("uzbek customs duty"))

	def test_does_not_match_iran_duty(self):
		self.assertFalse(lcv_math.is_uzbekistan_customs_duty("Iran Customs Duty"))

	def test_does_not_match_other(self):
		self.assertFalse(lcv_math.is_uzbekistan_customs_duty("Freight"))


class TestApplyGtdPrecedence(unittest.TestCase):
	def test_no_gtd_is_passthrough(self):
		components = {"Freight": 100.0, "Uzbekistan Customs Duty": 2_000_000.0}
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			components, gtd_duty=0, gtd_excise=0, gtd_present=False
		)
		self.assertEqual(out, components)
		self.assertEqual(warnings, [])
		# The passthrough must be a copy, not the same object.
		self.assertIsNot(out, components)

	def test_gtd_replaces_cost_line_uzbek_duty(self):
		components = {"Freight": 100.0, "Uzbekistan Customs Duty": 2_000_000.0}
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			components, gtd_duty=2_500_000, gtd_excise=0, gtd_present=True
		)
		self.assertEqual(out["Uzbekistan Customs Duty"], 2_500_000.0)  # GTD value, not 2,000,000
		self.assertEqual(out["Freight"], 100.0)
		self.assertEqual(len(warnings), 1)  # both sources present

	def test_gtd_adds_excise_component(self):
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 100.0}, gtd_duty=1_000_000, gtd_excise=300_000, gtd_present=True
		)
		self.assertEqual(out["Uzbekistan Customs Duty"], 1_000_000.0)
		self.assertEqual(out["Uzbekistan Excise"], 300_000.0)
		self.assertEqual(warnings, [])  # no cost-line duty was present

	def test_no_warning_when_only_gtd(self):
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 100.0, "Iran Customs Duty": 50.0},
			gtd_duty=1_000_000,
			gtd_excise=0,
			gtd_present=True,
		)
		self.assertEqual(warnings, [])
		self.assertEqual(out["Iran Customs Duty"], 50.0)  # Iran duty untouched
		self.assertEqual(out["Uzbekistan Customs Duty"], 1_000_000.0)

	def test_zero_gtd_duty_drops_uzbek_line_without_adding(self):
		# A cleared GTD with 0 duty still supersedes the cost-line Uzbek duty.
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{"Uzbekistan Customs Duty": 2_000_000.0}, gtd_duty=0, gtd_excise=0, gtd_present=True
		)
		self.assertNotIn("Uzbekistan Customs Duty", out)
		self.assertEqual(len(warnings), 1)

	def test_vat_never_added_from_gtd(self):
		# The function only ever emits duty/excise keys — never a VAT key.
		out, _ = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 100.0}, gtd_duty=1_000_000, gtd_excise=200_000, gtd_present=True
		)
		self.assertFalse(any(lcv_math.is_vat_component(k) for k in out))


class TestGtdPrecedenceNetsWhatIsAlreadyCapitalized(unittest.TestCase):
	"""A declaration is a standing figure, not a document that arrives once.

	Cost lines carry an ``lcv_ref`` stamp, so a second build simply cannot see
	them again. The GTD has no such stamp: every build re-reads the same cleared
	declaration. The question a second voucher has to answer is therefore not
	"what does the declaration say" but "what does it say that stock valuation
	does not already carry" — answering the first one capitalizes the duty twice,
	permanently, through a submitted voucher.
	"""

	def test_a_fully_capitalized_declaration_adds_nothing(self):
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{},
			gtd_duty=74_500_000,
			gtd_excise=9_000_000,
			gtd_present=True,
			capitalized={"Uzbekistan Customs Duty": 74_500_000, "Uzbekistan Excise": 9_000_000},
		)
		self.assertEqual(out, {})
		# Silence would read as "the declaration was ignored". One line per
		# component, so the empty preview is explained rather than merely empty.
		self.assertEqual(len(warnings), 2)

	def test_an_amended_declaration_adds_only_the_difference(self):
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{},
			gtd_duty=80_000_000,
			gtd_excise=0,
			gtd_present=True,
			capitalized={"Uzbekistan Customs Duty": 74_500_000},
		)
		self.assertEqual(out, {"Uzbekistan Customs Duty": 5_500_000.0})
		self.assertIn("5,500,000.00", warnings[0])

	def test_a_declaration_below_what_was_capitalized_is_never_negative(self):
		# A negative charge on a Landed Cost Voucher writes a negative valuation
		# adjustment into the stock ledger of every receipt line. Correcting an
		# over-capitalization means cancelling the voucher that caused it, which
		# is a decision with a GL reversal behind it — not one to take silently.
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{},
			gtd_duty=60_000_000,
			gtd_excise=0,
			gtd_present=True,
			capitalized={"Uzbekistan Customs Duty": 74_500_000},
		)
		self.assertEqual(out, {})
		self.assertEqual(len(warnings), 1)
		self.assertIn("cancel", warnings[0].lower())

	def test_a_capitalized_cost_line_duty_leaves_the_declarations_delta(self):
		# Voucher #1 ran before the declaration cleared and capitalized the
		# operator's 60,000,000 estimate. The declaration then says 74,500,000:
		# the import owes 14,500,000 more, not 74,500,000 more.
		out, _ = lcv_math.apply_gtd_customs_precedence(
			{},
			gtd_duty=74_500_000,
			gtd_excise=0,
			gtd_present=True,
			capitalized={"Uzbekistan Customs Duty": 60_000_000},
		)
		self.assertEqual(out, {"Uzbekistan Customs Duty": 14_500_000.0})

	def test_the_first_voucher_carries_the_whole_declaration(self):
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 100.0},
			gtd_duty=1_000_000,
			gtd_excise=300_000,
			gtd_present=True,
			capitalized={},
		)
		self.assertEqual(out["Uzbekistan Customs Duty"], 1_000_000.0)
		self.assertEqual(out["Uzbekistan Excise"], 300_000.0)
		self.assertEqual(warnings, [])

	def test_only_the_declarations_own_components_are_netted(self):
		# Freight already capitalized is handled by the ``lcv_ref`` stamp on the
		# cost line. Netting it here as well would swallow a second, genuinely
		# new freight cost of the same size.
		out, _ = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 500.0},
			gtd_duty=0,
			gtd_excise=0,
			gtd_present=True,
			capitalized={"Freight": 500.0},
		)
		self.assertEqual(out["Freight"], 500.0)


class TestTheGuardDoesNotFailOpen(unittest.TestCase):
	"""Three ways the netting could hand back MORE than the declaration.

	Every branch below guards a case where the answer is not merely wrong but
	wrong in the expensive direction: it capitalizes customs money into stock
	valuation a second time, through a submitted voucher, silently. A guard that
	fails open is worse than no guard, because the operator stops looking.
	"""

	def test_a_negative_already_capitalized_never_inflates_the_offer(self):
		"""stabler-yw1. ``amount`` on a charge row has no non-negative validation.

		A negative charge row — or two rows summing negative — made ``already``
		negative, and ``remaining = declared - already`` then came out ABOVE the
		declaration. Measured before the fix: declared 100, capitalized -50,
		offered 150, no warning. The old branches all tested ``already > 0``, so a
		negative fell through every one of them into the plain add.
		"""
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{},
			gtd_duty=100,
			gtd_excise=0,
			gtd_present=True,
			capitalized={"Uzbekistan Customs Duty": -50},
		)
		self.assertLessEqual(
			out.get("Uzbekistan Customs Duty", 0.0),
			100.0,
			"never offer more than the declaration itself",
		)
		self.assertEqual(out.get("Uzbekistan Customs Duty"), 100.0)
		self.assertTrue(warnings, "a negative capitalized figure must not pass silently")

	def test_a_description_that_differs_only_in_case_or_spacing_still_nets(self):
		"""stabler-j8a. The key is a free-text field an accountant can edit.

		``capitalized_components`` keys on the charge row's ``description``, which
		is editable Small Text on the voucher. Lowercase it, or let a stray space
		in, and an exact match scored ``already = 0`` and offered the whole
		declaration again — the precise failure this whole function exists to
		prevent, reachable by editing one text box.
		"""
		for variant in (
			"uzbekistan customs duty",
			"UZBEKISTAN CUSTOMS DUTY",
			"  Uzbekistan  Customs Duty  ",
		):
			with self.subTest(variant=variant):
				out, _ = lcv_math.apply_gtd_customs_precedence(
					{},
					gtd_duty=100,
					gtd_excise=0,
					gtd_present=True,
					capitalized={variant: 100},
				)
				self.assertEqual(
					out,
					{},
					f"{variant!r} names the same component and must net against it",
				)

	def test_a_component_that_merely_starts_the_same_is_not_netted(self):
		"""The normalization must not over-match, or it swallows a real charge.

		"Uzbekistan Customs Duty Penalty" is a different charge. Netting it would
		be the opposite failure: a genuinely new cost silently dropped.
		"""
		out, _ = lcv_math.apply_gtd_customs_precedence(
			{},
			gtd_duty=100,
			gtd_excise=0,
			gtd_present=True,
			capitalized={"Uzbekistan Customs Duty Penalty": 100},
		)
		self.assertEqual(out.get("Uzbekistan Customs Duty"), 100.0)


if __name__ == "__main__":
	unittest.main()
