"""What an operator is told when a stock posting is refused.

Found by running the operator UAT on anjan, 2026-08-31, after the material list
had already been taken off the kiosk. Every one of Ilyos Nazirov's three open
Work Orders is short of material in the source store, so the Start button's most
likely outcome is ERPNext's own refusal — and that refusal reads
(`erpnext/stock/stock_ledger.py:1713`):

    {0} units of {1} needed in {2} to complete this transaction.

where `{1}` is `frappe.get_desk_link("Item", item_code, show_title_with_name=True)`.
So the message hands back the item code, the item name and the missing quantity —
the exact three things the change removed from every other route — and it hands
them back as a `/app/item/...` link, which this app never shows anyone.

The rule this module encodes: **the words an operator sees carry no data**. Not
"carry sanitized data" — carry none, which is why the test below refuses a
message with a substitution slot in it. A slot is how an item code gets back in,
one well-meaning `.format()` at a time.

Frappe-free, so it lands in `make check` rather than only in the bench run.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_posting_errors -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from stabler.api._wo_errors import POST_FAILED, SHORT_STOCK, operator_posting_error


class TestWhatTheOperatorIsTold(unittest.TestCase):
	def test_a_short_store_is_reported_without_naming_the_material(self):
		"""The case that prompted this. ERPNext names the item, the quantity and
		the warehouse; the operator gets the one fact they can act on — go and tell
		the shift lead — and none of the three."""
		self.assertEqual(operator_posting_error("NegativeStockError"), SHORT_STOCK)

	def test_an_unrecognised_failure_is_still_replaced(self):
		"""Default-deny, and the reason is that this list cannot be complete:
		ERPNext raises from a dozen places in `stock_entry.py` alone and several of
		them interpolate a row's item into the message. Anything not recognised is
		therefore assumed to name something, rather than assumed safe."""
		self.assertEqual(operator_posting_error("BatchExpiredError"), POST_FAILED)
		self.assertEqual(operator_posting_error("ValidationError"), POST_FAILED)
		self.assertEqual(operator_posting_error(""), POST_FAILED)

	def test_a_refusal_to_be_here_at_all_reaches_the_operator_unchanged(self):
		"""`None` means re-raise. A permission error names no item and is the one
		refusal an operator can do something about — it is what a Manufacturing
		User met on every Work Order on anjan until the Custom DocPerm row was
		added on 2026-08-31, and replacing it with "could not be recorded" would
		have hidden that root cause behind a shrug."""
		self.assertIsNone(operator_posting_error("PermissionError"))

	def test_neither_message_has_anywhere_to_put_a_value(self):
		"""The guard that outlives this file's author.

		Both strings are constants and must stay constants. A `{0}` in either one
		is an invitation for the next person to pass the item in "just for this
		case", and the leak comes back through a message that still reads as
		sanitised. Checked on the strings themselves, not on their use, because the
		use is one line away from being edited."""
		for message in (SHORT_STOCK, POST_FAILED):
			self.assertNotIn("{", message)
			self.assertNotIn("%s", message)

	def test_the_operator_is_told_who_to_go_to(self):
		"""A dead end is worse than the leak it replaced. The operator is standing
		at a machine that will not start; a message that only says "no" leaves them
		with the tablet as the only thing to argue with."""
		for message in (SHORT_STOCK, POST_FAILED):
			self.assertIn("shift lead", message)


class TestTheHandlerIsActuallyWiredIn(unittest.TestCase):
	"""Read out of the source, because `manufacturing.py` imports frappe at module
	level and only the bench run can load it — while the failure this guards
	against is exactly the kind that keeps every unit test above green: a helper
	that decides the right thing and is never called.

	It also pins the boundary. `se.insert()` and `se.submit()` are the only two
	lines in that function that hand ERPNext's own words to the caller; everything
	above them throws in this app's words, which name no material. Widening the
	`try` would start swallowing our own refusals, and every one of those is a
	sentence somebody wrote for the operator on purpose.
	"""

	@staticmethod
	def _posting_block() -> str:
		src = (Path(__file__).resolve().parents[1] / "api" / "manufacturing.py").read_text("utf-8")
		src = re.sub(r"^\s*#.*$", "", src, flags=re.M)  # comments name these very symbols
		start = src.index("assert_stock_entry_valuation_sane(se)")
		return src[start : src.index('return {"name": se.name', start)]

	def test_the_posting_runs_inside_the_handler(self):
		block = self._posting_block()
		self.assertIn("operator_posting_error(type(exc).__name__)", block)
		for line in ("se.insert(ignore_permissions=False)", "se.submit()"):
			self.assertIn(line, block)
			self.assertLess(block.index("try:"), block.index(line), f"{line} is outside the try")

	def test_a_manager_still_gets_the_servers_own_words(self):
		"""`is_manager` short-circuits to None, and None re-raises. Dropped, a
		manager debugging a refused transfer would be told "tell the shift lead"
		— they are the shift lead."""
		self.assertIn("None if is_manager else operator_posting_error", self._posting_block())

	def test_what_the_operator_is_not_told_is_written_down(self):
		"""The detail is swallowed, not lost. Without this the change trades a leak
		for a silence, and the person the operator is sent to has nothing to read."""
		self.assertIn("frappe.log_error(", self._posting_block())


if __name__ == "__main__":
	unittest.main()
