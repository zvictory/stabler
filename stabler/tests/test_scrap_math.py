"""The scrap log's arithmetic, and the two things about it that can silently
double a number.

Measured on anjan 2026-08-27, read-only, and it is why this log looks nothing
like the stop log it mirrors: the floor already records scrap, by hand, 25 Stock
Entries moving 35 037 units worth $3 941 into two scrap warehouses, three people
doing it, latest 2026-08-22. What is missing is not the movement — it is the
reason, which survives today only as a free-text Uzbek paragraph in `remarks`.

Two guards here are load-bearing and neither is obvious:

  1. `already_scrapped_qty`. The draft this log writes is a plain Material
     Transfer, which touches no Work Order field, so ERPNext's own
     `transferred_qty - consumed_qty` does not fall when scrap leaves WIP. Two
     records for 5 kg each against 6 kg of stock would each pass on their own and
     the second would fail at submit, in the Desk, days later.

  2. A negative quantity. On a Material Transfer it does not merely fail
     validation — it reverses the entry. A record filed as a loss would read, in
     the ledger, as a gain.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_scrap_math -v
"""

from __future__ import annotations

import ast
import csv
import unittest
from pathlib import Path

from stabler.api._downtime import SEED_REASONS
from stabler.api._scrap import available_to_scrap, validate_scrap

_ROOT = Path(__file__).resolve().parents[1]
_TRANSLATIONS = _ROOT / "translations"
_LANGUAGES = ("en", "ru", "uz", "uzc", "tr")


def _catalogue(lang: str) -> dict:
	with (_TRANSLATIONS / f"{lang}.csv").open(encoding="utf-8", newline="") as fh:
		reader = csv.reader(fh)
		next(reader, None)
		return {row[0]: row[1] for row in reader if len(row) >= 2}


class TestWhatTheOrderStillHoldsInWip(unittest.TestCase):
	def test_what_arrived_less_what_was_written_off(self):
		self.assertEqual(available_to_scrap(20, 5), 15.0)

	def test_scrap_already_filed_comes_off_the_ceiling(self):
		"""The guard ERPNext cannot make. A plain Material Transfer moves stock
		without touching `transferred_qty` or `consumed_qty`, so the kilograms
		this log has already sent to the scrap warehouse are still standing in
		ERPNext's arithmetic. Without this subtraction two 5 kg records against
		6 kg of stock both pass, and the second one fails on negative stock at
		submit — in the Desk, days later, in front of somebody who cannot know
		what the right number was."""
		self.assertEqual(available_to_scrap(20, 5, 6), 9.0)

	def test_a_fully_consumed_line_holds_nothing(self):
		self.assertEqual(available_to_scrap(20, 20), 0.0)

	def test_a_line_never_transferred_holds_nothing(self):
		"""Material scrapped before the transfer entry was posted is material
		that is not in WIP yet. There is nothing to move out of it."""
		self.assertEqual(available_to_scrap(0, 0), 0.0)

	def test_books_that_already_disagree_report_nothing_rather_than_a_negative(self):
		"""A negative ceiling would make every quantity look too large and the
		message would blame the operator for somebody else's reconciliation."""
		self.assertEqual(available_to_scrap(5, 20), 0.0)

	def test_binary_float_noise_does_not_move_the_ceiling(self):
		"""The operator scrapping everything that is left types the number the
		screen showed them. A subtraction carried out in binary floats can leave
		that number a hair above the ceiling, and refusing it would be
		arithmetically correct and, to the person holding the bucket, nonsense."""
		self.assertEqual(available_to_scrap(0.3, 0.1), 0.2)
		self.assertTrue(validate_scrap(0.2, available_to_scrap(0.3, 0.1))[0])

	def test_blank_inputs_are_read_as_zero_rather_than_blowing_up(self):
		"""This is the ceiling a screen renders beside a row it has already
		accepted; `validate_scrap` is where a bad number is refused."""
		self.assertEqual(available_to_scrap(None, None), 0.0)
		self.assertEqual(available_to_scrap("20", "5", ""), 15.0)


class TestWhatMayBeRecorded(unittest.TestCase):
	def test_an_ordinary_loss_is_accepted(self):
		allowed, refusal = validate_scrap(3, 15)
		self.assertTrue(allowed)
		self.assertEqual(refusal, "")

	def test_everything_the_order_holds_may_be_scrapped(self):
		"""The boundary is inclusive. A whole batch does go in the bin."""
		self.assertTrue(validate_scrap(15, 15)[0])

	def test_a_blank_quantity_is_named_apart_from_a_typed_zero(self):
		"""Different mistakes, different messages — the kiosk puts the text under
		a field and has to know which one it failed on."""
		self.assertEqual(validate_scrap(None, 15)[1], "missing_qty")
		self.assertEqual(validate_scrap("", 15)[1], "missing_qty")
		self.assertEqual(validate_scrap("bir chelak", 15)[1], "missing_qty")

	def test_a_zero_quantity_is_refused(self):
		"""The double-tap. Recorded, it adds a row to "how often do we lose
		product" while adding nothing to "how much" — which is exactly how a
		frequency figure goes wrong in the direction nobody checks."""
		self.assertEqual(validate_scrap(0, 15)[1], "zero_qty")

	def test_a_negative_quantity_is_refused(self):
		"""The one refusal that is not hygiene. A negative quantity on a Material
		Transfer reverses it: the draft would carry stock INTO the line out of the
		scrap warehouse, and a record filed as a loss would read, in the ledger,
		as a gain. Nothing downstream would flag it — the entry is perfectly
		valid, it just points the other way."""
		self.assertEqual(validate_scrap(-3, 15)[1], "negative_qty")

	def test_more_than_wip_holds_is_refused(self):
		"""Negative stock is off on this site (measured 2026-08-27), so this
		would not silently mis-post — it would throw at submit, in the Desk, days
		after the bucket was emptied. Refusing it here puts the error in front of
		the only person who can still count what is in front of them."""
		self.assertEqual(validate_scrap(16, 15)[1], "more_than_wip_holds")

	def test_an_empty_line_is_named_apart_from_an_over_scrap(self):
		"""Two different fixes. "You typed too much" is corrected on this form;
		"this order has none of that material in WIP" cannot be — the operator
		picked the wrong item, or the transfer was never posted."""
		self.assertEqual(validate_scrap(3, 0)[1], "nothing_in_wip")


class TestTheReasonCatalogueIsTheOneThatAlreadyExists(unittest.TestCase):
	"""There is deliberately no seed list in `_scrap`.

	`_downtime.SEED_REASONS` already carries a `kind` of Downtime / Loss / Both,
	`list_stop_reasons(company, "Loss")` already filters on it, patch v101 has
	already planted the rows on every site and `test_downtime_catalogue` already
	pins every one of them into all five translation catalogues. A second
	catalogue would fork a translated, tested, deployed list for nothing — and
	the Loss rows in the existing one would be orphaned the day it was added.

	What this test guards is that the fork does not happen later by accident.
	"""

	def test_the_loss_half_of_the_shipped_catalogue_is_not_empty(self):
		loss = [r for r, k in SEED_REASONS if k in ("Loss", "Both")]
		self.assertGreaterEqual(len(loss), 5, f"fire yarısı boşalmış: {loss}")

	def test_scrap_declares_no_catalogue_of_its_own(self):
		"""Parsed rather than grepped: the module's own docstring names
		`_downtime.SEED_REASONS` to explain why it has none, and a substring
		search would read that sentence as the thing it forbids. Only a
		module-level binding counts."""
		tree = ast.parse((_ROOT / "api" / "_scrap.py").read_text(encoding="utf-8"))
		bound = [
			t.id
			for node in tree.body
			if isinstance(node, ast.Assign)
			for t in node.targets
			if isinstance(t, ast.Name)
		]
		forked = [n for n in bound if "SEED" in n or "REASON" in n]
		self.assertEqual(forked, [], f"ikinci sebep kataloğu doğmuş: {forked}")


class TestEveryRefusalTheUserCanSeeIsTranslated(unittest.TestCase):
	"""The lesson `test_downtime_catalogue` learned the expensive way, applied
	before deployment this time rather than after.

	Measured 2026-08-28 on the stop log, already live: all 35 `t()` keys in its
	screens were in all five catalogues and all 16 `_()` strings thrown behind
	them were in none, not even `en.csv`. The refusals are the only strings a
	user meets when something goes wrong, so the half that was translated is the
	half nobody reads.

	Read as source text rather than imported: `manufacturing.py` and the doctype
	controller both import frappe, and a test needing a bench would not run on
	the gate that let the miss through in the first place.
	"""

	_SOURCES = (
		_ROOT / "api" / "manufacturing.py",
		_ROOT / "stabler" / "doctype" / "stabler_line_scrap" / "stabler_line_scrap.py",
		_ROOT
		/ "stabler"
		/ "doctype"
		/ "stabler_manufacturing_settings"
		/ "stabler_manufacturing_settings.py",
	)
	#: Only the strings this feature added. The stop log's own list is pinned by
	#: `test_downtime_catalogue`; widening the net here would turn a regression
	#: guard into an unrelated backlog.
	_OURS = (
		"A scrap record needs a quantity.",
		"A scrap record with no quantity is a double-tap, not a loss.",
		"A negative quantity would move stock back onto the line. Record what was lost.",
		"{0} has nothing in WIP on this order to scrap.",
		"{0} holds only {1} of {2} in WIP on this order.",
		"{0} is not one of this order's materials.",
		"Scrap is not configured for {0}. Name the scrap warehouse in Stabler Manufacturing Settings.",
		"{0} is not a warehouse of {1}.",
		"A scrap record needs a Work Order.",
		"{0} has no WIP warehouse to scrap from.",
		"A scrap record cannot be changed once its stock transfer exists. Cancel that transfer and file a new record.",
		"Rejects were already entered when this order was finished. Record the loss in one place, not two.",
		"This order already has a scrap record. Enter the rejects there, not here.",
		"That scrap record's stock transfer was already submitted. It cannot be deleted.",
		"That quantity cannot be recorded.",
		"Unknown scrap reason: {0}",
		"{0} is not a loss reason.",
		"Scrap {0}: {1} — {2}, reported by {3}",
	)

	def test_each_refusal_is_still_thrown_by_the_code(self):
		"""Guards the list above. A refusal that was reworded silently stops being
		covered, and this test would keep passing on a string nobody throws."""
		src = "".join(p.read_text(encoding="utf-8") for p in self._SOURCES)
		for line in self._OURS:
			with self.subTest(line=line):
				escaped = "".join(ch if ord(ch) < 128 else f"\\u{ord(ch):04x}" for ch in line)
				self.assertTrue(line in src or escaped in src, f"artık kodda geçmiyor, liste bayat: {line}")

	def test_each_refusal_exists_in_all_five_catalogues(self):
		for lang in _LANGUAGES:
			catalogue = _catalogue(lang)
			for line in self._OURS:
				with self.subTest(lang=lang, line=line):
					# assertIn on a 6000-entry dict dumps the whole catalogue.
					self.assertTrue(line in catalogue, f"{lang}.csv eksik: {line}")

	def test_a_refusal_is_not_just_the_english_copied_over(self):
		"""Harvest fills a missing target with the source string, and the row then
		looks translated in every check that only asks whether the key is present.
		`en` is exempt: there it IS the source."""
		for lang in ("ru", "uz", "uzc", "tr"):
			catalogue = _catalogue(lang)
			for line in self._OURS:
				with self.subTest(lang=lang, line=line):
					self.assertNotEqual(catalogue.get(line), line, f"{lang}.csv çevrilmemiş: {line}")


class TestTheTwoLossPathsCannotBothCount(unittest.TestCase):
	"""The most important test in this file, and the only one that reads source.

	A finished-goods reject path shipped on 2026-06-08 (`410f2ba`) and has never
	been used: `process_loss_qty > 0` on 0 of 3757 Manufacture entries. It takes a
	bare `scrap_qty` at Finish and inflates `fg_completed_qty` to good+loss so
	ERPNext's own equality check passes — which draws the raw material for the
	lost units and receives none of it anywhere, absorbing the cost into the good
	output's unit cost.

	That is the same loss this log moves into the scrap warehouse. Recording both
	for one order charges the material twice: once into the good units' cost, once
	as stock standing in the scrap warehouse. Nothing throws; the two numbers are
	individually correct and their sum is wrong.

	So the two are mutually exclusive per Work Order, refused in both directions,
	server-side. Pinned as source text because both guards live in
	`manufacturing.py`, which imports frappe — and the whole point of a guard
	against a silent double-count is that it is checked by the gate that runs on
	every commit, not only by the one that needs a live bench.
	"""

	_MFG = _ROOT / "api" / "manufacturing.py"
	_CONTROLLER = _ROOT / "stabler" / "doctype" / "stabler_line_scrap" / "stabler_line_scrap.py"

	def test_finish_refuses_rejects_when_a_scrap_record_exists(self):
		"""The Finish side. Reading the source is the point: this guard is three
		lines inside a 200-line function, and the thing it prevents leaves no
		trace to assert on afterwards."""
		src = self._MFG.read_text(encoding="utf-8")
		self.assertIn("def _assert_no_scrap_record", src, "Finish tarafındaki çift sayım kapısı yok")
		self.assertIn(
			"This order already has a scrap record.", src, "Finish tarafındaki çift sayım mesajı yok"
		)

	def test_the_finish_guard_is_actually_called_from_the_manufacture_branch(self):
		"""A helper nobody calls is the most convincing kind of missing guard:
		grep finds it, the message is translated, and it never runs."""
		src = self._MFG.read_text(encoding="utf-8")
		self.assertIn("_assert_no_scrap_record(work_order)", src, "kapı tanımlı ama çağrılmıyor")

	def test_the_scrap_record_refuses_an_order_that_already_reported_rejects(self):
		"""The other direction, in `validate` so a Desk write is refused too."""
		src = self._CONTROLLER.read_text(encoding="utf-8")
		self.assertIn(
			"Rejects were already entered when this order was finished.",
			src,
			"fire kaydı tarafındaki çift sayım mesajı yok",
		)
		self.assertIn("def _assert_rejects_were_not_already_reported", src, "fire kaydı tarafındaki kapı yok")

	def test_the_scrap_side_guard_is_called_from_validate(self):
		"""Written after the first version of the test above stayed green when the
		CALL was deleted and only the definition left standing. A helper nobody
		invokes is the most convincing kind of missing guard: grep finds it, the
		message is translated, and it never runs — so both directions are pinned
		on the call site, not on the name."""
		tree = ast.parse(self._CONTROLLER.read_text(encoding="utf-8"))
		called = {
			node.func.attr
			for node in ast.walk(tree)
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
		}
		self.assertIn("_assert_rejects_were_not_already_reported", called, "kapı tanımlı ama çağrılmıyor")


if __name__ == "__main__":
	unittest.main()
