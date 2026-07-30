"""Source-level guardrails for the Tender CRM SPA boundary."""

import csv
import re
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
	"Could not load tender lots.",
	"Could not load tenders.",
	"Deadline",
	"Estimated total",
	"Kanban",
	"List",
	"No permitted lots for this tender.",
	"No tenders found for this company.",
	"Tenders and their permitted lots",
)
LANGUAGES = ("en", "ru", "uz", "uzc", "tr")


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

	@staticmethod
	def _catalog(language):
		with (TRANSLATIONS / f"{language}.csv").open(newline="", encoding="utf-8") as handle:
			return {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}

	def test_tender_crm_required_localizations_are_translated_in_every_catalog(self):
		"""A key that exists with an empty target is still an untranslated string.

		The previous version of this only checked that the row existed, which a
		`Key,` row satisfies while the user still reads English.
		"""
		for language in LANGUAGES:
			catalog = self._catalog(language)
			for key in REQUIRED_KEYS:
				self.assertIn(key, catalog, f"{language}: {key!r} has no row")
				self.assertTrue(catalog[key].strip(), f"{language}: {key!r} is untranslated")

	def test_every_string_the_board_renders_has_a_row_in_every_catalog(self):
		"""`REQUIRED_KEYS` is hand-maintained, so it cannot catch a string nobody
		remembered to add to it — nine of them shipped that way.

		This derives the keys from the page instead, which is the failure mode that
		actually happens: a new `t("…")` lands with no catalogue row at all and
		every language silently falls through to the English source. Emptiness is
		checked above rather than here on purpose — a few rows this page renders
		(`Owner`) arrived empty from outside this feature, and a guard that fails
		for someone else's debt gets deleted instead of fixed.
		"""
		source = TENDER_CRM.read_text()
		rendered = set(re.findall(r"""\bt\(\s*["']([^"']+)["']""", source))
		self.assertIn("Tender CRM", rendered, "the extraction itself must still find keys")
		for language in LANGUAGES:
			missing = sorted(rendered - set(self._catalog(language)))
			self.assertEqual(missing, [], f"{language}: no catalogue row for {missing}")

	def test_tender_crm_stays_inside_spa_and_uses_parent_api(self):
		source = TENDER_CRM.read_text()
		self.assertIn("stabler.api.tender_master.list_tender_masters", source)
		self.assertIn("stabler.api.tender_master.get_tender_master", source)
		self.assertIn("/tender/po-control", source)
		self.assertNotIn("/app/", source)
		self.assertNotIn("table-striped", source)

	def test_tender_crm_guards_stale_company_responses_and_keeps_optional_columns_absent(self):
		"""Document readiness is optional, so its cell must say nothing when it is absent.

		The whole column is hidden when no record carries readiness; printing an
		em-dash inside it would report "no documents" for a column that is not on
		screen. The check is anchored on `documentReadiness` rather than searching
		the file for an em-dash: the dash is this app's placeholder for any empty
		table cell, and the two lot-status cells legitimately use it.
		"""
		source = TENDER_CRM.read_text()
		self.assertGreaterEqual(
			source.count("isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)"), 2
		)
		self.assertIn('v-if="hasDocumentReadiness"', source)
		compact = re.sub(r"\s+", " ", source)
		readiness_cells = [
			compact[match.end() :].split("</tr>")[0].split("</button>")[0]
			for match in re.finditer(r"record\.documentReadiness !== undefined\"", compact)
		]
		self.assertEqual(len(readiness_cells), 2, "readiness is rendered in the list and the card")
		for cell in readiness_cells:
			self.assertNotIn("—", cell)

	def test_tender_crm_uses_table_body_skeletons_and_shows_the_derived_lot_breakdown(self):
		"""A Kanban card must report the LOT-DERIVED breakdown, not the parent's
		hand-typed `status`.

		The card is what a manager acts on, and the parent status is the one field
		nobody re-types when a lot moves: printing it on a card whose lane was
		derived from the lots puts two contradictory claims side by side ("New"
		under a lane that says Partial Result). The counts, the next lot deadline
		and the policy gap all come from the same permitted-lot pass the
		drill-down uses, so the card and the lot list can be reconciled.
		"""
		source = TENDER_CRM.read_text()
		self.assertNotIn("<tbody>\n\t\t\t\t\t\t<SkeletonRows", source)
		self.assertNotIn('<div class="small text-secondary mt-1">{{ record.status }}</div>', source)
		for expression in (
			"record.openLotCount",
			"record.submittedLotCount",
			"record.wonLotCount",
			"record.lostLotCount",
			"formatDate(record.earliestDeadline)",
			"record.policyGapCount",
		):
			self.assertIn(expression, source)

	def test_closing_tender_detail_invalidates_pending_detail_requests(self):
		source = TENDER_CRM.read_text()
		close_detail = source.split("function closeDetail() {", 1)[1].split("}\n\nwatch", 1)[0]
		self.assertIn("detailRequestGuard.start();", close_detail)
		self.assertIn("detailLoading.value = false;", close_detail)
