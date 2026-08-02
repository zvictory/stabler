"""Frappe-free unit tests for Tender Document Requirements & Derived Completion (B1).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_documents_api -v
"""

from __future__ import annotations

import unittest

from stabler.api._tender_documents import docs_summary, parse_doc_requirements


class TestTenderDocumentsRules(unittest.TestCase):
	def test_derived_done_from_uploaded_files(self):
		raw = [
			{
				"key": "gtd",
				"label": "Customs Declaration (ГТД)",
				"required": True,
				"scope": "lot",
				"files": [
					{
						"file_name": "gtd_2026.pdf",
						"file_url": "/private/files/gtd_2026.pdf",
						"uploaded_by": "declarant@acme.uz",
					}
				],
			}
		]
		reqs = parse_doc_requirements(raw)
		self.assertEqual(len(reqs), 1)
		doc = reqs[0]
		self.assertTrue(doc["done"])
		self.assertFalse(doc["unverified"])
		self.assertEqual(doc["file_count"], 1)
		self.assertEqual(doc["latest_file"]["file_name"], "gtd_2026.pdf")

	def test_derived_done_from_written_waiver(self):
		raw = [
			{
				"key": "cert",
				"label": "Origin Certificate",
				"required": True,
				"scope": "lot",
				"waiver_reason": "Approved by client buyer under waiver protocol #42",
				"waived_by": "manager@acme.uz",
				"waived_at": "2026-08-02T12:00:00Z",
			}
		]
		reqs = parse_doc_requirements(raw)
		self.assertEqual(len(reqs), 1)
		doc = reqs[0]
		self.assertTrue(doc["done"])
		self.assertFalse(doc["unverified"])
		self.assertEqual(doc["file_count"], 0)
		self.assertEqual(doc["waiver_reason"], "Approved by client buyer under waiver protocol #42")

	def test_legacy_manually_ticked_item_becomes_unverified(self):
		raw = [
			{
				"key": "contract",
				"label": "Signed Contract",
				"required": True,
				"done": True,  # Legacy manual tick
				"files": [],
				"waiver_reason": None,
			}
		]
		reqs = parse_doc_requirements(raw)
		self.assertEqual(len(reqs), 1)
		doc = reqs[0]
		# K3: legacy manual tick without files or waiver becomes unverified
		self.assertTrue(doc["unverified"])
		self.assertFalse(doc["done"])

	def test_docs_summary_metrics(self):
		raw = [
			{
				"key": "gtd",
				"label": "Customs Declaration (ГТД)",
				"required": True,
				"files": [{"file_name": "gtd.pdf"}],
			},
			{
				"key": "cert",
				"label": "Certificate",
				"required": True,
				"waiver_reason": "Waived",
			},
			{
				"key": "act",
				"label": "Acceptance Act",
				"required": True,
				"done": True,  # Unverified legacy
			},
			{
				"key": "invoice",
				"label": "Commercial Invoice",
				"required": True,
			},
		]
		reqs = parse_doc_requirements(raw)
		summary = docs_summary(reqs)

		self.assertEqual(summary["total"], 4)
		self.assertEqual(summary["required"], 4)
		self.assertEqual(summary["done_required"], 2)  # gtd + cert
		self.assertEqual(summary["unverified"], 1)  # act
		self.assertEqual(summary["missing"], ["Acceptance Act", "Commercial Invoice"])
		self.assertEqual(summary["readiness_pct"], 50)


if __name__ == "__main__":
	unittest.main()
