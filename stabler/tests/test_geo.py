"""Unit tests for the pure geo helpers (no frappe, no DB)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.api._geo import GeoError, norm_key, parse_coord_pair, resolve_bulk, to_number


class TestToNumber(unittest.TestCase):
	def test_float_and_int(self):
		self.assertEqual(to_number(41.31), 41.31)
		self.assertEqual(to_number(69), 69.0)

	def test_comma_decimal(self):
		self.assertEqual(to_number("41,3111"), 41.3111)

	def test_dot_decimal_with_spaces(self):
		self.assertEqual(to_number(" 69.2797 "), 69.2797)

	def test_empty_raises(self):
		with self.assertRaises(GeoError):
			to_number("")

	def test_garbage_raises(self):
		with self.assertRaises(GeoError):
			to_number("abc")


class TestParsePair(unittest.TestCase):
	def test_valid(self):
		self.assertEqual(parse_coord_pair(41.3111, 69.2797), (41.3111, 69.2797))

	def test_rounds_to_7dp(self):
		lat, lng = parse_coord_pair(41.123456789, 69.987654321)
		self.assertEqual(lat, 41.1234568)
		self.assertEqual(lng, 69.9876543)

	def test_lat_out_of_range(self):
		with self.assertRaises(GeoError):
			parse_coord_pair(91, 69)

	def test_lng_out_of_range(self):
		with self.assertRaises(GeoError):
			parse_coord_pair(41, 181)

	def test_zero_island_rejected(self):
		with self.assertRaises(GeoError):
			parse_coord_pair(0, 0)


class TestResolveBulk(unittest.TestCase):
	def setUp(self):
		self.by_name = {norm_key("OUT-001"): "OUT-001", norm_key("OUT-002"): "OUT-002"}
		self.by_code = {norm_key("PB01"): "OUT-001", norm_key("LC02"): "OUT-002"}
		self.by_oname = {norm_key("Pizza Bella"): "OUT-001", norm_key("Lola Cafe"): "OUT-002"}

	def _resolve(self, rows):
		return resolve_bulk(rows, self.by_name, self.by_code, self.by_oname)

	def test_match_by_code_and_name(self):
		updates, errors = self._resolve(
			[
				{"outlet_code": "PB01", "lat": 41.31, "lng": 69.27},
				{"outlet_name": "Lola Cafe", "lat": "41,33", "lng": "69,29"},
			]
		)
		self.assertEqual(errors, [])
		self.assertEqual(len(updates), 2)
		got = {u["outlet"]: (u["lat"], u["lng"]) for u in updates}
		self.assertEqual(got["OUT-001"], (41.31, 69.27))
		self.assertEqual(got["OUT-002"], (41.33, 69.29))

	def test_unknown_outlet_errors(self):
		updates, errors = self._resolve([{"outlet": "NOPE", "lat": 41, "lng": 69}])
		self.assertEqual(updates, [])
		self.assertEqual(len(errors), 1)
		self.assertIn("not found", errors[0]["reason"])

	def test_bad_coord_errors_but_keeps_others(self):
		updates, errors = self._resolve(
			[
				{"outlet": "OUT-001", "lat": 999, "lng": 69},
				{"outlet": "OUT-002", "lat": 41.33, "lng": 69.29},
			]
		)
		self.assertEqual(len(updates), 1)
		self.assertEqual(updates[0]["outlet"], "OUT-002")
		self.assertEqual(len(errors), 1)
		self.assertEqual(errors[0]["row"], 1)

	def test_missing_identifier(self):
		updates, errors = self._resolve([{"lat": 41, "lng": 69}])
		self.assertEqual(updates, [])
		self.assertIn("identifier", errors[0]["reason"])

	def test_duplicate_identifier_last_wins(self):
		updates, errors = self._resolve(
			[
				{"outlet": "OUT-001", "lat": 41.10, "lng": 69.10},
				{"outlet": "OUT-001", "lat": 41.20, "lng": 69.20},
			]
		)
		self.assertEqual(errors, [])
		self.assertEqual(len(updates), 1)
		self.assertEqual((updates[0]["lat"], updates[0]["lng"]), (41.20, 69.20))


if __name__ == "__main__":
	unittest.main()
