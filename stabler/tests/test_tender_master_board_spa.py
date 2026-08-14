"""SPA Source contract test for Single-Level Tender CRM (Flat Architecture).

Validates that:
- TenderCrmWrapper unconditionally renders TenderCrm
- TenderMasterBoard.vue and tenderMaster.js do not exist in the repository
- TenderCrm has a New tender button mounting TenderMasterDrawer
- TenderCrm handles ?deal= deep link
- Router wires /tender/crm

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_master_board_spa -v
"""

from __future__ import annotations

import os
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_ROUTER = os.path.join(_ROOT, "public", "js", "router.js")
_WRAPPER = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderCrmWrapper.vue")
_MASTER_BOARD = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderMasterBoard.vue")
_MASTER_COMPOSABLE = os.path.join(_ROOT, "public", "js", "composables", "tenderMaster.js")
_MASTER_DRAWER = os.path.join(_ROOT, "public", "js", "components", "TenderMasterDrawer.vue")
_TENDER_CRM = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderCrm.vue")


def _read(path: str) -> str:
	if not os.path.exists(path):
		return ""
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTenderMasterBoardSpaContract(unittest.TestCase):
	def test_wrapper_renders_tender_crm_unconditionally(self):
		source = _read(_WRAPPER)
		self.assertTrue(bool(source), "TenderCrmWrapper.vue does not exist")
		self.assertIn("<TenderCrm />", source)
		self.assertNotIn("TenderMasterBoard", source)
		self.assertNotIn("route.query?.tender", source)

	def test_deleted_level1_artifacts_do_not_exist(self):
		self.assertFalse(os.path.exists(_MASTER_BOARD), "TenderMasterBoard.vue should be deleted")
		self.assertFalse(os.path.exists(_MASTER_COMPOSABLE), "tenderMaster.js should be deleted")

	def test_tender_crm_has_new_tender_button_and_drawer(self):
		source = _read(_TENDER_CRM)
		self.assertTrue(bool(source), "TenderCrm.vue does not exist")
		self.assertIn("New tender", source)
		self.assertIn("TenderMasterDrawer", source)

	def test_tender_crm_handles_deal_deep_link(self):
		source = _read(_TENDER_CRM)
		self.assertIn("route.query?.deal", source)

	def test_master_drawer_calls_save_deal(self):
		source = _read(_MASTER_DRAWER)
		self.assertTrue(bool(source), "TenderMasterDrawer.vue does not exist")
		self.assertIn("stabler.api.crm.save_deal", source)

	def test_router_wires_tender_crm(self):
		source = _read(_ROUTER)
		self.assertIn("TenderCrm", source)
		self.assertIn('path: "/tender/crm"', source)


if __name__ == "__main__":
	unittest.main()
