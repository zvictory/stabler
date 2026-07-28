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

	def test_tender_dashboard_is_executive_ribbon_without_tables(self):
		source = _read(_DASHBOARD)

		self.assertIn("tenderData.value.executive_kpi", source)
		self.assertIn("<TenderExecutiveKpis", source)
		self.assertIn('<TenderFunnel mode="conversion"', source)
		self.assertIn(':days="tenderDays"', source)
		self.assertIn('t("Tender operations")', source)
		self.assertIn('t("Dashboard")', source)
		for removed in (
			"TenderTrendChart",
			"TenderExecutionFlow",
			"TenderPortfolioPreview",
			"portfolio_preview",
			"attention.value",
		):
			self.assertNotIn(removed, source)

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
			":aria-label=\"item.exact",
		):
			self.assertIn(text, kpis)
		self.assertIn('mode: { type: String, default: "full" }', funnel)
		self.assertIn('days: { type: Number, default: 90 }', funnel)
		self.assertIn('v-if="props.mode === \'full\'"', funnel)
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
