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

	def test_role_parsing_and_defaulting(self):
		raw = [
			{"key": "gtd", "label": "GTD", "role": "customs"},
			{"key": "cmr", "label": "CMR", "role": "logistics"},
			{"key": "inv", "label": "Invoice", "role": "finance"},
			{"key": "spec", "label": "Spec", "role": "general"},
			{"key": "other", "label": "Other"},  # No role -> general
			{"key": "bad", "label": "Bad", "role": "invalid_role"},  # Invalid -> general
		]
		reqs = parse_doc_requirements(raw)
		self.assertEqual(reqs[0]["role"], "customs")
		self.assertEqual(reqs[1]["role"], "logistics")
		self.assertEqual(reqs[2]["role"], "finance")
		self.assertEqual(reqs[3]["role"], "general")
		self.assertEqual(reqs[4]["role"], "general")
		self.assertEqual(reqs[5]["role"], "general")

	def test_docs_summary_filtering_by_role(self):
		raw = [
			{
				"key": "gtd",
				"label": "GTD",
				"required": True,
				"role": "customs",
				"files": [{"file_name": "gtd.pdf"}],
			},
			{
				"key": "cert",
				"label": "Certificate",
				"required": True,
				"role": "customs",
			},  # missing customs doc
			{"key": "cmr", "label": "CMR", "required": True, "role": "logistics"},  # missing logistics doc
			{
				"key": "spec",
				"label": "Spec",
				"required": True,
				"role": "general",
				"files": [{"file_name": "spec.pdf"}],
			},
		]
		reqs = parse_doc_requirements(raw)

		# All roles
		all_summary = docs_summary(reqs)
		self.assertEqual(all_summary["total"], 4)
		self.assertEqual(all_summary["required"], 4)
		self.assertEqual(all_summary["done_required"], 2)

		# Customs role filter
		customs_summary = docs_summary(reqs, role="customs")
		self.assertEqual(customs_summary["total"], 2)
		self.assertEqual(customs_summary["required"], 2)
		self.assertEqual(customs_summary["done_required"], 1)
		self.assertEqual(customs_summary["missing"], ["Certificate"])
		self.assertEqual(customs_summary["readiness_pct"], 50)

		# Logistics role filter
		logistics_summary = docs_summary(reqs, role="logistics")
		self.assertEqual(logistics_summary["total"], 1)
		self.assertEqual(logistics_summary["required"], 1)
		self.assertEqual(logistics_summary["done_required"], 0)
		self.assertEqual(logistics_summary["missing"], ["CMR"])
		self.assertEqual(logistics_summary["readiness_pct"], 0)

	def test_standard_doc_requirements(self):
		from stabler.api._tender_documents import default_doc_requirements

		defaults = default_doc_requirements()
		self.assertGreaterEqual(len(defaults), 4)
		roles = {d["role"] for d in defaults}
		self.assertTrue({"customs", "logistics", "finance", "general"}.issubset(roles))


class TestTenderDocumentsApiSource(unittest.TestCase):
	def test_endpoints_are_defined_and_gated(self):
		import ast
		import os

		filepath = os.path.join(os.path.dirname(__file__), "..", "api", "tender_documents.py")
		with open(filepath, encoding="utf-8") as f:
			tree = ast.parse(f.read(), filename=filepath)

		funcs = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
		for name in (
			"list_tender_documents",
			"upload_tender_document",
			"waive_tender_document",
			"download_tender_document",
		):
			self.assertIn(name, funcs, f"Missing endpoint {name}")


if __name__ == "__main__":
	unittest.main()
