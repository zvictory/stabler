"""Every way out of the journal drawer asks before discarding a draft.

The journal editor used to be a pane inside the page. There were exactly two
ways to leave it — Escape and the Cancel button — and both went through
`requestCancelEdit`, which prompts when `isDraftDirty` says there is work to
lose. Moving the editor into an offcanvas adds two more: the ✕ in the header and
a click on the dimmed backdrop.

The backdrop is the dangerous one. Escape and Cancel look like decisions; a
stray click beside a wide drawer does not, and a journal entry is typed one
account at a time. Wiring either of them straight to `pane = "empty"` would
throw the lines away without a word, and nothing else in the suite would notice,
because the guard itself would still be perfectly correct — just no longer on
the path anyone takes.

Read from the source: a Vue SFC cannot be mounted without a Frappe bootstrap,
and `make test-js` only reaches `composables/`. What is pinned here is a small
set of wiring facts, and the edit that breaks them changes exactly this text.
`journal.spec.js` covers `isDraftDirty` itself.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "pages" / "money" / "JournalEntries.vue"


class TestJournalDrawerExitPaths(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_drawer(self):
		"""Anchor: without the drawer, every assertion below is vacuous."""
		self.assertIn('class="offcanvas offcanvas-end je-drawer"', self.body)

	def test_the_backdrop_asks_before_it_closes(self):
		backdrop = re.search(r'<div v-if="pane[^>]*offcanvas-backdrop[^>]*>', self.body)
		self.assertIsNotNone(backdrop, "could not find the backdrop element")
		self.assertIn(
			'@click="requestClose"',
			backdrop.group(0),
			"the backdrop closes the drawer directly — a stray click would discard the draft",
		)

	def test_the_close_button_asks_before_it_closes(self):
		button = re.search(r'<button[^>]*class="btn-close"[^>]*>', self.body)
		self.assertIsNotNone(button, "could not find the drawer's close button")
		self.assertIn('@click="requestClose"', button.group(0))

	def test_closing_while_editing_goes_through_the_draft_guard(self):
		"""`requestClose` may not reimplement the prompt, it must delegate to it.

		A second copy of "ask if dirty" is a second copy that can rot: the
		wording, the danger flag and the `submitting` check all live in
		`requestCancelEdit`, and a drawer with its own version would drift from
		what Escape does on the very same draft.
		"""
		block = re.search(r"function requestClose\(\) \{(.*?)\n\}", self.body, re.S)
		self.assertIsNotNone(block, "could not read requestClose — has it been renamed?")
		self.assertIn(
			"requestCancelEdit()",
			block.group(1),
			"requestClose closes the editor without consulting the draft guard",
		)

	def test_escape_still_closes_the_drawer_rather_than_the_page(self):
		"""The drawer is a layer over the list, so Escape has to peel it off first.

		Before the drawer, `pane === "view"` was a pane inside the page and
		Escape leaving for /money was right. Now it would navigate out from under
		an open drawer.
		"""
		block = re.search(r"useEscapeBack\(\(\) => \{(.*?)\n\}, ", self.body, re.S)
		self.assertIsNotNone(block, "could not read the useEscapeBack handler")
		self.assertIn('pane.value === "view"', block.group(1))

	def test_escape_actually_reaches_that_handler(self):
		"""The branch above is worth nothing if the composable never calls it.

		It did not, for a day. `useEscapeBack` bails out on any open
		`.offcanvas.show` because "those close themselves" — true of an offcanvas
		Bootstrap instantiated, false of this one, which is markup plus a `show`
		class. So Escape was a dead key on an open drawer while the handler
		beside it read perfectly correct, and the test above stayed green
		throughout: it can see that a branch exists, not that anything reaches
		it. `ownsDrawer` is what puts it back on the path, and this pins it.
		"""
		self.assertRegex(
			self.body,
			r"ownsDrawer:\s*\(\)\s*=>",
			"the page no longer tells useEscapeBack that the drawer is its own",
		)


if __name__ == "__main__":
	unittest.main()
