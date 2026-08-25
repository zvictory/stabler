"""Behaviour contract for the tender intake payload (ADR-202 / 203 / 205).

`save_deal_intake` stores one JSON blob on `CRM Deal.custom_tender_intake`, and
two different screens write to it: `TenderMasterDrawer.vue` (the kanban drawer)
and `TenderIntake.vue` (the PO board panel). Neither sends the whole blob — each
sends the fields it owns. Until this module existed, `_clean_intake` rebuilt the
stored JSON from the whitelists alone, so **every key the sender left out was
cleared**: opening the drawer on a tender and pressing Save wiped the lot number,
the guarantee, the Go/No-Go decision and the document checklist that the other
screen had entered. That is defect #1 and defect #2 of the design-board decision
(`docs/plans/2026-08-17-mikas-tender-workflow-formlari-tasarim-kurulu-karari.md`).

The three rules pinned here:

* **PATCH, not PUT** (ADR-202/3) — an *absent* key keeps its stored value; a key
  that is *present and empty* still clears, because otherwise a user could never
  empty a field they once filled.
* **The contract is visible** (ADR-202/2) — a key the server does not carry is
  reported instead of dropped. A form that says "saved" and did not save costs
  more than one that refuses.
* **One deadline name** (ADR-203) — `bid_deadline`. `submission_deadline` is the
  drawer's old key and is tolerated on *read* for one release, so a browser still
  running the previous bundle does not lose its deadline chip mid-deploy.

Pure on purpose — no Frappe doubles. `_clean_intake` needs `frappe.utils.now()`
for its document-audit stamp (bound to `frappe.local`, which a site-free process
never binds), so each test patches only `tender.now` and restores it in
`tearDown`, the same discipline `test_tender_intake_master_fields.py` uses.
`frappe.session.user` is sidestepped via the `audit_actor` parameter.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_intake_contract -v
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import stabler.api.tender as tender

_ACTOR = "test@example.com"
_NOW = "2026-08-10 10:00:00"
_LATER = "2026-08-24 12:00:00"

ROOT = Path(__file__).resolve().parents[1]


def _clean(payload: dict, prior: dict | None = None) -> dict:
	"""`_clean_intake` then the exact JSON round trip `save_deal_intake` /
	`deal_intake` perform via `frappe.db.set_value` + `_parse_intake`."""
	cleaned = tender._clean_intake(payload, prior or {}, audit_actor=_ACTOR)
	return tender._parse_intake(json.dumps(cleaned, ensure_ascii=False))


class _PatchedNow(unittest.TestCase):
	def setUp(self):
		self._orig_now = tender.now
		tender.now = lambda: _NOW

	def tearDown(self):
		tender.now = self._orig_now


# --------------------------------------------------------------------------- #
# ADR-202/3 — partial save keeps what it did not send
# --------------------------------------------------------------------------- #
class TestAPartialSaveKeepsWhatItDidNotSend(_PatchedNow):
	def _stored(self) -> dict:
		"""A tender as the two screens between them have filled it in."""
		return _clean(
			{
				"lot_no": "LOT-7",
				"buyer": "Uzbekgidroenergo",
				"bid_deadline": "2026-09-01",
				"guarantee_amount": "1500000",
				"cert_required": 1,
				"go_no_go": "go",
				"notes": "call the buyer before the site visit",
			}
		)

	def test_a_payload_that_only_carries_items_keeps_the_go_no_go_decision(self):
		"""The decision-board's own named hook (ADR-202 test kancası).

		The Go/No-Go is a management decision with an audit stamp. The drawer
		never shows it and never sends it — so under the old rebuild-from-scratch
		rule, saving item lines in the drawer silently revoked a director's
		decision and erased who made it and when."""
		out = _clean({"items": [{"item_code": "RAIL-01", "qty": 2, "rate": 10}]}, prior=self._stored())
		self.assertEqual(out["go_no_go"], "go")
		self.assertEqual(out["go_no_go_by"], _ACTOR)
		self.assertEqual(out["go_no_go_at"], _NOW)

	def test_an_absent_scalar_key_is_preserved_not_cleared(self):
		"""Defect #1: the drawer does not carry the lot-level fields at all, so
		every drawer save used to blank the sourcing user's work."""
		out = _clean({"title": "new title"}, prior=self._stored())
		self.assertEqual(out["lot_no"], "LOT-7")
		self.assertEqual(out["buyer"], "Uzbekgidroenergo")
		self.assertEqual(out["bid_deadline"], "2026-09-01")
		self.assertEqual(out["notes"], "call the buyer before the site visit")

	def test_an_absent_numeric_key_is_preserved_not_zeroed(self):
		"""A zeroed guarantee is worse than a cleared string: it reads as a real
		measurement ("no guarantee required") rather than as missing data."""
		out = _clean({"title": "new title"}, prior=self._stored())
		self.assertEqual(out["guarantee_amount"], 1500000.0)

	def test_an_absent_checkbox_keeps_its_stored_state(self):
		"""`cert_required` is the sharpest of the three: `1 if data.get(...)`
		cannot tell "the sender left it out" from "the user unticked it", so an
		absent key silently reads as *unticked* and drops a certificate
		requirement from the BPM branch."""
		out = _clean({"title": "new title"}, prior=self._stored())
		self.assertEqual(out["cert_required"], 1)

	def test_a_key_that_is_present_and_empty_still_clears_the_field(self):
		"""The other half of PATCH, and the reason absent/empty must differ: a
		user who typed a lot number by mistake has to be able to remove it."""
		out = _clean({"lot_no": ""}, prior=self._stored())
		self.assertEqual(out["lot_no"], "")
		self.assertEqual(out["buyer"], "Uzbekgidroenergo")

	def test_an_absent_decision_does_not_restamp_the_audit_trail(self):
		"""Preserving the decision must preserve *when it was made*. Re-stamping
		it on every unrelated save would make the audit trail say the director
		decided at the moment someone edited an item line."""
		prior = self._stored()
		tender.now = lambda: _LATER
		out = _clean({"lot_no": "LOT-7"}, prior=prior)
		self.assertEqual(out["go_no_go_at"], _NOW)


# --------------------------------------------------------------------------- #
# ADR-202/2 — the contract is visible; nothing is dropped in silence
# --------------------------------------------------------------------------- #
class TestTheContractIsVisible(unittest.TestCase):
	def test_a_key_the_contract_does_not_carry_is_reported(self):
		"""Defect #3 in one line: `title` sat outside the whitelist for months.
		Nothing failed, nothing logged — the field just read back as the
		customer's name forever. Naming the key is what makes that a five-minute
		bug instead of a five-month one."""
		self.assertEqual(tender.unknown_intake_keys({"lot_no": "L1", "budget": 5}), ["budget"])

	def test_every_field_the_two_intake_screens_send_is_accepted(self):
		"""Both writers, measured from source: `TenderMasterDrawer.vue`'s
		`intakePayload` and `TenderIntake.vue`'s `OWNED_FIELDS`. If rejection
		ever outruns the whitelist, the save the user presses does not fail
		quietly — it fails loudly, on every tender.

		The two sets are disjoint by design since ADR-201: one writer per key.
		`test_tender_intake_single_writer.py` is what holds them apart; this one
		only asks that their union is storable."""
		drawer = {
			"title",
			"tender_no",
			"source",
			"publication_date",
			"bid_deadline",
			"currency",
			"estimated_total",
			"items",
			"tender_files",
			# Section E, moved off the PO board by ADR-206.
			"go_no_go",
			"guarantee_amount",
			"guarantee_return",
			"penalty_pct_per_day",
			"cert_required",
			"purchase_method",
		}
		po_board = {
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
		}
		self.assertEqual(drawer & po_board, set(), "one writer per key (ADR-201)")
		self.assertEqual(tender.unknown_intake_keys(dict.fromkeys(drawer | po_board, "")), [])

	def test_the_previous_bundle_s_deadline_key_is_still_accepted(self):
		"""ADR-203's transition clause. A deploy swaps the API and the bundle at
		once, but a browser tab opened before it keeps the old bundle in memory —
		rejecting `submission_deadline` would turn every such tab's Save into an
		error until the user reloads."""
		self.assertEqual(tender.unknown_intake_keys({"submission_deadline": "2026-09-01"}), [])

	def test_server_owned_keys_are_ignored_rather_than_rejected(self):
		"""`_clean_intake` re-reads these from the prior payload and never from
		the browser, and three of its four callers hand it the *stored blob* as
		the payload (`_clean_intake(intake, intake)` at tender.py:1739 / :1907).
		Rejecting them would make the server throw on its own data."""
		self.assertEqual(tender.unknown_intake_keys({"assigned_to": "x", "submitted_at": "y"}), [])

	def test_save_deal_intake_rejects_the_payload_instead_of_dropping_keys(self):
		"""Source contract: the pure classifier above is only worth having if the
		endpoint actually calls it. End-to-end rejection is DB-bound and belongs
		to `make test-bench`; this assertion is what keeps the wiring from being
		deleted in between."""
		source = (ROOT / "api/tender.py").read_text(encoding="utf-8")
		start = source.index("def save_deal_intake(")
		body = source[start : source.index("\n@frappe.whitelist()", start)]
		self.assertIn("unknown_intake_keys(", body)
		self.assertIn("frappe.throw(", body)


# --------------------------------------------------------------------------- #
# ADR-205 — the checklist is not collateral damage of an intake save
# --------------------------------------------------------------------------- #
class TestTheDocumentChecklistSurvivesASaveThatNeverMentionedIt(_PatchedNow):
	def _with_documents(self) -> dict:
		return _clean(
			{
				"lot_no": "LOT-7",
				"documents": [
					{"key": "gtd", "label": "ГТД", "required": 1, "role": "customs"},
					{"key": "contract", "label": "Shartnoma", "required": 1},
				],
			}
		)

	def test_an_absent_documents_key_preserves_the_checklist(self):
		"""Defect #2, exactly: the drawer sent `documents: []` on every save, and
		an empty list rebuilt the checklist as empty — deleting the requirement
		rows, their uploaded files and their waiver justifications. The document
		centre calls itself the single source of truth; this is what makes that
		claim true."""
		prior = self._with_documents()
		self.assertEqual(len(prior["documents"]), 2)
		out = _clean({"lot_no": "LOT-7"}, prior=prior)
		self.assertEqual([d["key"] for d in out["documents"]], ["gtd", "contract"])

	def test_an_explicit_empty_list_still_clears_the_checklist(self):
		"""`TenderIntake.vue` is a real template editor (`rmDoc()` at :125), so
		"the client sent an empty list" has to keep meaning "the user removed
		every row" — the same present-replaces/absent-preserves rule the item
		lines already follow."""
		out = _clean({"documents": []}, prior=self._with_documents())
		self.assertEqual(out["documents"], [])


# --------------------------------------------------------------------------- #
# ADR-203 — one deadline name
# --------------------------------------------------------------------------- #
class TestOneDeadlineName(unittest.TestCase):
	def test_the_bid_milestone_reads_the_old_key_when_the_new_one_is_absent(self):
		"""Defect #4: the drawer wrote `submission_deadline`, the deadline
		timeline read `bid_deadline`, and nothing joined them — so a tender
		entered through the drawer showed "not set" on its bid milestone and
		never raised an SLA warning, however close the deadline was."""
		self.assertEqual(tender._intake_bid_deadline({"submission_deadline": "2026-09-01"}), "2026-09-01")

	def test_the_new_key_wins_when_a_record_carries_both(self):
		"""Records written before the transition carry both. `bid_deadline` is
		the one the PO board still edits, so it is the fresher fact."""
		both = {"bid_deadline": "2026-09-05", "submission_deadline": "2026-09-01"}
		self.assertEqual(tender._intake_bid_deadline(both), "2026-09-05")

	def test_a_record_with_neither_key_reads_as_not_set(self):
		"""`_milestone()` distinguishes "no date" from "a date in the past"; a
		falsy sentinel here must stay falsy rather than become the epoch."""
		self.assertEqual(tender._intake_bid_deadline({}), "")


# --------------------------------------------------------------------------- #
# ADR-202/1 — the uploaded tender files reach storage
# --------------------------------------------------------------------------- #
class TestTheUploadedTenderFilesReachStorage(_PatchedNow):
	@staticmethod
	def _files() -> list[dict]:
		return [{"file_name": "lot.pdf", "file_url": "/files/lot.pdf", "file_size": 2048}]

	def test_uploaded_files_survive_the_round_trip(self):
		"""The drawer uploads the tender pack, sends it as `tender_files`
		(:274) and reads it back on the next open (:175). The key was in neither
		whitelist, so the read-back was always empty and the upload list looked
		like it had never happened."""
		out = _clean({"tender_files": self._files()})
		self.assertEqual(
			out["tender_files"], [{"file_name": "lot.pdf", "file_url": "/files/lot.pdf", "file_size": 2048.0}]
		)

	def test_an_absent_tender_files_key_preserves_the_uploads(self):
		"""Same PATCH rule as everything else: the PO board panel never sends
		this key, and saving there must not detach the tender pack."""
		prior = _clean({"tender_files": self._files()})
		out = _clean({"lot_no": "LOT-7"}, prior=prior)
		self.assertEqual(len(out["tender_files"]), 1)

	def test_a_row_without_a_url_is_not_a_file(self):
		"""A row with no `file_url` cannot be downloaded or attached to anything.
		Storing it would put a permanently broken link in the drawer's file list
		and in every later read of the tender pack."""
		out = _clean({"tender_files": [{"file_name": "ghost.pdf"}]})
		self.assertEqual(out["tender_files"], [])


if __name__ == "__main__":
	unittest.main()
