"""Who may author a document requirement row, and what they may not touch.

Until 2026-08-28 the checklist template had exactly one author in the whole
app: `TenderIntake.vue`'s `seedDocs`/`addDoc`, writing through the intake JSON
blob. The document centre could attach a file to a requirement but could not
create one — so ADR-201 ("the PO board panel loses its edit rights") could not
be applied without making the checklist un-creatable. That was recorded as the
ADR's reopening condition; this module is that condition coming true.

The requirement writer moves to the document centre, and the reconciliation
rule moves with it: a browser owns **label / required / date / role** and
nothing else. Files, waiver justifications and the derived done/unverified
flags are server facts. A template edit that trusted the browser's `done`
would let anyone mark a customs declaration satisfied by typing, which is the
whole reason the upload/waive endpoints exist.

Pure on purpose — the reconciliation is frappe-free, so it is tested without a
bench and cannot pass for a framework reason.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_document_requirements -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from stabler.api._tender_documents import merge_client_requirements

_APP = Path(__file__).resolve().parents[1]
API = (_APP / "api/tender_documents.py").read_text(encoding="utf-8")


def _prior_row(**over):
	base = {
		"key": "gtd",
		"label": "Customs Declaration",
		"required": True,
		"role": "customs",
		"scope": "lot",
		"date": "",
		"files": [{"file_name": "gtd.pdf", "file_url": "/private/files/gtd.pdf"}],
		"waiver_reason": "",
		"waived_by": "",
		"waived_at": "",
	}
	base.update(over)
	return base


class TestTheBrowserOwnsTheTemplateAndNothingElse(unittest.TestCase):
	def test_renaming_a_requirement_keeps_its_uploaded_file(self):
		"""The point of moving the writer here. A template edit that dropped
		files would re-create defect #2 in the new home: the declarant's
		uploaded ГТД disappears because someone fixed a typo in the label."""
		out = merge_client_requirements(
			[{"key": "gtd", "label": "Customs Declaration (ГТД)", "required": True, "role": "customs"}],
			[_prior_row()],
		)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["label"], "Customs Declaration (ГТД)")
		self.assertEqual([f["file_url"] for f in out[0]["files"]], ["/private/files/gtd.pdf"])
		self.assertTrue(out[0]["done"], "dosyası duran gereklilik hâlâ karşılanmış olmalı")

	def test_a_waiver_survives_a_template_edit(self):
		"""A waiver is a written justification with an author and a timestamp —
		an audit fact, not a checkbox. Re-typing the label must not erase it."""
		out = merge_client_requirements(
			[{"key": "cert", "label": "Certificate of origin", "required": True}],
			[
				_prior_row(
					key="cert",
					label="Certificate",
					files=[],
					waiver_reason="supplier is EU-registered",
					waived_by="sourcing@acme.uz",
					waived_at="2026-08-01 10:00:00",
				)
			],
		)
		self.assertEqual(out[0]["waiver_reason"], "supplier is EU-registered")
		self.assertEqual(out[0]["waived_by"], "sourcing@acme.uz")
		self.assertTrue(out[0]["done"], "muafiyetli gereklilik karşılanmış sayılır")

	def test_a_new_row_starts_unsatisfied_however_the_browser_labels_it(self):
		"""`done` is derived, never accepted. Otherwise the template editor is
		a way to mark every requirement complete without uploading anything."""
		out = merge_client_requirements(
			[
				{
					"key": "invoice",
					"label": "Commercial invoice",
					"required": True,
					"done": True,
					"files": [{"file_name": "forged.pdf", "file_url": "/private/files/forged.pdf"}],
					"waiver_reason": "trust me",
				}
			],
			[],
		)
		self.assertEqual(out[0]["files"], [])
		self.assertFalse(out[0]["done"])
		self.assertFalse(out[0].get("waiver_reason"))

	def test_dropping_a_row_removes_it(self):
		"""`rmDoc` has to keep meaning what it meant on the old screen."""
		out = merge_client_requirements(
			[{"key": "gtd", "label": "Customs Declaration", "required": True}],
			[_prior_row(), _prior_row(key="cert", label="Certificate", files=[])],
		)
		self.assertEqual([r["key"] for r in out], ["gtd"])

	def test_an_empty_row_is_ignored_not_stored(self):
		"""`addDoc` appends a blank line the user may never fill in. A blank
		requirement counts against readiness while naming nothing to upload."""
		out = merge_client_requirements([{"key": "", "label": "   "}], [])
		self.assertEqual(out, [])

	def test_the_same_key_twice_collapses(self):
		out = merge_client_requirements(
			[
				{"key": "gtd", "label": "First", "required": True},
				{"key": "gtd", "label": "Second", "required": False},
			],
			[],
		)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["label"], "First")


class TestTheEndpointIsGatedLikeTheOthers(unittest.TestCase):
	"""Source assertions: the write gate is the reason this endpoint is safe to
	expose, and a gate is easy to forget on the newest function in a module."""

	def _body(self) -> str:
		m = re.search(
			r"@frappe\.whitelist\(\)\s*\ndef set_tender_document_requirements\((.*?)\n@frappe\.whitelist\(\)",
			API + "\n@frappe.whitelist()",
			re.S,
		)
		self.assertIsNotNone(m, "set_tender_document_requirements bulunamadı")
		return m.group(1)

	def test_it_is_whitelisted(self):
		self.assertRegex(API, r"@frappe\.whitelist\(\)\s*\ndef set_tender_document_requirements\(")

	def test_it_loads_the_deal_with_a_write_permission_check(self):
		"""`_get_deal_and_master(..., "write")` is what applies company scope,
		the tender module gate and the CRM Deal write permission at once."""
		self.assertIn('_get_deal_and_master(deal, company, "write")', self._body())

	def test_it_applies_the_row_role_write_gate(self):
		"""Creating a customs row is a declarant/director act, the same as
		uploading to one. Without this a logist could author — and therefore
		silently retire — a customs requirement."""
		self.assertIn("_require_doc_role_write(", self._body())

	def test_it_refuses_to_write_a_master_scope_key(self):
		# A master-level requirement belongs to the parent tender and is shared
		# by every lot under it. This endpoint writes the lot list only, so a
		# payload naming a master key is refused rather than quietly writing a
		# lot row with the same key — two rows, one key, and `_resolve_target`
		# would then send uploads to the master one (ADR-202/2: reject, never
		# silently drop).
		body = self._body()
		self.assertIn(
			"custom_tender_documents",
			body,
			"uç, master'ın gereklilik listesini hiç okumuyor — çakışmayı göremez",
		)
		self.assertIn("frappe.throw", body)
		# And the lot list is what it writes: the master field must never be the
		# save target, or a lot edit would rewrite every sibling lot's checklist.
		self.assertIn('_save_requirements(deal_doc, "custom_tender_intake"', body)
		self.assertNotIn("_save_requirements(master_doc", body)
