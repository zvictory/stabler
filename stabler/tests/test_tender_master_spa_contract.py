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

	def test_tender_crm_guards_stale_company_responses_and_keeps_optional_columns_absent(self):
		source = TENDER_CRM.read_text()
		self.assertGreaterEqual(source.count("isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)"), 2)
		self.assertIn('v-if="hasDocumentReadiness"', source)
		self.assertNotIn('<span v-else>—</span>', source)

	def test_tender_crm_uses_table_body_skeletons_and_shows_terminal_statuses_on_kanban_cards(self):
		source = TENDER_CRM.read_text()
		self.assertNotIn('<tbody>\n\t\t\t\t\t\t<SkeletonRows', source)
		self.assertIn('<div class="small text-secondary mt-1">{{ record.status }}</div>', source)
