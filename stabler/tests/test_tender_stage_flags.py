"""The stage payload carries the two facts that make a column terminal.

Prompt 18's acceptance row C15: *Paid* and *Closed* must be distinguishable from
ordinary columns. `_stages()` has always selected `is_won` and `is_closed` — the
board just rendered neither, so a won column and a dead column looked exactly
like the five in between.

This module pins the SERVER half: the flags are selected, and they mean what the
doctype says they mean. The client half — that the header actually draws them, as
text rather than as a colour or a tooltip — is
`public/js/tests/contractBoardLegibility.spec.js`. Same split, same reason, as
test_tender_crm_card_currency.py: a claim about the payload belongs in the
language that builds it.
"""

import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api", "tender.py")
DOCTYPE = os.path.join(HERE, "..", "stabler", "doctype", "stabler_so_stage", "stabler_so_stage.json")


class TestTheStagePayloadCarriesItsFlags(unittest.TestCase):
	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.api = fh.read()
		with open(DOCTYPE, encoding="utf-8") as fh:
			self.fields = {f["fieldname"]: f for f in json.load(fh)["fields"]}

	def test_the_reader_selects_both_flags(self):
		# WHAT WOULD MAKE THIS FAIL: trimming the field list. The board renders
		# these two, and a column that quietly stops being marked as won reads as
		# an ordinary stage — the failure is invisible, because the header still
		# looks fine. Nothing else in the repository pinned this list.
		m = re.search(r"def _stages\(\)[\s\S]*?limit_page_length=0,\s*\)", self.api)
		self.assertIsNotNone(m, "_stages has moved")
		for flag in ("is_won", "is_closed"):
			with self.subTest(flag=flag):
				self.assertIn(f'"{flag}"', m.group(0))

	def test_the_flags_are_the_ones_the_doctype_defines(self):
		# WHAT WOULD MAKE THIS FAIL: the query selecting a field the doctype does
		# not have. `_stages` uses `frappe.get_all`, which would raise on an
		# unknown column at request time — the board would go blank rather than
		# lose a badge, and no source-text test above would notice.
		for flag in ("is_won", "is_closed"):
			with self.subTest(flag=flag):
				self.assertIn(flag, self.fields, f"Stabler SO Stage has no {flag}")
				self.assertEqual(self.fields[flag]["fieldtype"], "Check")

	def test_both_flags_mean_terminal_and_only_one_means_won(self):
		# WHAT WOULD MAKE THIS FAIL: the descriptions drifting from what the board
		# now says. The header's chips read "Won" and "Closed" because that is
		# what the doctype calls these flags ("Is Won", "Is Closed"); if the
		# meaning is edited here, the two words on screen become a second,
		# quieter definition of the same thing.
		self.assertIn("Terminal", self.fields["is_won"].get("description", ""))
		self.assertIn("Terminal", self.fields["is_closed"].get("description", ""))
		self.assertEqual(self.fields["is_won"]["label"], "Is Won")
		self.assertEqual(self.fields["is_closed"]["label"], "Is Closed")

	def test_the_seeded_stages_actually_exercise_both(self):
		# WHAT WOULD MAKE THIS FAIL: a default set where no stage is won and none
		# is closed. Then every column looks alike on a fresh site, the chips are
		# never drawn, and C15 is satisfied only in principle — which is how a
		# rendering defect survives a demo.
		m = re.search(r"_DEFAULT_STAGES = \[([\s\S]*?)\n\]", self.api)
		self.assertIsNotNone(m, "_DEFAULT_STAGES has moved")
		rows = re.findall(r'\("([^"]+)", (\d+), "([^"]+)", (\d), (\d)\)', m.group(1))
		self.assertTrue(rows, "no default stages parsed")
		self.assertEqual([r[0] for r in rows if r[3] == "1"], ["Paid"])
		self.assertEqual([r[0] for r in rows if r[4] == "1"], ["Closed"])


if __name__ == "__main__":
	unittest.main()
