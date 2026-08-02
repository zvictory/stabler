"""Static contract checks for the tender operations dashboard SPA.

The project does not ship a Vue test runner. These checks keep the public
dashboard contract executable without adding a browser-only dependency.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa -v
"""

from __future__ import annotations

import os
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_DASHBOARD = os.path.join(_ROOT, "public", "js", "pages", "Dashboard.vue")
_SALES_BOARD = os.path.join(_ROOT, "public", "js", "pages", "sales", "SalesOrderBoard.vue")
_TREND_CHART = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderTrendChart.vue")
_EXECUTION_FLOW = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderExecutionFlow.vue")
_PORTFOLIO_PREVIEW = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderPortfolioPreview.vue")
_EXECUTIVE_KPIS = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderExecutiveKpis.vue")
_FUNNEL = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderFunnel.vue")
_CONTROL_TOWER = os.path.join(_ROOT, "public", "js", "pages", "tender", "TenderControlTower.vue")
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
		self.assertIn('<TenderFunnel', overview)
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

	def test_tender_dashboard_composes_the_role_adaptive_control_tower(self):
		# The two dashboard assertions that used to open this test (`executive_kpi`
		# and the `t("Tender operations")` pretitle) belonged to the Bootstrap header
		# and the discarded aggregate payload — both gone. What remains is a contract
		# about the control-tower component itself.
		control_tower = _read(_CONTROL_TOWER)
		for component in ("TenderExecutiveKpis", "TenderTrendChart", "TenderExecutionFlow"):
			self.assertIn(component, control_tower)
		for field in ("role_scope", "acquisition", "attention", "execution", "my_work", "finance"):
			self.assertIn(field, control_tower)
		self.assertNotIn("portfolio_preview", control_tower)

	def test_attention_panel_shows_three_items_before_expansion(self):
		control_tower = _read(_CONTROL_TOWER)

		self.assertIn("attention.value.slice(0, 3)", control_tower)
		self.assertIn("visibleAttention", control_tower)
		self.assertIn("remainingAttentionCount", control_tower)
		self.assertIn('t("Show more")', control_tower)
		self.assertIn('t("Show less")', control_tower)

	def test_execution_flow_has_seven_clickable_filtered_stages(self):
		execution_flow = _read(_EXECUTION_FLOW)
		for field in (
			"sales_orders",
			"purchase_orders",
			"purchase_receipts",
			"purchase_invoices",
			"sales_invoices",
			"delivery_notes",
		):
			self.assertIn(field, execution_flow)
		for route in (
			"sales-orders",
			"purchasing-orders",
			"purchasing-receipts",
			"purchasing-invoices",
			"sales-invoices",
			"sales-delivery-notes",
		):
			self.assertIn(route, execution_flow)
		self.assertIn("<button", execution_flow)
		self.assertIn("tender_only", execution_flow)
		self.assertNotIn('`${t("PI")}/${t("SI")}`', execution_flow)

	def test_portfolio_and_delivery_notes_are_spa_routes(self):
		router = _read(_ROUTER)
		self.assertIn('path: "/tender/portfolio"', router)
		self.assertIn('name: "tender-portfolio"', router)
		self.assertIn('name: "sales-delivery-notes"', router)
		self.assertIn("DeliveryNotes", router)
		delivery_notes = _read(_DELIVERY_NOTES)
		self.assertIn("stabler.api.sales.list_delivery_notes", delivery_notes)
		self.assertIn("stabler.api.sales.get_delivery_note", delivery_notes)
		self.assertNotIn("/app/", delivery_notes)

	def test_control_tower_preserves_dashboard_period_in_drilldowns(self):
		control_tower = _read(_CONTROL_TOWER)
		self.assertIn("from_date", control_tower)
		self.assertIn("to_date", control_tower)
		self.assertIn("tender-crm", control_tower)
		self.assertIn(':period="data.period"', control_tower)

	def test_tender_dashboard_renders_executive_content_without_legacy_empty_gate(self):
		source = _read(_DASHBOARD)

		self.assertNotIn("const tenderEmpty", source)
		self.assertNotIn('v-else-if="tenderEmpty"', source)
		for legacy_state in ("acquisition = {}", "attention = {}", "execution = {}"):
			self.assertNotIn(legacy_state, source)

	def test_tender_today_is_read_in_local_time(self):
		"""Tashkent is UTC+5, so `toISOString()` dates the desk a day back all night.

		The dashboard owned this contract while it built a from/to range for the
		aggregate request. That range is gone with the period select, and the only
		tender screen that still turns "now" into a date is the desk — which reaches
		for the shared `todayIso()` helper rather than rolling its own.
		"""
		desk = _read(_OPERATIONS_DESK)

		self.assertIn("todayIso", desk)
		self.assertIn("const todayStr = todayIso();", desk)
		self.assertNotIn("new Date().toISOString()", desk)

	def test_dashboard_composes_executive_kpis_and_conversion_only_funnel(self):
		kpis = _read(_EXECUTIVE_KPIS)
		funnel = _read(_FUNNEL)

		for label in (
			"Active tenders",
			"Portfolio value",
			"Avg margin",
			"At risk",
			"Win rate",
			"Net remaining",
		):
			self.assertIn(f't("{label}")', kpis)
		for text in (
			"formatCompactMoney",
			"formatMoney",
			"font-monospace",
			':title="item.exact"',
			':aria-label="item.exact',
		):
			self.assertIn(text, kpis)
		self.assertIn('mode: { type: String, default: "full" }', funnel)
		self.assertIn("days: { type: Number, default: 90 }", funnel)
		self.assertIn("v-if=\"props.mode === 'full'\"", funnel)
		self.assertIn("days: props.days", funnel)
		self.assertIn("watch([activeCompany, () => props.days], load);", funnel)

	def test_dashboard_offers_no_period_control_it_cannot_honour(self):
		"""The Last 30/90/180 days select is gone, and must not come back alone.

		It drove `?days=` and a `tender_dashboard` request whose payload the template
		never rendered, so changing the period changed nothing on screen. If a period
		filter is wanted again it belongs to whatever actually reads it — the desk —
		not to a header the desk no longer has.
		"""
		source = _read(_DASHBOARD)
		self.assertNotIn("tenderDays", source)
		self.assertNotIn('id="tender-period"', source)

	def test_p1_components_preserve_visual_and_keyboard_accessibility(self):
		trend_source = _read(_TREND_CHART)
		self.assertIn('<svg role="img"', trend_source)
		self.assertIn("<title", trend_source)
		self.assertIn("visually-hidden", trend_source)
		self.assertIn("prefers-reduced-motion", trend_source)

		execution_source = _read(_EXECUTION_FLOW)
		self.assertIn('t("Won")', execution_source)
		self.assertIn('t("PI")', execution_source)
		self.assertIn('t("SI")', execution_source)
		self.assertIn("@media (max-width", execution_source)

		portfolio_source = _read(_PORTFOLIO_PREVIEW)
		self.assertIn(":data-label=\"t('Tender')\"", portfolio_source)
		self.assertIn(":data-label=\"t('Progress')\"", portfolio_source)
		self.assertIn('tabindex="0"', portfolio_source)
		self.assertIn("@keydown.enter", portfolio_source)
		self.assertIn("@keydown.space.prevent", portfolio_source)
		self.assertIn('role="progressbar"', portfolio_source)
		self.assertIn("aria-valuenow", portfolio_source)
		self.assertIn("@media (max-width", portfolio_source)

	def test_portfolio_risk_has_distinct_good_warn_and_risk_semantics(self):
		source = _read(_PORTFOLIO_PREVIEW)
		for key, label, color in (
			("good", "On track", "bg-green-lt text-green"),
			("warn", "Needs attention", "bg-yellow-lt text-yellow"),
			("risk", "At risk", "bg-red-lt text-red"),
		):
			self.assertIn(f'{key}: {{ label: t("{label}"), class: "{color}" }}', source)
		self.assertIn("riskMeta[row.risk] || riskMeta.good", source)

	def test_sales_order_board_reads_dashboard_period_and_status(self):
		source = _read(_SALES_BOARD)
		self.assertIn("useRoute", source)
		self.assertIn("tenderRouteFilters", source)
		self.assertIn("delivery_pending", source)


if __name__ == "__main__":
	unittest.main()
