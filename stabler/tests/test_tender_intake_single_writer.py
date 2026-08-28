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
against the code, that stranded thirteen keys, so this slice delivered
ADR-201's *purpose* — no key with two writers — and left them editable here
until they had somewhere else to go.

The document checklist was the thirteenth, and it left on 2026-08-28: the
document centre grew a requirement writer
(`tender_documents.set_tender_document_requirements`), the checklist stopped
being editable here, and `documents` left the intake contract entirely — the
backend now ignores the key rather than merging it. Twelve remain, waiting on
ADR-209's form-layer slice.

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
# The twelve with no other home. `documents` was the thirteenth until the
# document centre could author a requirement row (2026-08-28).
_PO_BOARD_OWNED = (
	"lot_no",
	"buyer",
	"volume",
	"unit",
	"delivery_deadline",
	"result",
	"won_price",
	"notes",
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

	def test_the_twelve_with_no_other_home_stay_editable_here(self):
		"""ADR-201 says this panel loses its edit rights. Applied literally
		today it would leave these twelve editable on no screen at all, so
		they deliberately keep their inputs."""
		for field in _PO_BOARD_OWNED:
			with self.subTest(field=field):
				self.assertTrue(_bound(INTAKE, field))

	def test_the_checklist_is_no_longer_authored_here(self):
		"""ADR-201's document half, closed 2026-08-28.

		It stayed open for one reason: `tender_documents.py` could attach a
		file to a requirement but could not create one, so deleting these
		functions would have left the checklist un-creatable anywhere in the
		app. `set_tender_document_requirements` removed that reason.

		What is pinned is the *writer count*, not the deletion. A checklist
		row carries a role gate — a customs requirement may only be created,
		renamed or dropped by a declarant — and a second authoring surface is
		a second place for that gate to be forgotten."""
		for fn in ("function seedDocs(", "function addDoc(", "function rmDoc("):
			with self.subTest(fn=fn):
				self.assertNotIn(fn, INTAKE)

	def test_it_no_longer_calls_the_document_write_endpoints_either(self):
		"""Upload and waiver were never a second *writer* — they called the
		same endpoints the document centre calls. They go anyway: a screen
		that can attach a file to a row it cannot name is a half-surface, and
		the readiness badge here links to the centre that owns all of it."""
		for endpoint in (
			"upload_tender_document",
			"remove_tender_document",
			"waive_tender_document",
			"set_tender_document_requirements",
		):
			with self.subTest(endpoint=endpoint):
				# The dotted call path, not the bare name: the header comment
				# names the new writer on purpose, and a screen that explains
				# where its checklist went is the opposite of the defect here.
				self.assertNotIn(f"stabler.api.tender_documents.{endpoint}", INTAKE)

	def test_the_checklist_is_still_readable_here(self):
		"""The other half of the decision, and the reason this is not simply
		a deletion. A sourcing user on the PO board has to see that the ГТД is
		still missing without leaving the board — they just no longer type it
		here. Losing the summary would trade one defect for a worse one."""
		self.assertIn("intake.documents.length", INTAKE)
		self.assertIn("/tender/documents?deal=", INTAKE)


class TestTheChecklistHasExactlyOneWriter(unittest.TestCase):
	"""The ratchet that replaces ADR-201's reopening condition, now that the
	condition has come true.

	The old ratchet counted the document centre's endpoints and failed on the
	seventh, because a seventh endpoint was the signal that the centre might
	have learned to author a requirement. It has, so counting endpoints now
	only produces false alarms. What is worth failing on is the thing the move
	bought: exactly one place in the app writes a checklist row, and it is
	behind the per-row role gate.

	Both directions matter. A second writer reappearing is the defect this
	whole module exists for; the sole writer disappearing would leave the
	checklist un-creatable again — the state that kept ADR-201 open for eleven
	days.
	"""

	API = (_APP / "api/tender_documents.py").read_text(encoding="utf-8")
	SPA = _APP / "public/js"

	def test_the_document_centre_is_the_writer(self):
		self.assertRegex(self.API, r"@frappe\.whitelist\(\)\s*\ndef set_tender_document_requirements\(")

	def test_exactly_one_screen_calls_it(self):
		"""Grepped over the whole SPA, not just the two screens this module
		reads — a third screen embedding a checklist editor is exactly the
		regression that would slip past a two-file assertion."""
		wire = "stabler.api.tender_documents.set_tender_document_requirements"
		callers = sorted(
			f.relative_to(self.SPA).as_posix()
			for f in self.SPA.rglob("*.vue")
			if wire in f.read_text(encoding="utf-8")
		)
		self.assertEqual(callers, ["pages/tender/TenderDocuments.vue"], f"yazar kümesi: {callers}")

	def test_the_intake_endpoint_refuses_to_be_a_second_writer(self):
		"""The backend half. `save_deal_intake` used to merge a client
		`documents` list, which is how a stale browser tab could delete a
		checklist together with its uploads and waivers. It now carries the
		stored value through whatever the payload says."""
		tender = (_APP / "api/tender.py").read_text(encoding="utf-8")
		clean = tender[tender.index("def _clean_intake(") :]
		clean = clean[: clean.index("\ndef ", 1)]
		# Read the code, not the prose. The comment above the line names
		# `merge_client_requirements` to say where the reconciliation moved to,
		# and an assertion that cannot tell a comment from a call would force
		# that explanation out of the file.
		code = "\n".join(ln for ln in clean.splitlines() if not ln.lstrip().startswith("#"))
		self.assertIn('out["documents"] = parse_doc_requirements(prior.get("documents"))', code)
		self.assertNotIn("merge_client_requirements", code)
		self.assertNotIn('data.get("documents")', code)


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
