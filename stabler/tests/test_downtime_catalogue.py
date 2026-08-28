"""The stop log's arithmetic, and the catalogue's promise to be readable.

Measured on anjan 2026-08-28, read-only, and it is the whole reason this module
exists: 0 Downtime Entry rows, 0 Work Orders carrying `process_loss_qty`, 0
carrying a `scrap_warehouse`, 0 `BOM Scrap Item` rows and 0 Stock Entry rows
flagged `is_scrap_item` — against 3757 Manufacture entries. Nothing has ever
been recorded about why a line stopped or what it lost.

The reason the seed list is tested rather than just written: a catalogue is only
worth having if the operator recognises the words. Every seeded reason is
therefore pinned to exist in all five translation catalogues, because a reason
that renders in English on an Uzbek kiosk is a reason the operator scrolls past
on the way to "Other" — and a catalogue whose most-used entry is "Other" has
stopped being a catalogue.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_downtime_catalogue -v
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from stabler.api._downtime import (
	MAX_STOP_MINUTES,
	REASON_KINDS,
	SEED_REASONS,
	stop_minutes,
	validate_stop,
)

_TRANSLATIONS = Path(__file__).resolve().parents[1] / "translations"
_LANGUAGES = ("en", "ru", "uz", "uzc", "tr")


def _catalogue(lang: str) -> dict:
	with (_TRANSLATIONS / f"{lang}.csv").open(encoding="utf-8", newline="") as fh:
		reader = csv.reader(fh)
		next(reader, None)
		return {row[0]: row[1] for row in reader if len(row) >= 2}


class TestAStopIsMeasuredInMinutes(unittest.TestCase):
	def test_a_quarter_hour_reads_as_fifteen(self):
		self.assertEqual(stop_minutes("2026-08-28 09:00:00", "2026-08-28 09:15:00"), 15.0)

	def test_a_stop_across_midnight_is_still_measured(self):
		"""Night shifts run here — orders are opened as late as 23:00. A helper
		that subtracted clock times instead of stamps would return a negative
		number for the one shift nobody is watching."""
		self.assertEqual(stop_minutes("2026-08-28 23:40:00", "2026-08-29 00:10:00"), 30.0)

	def test_seconds_are_kept_to_one_decimal(self):
		self.assertEqual(stop_minutes("2026-08-28 09:00:00", "2026-08-28 09:00:30"), 0.5)


class TestTheDisplayHelperNeverBlowsUpAScreen(unittest.TestCase):
	"""`stop_minutes` renders beside a row the database has already accepted.
	Raising there turns one bad row into a blank page, which is why the refusal
	lives in `validate_stop` instead."""

	def test_a_missing_stamp_reads_as_zero(self):
		self.assertEqual(stop_minutes(None, "2026-08-28 09:15:00"), 0.0)
		self.assertEqual(stop_minutes("2026-08-28 09:00:00", None), 0.0)

	def test_a_backwards_pair_reads_as_zero_rather_than_negative(self):
		"""A negative duration would be summed into a shift total and quietly
		shorten it — the one arithmetic error that makes downtime look better."""
		self.assertEqual(stop_minutes("2026-08-28 09:15:00", "2026-08-28 09:00:00"), 0.0)

	def test_garbage_reads_as_zero(self):
		self.assertEqual(stop_minutes("dun aksam", "2026-08-28 09:00:00"), 0.0)


class TestWhatMayBeWritten(unittest.TestCase):
	def test_an_ordinary_stop_is_accepted(self):
		allowed, reason = validate_stop("2026-08-28 09:00:00", "2026-08-28 09:35:00")
		self.assertTrue(allowed)
		self.assertEqual(reason, "")

	def test_a_stop_that_ends_before_it_starts_is_refused(self):
		self.assertEqual(
			validate_stop("2026-08-28 09:15:00", "2026-08-28 09:00:00")[1], "ends_before_it_starts"
		)

	def test_a_zero_length_stop_is_refused(self):
		"""The double-tap. Recorded, it adds a stop to the count while adding no
		minutes — which is exactly how a "stops per shift" figure goes wrong in
		the direction nobody checks."""
		self.assertEqual(validate_stop("2026-08-28 09:00:00", "2026-08-28 09:00:00")[1], "zero_length")

	def test_a_stop_longer_than_a_shift_is_refused(self):
		"""The forgotten timer: opened before going home, closed the next
		morning. That single row outweighs a month of real stops in any total."""
		self.assertEqual(validate_stop("2026-08-28 06:00:00", "2026-08-29 06:00:00")[1], "too_long")

	def test_the_boundary_itself_is_still_a_stop(self):
		self.assertTrue(validate_stop("2026-08-28 06:00:00", "2026-08-28 18:00:00")[0])
		self.assertEqual(MAX_STOP_MINUTES, 12 * 60)

	def test_both_missing_stamps_are_named_separately(self):
		"""The kiosk puts the message under a field, so it has to know which."""
		self.assertEqual(validate_stop(None, "2026-08-28 09:00:00")[1], "missing_start")
		self.assertEqual(validate_stop("2026-08-28 09:00:00", None)[1], "missing_end")


class TestTheCatalogueIsUsableBeforeItIsCorrect(unittest.TestCase):
	"""This list is a draft written to be corrected, not a claim about this
	factory. What is pinned is the part a wrong draft still has to get right."""

	def test_no_reason_is_listed_twice(self):
		names = [reason for reason, _kind in SEED_REASONS]
		self.assertEqual(len(names), len(set(names)))

	def test_every_reason_declares_which_question_it_answers(self):
		"""A line waiting on material is a stop and never a loss; a batch that
		came out off-spec is a loss and not necessarily a stop. Collapsing the
		two would put half the list in front of an operator answering the other
		question."""
		for reason, kind in SEED_REASONS:
			with self.subTest(reason=reason):
				self.assertIn(kind, REASON_KINDS)

	def test_both_questions_have_real_answers(self):
		"""A catalogue with one loss reason and eighteen stop reasons is a stop
		catalogue with a loss field bolted on, and the loss half would be logged
		as "Other" from day one."""
		for kind in ("Downtime", "Loss"):
			usable = [r for r, k in SEED_REASONS if k in (kind, "Both")]
			self.assertGreaterEqual(len(usable), 5, f"{kind}: {usable}")

	def test_other_exists_and_is_last(self):
		"""It has to exist — refusing an escape hatch makes operators pick the
		nearest wrong reason, which is worse than an honest "Other". It has to be
		last, because first is where a hurried thumb lands."""
		self.assertEqual(SEED_REASONS[-1][0], "Other")
		self.assertEqual(len([r for r, _k in SEED_REASONS if r == "Other"]), 1)

	def test_every_seeded_reason_is_translated_into_all_five_languages(self):
		"""The one that makes the catalogue worth having. The floor reads Uzbek;
		an English list is a list the operator scrolls past on the way to
		"Other", and a catalogue whose commonest entry is "Other" has stopped
		being a catalogue."""
		for lang in _LANGUAGES:
			catalogue = _catalogue(lang)
			for reason, _kind in SEED_REASONS:
				with self.subTest(lang=lang, reason=reason):
					# assertIn would print the whole catalogue on failure.
					self.assertTrue(reason in catalogue, f"{lang}.csv'de yok: {reason}")
					self.assertTrue(catalogue[reason].strip(), f"{lang}.csv boş: {reason}")

	def test_a_translation_is_not_just_the_english_copied_over(self):
		"""Harvest fills a missing target with the source string, and the row
		then looks translated in every check that only asks whether the key is
		present. Uzbek and Russian share no word with English here, so this is
		safe to assert — and it is the difference between a translated catalogue
		and one that was run through the harvester."""
		for lang in ("ru", "uz", "uzc", "tr"):
			catalogue = _catalogue(lang)
			untranslated = [r for r, _k in SEED_REASONS if catalogue.get(r) == r]
			self.assertEqual(untranslated, [], f"{lang}: kaynakla aynı kalmış: {untranslated}")


if __name__ == "__main__":
	unittest.main()


class TestEveryRefusalTheUserCanSeeIsTranslated(unittest.TestCase):
	"""The seeded reasons were translated; the refusals were not.

	Measured 2026-08-28, after this feature had already been deployed: all 35
	`t()` keys in the two new screens were present in all five catalogues, and
	all 16 `_()` strings thrown by the endpoints behind them were present in
	NONE — not even `en.csv`. They are the only strings on this feature a user
	meets when something goes wrong: a bad date range, an unknown line, a stop
	longer than a shift. So the half that was translated is the half nobody
	reads, and the half that was missed is the half that only ever appears at
	the worst moment, in English, inside an otherwise Russian or Uzbek screen.

	Reading the source as text rather than importing it keeps this in `make
	check`: `manufacturing.py` imports frappe, and a test that needed a bench
	would not run on the gate that let the miss through in the first place.
	"""

	_SOURCES = (
		Path(__file__).resolve().parents[1] / "api" / "manufacturing.py",
		Path(__file__).resolve().parents[1]
		/ "stabler"
		/ "doctype"
		/ "stabler_line_stop"
		/ "stabler_line_stop.py",
	)
	# Only the ones this feature added. The rest of manufacturing.py predates it
	# and is not this test's business — widening the net here would turn a
	# regression guard into an unrelated backlog.
	_OURS = (
		"Unknown Work Order: {0}",
		"Expected a date as YYYY-MM-DD, got: {0}",
		"{0} is {1} — its planned date is the record of when it ran.",
		"Unknown kind: {0}",
		"Unknown reason: {0}",
		"Unknown line: {0}",
		"That Work Order belongs to another company.",
		"That line belongs to another company.",
		"Expected dates as YYYY-MM-DD, got: {0} – {1}",
		"The window ends before it starts: {0} – {1}",
		"A planning window may cover at most {0} days.",
		"A stop needs a start time.",
		"A stop needs an end time.",
		"A stop with no length is a double-tap, not an event.",
		"The stop ends before it starts.",
		"A stop longer than 12 hours is a forgotten timer. Split it, or correct the times.",
		"These times cannot be recorded.",
	)

	def test_each_refusal_is_still_thrown_by_the_code(self):
		"""Guards the list above: a refusal that was reworded silently stops being
		covered, and this test would keep passing on a string nobody throws.

		The source spells its dashes as `\\u2014` / `\\u2013` escapes while the
		catalogue key has to carry the character itself — `_()` looks up the value
		Python built, not the bytes on disk. So the source is searched for either
		spelling; comparing raw text against the runtime string reports three
		perfectly correct rows as missing, which is how this comment got written.
		"""
		src = "".join(p.read_text(encoding="utf-8") for p in self._SOURCES)
		for line in self._OURS:
			with self.subTest(line=line):
				escaped = "".join(ch if ord(ch) < 128 else f"\\u{ord(ch):04x}" for ch in line)
				self.assertTrue(
					line in src or escaped in src,
					f"artık kodda geçmiyor, liste bayat: {line}",
				)

	def test_each_refusal_exists_in_all_five_catalogues(self):
		for lang in ("en", "ru", "uz", "uzc", "tr"):
			catalogue = _catalogue(lang)
			for line in self._OURS:
				with self.subTest(lang=lang, line=line):
					# `assertIn` on a 6000-entry dict dumps the whole catalogue on
					# failure; assertTrue keeps the message readable.
					self.assertTrue(line in catalogue, f"{lang}.csv eksik: {line}")

	def test_a_refusal_is_not_just_the_english_copied_over(self):
		"""A harvested row carries the English across unchanged, which reads as
		translated and is not. `en` is exempt: there it IS the source."""
		for lang in ("ru", "uz", "uzc", "tr"):
			catalogue = _catalogue(lang)
			for line in self._OURS:
				with self.subTest(lang=lang, line=line):
					self.assertNotEqual(catalogue.get(line), line, f"{lang}.csv çevrilmemiş: {line}")
