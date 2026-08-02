"""SPA Source contract tests for Tender Document Center (B3).

Enforces K5 (no raw file links, all downloads use gated API endpoint)
and validates router registration and component imports.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_documents_spa -v
"""

from __future__ import annotations

import os
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_ROUTER = os.path.join(_ROOT, "public", "js", "router.js")
_DOCS_PAGE = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderDocuments.vue")
_WORKSPACES_TABS = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderWorkspaceTabs.vue")


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTenderDocumentsSpaContract(unittest.TestCase):
	def test_route_is_registered_in_router(self):
		source = _read(_ROUTER)
		self.assertIn("TenderDocuments.vue", source)
		self.assertIn('path: "/tender/documents"', source)
		self.assertIn('name: "tender-documents"', source)

	def test_documents_tab_added_to_workspace_tabs(self):
		source = _read(_WORKSPACES_TABS)
		self.assertIn('key: "documents"', source)
		self.assertIn('t("Documents")', source)

	def test_k5_no_raw_file_links_in_documents_page(self):
		"""K5: SPA download links must pass through the gated API endpoint."""
		source = _read(_DOCS_PAGE)
		self.assertIn("stabler.api.tender_documents.download_tender_document", source)
		self.assertIn("getGatedDownloadUrl", source)
		# Ensure no direct un-gated "/files/" string concatenation is used for downloads
		self.assertNotIn('href="`/files/', source)
		self.assertNotIn('href="`/private/files/', source)


if __name__ == "__main__":
	unittest.main()
