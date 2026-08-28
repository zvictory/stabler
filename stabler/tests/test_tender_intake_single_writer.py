"""One writer per intake field (ADR-201).

`save_deal_intake` stores a single JSON blob and two screens write to it: the
kanban drawer (`TenderMasterDrawer.vue`) and the PO control board's panel
(`TenderIntake.vue`, embedded at `PoControlBoard.vue:368`). Before slice 1 the
server rebuilt that blob from the whitelist on every save, so whichever screen
saved last erased what the other had entered — defect #1 and #2 of the
design-board decision.

Slice 1 made the endpoint PATCH: an absent key keeps its stored value. That
turned "the other screen wipes my work" into a *contract* question — who owns
which key — and this module is where that answer lives.

ADR-201 as written retires `TenderIntake.vue`'s edit rights entirely. Measured
against the code, that strands thirteen keys: only this screen edits `lot_no`,
`buyer`, `volume`, `unit`, `delivery_deadline`, `result`, `won_price`, `notes`,
the four `fx_*` keys and the document checklist, and the drawer has no section
for any of them (that is ADR-209's form-layer slice, not this one). So this
slice delivers ADR-201's *purpose* — no key with two writers — and leaves the
thirteen editable here until they have somewhere else to go.

Pure source assertions: no bundle, no browser, no DB. What is being pinned is a
division of ownership, and ownership is readable in the source.
"""

import re
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]
INTAKE = (_APP / "public/js/pages/tender/TenderIntake.vue").read_text(encoding="utf-8")
DRAWER = (_APP / "public/js/components/TenderMasterDrawer.vue").read_text(encoding="utf-8")

# The seven the drawer took over in slices 1 and 2 (ADR-203 + ADR-206).
_DRAWER_OWNED = (
	"bid_deadline",
	"guarantee_amount",
	"guarantee_return",
	"cert_required",
	"penalty_pct_per_day",
	"go_no_go",
	"purchase_method",
)
# The thirteen with no other home. `documents` has no `v-model` of its own —
# it is edited row by row through seedDocs/addDoc/rmDoc.
_PO_BOARD_OWNED = (
	"lot_no",
	"buyer",
	"volume",
	"unit",
	"delivery_deadline",
	"result",
	"won_price",
	"notes",
	"documents",
	"fx_currency",
	"fx_amount",
	"fx_bid_rate",
	"fx_pay_rate",
)


def _owned_fields() -> list[str]:
	"""The list `TenderIntake.vue` declares as the fields it owns."""
	m = re.search(r"const OWNED_FIELDS = \[(.*?)\];", INTAKE, re.S)
	return re.findall(r'"(\w+)"', m.group(1)) if m else []


def _bound(source: str, field: str) -> bool:
	return bool(re.search(rf'v-model[.\w]*="intake\.{field}"', source))


class TestTheTwoScreensNoLongerWriteTheSameField(unittest.TestCase):
	def test_the_screen_declares_what_it_owns_in_one_place(self):
		"""A payload assembled inline drifts from the template that feeds it.
		Naming the set once is what lets the two assertions below be true at
		the same time — and what makes the next person's addition a decision
		rather than an accident."""
		self.assertEqual(sorted(_owned_fields()), sorted(_PO_BOARD_OWNED))

	def test_it_does_not_send_the_seven_the_drawer_owns(self):
		"""This is the whole point. Both screens read the same blob, and this
		one is embedded in a board a user can leave open for hours. Sending
		its copy of `go_no_go` back means a decision recorded in the drawer at
		11:00 is silently replaced by the 09:00 value at 11:05 — defect #1
		again, no longer as a wipe but as a rollback, which is worse because
		the field still looks filled."""
		owned = set(_owned_fields())
		for field in _DRAWER_OWNED:
			with self.subTest(field=field):
				self.assertNotIn(field, owned)

	def test_it_no_longer_spreads_the_whole_reactive_into_the_payload(self):
		"""`JSON.stringify({ ...intake })` sends all twenty keys whatever the
		list above says. The list is only a contract if the payload is built
		from it."""
		save = INTAKE[INTAKE.index("async function save()") :]
		save = save[: save.index("\n}")]
		self.assertNotIn("...intake", save)
		self.assertIn("OWNED_FIELDS", save)


class TestTheFieldsItStoppedSendingAreAlsoNoLongerEditable(unittest.TestCase):
	"""Removing a key from the payload without removing its input is the worst
	of the three states: the user types, presses Save, is told it saved, and
	the value is gone on reload. A form that refuses is cheaper than a form
	that lies."""

	def test_no_input_remains_bound_to_a_field_the_drawer_owns(self):
		for field in _DRAWER_OWNED:
			with self.subTest(field=field):
				self.assertFalse(_bound(INTAKE, field))

	def test_each_of_them_is_editable_in_the_drawer_instead(self):
		"""The other half — the fields have to be editable *somewhere*. This is
		what separates this slice from simply deleting the controls.

		Measured on the drawer's payload, not on its `form` keys: ADR-203
		renamed the wire key to `bid_deadline` while the drawer's own field is
		still called `submission_deadline`. That is internal naming, and the
		contract is what crosses the wire."""
		payload = DRAWER[DRAWER.index("const intakePayload = {") :]
		payload = payload[: payload.index("await call(")]
		for field in _DRAWER_OWNED:
			with self.subTest(field=field):
				self.assertIn(f"{field}:", payload)

	def test_the_thirteen_with_no_other_home_stay_editable_here(self):
		"""ADR-201 says this panel loses its edit rights. Applied literally
		today it would leave these thirteen editable on no screen at all, so
		they deliberately keep their inputs."""
		for field in _PO_BOARD_OWNED:
			if field == "documents":
				continue  # edited row by row, not through a v-model
			with self.subTest(field=field):
				self.assertTrue(_bound(INTAKE, field))

	def test_the_document_checklist_is_still_authored_here_by_decision(self):
		"""Decided 2026-08-28 by Zafar, not conceded.

		`tender_documents.py` can attach a file to a requirement but cannot
		create one — seedDocs/addDoc are the only code anywhere that writes a
		requirement row. Deleting them would not close ADR-201 either: the
		file and waiver buttons on this screen call the same three endpoints
		the document centre calls, so they are one writer reached from two
		screens, not two writers. Closing the document half needs a
		requirement writer in the document centre; that is the reopening
		condition below, and it is not worth building for a tenant with zero
		tenders."""
		self.assertIn("function seedDocs()", INTAKE)
		self.assertIn("function addDoc()", INTAKE)


class TestTheReopeningConditionIsExecutable(unittest.TestCase):
	"""ADR-201's document half stays open on a condition, and a condition that
	lives only in prose is the defect this repository keeps paying for — four
	times in one session on 2026-08-28 alone. So the condition is a ratchet.

	`tender_documents.py` ships exactly these six endpoints. The day it grows a
	seventh, someone is extending the document centre, and that is precisely
	when to ask whether it now authors requirement rows — because if it does,
	`TenderIntake.vue` must stop, and `documents` leaves the intake contract.
	This fails on the seventh endpoint whatever it turns out to be: a false
	alarm costs one line here, and the alternative is the condition going
	unnoticed exactly when it comes true.
	"""

	_KNOWN = (
		"list_tender_documents",
		"upload_tender_document",
		"waive_tender_document",
		"remove_tender_document",
		"download_tender_document",
		"tender_document_targets",
	)

	def test_the_document_centre_still_cannot_author_a_requirement(self):
		src = (_APP / "api/tender_documents.py").read_text(encoding="utf-8")
		found = re.findall(r"@frappe\.whitelist\([^)]*\)\s*\ndef (\w+)\(", src)
		self.assertTrue(found, "desen tutmuyor: tender_documents.py'de hiç uç bulunamadı")
		self.assertEqual(
			sorted(found),
			sorted(self._KNOWN),
			"tender_documents.py'nin uç kümesi değişti. Yeni uç bir gereklilik "
			"satırı yazıyorsa ADR-201'in belge yarısı artık kapatılabilir: "
			"TenderIntake.vue'nun seedDocs/addDoc/rmDoc'u kaldırılmalı ve "
			"`documents` intake sözleşmesinden çıkmalı. Yazmıyorsa yalnız "
			"yukarıdaki listeyi güncelle.",
		)


class TestTheDecisionIsStillVisibleWhereItIsNoLongerEditable(unittest.TestCase):
	"""ADR-201's read-only summary: deadline, guarantee, FX and Go/No-Go. A
	sourcing user on the PO board needs to *see* the bid guarantee is due back
	next week; they just no longer type it here."""

	def test_the_summary_reads_the_decision_and_the_guarantee(self):
		summary = INTAKE[INTAKE.index("<template>") : INTAKE.index('v-if="editing"')]
		for field in ("go_no_go", "guarantee_amount", "guarantee_return"):
			with self.subTest(field=field):
				self.assertIn(f"intake.{field}", summary)

	def test_the_guarantee_is_formatted_in_the_user_s_language(self):
		"""Four of the five shipped languages group thousands with a space and
		use a decimal comma. `formatMoney` defaults to en-US when the language
		is left out, so an omitted argument does not fail — it quietly prints
		one number on this screen in a format the rest of the screen does not
		use."""
		self.assertIn("formatMoney(intake.guarantee_amount, currency, user.language)", INTAKE)

	def test_it_says_where_the_fields_went(self):
		"""A control that disappears with no explanation reads as a bug, and
		the user's next move is to file one."""
		self.assertIn("Edited in the tender drawer", INTAKE)
