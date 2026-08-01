"""PI Group report bucketing — pure, no site required."""

import unittest
from typing import ClassVar

from stabler.api import _pi_group_report as pgr


class BucketMapTest(unittest.TestCase):
	SPEC: ClassVar[dict[str, list[str]]] = {
		"ORIGIN": ["BOOKED", "STUFFED", "GATE_IN"],
		"TRANSIT": ["ON_BOARD", "IN_TRANSIT", "DISCHARGED"],
		"DESTINATION": ["AVAILABLE", "ARRIVED_AT_IRAN"],
		"DELIVERED": ["DELIVERED_TO_UZBEKISTAN"],
	}

	def test_map_matches_the_msaerp_spec_exactly(self):
		for bucket, statuses in self.SPEC.items():
			for st in statuses:
				with self.subTest(status=st):
					self.assertEqual(pgr.bucket_of(st), bucket)

	def test_every_pipeline_status_lands_in_exactly_one_bucket(self):
		# The whole 9-status sea pipeline is covered — nothing silently dropped.
		from stabler.stabler.imports_module.sea_lifecycle import SEA_PIPELINE

		for st in SEA_PIPELINE:
			with self.subTest(status=st):
				self.assertIsNotNone(pgr.bucket_of(st), f"{st} maps to no bucket")

	def test_cancelled_is_out_of_the_journey(self):
		self.assertIsNone(pgr.bucket_of("Cancelled"))
		self.assertIsNone(pgr.bucket_of("CANCELLED"))

	def test_unknown_status_is_none_not_a_guess(self):
		for st in ("", None, "CUSTOMS_CLEARANCE", "RELEASED", "DRAFT", "CLOSED"):
			with self.subTest(status=st):
				self.assertIsNone(pgr.bucket_of(st))


class TallyTest(unittest.TestCase):
	def test_total_equals_sum_of_buckets(self):
		# The invariant the report's arithmetic depends on: cancelled/unknown
		# rows are excluded from buckets AND total, so the row always adds up.
		out = pgr.tally(["BOOKED", "ON_BOARD", "Cancelled", "AVAILABLE", "WAT"])
		self.assertEqual(out["total"], sum(out["counts"].values()))
		self.assertEqual(out["total"], 3)

	def test_amounts_fold_through_the_same_map(self):
		out = pgr.tally(
			["BOOKED", "ON_BOARD", "Cancelled", "DELIVERED_TO_UZBEKISTAN"],
			[100.0, 250.0, 999.0, 50.0],
		)
		self.assertEqual(out["amounts"]["ORIGIN"], 100.0)
		self.assertEqual(out["amounts"]["TRANSIT"], 250.0)
		self.assertEqual(out["amounts"]["DELIVERED"], 50.0)
		# The cancelled CI's 999 must not inflate the shipped value.
		self.assertEqual(out["amount_total"], 400.0)


class PendingTest(unittest.TestCase):
	def test_formulas_match_the_spec(self):
		self.assertEqual(pgr.pending_containers(10, 6), 4.0)
		self.assertEqual(pgr.pending_containers(10, 6, cro_count=1), 3.0)
		self.assertEqual(pgr.pending_amount(1000.0, 600.0), 400.0)

	def test_negative_pending_is_shown_not_clamped(self):
		# Over-shipment is a data signal, not a rendering inconvenience.
		self.assertEqual(pgr.pending_containers(4, 6), -2.0)
		self.assertEqual(pgr.pending_amount(500.0, 800.0), -300.0)

	def test_none_inputs_degrade_to_zero(self):
		self.assertEqual(pgr.pending_containers(None, None), 0.0)
		self.assertEqual(pgr.pending_amount(None, None), 0.0)


if __name__ == "__main__":
	unittest.main()
