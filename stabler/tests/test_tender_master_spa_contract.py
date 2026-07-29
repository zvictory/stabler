"""Source-level guardrails for the Tender CRM SPA boundary."""

from pathlib import Path
import unittest


TENDER_CRM = Path(__file__).parents[1] / "public/js/pages/tender/TenderCrm.vue"


class TestTenderMasterSpaContract(unittest.TestCase):
	def test_tender_crm_stays_inside_spa_and_uses_parent_api(self):
		source = TENDER_CRM.read_text()
		self.assertIn("stabler.api.tender_master.list_tender_masters", source)
		self.assertIn("stabler.api.tender_master.get_tender_master", source)
		self.assertIn("/tender/po-control", source)
		self.assertNotIn("/app/", source)
		self.assertNotIn("table-striped", source)
