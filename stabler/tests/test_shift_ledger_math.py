"""Which stop the shift ledger names, out of everything that stopped.

The strip has room for one line of context under the downtime figure — the
design writes it as `Простой 42 мин · Линия 2 · мойка фризера`. Choosing what
goes there is the whole of this module, and the obvious implementation is the
wrong one: picking the single longest stop names a 12-minute changeover over a
line that lost 40 minutes in eight short ones. What a supervisor needs is the
line and reason that cost the most time in total.

Frappe-free on purpose — this is arithmetic over rows, and it lands in
`make check` rather than only in the bench run.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_shift_ledger_math -v
"""

from __future__ import annotations

import unittest

from stabler.api._shift_ledger import top_stop_contributor


def stop(line, reason, minutes):
	return {"line": line, "reason": reason, "minutes": minutes}


class TestTheLedgerNamesWhatCostTheMostTime(unittest.TestCase):
	def test_nothing_stopped_names_nothing(self):
		"""`None`, not a zero row: the strip renders the context line only when
		there is one, and a row reading `— · — · 0 мин` is furniture."""
		self.assertIsNone(top_stop_contributor([]))
		self.assertIsNone(top_stop_contributor(None))

	def test_one_stop_is_its_own_answer(self):
		self.assertEqual(
			top_stop_contributor([stop("Line 2", "Freezer wash", 42)]),
			{"line": "Line 2", "reason": "Freezer wash", "minutes": 42.0},
		)

	def test_many_short_stops_outweigh_one_long_one(self):
		"""The case the obvious implementation gets wrong. Eight four-minute
		stops on one line are a line that is not running; a single twelve-minute
		changeover on another is a line that is. Naming the changeover sends the
		supervisor to the wrong machine."""
		rows = [stop("Line 1", "Film jam", 4) for _ in range(8)]
		rows.append(stop("Line 3", "Changeover", 12))
		self.assertEqual(
			top_stop_contributor(rows),
			{"line": "Line 1", "reason": "Film jam", "minutes": 32.0},
		)

	def test_the_same_line_with_two_reasons_is_two_answers(self):
		"""Grouped by line AND reason, never by line alone. "Line 2 lost 50
		minutes" is true and useless; the reason is what somebody can act on."""
		rows = [
			stop("Line 2", "Freezer wash", 20),
			stop("Line 2", "No film", 30),
		]
		self.assertEqual(
			top_stop_contributor(rows),
			{"line": "Line 2", "reason": "No film", "minutes": 30.0},
		)

	def test_a_stop_with_no_reason_still_counts_its_minutes(self):
		"""`reason` is optional on rows written before the catalogue existed, and
		dropping them would make the ledger's total disagree with the sum of the
		stop log — the one comparison anybody checking this number will make."""
		rows = [stop("Line 1", None, 25), stop("Line 1", "Film jam", 10)]
		top = top_stop_contributor(rows)
		self.assertEqual(top["line"], "Line 1")
		self.assertEqual(top["minutes"], 25.0)
		self.assertIsNone(top["reason"])

	def test_missing_or_unparseable_minutes_are_read_as_zero(self):
		"""`minutes` is not a required field — a stop still open has none. It
		must not raise, and it must not win."""
		rows = [stop("Line 1", "Open stop", None), stop("Line 2", "Film jam", 5)]
		self.assertEqual(top_stop_contributor(rows)["line"], "Line 2")

	def test_a_tie_is_broken_the_same_way_every_time(self):
		"""Two lines that lost the same minutes must not make the tile flicker
		between page loads. Ties settle on the name, which is stable."""
		rows = [stop("Line 9", "A", 10), stop("Line 1", "B", 10)]
		first = top_stop_contributor(rows)
		self.assertEqual(first, top_stop_contributor(list(reversed(rows))))
		self.assertEqual(first["line"], "Line 1")

	def test_a_row_with_no_line_is_not_a_contributor(self):
		"""`line` is required on the doctype, so a blank one is corrupt data
		rather than a case to model. It is dropped instead of being named as
		an empty line the supervisor cannot walk to."""
		rows = [stop("", "Ghost", 99), stop("Line 4", "Film jam", 3)]
		self.assertEqual(top_stop_contributor(rows)["line"], "Line 4")


if __name__ == "__main__":
	unittest.main()
