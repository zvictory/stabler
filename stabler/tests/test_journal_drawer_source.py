"""Every way out of the journal drawer asks before discarding a draft.

The journal editor used to be a pane inside the page, then an offcanvas
hand-rolled inline in `JournalEntries.vue` — `pane` = 'empty' | 'view' | 'edit'
driving markup in the same file. There were exactly two ways to leave it —
Escape and the Cancel button — and both went through `requestCancelEdit`, which
prompts when `isDraftDirty` says there is work to lose. The backdrop and the
header ✕ are two more, and the dangerous ones: Escape and Cancel look like
decisions, a stray click beside a wide drawer does not, and a journal entry is
typed one account at a time.

This file used to pin that guard inside `JournalEntries.vue`. The drawer has
since moved into its own component, `JournalEntryDrawer.vue` — full-width list,
`mode`/`name` props, `close`/`saved` emits — because the row table needs six
comfortable columns and a 7/8-col pane never had them. The guard moved with it:
`requestClose`, `requestCancelEdit`, the backdrop and the ✕ all now live in the
component, not the page. What the page keeps is the ONE thing a component
cannot own for itself — Escape is a page-level key, and `useEscapeBack` is
called from every page in this codebase, never from a drawer — so the page's
handler now delegates to an exposed method instead of re-implementing the
question.

Read from the source: a Vue SFC cannot be mounted without a Frappe bootstrap,
and `make test-js` only reaches `composables/`. What is pinned here is a small
set of wiring facts, and the edit that breaks them changes exactly this text.
`journal.spec.js` covers `isDraftDirty`, `ratesByCurrency` and
`applyRateToCurrency` themselves.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DRAWER_SOURCE = Path(__file__).parents[1] / "public" / "js" / "components" / "JournalEntryDrawer.vue"
PAGE_SOURCE = Path(__file__).parents[1] / "public" / "js" / "pages" / "money" / "JournalEntries.vue"


class TestJournalDrawerExitPaths(unittest.TestCase):
	"""The draft guard, read from the component that now owns it."""

	@classmethod
	def setUpClass(cls):
		cls.body = DRAWER_SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_drawer(self):
		"""Anchor: if the path drifts, every assertion below verifies empty text."""
		self.assertIn('class="offcanvas offcanvas-end je-drawer', self.body)

	def test_the_backdrop_asks_before_it_closes(self):
		backdrop = re.search(r'<div class="offcanvas-backdrop[^>]*>', self.body)
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

	def test_cancel_button_also_goes_through_the_guard(self):
		button = re.search(r"<button[^>]*@click=\"requestCancelEdit\"[^>]*>", self.body)
		self.assertIsNotNone(button, "the Cancel button no longer asks before discarding")

	def test_the_guard_is_exposed_for_escape_to_reach(self):
		"""The page cannot see this component's dirty state — `form` and
		`pristine` live behind `mode`/`name` props now, not a page-level `pane`
		ref — so the only way the page's Escape handler can ask the same
		question Cancel does is through an imperative method. Drop this and
		Escape silently stops asking: the page-side test can only see that it
		CALLS a ref, not that the ref has anything behind it to call.
		"""
		self.assertIn("defineExpose({ requestClose })", self.body)


class TestJournalDrawerContract(unittest.TestCase):
	"""The props/emits the plan specified, and what section 3 needs to keep working."""

	@classmethod
	def setUpClass(cls):
		cls.body = DRAWER_SOURCE.read_text(encoding="utf-8")

	def test_takes_mode_and_name(self):
		props = re.search(r"defineProps\(\{(.*?)\n\}\);", self.body, re.S)
		self.assertIsNotNone(props, "could not read defineProps — has it moved?")
		self.assertIn("mode:", props.group(1))
		self.assertIn("name:", props.group(1))

	def test_emits_close_and_saved(self):
		emits = re.search(r"defineEmits\(([^)]*)\)", self.body)
		self.assertIsNotNone(emits, "could not read defineEmits")
		self.assertIn('"close"', emits.group(1))
		self.assertIn('"saved"', emits.group(1))

	def test_width_is_the_planned_custom_property(self):
		"""Section 2 asks for `--drawer-w: min(1100px, 96vw)` specifically — the
		row table (Account, Party, Debit, Credit, delete) does not sit comfortably
		any narrower, which is exactly why it never fit the old 7/8-col pane."""
		self.assertIn("--drawer-w: min(1100px, 96vw)", self.body)
		self.assertIn("width: var(--drawer-w)", self.body)

	def test_the_header_rate_composables_still_come_from_journal_js(self):
		"""Section 3 lifted the exchange rate to the entry, keyed by currency
		instead of by row — `ratesByCurrency`/`applyRateToCurrency` in
		composables/journal.js. Section 2 moves the edit form to a new file; it
		must not strand that wiring on the old one."""
		self.assertIn("ratesByCurrency", self.body)
		self.assertIn("applyRateToCurrency", self.body)
		self.assertIn("entryRates", self.body)
		self.assertIn("setEntryRate", self.body)
		self.assertIn("refreshEntryRate", self.body)

	def test_rate_touched_survives_the_move(self):
		"""A rate the user typed over must not be re-fetched when the posting
		date changes — see `ratesToRefresh()` in journal.js, which reads this
		flag. Dropping it from either `emptyRow()` or `onAccountChange()` while
		moving the form reopens the gap it closed."""
		self.assertIn("_rateTouched: false", self.body)
		self.assertIn("_rateTouched = false", self.body)


class TestJournalEntriesPageAfterExtraction(unittest.TestCase):
	"""What the page looks like once the drawer moves out of it."""

	@classmethod
	def setUpClass(cls):
		cls.body = PAGE_SOURCE.read_text(encoding="utf-8")

	def test_the_list_is_full_width(self):
		self.assertIn('<div class="col-12">', self.body)

	def test_the_table_no_longer_caps_its_own_height(self):
		"""The 7/8 detail pane is gone — the list no longer has to fit beside it
		in a fixed slice of the viewport."""
		self.assertNotIn("calc(100vh - 12rem)", self.body)

	def test_the_pane_state_machine_is_gone(self):
		"""`pane` was 'empty' | 'view' | 'edit', read all over this file. A
		`drawer` ref — present or not — replaces all three states."""
		self.assertNotIn("pane.value", self.body)
		self.assertNotRegex(self.body, r"\bconst pane\s*=\s*ref\(")

	def test_a_single_drawer_ref_replaces_it(self):
		self.assertRegex(self.body, r"const drawer = ref\(null\)")

	def test_the_drawer_component_is_wired_with_the_planned_contract(self):
		tag = re.search(r"<JournalEntryDrawer\b(.*?)/>", self.body, re.S)
		self.assertIsNotNone(tag, "JournalEntryDrawer is not used in the template")
		body = tag.group(1)
		self.assertIn(':mode="drawer.mode"', body)
		self.assertIn(':name="drawer.name"', body)
		self.assertIn("@close=", body)
		self.assertIn("@saved=", body)

	def test_escape_still_tells_the_composable_the_drawer_is_its_own(self):
		"""`ownsDrawer` is not optional: without it `useEscapeBack` bails out on
		any open `.offcanvas.show`, on the assumption "those close themselves" —
		true of an offcanvas Bootstrap instantiated, false of this hand-rolled
		one, so Escape would go back to being a dead key on an open drawer.
		Rewritten in terms of the drawer ref, not dropped."""
		self.assertRegex(self.body, r"ownsDrawer:\s*\(\)\s*=>\s*!!drawer\.value")

	def test_escape_delegates_to_the_drawer_s_own_guard(self):
		"""The page cannot re-implement the dirty check — it no longer has
		`form` or `pristine` in scope — so its Escape handler has to reach into
		the mounted drawer instance (a template ref) rather than branch on a
		mode it cannot see. A bare `requestClose()` is not enough to assert:
		the OLD per-pane handler also called a same-named page-local function,
		so the check has to name the ref, not just the method."""
		block = re.search(r"useEscapeBack\(\(\) => \{(.*?)\n\}, ", self.body, re.S)
		self.assertIsNotNone(block, "could not read the useEscapeBack handler")
		self.assertRegex(
			block.group(1),
			r"drawerRef\.value\?\.\s*requestClose\(\)",
			"Escape does not delegate to the drawer ref's own exposed requestClose",
		)

	def test_the_row_highlight_reads_the_drawer_not_the_old_detail_ref(self):
		"""`detail` was the page's own copy of the viewed entry; it lived here so
		the selected row could be highlighted. That state is inside the drawer
		component now — the page only has the (mode, name) it asked for."""
		self.assertRegex(self.body, r"drawer\?\.\w+\s*===\s*r\.name")


if __name__ == "__main__":
	unittest.main()
