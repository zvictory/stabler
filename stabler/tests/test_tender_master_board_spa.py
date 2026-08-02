"""SPA Source contract test for Level 1 Tender Master Board (Section 1).

Validates component structure, endpoints called, design layer usage,
and router wiring.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_master_board_spa -v
"""

from __future__ import annotations

import os
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_ROUTER = os.path.join(_ROOT, "public", "js", "router.js")
_MASTER_BOARD = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderMasterBoard.vue")
_MASTER_DRAWER = os.path.join(_ROOT, "public", "js", "components", "TenderMasterDrawer.vue")
_TENDER_CRM = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderCrm.vue")


def _read(path: str) -> str:
	if not os.path.exists(path):
		return ""
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTenderMasterBoardSpaContract(unittest.TestCase):
	def test_master_board_file_exists_and_uses_design_layer(self):
		source = _read(_MASTER_BOARD)
		self.assertTrue(bool(source), "TenderMasterBoard.vue does not exist")
		self.assertIn("<TenderPage", source)

	def test_master_board_calls_required_api_endpoints(self):
		source = _read(_MASTER_BOARD)
		self.assertIn("stabler.api.tender_master.list_tender_masters", source)
		self.assertIn("stabler.api.tender_master.orphan_tender_lots", source)

	def test_master_drawer_calls_save_endpoint(self):
		source = _read(_MASTER_DRAWER)
		self.assertTrue(bool(source), "TenderMasterDrawer.vue does not exist")
		self.assertIn("stabler.api.tender_master.save_tender_master", source)

	def test_router_wires_tender_crm_level1(self):
		source = _read(_ROUTER)
		self.assertIn("TenderMasterBoard", source)
		self.assertIn('path: "/tender/crm"', source)

	def test_tender_crm_includes_breadcrumb_navigation(self):
		source = _read(_TENDER_CRM)
		self.assertIn('to="/tender/crm"', source)


if __name__ == "__main__":
	unittest.main()
