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
_ROUTER = os.path.join(_ROOT, "public", "js", "router.js")
_DELIVERY_NOTES = os.path.join(_ROOT, "public", "js", "pages", "sales", "DeliveryNotes.vue")


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTenderDashboardSpaContract(unittest.TestCase):
	def test_dashboard_uses_capability_gate_and_aggregate_endpoint(self):
		source = _read(_DASHBOARD)
		self.assertIn('session.canAccessModule("tender")', source)
		self.assertIn("stabler.api.tender.tender_dashboard", source)
		self.assertIn('v-if="tenderEnabled"', source)
		self.assertIn("v-else", source)

	def test_company_disabled_tender_keeps_financial_fallback(self):
		source = _read(_DASHBOARD)
		self.assertIn("if (tenderEnabled.value) return loadTender();", source)
		self.assertIn("return loadFinancial();", source)

	def test_dashboard_has_no_desk_links(self):
		source = _read(_DASHBOARD)
		self.assertNotIn('"/app/', source)
		self.assertNotIn("'/app/", source)

	def test_dashboard_error_is_announced_and_focuses_retry(self):
		source = _read(_DASHBOARD)
		for text in (
			'role="alert"',
			'aria-live="assertive"',
			'ref="retryButton"',
			"await nextTick()",
			"retryButton.value?.focus()",
		):
			self.assertIn(text, source)

	def test_tender_dashboard_composes_the_role_adaptive_control_tower(self):
		source = _read(_DASHBOARD)

		self.assertIn("executive_kpi", source)
		self.assertIn("<TenderControlTower", source)
		self.assertIn(':data="tenderData"', source)
		self.assertIn('t("Tender operations")', source)
		self.assertNotIn('<TenderFunnel mode="conversion"', source)

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

	def test_tender_dashboard_serializes_selected_dates_in_local_time(self):
		source = _read(_DASHBOARD)

		self.assertIn("function localDate(date)", source)
		self.assertNotIn("toISOString()", source)
		for getter in ("getFullYear()", "getMonth() + 1", "getDate()"):
			self.assertIn(getter, source)

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

	def test_dashboard_requests_the_selected_day_range(self):
		source = _read(_DASHBOARD)
		self.assertIn("const tenderDays = ref(Number(route.query.days) || 90);", source)
		self.assertIn("function tenderDates(days)", source)
		self.assertIn("const dateRange = tenderDates(tenderDays.value);", source)
		self.assertIn("...dateRange", source)
		self.assertIn("days: tenderDays.value", source)

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
