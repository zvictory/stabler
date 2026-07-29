"""Source-level guardrails for the Tender CRM SPA boundary."""

import csv
import unittest
from pathlib import Path

TENDER_CRM = Path(__file__).parents[1] / "public/js/pages/tender/TenderCrm.vue"
ROUTER = Path(__file__).parents[1] / "public/js/router.js"
SIDEBAR = Path(__file__).parents[1] / "public/js/components/Sidebar.vue"
TENDER_NAV = Path(__file__).parents[1] / "public/js/pages/tender/TenderNav.vue"
CONTROL_TOWER = Path(__file__).parents[1] / "public/js/pages/tender/TenderControlTower.vue"
TRANSLATIONS = Path(__file__).parents[1] / "translations"
REQUIRED_KEYS = (
	"Tender CRM",
	"All tenders",
	"Lots",
	"Parent tender",
	"Bid Preparation",
	"Submission deadline",
	"No tenders found",
	"Back to all tenders",
	"Open lot workspace",
)


class TestTenderMasterSpaContract(unittest.TestCase):
	def test_tender_crm_route_and_navigation_are_wired(self):
		router = ROUTER.read_text()
		sidebar = SIDEBAR.read_text()
		nav = TENDER_NAV.read_text()
		self.assertIn('path: "/tender/crm"', router)
		self.assertIn('name: "tender-crm"', router)
		self.assertIn('path: "/tender/crm"', sidebar)
		self.assertIn('to="/tender/crm"', nav)
		self.assertIn("v-if=\"can('director') || can('sourcing')\"", nav)
		self.assertIn('{ view: "director", path: "/tender/crm"', sidebar)
		self.assertIn('{ view: "sourcing", path: "/tender/crm"', sidebar)

	def test_tender_crm_preserves_allowlisted_dashboard_query_filters(self):
		source = TENDER_CRM.read_text()
		control_tower = CONTROL_TOWER.read_text()
		self.assertIn('import { useRoute, useRouter } from "vue-router"', source)
		self.assertIn("...tenderMasterListParams(route.query)", source)
		self.assertIn("JSON.stringify(tenderMasterListParams(route.query))", source)
		self.assertIn('name: "tender-crm"', control_tower)
		self.assertIn("deal: item.deal", control_tower)
		attention = control_tower.split("function openAttention(item) {", 1)[1].split(
			"function attentionLabel", 1
		)[0]
		self.assertIn("...periodQuery.value", attention)
		self.assertIn("...periodQuery.value", control_tower)

	def test_tender_crm_required_localizations_exist_in_every_catalog(self):
		for language in ("en", "ru", "uz", "uzc", "tr"):
			with (TRANSLATIONS / f"{language}.csv").open(newline="") as handle:
				sources = {row[0] for row in csv.reader(handle) if row}
			self.assertTrue(set(REQUIRED_KEYS).issubset(sources), language)

	def test_tender_crm_stays_inside_spa_and_uses_parent_api(self):
		source = TENDER_CRM.read_text()
		self.assertIn("stabler.api.tender_master.list_tender_masters", source)
		self.assertIn("stabler.api.tender_master.get_tender_master", source)
		self.assertIn("/tender/po-control", source)
		self.assertNotIn("/app/", source)
		self.assertNotIn("table-striped", source)

	def test_tender_crm_guards_stale_company_responses_and_keeps_optional_columns_absent(self):
		source = TENDER_CRM.read_text()
		self.assertGreaterEqual(
			source.count("isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)"), 2
		)
		self.assertIn('v-if="hasDocumentReadiness"', source)
		self.assertNotIn("<span v-else>—</span>", source)

	def test_tender_crm_uses_table_body_skeletons_and_shows_terminal_statuses_on_kanban_cards(self):
		source = TENDER_CRM.read_text()
		self.assertNotIn("<tbody>\n\t\t\t\t\t\t<SkeletonRows", source)
		self.assertIn('<div class="small text-secondary mt-1">{{ record.status }}</div>', source)

	def test_closing_tender_detail_invalidates_pending_detail_requests(self):
		source = TENDER_CRM.read_text()
		close_detail = source.split("function closeDetail() {", 1)[1].split("}\n\nwatch", 1)[0]
		self.assertIn("detailRequestGuard.start();", close_detail)
		self.assertIn("detailLoading.value = false;", close_detail)
