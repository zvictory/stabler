import unittest
import os

class TestTenderCrmSpaSource(unittest.TestCase):
	def test_tender_crm_vue_file_exists(self):
		filepath = os.path.join(
			os.path.dirname(__file__), "..", "public", "js", "pages", "tender", "TenderCrm.vue"
		)
		self.assertTrue(os.path.exists(filepath))
		with open(filepath, "r", encoding="utf-8") as f:
			content = f.read()
		self.assertIn("stabler.api.tender.crm_board", content)
		self.assertIn("stabler.api.tender.move_deal_stage", content)
		self.assertIn("viewMode", content)
		self.assertIn("drawerOpen", content)
