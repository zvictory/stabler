"""Behaviour contracts for the tender intake item lines.

The lines are the tender scope: the RFQ step copies them line by line, so a
line that vanishes on an unrelated save is a tender that quietly changed what
it asks suppliers for. This module is pure on purpose — no Frappe doubles,
because the rules here must not depend on framework behavior at all.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_intake_items -v
"""

from __future__ import annotations

import json
import unittest

from stabler.api._tender_intake_items import (
	INTAKE_ITEM_LIMIT,
	clean_intake_items,
	parse_intake,
	read_intake_items,
	sanitize_intake_items,
)


def _line(**overrides):
	base = {
		"item_code": "RAIL-01",
		"item_name": "Rail 01",
		"qty": 10,
		"uom": "Nos",
		"rate": 2.5,
		"amount": 25.0,
	}
	base.update(overrides)
	return base


class TestSanitizeIntakeItems(unittest.TestCase):
	def test_amount_is_recomputed_server_side(self):
		"""A client-stale amount is a fact that was never true; the pipeline
		totals read amounts as facts."""
		out = sanitize_intake_items([_line(amount=999999.0)])
		self.assertEqual(out[0]["amount"], 25.0)

	def test_lines_without_an_item_are_dropped(self):
		self.assertEqual(sanitize_intake_items([_line(item_code="  "), {"qty": 3}]), [])

	def test_lines_with_non_positive_qty_are_dropped(self):
		"""The drawer filters its own rows, so a broken line arriving here was
		never part of the tender the user saw."""
		self.assertEqual(sanitize_intake_items([_line(qty=0), _line(qty=-2)]), [])

	def test_negative_rates_are_clamped_to_zero(self):
		out = sanitize_intake_items([_line(rate=-5, amount=-50)])
		self.assertEqual(out[0]["rate"], 0.0)
		self.assertEqual(out[0]["amount"], 0.0)

	def test_line_count_is_capped(self):
		lines = [_line(item_code=f"IT-{i}") for i in range(INTAKE_ITEM_LIMIT + 10)]
		self.assertEqual(len(sanitize_intake_items(lines)), INTAKE_ITEM_LIMIT)

	def test_long_strings_are_truncated(self):
		out = sanitize_intake_items([_line(item_name="x" * 500, uom="y" * 100)])
		self.assertEqual(len(out[0]["item_name"]), 140)
		self.assertEqual(len(out[0]["uom"]), 40)

	def test_non_dict_entries_are_ignored(self):
		out = sanitize_intake_items(["nope", 7, None, _line()])
		self.assertEqual(len(out), 1)


class TestCleanIntakeItems(unittest.TestCase):
	def test_absent_key_preserves_the_prior_lines(self):
		"""The PO-control editor saves deadline/checklist fields without item
		lines; an absent key read as 'no items' wiped the tender scope there."""
		prior = [_line()]
		out = clean_intake_items({"buyer": "UZEX", "volume": 1200}, prior)
		self.assertEqual(out, prior)

	def test_none_value_preserves_the_prior_lines(self):
		prior = [_line()]
		out = clean_intake_items({"items": None}, prior)
		self.assertEqual(out, prior)

	def test_present_list_replaces_the_prior_lines(self):
		"""The drawer owns the lines and sends the full set — including the
		empty set after the user removed every row."""
		prior = [_line(item_code="OLD-1")]
		out = clean_intake_items({"items": [_line(item_code="NEW-1")]}, prior)
		self.assertEqual([row["item_code"] for row in out], ["NEW-1"])

	def test_present_empty_list_clears_the_lines(self):
		self.assertEqual(clean_intake_items({"items": []}, [_line()]), [])


class TestReadIntakeItems(unittest.TestCase):
	def test_lines_round_trip_through_the_stored_json(self):
		doc = {"custom_tender_intake": json.dumps({"items": [_line()]})}
		out = read_intake_items(doc)
		self.assertEqual(out[0]["item_code"], "RAIL-01")
		self.assertEqual(out[0]["qty"], 10.0)
		self.assertEqual(out[0]["amount"], 25.0)

	def test_missing_or_damaged_storage_reads_as_no_lines(self):
		for raw in (None, "", "not json", {"items": None}):
			with self.subTest(raw=raw):
				doc = {"custom_tender_intake": raw}
				self.assertEqual(read_intake_items(doc), [])

	def test_stored_lines_are_sanitized_on_the_way_out(self):
		"""An RFQ raised months later must see the same lines the drawer
		captured — the reader re-runs the writer's rules instead of trusting
		that every historical row was clean."""
		doc = {"custom_tender_intake": json.dumps({"items": [_line(qty=-1), _line(amount=1.0)]})}
		out = read_intake_items(doc)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["amount"], 25.0)


class TestParseIntake(unittest.TestCase):
	def test_passthrough_for_dicts_and_json_for_strings(self):
		self.assertEqual(parse_intake({"a": 1}), {"a": 1})
		self.assertEqual(parse_intake('{"a": 1}'), {"a": 1})

	def test_empty_and_damaged_input_reads_as_empty(self):
		for raw in (None, "", "{broken"):
			with self.subTest(raw=raw):
				self.assertEqual(parse_intake(raw), {})


if __name__ == "__main__":
	unittest.main()
