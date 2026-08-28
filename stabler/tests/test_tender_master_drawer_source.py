"""`TenderMasterDrawer.vue`'s intake save/restore keeps its seven tender-master
fields wired end-to-end, and the organization-name placeholder for `title` is
not allowed to be its only source.

`form.title` is seeded from `val.title || val.organization || ""` before the
intake read-back resolves (`watch(props.deal)`'s synchronous body, `:147`) —
a reasonable placeholder while nothing better is known yet. What makes that
placeholder safe is the async `.then()` a few lines later (`:166`) which
overwrites it once `intake.title` comes back from `deal_intake`. Break that
override — or send `title` to `save_deal_intake` without it ever coming back
— and the placeholder stops being a placeholder: it sits in a required field,
looks like real data, and a save persists the customer's name over the real
title with no error anywhere. Proven on production mikas 2026-08-15:
`docs/uat/evidence/2026-08-15-tender-crud-uat/README.md` (`UAT-A3-EDIT-OPEN`,
`UAT-A3-EDIT-SAVE`).

This is the Vue half of the contract; `test_tender_intake_master_fields.py`
covers the backend whitelist (`_clean_intake`) that was actually dropping the
keys. Neither guard is sufficient alone: the backend test cannot see that the
drawer stops asking for `title` back, and this one cannot see that the
backend used to throw the answer away.

A JS component cannot be mounted (`@vue/test-utils` is not a dependency
here), so — same discipline as `test_money_input_source.py` — this reads the
source text.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_master_drawer_source -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "components" / "TenderMasterDrawer.vue"
# The caller is half of the same causal chain, so it is pinned here rather than
# in the kanban's own source test: the corruption needs both ends to line up,
# and a guard split across two files is a guard nobody reads as one rule.
CALLER = Path(__file__).parents[1] / "public" / "js" / "pages" / "tender" / "TenderCrm.vue"

_MASTER_FIELDS = (
	"title",
	"tender_no",
	"source",
	"publication_date",
	# ADR-203: the field is labelled "Submission Deadline" in the UI, but the key
	# it writes is `bid_deadline` -- the one the deadline timeline and the SLA
	# badge read. The old key survives on the read side only (see the transition
	# test below), so it is not in this write-and-read-back set.
	"bid_deadline",
	"currency",
	"estimated_total",
)

_TITLE_SEED = 'form.title = val.title || ""'
_TITLE_RESTORE = 'form.title = intake.title || ""'


class TestTenderMasterDrawerIntakeContract(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_component(self):
		"""Anchor: if the path or the surrounding code drifts, every assertion
		below verifies empty text instead of the real component."""
		self.assertIn("const intakePayload = {", self.body)
		self.assertIn(_TITLE_SEED, self.body)
		self.assertIn(_TITLE_RESTORE, self.body)

	def test_every_master_field_is_sent_in_the_intake_payload(self):
		"""A field missing here never reaches `save_deal_intake` at all — no
		backend whitelist fix can restore what the browser never sent."""
		start = self.body.index("const intakePayload = {")
		end = self.body.index("tender_files:", start)
		payload_block = self.body[start:end]
		for field in _MASTER_FIELDS:
			with self.subTest(field=field):
				self.assertIn(f"{field}:", payload_block)

	def test_every_master_field_is_restored_from_the_intake_read_back(self):
		"""The other half of the round trip: once `save_deal_intake` returns
		the field, the drawer must actually read it back on the next open —
		or a correct backend still shows the user stale/placeholder data."""
		start = self.body.index(".then((res) => {")
		end = self.body.index("Array.isArray(intake.tender_files)", start)
		restore_block = self.body[start:end]
		for field in _MASTER_FIELDS:
			with self.subTest(field=field):
				self.assertIn(f"intake.{field}", restore_block)

	def test_the_previous_deadline_key_is_read_but_no_longer_written(self):
		"""ADR-203's transition, both halves. Records saved before the rename
		carry `submission_deadline` and must still open with their deadline
		filled in -- but writing it again would keep the two keys alive and
		leave the bid milestone reading whichever one happened to be last."""
		start = self.body.index("const intakePayload = {")
		end = self.body.index("tender_files:", start)
		self.assertNotIn("submission_deadline:", self.body[start:end])
		self.assertIn("intake.bid_deadline || intake.submission_deadline", self.body)

	def test_the_drawer_does_not_send_the_document_checklist(self):
		"""ADR-205 / defect #2. This form has no checklist editor, so the only
		thing it can say about `documents` is an empty list -- and an empty list
		used to rebuild the checklist as empty, deleting requirement rows, their
		uploaded files and their waiver justifications. Saying nothing is the
		only correct thing a form with no opinion can say."""
		start = self.body.index("const intakePayload = {")
		end = self.body.index("await call(", start)
		self.assertNotIn("documents:", self.body[start:end])

	def test_the_organization_placeholder_is_corrected_once_intake_arrives(self):
		"""The specific defect: `title` has a customer-name placeholder that
		must be overwritten, not merely a blank one that fails loudly."""
		self.assertIn(_TITLE_RESTORE, self.body)

	def test_a_stored_intake_with_no_title_clears_the_seed_rather_than_keeping_it(self):
		"""The half the conditional restore never covered.

		`if (intake.title) …` corrects the seed only when the record already has
		a stored title. On a record saved before 8abffa2 put `title` in the
		whitelist, the intake comes back without one, the guard does not fire,
		and the customer name stays sitting in a required field looking like
		data somebody typed. Since 8abffa2 that field is persisted — so the next
		save writes the customer's name over the tender's title permanently,
		with no error at any layer. Before the whitelist the value was silently
		dropped; after it, it is silently wrong, which is worse.

		The intake JSON is `title`'s only home — `crm.save_deal` does not accept
		it — so the stored value is the only truth there is, and the restore has
		to be unconditional for exactly the reason the six evaluation fields
		below are: a guard that skips an empty value makes "no title yet"
		indistinguishable from "this title".
		"""
		self.assertIn('form.title = intake.title || ""', self.body)
		self.assertNotIn("if (intake.title)", self.body)

	def test_the_seed_does_not_borrow_the_customer_name(self):
		"""`title` is a required field with its own validation and its own
		placeholder text. Pre-filling it from a different concept — the
		customer's organization — is not a default, it is an answer the user
		never gave, and the required-field check it satisfies is the only thing
		that would otherwise have asked them.

		Scoped to the title line: `form.organization = val.organization || ""`
		on the line above is the same expression doing an entirely correct job,
		so a file-wide search reports the wrong one.
		"""
		seed = [ln for ln in self.body.splitlines() if "form.title = val." in ln]
		self.assertEqual(len(seed), 1, "expected exactly one title seed line")
		self.assertNotIn("organization", seed[0])

	def test_the_caller_does_not_pass_the_cards_display_label_as_a_title(self):
		"""The other end of the chain.

		`crm_board` sets each card's `label` from `_deal_label()`, which returns
		the organization, or the lead name, or — when both are empty — the deal
		ID itself. `openEditDrawer` mapped that straight onto `title`, so the
		drawer's seed was not even reaching its own organization fallback: the
		caller was handing it a wrong title as though it were a real one.
		"""
		caller = CALLER.read_text(encoding="utf-8")
		start = caller.index("function openEditDrawer")
		block = caller[start : caller.index("\n}", start)]
		self.assertIn("editingTender.value", block, "the test is reading the wrong function")
		self.assertNotIn("title: c.label", block)

	def test_the_placeholder_seed_runs_before_the_restore_can_correct_it(self):
		"""If the ordering were reversed, the intake restore would run and
		then be immediately clobbered by the organization fallback — the
		exact silent-failure shape this whole file exists to catch."""
		seed_at = self.body.index(_TITLE_SEED)
		restore_at = self.body.index(_TITLE_RESTORE)
		self.assertLess(seed_at, restore_at)


if __name__ == "__main__":
	unittest.main()


# --------------------------------------------------------------------------- #
# ADR-206 — the evaluation form moves to where the decision is made
# --------------------------------------------------------------------------- #
_EVALUATION_FIELDS = (
	"go_no_go",
	"guarantee_amount",
	"guarantee_return",
	"penalty_pct_per_day",
	"cert_required",
	"purchase_method",
)

# Server-owned: `_clean_intake` stamps these from the server clock and the
# session user, and never reads them from the payload.
_DECISION_STAMP = ("go_no_go_at", "go_no_go_by")


class TestTheEvaluationSectionLivesWhereTheDecisionIsMade(unittest.TestCase):
	"""ADR-206. Go/No-Go, the guarantee, the daily penalty, the certificate
	requirement and the purchase method are *pre-win* decisions, and they are
	made in the kanban drawer — where a manager looks at a tender and decides
	whether to bid at all. Today they live only in `TenderIntake.vue`, which is
	embedded in the **PO control board**: a post-win screen nobody opens before
	a tender is won. So the decision surface sits behind the decision."""

	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def _payload_block(self) -> str:
		start = self.body.index("const intakePayload = {")
		return self.body[start : self.body.index("await call(", start)]

	def test_every_evaluation_field_is_sent_in_the_intake_payload(self):
		"""A field the drawer does not send cannot be decided in the drawer,
		whatever the form shows."""
		block = self._payload_block()
		for field in _EVALUATION_FIELDS:
			with self.subTest(field=field):
				self.assertIn(f"{field}:", block)

	def test_every_evaluation_field_is_restored_from_the_intake_read_back(self):
		"""The other half. Without the read-back the drawer opens blank on an
		existing tender, and the first save writes those blanks over a decision
		somebody already made — the defect-#1 shape, one field set later."""
		start = self.body.index(".then((res) => {")
		restore = self.body[start : self.body.index("const lines =", start)]
		for field in _EVALUATION_FIELDS:
			with self.subTest(field=field):
				self.assertIn(f"intake.{field}", restore)

	def test_the_section_is_lettered_E_after_the_existing_four(self):
		"""The drawer numbers its sections A–D and the decision document calls
		this one E (mockup Tab 1/Tab 2). A fifth section with no letter reads as
		an afterthought bolted to the bottom of the form."""
		self.assertIn('<span class="tgm-sec-num">E</span>', self.body)

	def test_the_decision_stamp_is_never_sent_from_the_browser(self):
		"""ADR-206 keeps today's behaviour: the server stamps who decided and
		when. A browser-supplied stamp is a claim about the past that nobody can
		check — and the audit trail is the only reason to record a decision
		rather than just its outcome."""
		block = self._payload_block()
		for key in _DECISION_STAMP:
			with self.subTest(key=key):
				self.assertNotIn(f"{key}:", block)
