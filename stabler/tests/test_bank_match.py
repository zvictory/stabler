"""Unit tests for the pure bank-reconciliation match scorer (no Frappe)."""
from __future__ import annotations

import unittest
from decimal import Decimal

from stabler.integrations.bank_statement.match import (
	HIGH,
	LOW,
	MEDIUM,
	allocate_partial,
	rank_candidates,
	score_match,
)

BANK = {
	"amount": 5000000,
	"date": "2026-01-15",
	"reference": "123",
	"counterparty_inn": "301654321",
	"description": "Oplata za moloko OOO Postavshchik",
}


class ScoreTest(unittest.TestCase):
	def test_perfect_match_is_high(self):
		cand = {"amount": 5000000, "date": "2026-01-15", "reference": "123",
			"party_inn": "301654321", "party_name": "Postavshchik", "voucher_no": "PE-1"}
		r = score_match(BANK, cand)
		self.assertEqual(r["band"], HIGH)
		self.assertGreaterEqual(r["score"], 80)
		self.assertIn("amount exact", r["reasons"])
		self.assertIn("INN match", r["reasons"])

	def test_amount_mismatch_caps_low(self):
		cand = {"amount": 9999999, "date": "2026-01-15", "reference": "123", "party_inn": "301654321"}
		r = score_match(BANK, cand)
		self.assertEqual(r["band"], LOW)
		self.assertEqual(r["score"], 0)

	def test_amount_and_date_only_is_medium(self):
		cand = {"amount": 5000000, "date": "2026-01-16"}  # exact amount, 1 day off
		r = score_match(BANK, cand)
		self.assertEqual(r["band"], MEDIUM)  # 50 (amount) + 15 (1-3d) = 65
		self.assertGreaterEqual(r["score"], 50)

	def test_date_decay(self):
		near = score_match(BANK, {"amount": 5000000, "date": "2026-01-15"})["score"]
		far = score_match(BANK, {"amount": 5000000, "date": "2026-01-30"})["score"]  # >7d, no date pts
		self.assertGreater(near, far)

	def test_payee_in_description_when_no_inn(self):
		cand = {"amount": 5000000, "date": "2026-01-15", "party_name": "Postavshchik"}
		r = score_match(BANK, cand)
		self.assertIn("payee in purpose", r["reasons"])

	def test_unparseable_dates_dont_crash(self):
		r = score_match({"amount": 100, "date": "bad"}, {"amount": 100, "date": None})
		self.assertEqual(r["reasons"][0] if r["reasons"] else "", "amount exact")


class RankTest(unittest.TestCase):
	def test_best_first(self):
		cands = [
			{"amount": 5000000, "date": "2026-02-20", "voucher_no": "far"},      # exact amt, far date
			{"amount": 5000000, "date": "2026-01-15", "reference": "123",
			 "party_inn": "301654321", "voucher_no": "perfect"},
			{"amount": 4000000, "date": "2026-01-15", "voucher_no": "wrongamt"}, # amount mismatch
		]
		ranked = rank_candidates(BANK, cands)
		self.assertEqual(ranked[0]["voucher_no"], "perfect")
		self.assertEqual(ranked[-1]["voucher_no"], "wrongamt")
		self.assertEqual(ranked[-1]["match_score"], 0)

	def test_empty(self):
		self.assertEqual(rank_candidates(BANK, []), [])


# ---------------------------------------------------------------------------
# Journal Entry candidates
# ---------------------------------------------------------------------------

class JECandidateTest(unittest.TestCase):
	"""The scorer must work identically for JE candidates — voucher_type is
	just metadata; scoring uses amount/date/reference/INN."""

	JE_CAND = {
		"voucher_type": "Journal Entry",
		"voucher_no": "JV-2026-00001",
		"amount": 5000000,
		"date": "2026-01-15",
		"reference": "123",      # cheque_no
		"party_type": "Supplier",
		"party": "SUP-001",
		"party_name": "Postavshchik",
		"party_inn": "301654321",
	}

	def test_je_perfect_match_is_high(self):
		r = score_match(BANK, self.JE_CAND)
		self.assertEqual(r["band"], HIGH)
		self.assertIn("INN match", r["reasons"])

	def test_je_amount_mismatch_caps_low(self):
		bad = dict(self.JE_CAND, amount=1)
		r = score_match(BANK, bad)
		self.assertEqual(r["band"], LOW)
		self.assertEqual(r["score"], 0)

	def test_je_no_inn_falls_back_to_payee_name(self):
		no_inn = dict(self.JE_CAND, party_inn="")
		r = score_match(BANK, no_inn)
		# payee "postavshchik" is in description
		self.assertIn("payee in purpose", r["reasons"])

	def test_rank_candidates_mixes_pe_and_je(self):
		"""JE and PE candidates are scored on the same scale; best floats to top."""
		cands = [
			{"voucher_type": "Payment Entry", "voucher_no": "PE-1",
			 "amount": 5000000, "date": "2026-01-15", "reference": "999",
			 "party_inn": "", "party_name": ""},
			dict(self.JE_CAND),  # perfect
		]
		ranked = rank_candidates(BANK, cands)
		self.assertEqual(ranked[0]["voucher_no"], "JV-2026-00001")

	def test_je_reference_mismatch_does_not_get_ref_points(self):
		bad_ref = dict(self.JE_CAND, reference="WRONG")
		r = score_match(BANK, bad_ref)
		self.assertNotIn("reference match", r["reasons"])


# ---------------------------------------------------------------------------
# INN enrichment
# ---------------------------------------------------------------------------

class INNEnrichmentTest(unittest.TestCase):
	"""Bank line carries an INN; candidates with matching INN score higher
	than ones with only name similarity."""

	BANK_INN = {
		"amount": 1000000,
		"date": "2026-03-10",
		"reference": "",
		"counterparty_inn": "302112233",
		"description": "Uplata OOO Moloko",
	}

	def test_inn_match_beats_name_match(self):
		inn_cand = {"voucher_type": "Payment Entry", "voucher_no": "PE-A",
		            "amount": 1000000, "date": "2026-03-10",
		            "party_inn": "302112233", "party_name": "Moloko"}
		name_cand = {"voucher_type": "Payment Entry", "voucher_no": "PE-B",
		             "amount": 1000000, "date": "2026-03-10",
		             "party_inn": "", "party_name": "Moloko"}
		r_inn = score_match(self.BANK_INN, inn_cand)
		r_name = score_match(self.BANK_INN, name_cand)
		self.assertIn("INN match", r_inn["reasons"])
		self.assertIn("payee in purpose", r_name["reasons"])
		self.assertGreater(r_inn["score"], r_name["score"])

	def test_wrong_inn_does_not_get_inn_points(self):
		wrong_inn = {"voucher_type": "Payment Entry", "voucher_no": "PE-C",
		             "amount": 1000000, "date": "2026-03-10",
		             "party_inn": "999999999", "party_name": "SomeCo"}
		r = score_match(self.BANK_INN, wrong_inn)
		self.assertNotIn("INN match", r["reasons"])

	def test_bank_line_without_inn_uses_name_fallback(self):
		bank_no_inn = dict(self.BANK_INN, counterparty_inn="")
		cand = {"amount": 1000000, "date": "2026-03-10",
		        "party_inn": "302112233", "party_name": "Moloko"}
		r = score_match(bank_no_inn, cand)
		# INN can't match because bank line has no INN.
		self.assertNotIn("INN match", r["reasons"])
		# Name "moloko" is in description "uplata ooo moloko"
		self.assertIn("payee in purpose", r["reasons"])


# ---------------------------------------------------------------------------
# Partial allocation
# ---------------------------------------------------------------------------

class AllocatePartialTest(unittest.TestCase):
	"""allocate_partial must sum exactly to total with no residual."""

	def _sum(self, allocs: list[str]) -> Decimal:
		return sum(Decimal(a) for a in allocs)

	def test_single_voucher_gets_whole_amount(self):
		allocs = allocate_partial(1000, [1000])
		self.assertEqual(len(allocs), 1)
		self.assertEqual(self._sum(allocs), Decimal("1000"))

	def test_two_equal_vouchers_split_evenly(self):
		allocs = allocate_partial(1000, [500, 500], precision=2)
		self.assertEqual(self._sum(allocs), Decimal("1000"))
		self.assertEqual(allocs[0], allocs[1])

	def test_three_vouchers_sum_exact(self):
		# 1000 / 3 = 333.33…  — last absorbs residual
		allocs = allocate_partial(1000, [333, 333, 334], precision=2)
		self.assertEqual(self._sum(allocs), Decimal("1000"))
		self.assertEqual(len(allocs), 3)

	def test_uzs_precision_zero(self):
		"""UZS has no fractional part — precision=0, amounts are whole."""
		allocs = allocate_partial(5000000, [2000000, 3000000], precision=0)
		self.assertEqual(self._sum(allocs), Decimal("5000000"))
		for a in allocs:
			self.assertNotIn(".", a)

	def test_residual_goes_to_last(self):
		"""10 / 3 can't split without residual; last item absorbs it."""
		allocs = allocate_partial(10, [1, 1, 1], precision=2)
		total = self._sum(allocs)
		self.assertEqual(total, Decimal("10"))
		# Last item should be >= others
		self.assertGreaterEqual(Decimal(allocs[-1]), Decimal(allocs[0]))

	def test_zero_amount_voucher_gets_zero(self):
		allocs = allocate_partial(100, [0, 100], precision=2)
		self.assertEqual(Decimal(allocs[0]), Decimal("0"))
		self.assertEqual(self._sum(allocs), Decimal("100"))

	def test_all_zero_amounts_last_gets_total(self):
		allocs = allocate_partial(500, [0, 0, 0], precision=2)
		self.assertEqual(self._sum(allocs), Decimal("500"))
		self.assertEqual(Decimal(allocs[-1]), Decimal("500"))

	def test_string_total_accepted(self):
		allocs = allocate_partial("250.75", [100, 150], precision=2)
		self.assertEqual(self._sum(allocs), Decimal("250.75"))

	def test_negative_total_raises(self):
		with self.assertRaises(ValueError):
			allocate_partial(-100, [100])

	def test_empty_vouchers_raises(self):
		with self.assertRaises(ValueError):
			allocate_partial(100, [])

	def test_large_uzs_amounts_no_drift(self):
		"""Simulate a 25 000 000 сўм bank line split across 4 vouchers."""
		total = 25_000_000
		vamts = [6_000_000, 7_500_000, 8_000_000, 3_500_000]
		allocs = allocate_partial(total, vamts, precision=0)
		self.assertEqual(self._sum(allocs), Decimal(str(total)))

	def test_proportional_split(self):
		"""Verify proportions are approximately correct (not just summing right)."""
		allocs = allocate_partial(1000, [1, 3], precision=2)
		# 1/(1+3)=25%, 3/(1+3)=75%
		self.assertAlmostEqual(float(allocs[0]), 250.0, delta=1.0)
		self.assertAlmostEqual(float(allocs[1]), 750.0, delta=1.0)
		self.assertEqual(self._sum(allocs), Decimal("1000"))


if __name__ == "__main__":
	unittest.main()
