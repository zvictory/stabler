"""An unconfirmed finish, kept where it survives the person who typed it.

The finish dialog is the end of a shift: somebody walked the pallet, counted the
good boxes and the rejects, and typed the result. Holding that in component state
means a locked tablet or a badge-out throws away work that has already been done
in the physical world, and cannot be redone without walking the pallet again.

So it lives on the Work Order. These tests cover the part that does not need a
database — what gets written, what comes back, and the two ways a draft can lie:
by disappearing when the count is legitimately zero, and by carrying an author or
a timestamp that the caller chose.

No bench and no DB, which is why this file is in the push gate.
"""

from __future__ import annotations

import unittest

from stabler.api.manufacturing import _decode_finish_draft, _encode_finish_draft


class TestFinishDraftRoundTrip(unittest.TestCase):
	@staticmethod
	def _row(payload, at="2026-08-25 18:40:00", by="packer@x.uz"):
		return {
			"custom_finish_draft": payload,
			"custom_finish_draft_at": at,
			"custom_finish_draft_by": by,
		}

	def test_the_numbers_come_back_as_numbers(self):
		"""They go straight into number inputs. A string reads as 0 in some browsers
		and concatenates in others, and either way the operator confirms a count
		they never typed."""
		draft = _decode_finish_draft(self._row(_encode_finish_draft(produced_qty=180, scrap_qty=4)))
		self.assertEqual(draft["produced_qty"], 180.0)
		self.assertEqual(draft["scrap_qty"], 4.0)
		self.assertIsInstance(draft["produced_qty"], float)

	def test_numbers_are_coerced_on_the_way_out_not_just_on_the_way_in(self):
		"""The encoder already converts, so a round trip never exercises this — which
		is exactly why it needs its own test. The decoder's contract is "you get
		numbers", and it has to hold for a payload the encoder did not write: an
		older schema, a console write, a System Manager editing past the read_only
		flag. A string here reaches a number input and confirms a count nobody typed.
		"""
		draft = _decode_finish_draft(self._row('{"produced_qty": "180", "scrap_qty": "4"}'))
		self.assertEqual(draft["produced_qty"], 180.0)
		self.assertEqual(draft["scrap_qty"], 4.0)
		self.assertIsInstance(draft["produced_qty"], float)
		self.assertIsInstance(draft["scrap_qty"], float)

	def test_a_zero_count_is_still_a_draft(self):
		"""Nothing good and forty rejects is a real thing to report, and it is the
		shift you least want to make somebody count twice. Treated as "no draft" it
		vanishes on the walk back to the tablet."""
		draft = _decode_finish_draft(self._row(_encode_finish_draft(produced_qty=0, scrap_qty=40)))
		self.assertIsNotNone(draft)
		self.assertEqual(draft["produced_qty"], 0.0)
		self.assertEqual(draft["scrap_qty"], 40.0)

	def test_the_batch_details_survive_too(self):
		payload = _encode_finish_draft(
			produced_qty=10,
			scrap_qty=0,
			batch_no="ICE-20260825",
			mfg_date="2026-08-25",
			expiry_date="2027-02-25",
		)
		draft = _decode_finish_draft(self._row(payload))
		self.assertEqual(draft["batch_no"], "ICE-20260825")
		self.assertEqual(draft["mfg_date"], "2026-08-25")
		self.assertEqual(draft["expiry_date"], "2027-02-25")

	def test_the_author_and_the_time_come_from_the_row_not_the_payload(self):
		"""One order has two operators, so "whose count is this" decides whether the
		person reading it confirms or re-counts. Taken from inside the JSON it would
		be whatever the caller sent — the server writes those columns itself, and
		decoding must read them from there even when the payload disagrees.
		"""
		forged = '{"produced_qty": 5, "saved_by": "someone-else@x.uz", "saved_at": "1999-01-01 00:00:00"}'
		draft = _decode_finish_draft(self._row(forged, at="2026-08-25 18:40:00", by="packer@x.uz"))
		self.assertEqual(draft["saved_by"], "packer@x.uz")
		self.assertEqual(draft["saved_at"], "2026-08-25 18:40:00")

	def test_an_empty_field_is_no_draft(self):
		for empty in (None, "", "   "):
			self.assertIsNone(_decode_finish_draft(self._row(empty)))

	def test_an_unreadable_draft_is_no_draft_rather_than_an_error(self):
		"""The field is editable in Desk and outlives schema changes. One row somebody
		typed into by hand must not take the kiosk down for the whole shift — an
		operator cannot fix JSON, and losing one draft beats losing the screen."""
		for junk in ("{not json", "[]", '"a string"', "null", "42"):
			self.assertIsNone(_decode_finish_draft(self._row(junk)), junk)

	def test_a_row_without_the_columns_has_no_draft(self):
		"""Between a code deploy and the migrate behind it the columns do not exist.
		The kiosk keeps working without draft support rather than 500ing."""
		self.assertIsNone(_decode_finish_draft({}))
