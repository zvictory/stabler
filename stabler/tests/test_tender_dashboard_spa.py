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
def _read(path: str) -> str:
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTenderDashboardSpaContract(unittest.TestCase):
	def test_dashboard_uses_capability_gate_and_aggregate_endpoint(self):
		source = _read(_DASHBOARD)
		self.assertIn('session.canAccessModule("tender")', source)
		self.assertIn('stabler.api.tender.tender_dashboard', source)
		self.assertIn('v-if="tenderEnabled"', source)
		self.assertIn('v-else', source)

	def test_company_disabled_tender_keeps_financial_fallback(self):
		source = _read(_DASHBOARD)
		self.assertIn("if (tenderEnabled.value) return loadTender();", source)
		self.assertIn("return loadFinancial();", source)

	def test_dashboard_has_accessible_spa_drilldowns_without_desk_links(self):
		source = _read(_DASHBOARD)
		self.assertIn('router.push({ name, query })', source)
		self.assertIn('type="button" class="tender-metric-card"', source)
		self.assertIn('.tender-metric-card:focus-visible', source)
		self.assertIn('.tender-metric-card:active', source)
		self.assertNotIn('"/app/', source)
		self.assertNotIn("'/app/", source)

	def test_dashboard_presents_explicit_lifecycle_and_execution_counts(self):
		source = _read(_DASHBOARD)
		for text in (
			"Tayyor",
			"Yuborilgan",
			"Sales orders",
			"Qabul qilingan PO",
			"Tekshirilmagan tarix",
			"Missing required checks",
		):
			self.assertIn(text, source)
		self.assertIn("execution.received || 0 }} / {{ execution.purchase_orders || 0", source)
		self.assertIn("execution.delivered || 0 }} / {{ execution.sales_orders || 0", source)

	def test_dashboard_execution_cards_stack_on_phone(self):
		source = _read(_DASHBOARD)
		self.assertIn('class="col-12 col-md-6 col-lg-3"', source)
		self.assertIn("TenderExecutionFlow", source)

	def test_dashboard_error_is_announced_and_focuses_retry(self):
		source = _read(_DASHBOARD)
		for text in ('role="alert"', 'aria-live="assertive"', 'ref="retryButton"', 'await nextTick()', 'retryButton.value?.focus()'):
			self.assertIn(text, source)

	def test_dashboard_gates_role_specific_destinations(self):
		source = _read(_DASHBOARD)
		self.assertIn('role_scope.views', source)
		for view in ("director", "sourcing", "declarant", "logist"):
			self.assertIn(view, source)

	def test_p1_dashboard_composes_accessible_visuals(self):
		source = _read(_DASHBOARD)
		for component in (
			"TenderTrendChart",
			"TenderExecutionFlow",
			"TenderPortfolioPreview",
		):
			self.assertIn(component, source)
		self.assertIn("portfolio_preview", source)
		self.assertIn("prefers-reduced-motion", source)
		self.assertNotIn("/app/", source)

	def test_dashboard_requests_a_three_month_trend_without_widening_kpis(self):
		source = _read(_DASHBOARD)
		self.assertIn("function trendDates(period)", source)
		self.assertIn("trend_from_date: trendRange.from_date", source)
		self.assertIn("trend_to_date: trendRange.to_date", source)

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
		self.assertIn(':data-label="t(\'Tender\')"', portfolio_source)
		self.assertIn(':data-label="t(\'Progress\')"', portfolio_source)
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
			self.assertIn(f"{key}: {{ label: t(\"{label}\"), class: \"{color}\" }}", source)
		self.assertIn("riskMeta[row.risk] || riskMeta.good", source)

	def test_sales_order_board_reads_dashboard_period_and_status(self):
		source = _read(_SALES_BOARD)
		self.assertIn("useRoute", source)
		self.assertIn("tenderRouteFilters", source)
		self.assertIn("delivery_pending", source)

if __name__ == "__main__":
	unittest.main()
