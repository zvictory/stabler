"""Static contract checks for the tender operations dashboard SPA.

The project does not ship a Vue test runner. These checks keep the public
dashboard contract executable without adding a browser-only dependency.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa -v
"""

from __future__ import annotations

import os
import re
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_DASHBOARD = os.path.join(_ROOT, "public", "js", "pages", "Dashboard.vue")
_SALES_BOARD = os.path.join(_ROOT, "public", "js", "pages", "sales", "SalesOrderBoard.vue")
_TREND_CHART = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderTrendChart.vue")
_EXECUTION_FLOW = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderExecutionFlow.vue")
_EXECUTIVE_KPIS = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderExecutiveKpis.vue")
_FUNNEL = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderFunnel.vue")
_OPERATIONS_DESK = os.path.join(_ROOT, "public", "js", "pages", "tender", "OperationsDesk.vue")
_OVERVIEW = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderOverview.vue")
_FLOW = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderFlow.vue")
_FLOW_LABELS = os.path.join(_ROOT, "public", "js", "pages", "tender", "flowLabels.js")
_ROUTER = os.path.join(_ROOT, "public", "js", "router.js")
_DELIVERY_NOTES = os.path.join(_ROOT, "public", "js", "pages", "sales", "DeliveryNotes.vue")


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTenderDashboardSpaContract(unittest.TestCase):
	def test_dashboard_uses_capability_gate_and_delegates_to_the_overview(self):
		"""On a tender company the dashboard redirects to /tender/portfolio."""
		source = _read(_DASHBOARD)
		router = _read(_ROUTER)
		self.assertIn('if (to.path === "/dashboard" && session.canAccessModule("tender"))', router)
		self.assertIn('return "/tender/portfolio";', router)

		# The dashboard no longer fetches tender data itself. It called
		# `stabler.api.tender.tender_dashboard` into a `tenderData` ref the template
		# never read, so the only visible effect that request had was its failure
		# path: an error card that hid a desk which had loaded perfectly well. The
		# desk loads itself on mount and reloads on company change
		# (OperationsDesk.vue:526 and :510).
		self.assertNotIn("stabler.api.tender.tender_dashboard", source)

	def test_overview_is_not_a_second_copy_of_the_operations_desk(self):
		"""The dashboard and `/tender/desk` must not be the same screen.

		They were, for a day: the dashboard embedded `OperationsDesk` whole, so two
		routes rendered byte-identical content and neither had a reason to exist.
		The overview answers a different question — where the whole pipeline stands
		— and it must keep answering it from its own two endpoints.
		"""
		overview = _read(_OVERVIEW)
		self.assertNotIn("OperationsDesk", overview)
		self.assertNotIn("stabler.api.tender_desk.operations_desk", overview)

		# The two blocks the user asked back onto the dashboard: the pipeline/funnel
		# ("full" mode is what draws the stage bands, not just the conversion rungs)
		# and the process view.
		self.assertIn("<TenderFunnel", overview)
		self.assertIn('mode="full"', overview)
		self.assertIn('ref="funnelRef"', overview)
		self.assertIn("stabler.api.tender.tender_flow", overview)

		# Role gates mirror the endpoints: tender_flow is director-only
		# (api/tender.py:3065), tender_funnel is director|sourcing (:2204). Calling
		# them without the view returns 403 and paints an empty panel — worse than
		# not drawing the block at all.
		self.assertIn('session.tenderViews.includes("director")', overview)
		self.assertIn('session.tenderViews.includes("sourcing")', overview)
		self.assertIn("if (!canFlow.value || !activeCompany.value) return;", overview)

		# One shell, one bar, one heading — same as every other tender screen.
		root = overview[overview.index("<template>") + len("<template>") :].lstrip()
		self.assertTrue(root.startswith("<TenderPage"), root[:60])

	def test_process_step_names_are_defined_once_for_both_screens(self):
		"""`/tender/flow` and the dashboard strip name the same five steps.

		Two screens spelling one step differently is the same trust bug the flow
		screen warns about in its own header, so the words live in one module and
		both screens import them.
		"""
		labels = _read(_FLOW_LABELS)
		for step in ("seen", "go", "sourcing", "priced", "submitted"):
			self.assertIn(f"{step}:", labels)
		for state in ("in", "edge", "out", "unknown", "empty"):
			self.assertIn(f"{state}:", labels)
		for export in ("stepLabel", "stateLabel", "waitState"):
			self.assertIn(f"export const {export}", labels)

		for consumer in (_FLOW, _OVERVIEW):
			source = _read(consumer)
			self.assertIn('from "./flowLabels.js"', source)
			self.assertNotIn("const STEP_LABELS", source)
			self.assertNotIn("const STATE_LABEL", source)

	def test_chevron_and_stage_boxes_share_the_flow_strips_vocabulary(self):
		"""F12 (docs/design/prompts/15-pipeline-overview.md, S2): the chevron
		strip, the stage boxes and the flow strip are all drawn on this one
		screen (TenderOverview embeds TenderFunnel), and measured 2026-09-02 they
		spelled three of the five stages three different ways -- e.g. `seen` read
		"Intake" on the chevron, "Under review" on its stage box and "Intake —
		file opened" on the flow strip, within one scroll.

		`flowLabels.js` exists precisely to prevent this (see the test above) but
		was wired to the flow strip only. TenderFunnel.vue must import the same
		`stepLabel` rather than keep an independent literal for each of the five
		pipeline stages, on both surfaces it draws.
		"""
		funnel = _read(_FUNNEL)
		self.assertIn('from "./flowLabels.js"', funnel)
		self.assertNotIn("const STEP_LABELS", funnel)
		# The chevron: PIPE_LABELS was a second, independent copy of the same
		# five names. Its removal, not just stepLabel's presence, is the claim --
		# stepLabel could be imported and unused while PIPE_LABELS kept winning.
		self.assertNotIn("const PIPE_LABELS", funnel)
		self.assertRegex(funnel, r"label:\s*stepLabel\(row\.key\)")
		# The stage boxes: each of the five pipeline stages' own `label:` comes
		# from the shared source, not a literal re-typed in this file. `won` and
		# `lost` are excluded on purpose -- S2 compares the five open phases the
		# chevron and the flow strip both walk, not the two terminal outcomes.
		for stage in ("seen", "go", "sourcing", "priced", "submitted"):
			with self.subTest(stage=stage):
				self.assertIn(f'stepLabel("{stage}")', funnel)

	def test_company_disabled_tender_keeps_financial_fallback(self):
		source = _read(_DASHBOARD)
		self.assertIn("loadFinancial()", source)

	def test_dashboard_has_no_desk_links(self):
		source = _read(_DASHBOARD)
		self.assertNotIn('"/app/', source)
		self.assertNotIn("'/app/", source)

	def test_desk_announces_its_own_load_failure(self):
		"""Announcing a failed tender load is the desk's job, not the dashboard's.

		The dashboard used to own an `aria-live` error card with a focused "Try
		again" — but it reported the failure of the aggregate request nothing
		rendered, and while it showed, the desk was not drawn at all. The desk now
		reports its own failure in place, and the financial fallback keeps its alert.
		"""
		desk = _read(_OPERATIONS_DESK)
		self.assertIn('role="alert"', desk)
		self.assertIn('t("Failed to load operations desk.")', desk)

		source = _read(_DASHBOARD)
		self.assertIn('class="alert alert-danger"', source)
		self.assertIn('role="alert"', source)

	def test_unreachable_dashboard_components_are_deleted(self):
		"""Hiçbir ekranın çizmediği bileşenin erişilebilirlik sözleşmesi
		hiçbir şeyi kanıtlamaz.

		Bu üç dosya hiçbir yerden import edilmiyordu (ölçüldü 2026-09-01:
		`.vue`/`.js` grafiğinde 0 çağrı) — yani hiçbir rota onları render
		etmiyordu. Buranın eski hâli `<svg role="img">`, `prefers-reduced-motion`
		ve `t("PI")` iddialarını tutuyordu ve hepsi GEÇİYORDU; geçmelerinin
		sebebi kodun doğru olması değil, kodun hiç çalışmamasıydı. Ölü kodun
		üstündeki yeşil bir test kanıt değil örtüdür.

		Geri gelirlerse bir rotaya bağlanarak gelirler; erişilebilirlik
		sözleşmesi o zaman, RENDER EDİLEN bir bileşen üzerinde yeniden yazılır.

		Silme kararı Zafar'ın (Aşama A §10.5).
		"""
		for path in (_TREND_CHART, _EXECUTION_FLOW, _EXECUTIVE_KPIS):
			self.assertFalse(os.path.exists(path), f"{os.path.basename(path)} should be deleted")

	def test_sales_order_board_reads_dashboard_period_and_status(self):
		source = _read(_SALES_BOARD)
		self.assertIn("useRoute", source)
		self.assertIn("tenderRouteFilters", source)
		# `delivery_pending` was asserted here as a stand-in for "the board
		# speaks the dashboard's status vocabulary". It stopped being present on
		# 2026-09-02 without the board losing that capability: the word moved to
		# the server (`_funnel.delivery_state`, prompt 18's C17) and the client
		# stopped re-deriving a fact the server already knew. Kept, not deleted,
		# and pointed at what this test's name actually claims — that the
		# route's filters REACH the filter. The literal never checked that: it
		# passed even when `filterTenderRows` was called with no filters at all.
		self.assertTrue(
			re.search(r"filterTenderRows\(cards\.value, boardFilters\.value\)", source),
			"the board no longer passes the route's filters to filterTenderRows",
		)


if __name__ == "__main__":
	unittest.main()
