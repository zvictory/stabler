<script setup>
import { ref, computed, watch, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../stores/session.js";
import { dashboardApi } from "../api/dashboard.js";
import { call } from "../api/client.js";
import { formatMoney, formatCompactMoney } from "../composables/money.js";
import { formatDateTime } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import KpiCard from "../components/KpiCard.vue";
import ApexChart from "../components/ApexChart.vue";
import EmptyState from "../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user, currency } = storeToRefs(session);
const router = useRouter();

const loading = ref(true);
const summary = ref({ cash: [], ar: [], ap: [], revenue_mtd: [], revenue_trend_pct: null, dominant_currency: "" });
const trend = ref({ months: [], revenue: [], expense: [] });
const activity = ref([]);
const lowStock = ref([]);
const error = ref(null);
const tenderLoading = ref(true);
const tenderError = ref(null);
const tenderPeriod = ref(new Date().toISOString().slice(0, 7));
const tenderData = ref({
	period: {},
	role_scope: { views: [], acquisition_scope: "none", execution_scope: "assigned" },
	acquisition: {},
	execution: { customs_proxy: {} },
	attention: { count: 0, items: [] },
	my_work: {},
});

const tenderEnabled = computed(() => session.canAccessModule("tender"));
const acquisition = computed(() => tenderData.value.acquisition || {});
const execution = computed(() => tenderData.value.execution || {});
const attention = computed(() => tenderData.value.attention?.items || []);
const myWork = computed(() => tenderData.value.my_work || {});
const tenderFinance = computed(() => tenderData.value.finance || null);
const tenderViews = computed(() => tenderData.value.role_scope.views || []);
const acquisitionDestination = computed(() =>
	tenderViews.value.includes("director") ? "tender-director" : (tenderViews.value.includes("sourcing") ? "tender-my-tenders" : ""),
);
const canOpenAcquisition = computed(() => hasTenderView("director") || hasTenderView("sourcing"));
const canOpenSalesExecution = computed(() => tenderData.value.role_scope.execution_scope === "portfolio");
const tenderEmpty = computed(
	() =>
		!tenderLoading.value &&
		!tenderError.value &&
		!acquisition.value.identified &&
		!execution.value.purchase_orders &&
		!execution.value.sales_orders &&
		!attention.value.length,
);

const money = (v, ccy) => formatMoney(v, ccy || currency.value, user.value.language);
// Chart currency: dominant transaction currency once trend data loads, base currency until then.
const chartCurrency = computed(() => trend.value.currency || currency.value);
const compact = (v) => formatCompactMoney(v, chartCurrency.value, user.value.language);

// Render a per-currency breakdown as pre-formatted strings (dominant first).
// Falls back to a zero row in the dominant currency when the rows array is empty.
const sumRows = (rows) => (rows || []).reduce((s, r) => s + Math.abs(r.amount), 0);
const lines = (rows) => {
	const effective =
		rows?.length
			? rows
			: [{ amount: 0, currency: summary.value.dominant_currency || currency.value }];
	return effective.map((r) => formatMoney(r.amount, r.currency, user.value.language));
};

async function loadFinancial() {
	if (!activeCompany.value) {
		loading.value = false;
		return;
	}
	loading.value = true;
	error.value = null;
	try {
		const [summary_data, trend_data, activity_data, ls] = await Promise.all([
			dashboardApi.summary(activeCompany.value),
			dashboardApi.revenueTrend(activeCompany.value, 12),
			dashboardApi.recentActivity(activeCompany.value, 8),
			call("stabler.api.inventory.low_stock_alerts", {
				company: activeCompany.value,
				limit: 6,
			}).catch(() => []),
		]);
		summary.value = summary_data || summary.value;
		trend.value = trend_data || trend.value;
		activity.value = activity_data || [];
		lowStock.value = Array.isArray(ls) ? ls : [];
	} catch (e) {
		error.value = e?.response?.data?.exception || e.message || t("Failed to load dashboard.");
	} finally {
		loading.value = false;
	}
}

function periodDates(period) {
	const [year, month] = String(period || "").split("-").map(Number);
	if (!year || !month) return {};
	return {
		from_date: `${period}-01`,
		to_date: `${period}-${String(new Date(year, month, 0).getDate()).padStart(2, "0")}`,
	};
}

async function loadTender() {
	if (!activeCompany.value) {
		tenderLoading.value = false;
		return;
	}
	tenderLoading.value = true;
	tenderError.value = null;
	try {
		tenderData.value = await call("stabler.api.tender.tender_dashboard", {
			company: activeCompany.value,
			...periodDates(tenderPeriod.value),
		});
	} catch (e) {
		tenderError.value = e?.response?.data?.exception || e?.message || t("Tender dashboard could not be loaded.");
	} finally {
		tenderLoading.value = false;
	}
}

async function load() {
	if (tenderEnabled.value) return loadTender();
	return loadFinancial();
}

function navigate(name, filters = {}) {
	const query = { period: tenderPeriod.value, ...filters };
	router.push({ name, query });
}

function hasTenderView(view) {
	return tenderViews.value.includes(view);
}

function openAttention(item) {
	if (!item.deal) return;
	router.push({ name: "tender-po-control", query: { period: tenderPeriod.value, deal: item.deal } });
}

function attentionLabel(item) {
	if (item.kind === "bid_deadline") {
		if (item.days_left < 0) return `${t("Bid deadline")}: ${Math.abs(item.days_left)} ${t("days late")}`;
		return `${t("Bid deadline")}: ${item.days_left} ${t("days left")}`;
	}
	if (item.kind === "documents") return t("Missing required checks");
	return t("Unverified history");
}

function attentionDetail(item) {
	if (item.kind === "documents") return (item.missing || []).join(", ");
	if (item.kind === "unverified_history") return t("Result exists, but submission evidence is missing.");
	return item.date || "";
}

onMounted(load);
watch([activeCompany, tenderEnabled], load);

const revenueChartOptions = computed(() => ({
	chart: { stacked: false, sparkline: { enabled: false } },
	colors: ["#206bc4", "#d63939"],
	stroke: { width: [2, 2], curve: "smooth" },
	fill: {
		type: "gradient",
		gradient: { shadeIntensity: 0.3, opacityFrom: 0.4, opacityTo: 0, stops: [0, 90] },
	},
	dataLabels: { enabled: false },
	xaxis: { categories: trend.value.months, labels: { style: { fontSize: "11px" } } },
	yaxis: { labels: { formatter: (v) => compact(v) } },
	tooltip: { y: { formatter: (v) => formatMoney(v, chartCurrency.value, user.value.language) } },
	legend: { position: "top", horizontalAlign: "right" },
	grid: { strokeDashArray: 4 },
}));

const revenueSeries = computed(() => [
	{ name: t("Revenue"), data: trend.value.revenue || [] },
	{ name: t("Expense"), data: trend.value.expense || [] },
]);

const cashFlowOptions = computed(() => ({
	chart: { stacked: true },
	colors: ["#2fb344", "#d63939"],
	plotOptions: { bar: { borderRadius: 4, columnWidth: "60%" } },
	dataLabels: { enabled: false },
	xaxis: { categories: trend.value.months },
	yaxis: { labels: { formatter: (v) => compact(v) } },
	tooltip: { y: { formatter: (v) => formatMoney(v, chartCurrency.value, user.value.language) } },
	legend: { position: "top", horizontalAlign: "right" },
	grid: { strokeDashArray: 4 },
}));

const cashFlowSeries = computed(() => [
	{ name: t("Inflow"), data: trend.value.revenue || [] },
	{ name: t("Outflow"), data: (trend.value.expense || []).map((v) => -Math.abs(v)) },
]);

const isFirstRun = computed(
	() =>
		!loading.value &&
		!error.value &&
		sumRows(summary.value.cash) === 0 &&
		sumRows(summary.value.ar) === 0 &&
		sumRows(summary.value.ap) === 0 &&
		sumRows(summary.value.revenue_mtd) === 0 &&
		!activity.value.length,
);

const activityIcon = (type) => {
	switch (type) {
		case "Sales Invoice":
			return "ti-file-invoice";
		case "Purchase Invoice":
			return "ti-receipt";
		case "Payment Entry":
			return "ti-cash";
		case "Journal Entry":
			return "ti-book";
		default:
			return "ti-circle-dot";
	}
};
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ tenderEnabled ? t("Tender operations") : t("Overview") }}</div>
					<h2 class="page-title">{{ tenderEnabled ? t("Tender control center") : t("Dashboard") }}</h2>
				</div>
				<div class="col-auto">
					<button class="btn btn-outline-primary btn-sm" @click="load" :disabled="tenderEnabled ? tenderLoading : loading">
						<i class="ti ti-refresh"></i>
						{{ t("Refresh") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<div v-if="!tenderEnabled && error" class="alert alert-danger" role="alert">
				<div class="d-flex">
					<div><i class="ti ti-alert-triangle me-2"></i></div>
					<div>{{ error }}</div>
				</div>
			</div>

			<EmptyState
				v-if="!activeCompany"
				icon="ti-building"
				accentIcon="ti-arrow-up"
				tone="primary"
				:title='t("No company selected")'
				:subtitle='t("Pick a company from the switcher in the header to see your financial overview.")'
			/>

			<template v-else>
				<template v-if="tenderEnabled">
					<div class="d-flex flex-wrap align-items-end gap-2 mb-3">
						<div>
							<label class="form-label small mb-1" for="tender-period">{{ t("Period") }}</label>
							<input id="tender-period" v-model="tenderPeriod" type="month" class="form-control" @change="loadTender" />
						</div>
						<div class="text-secondary small pb-1">
							{{ tenderData.period.from_date || periodDates(tenderPeriod).from_date }} — {{ tenderData.period.to_date || periodDates(tenderPeriod).to_date }}
						</div>
					</div>

					<div v-if="tenderLoading" class="row row-cards">
						<div v-for="index in 6" :key="index" class="col-12 col-lg-6">
							<div class="card"><div class="card-body placeholder-glow"><span class="placeholder col-4 mb-3"></span><span class="placeholder col-12"></span><span class="placeholder col-8"></span></div></div>
						</div>
						</div>

					<div v-else-if="tenderError" class="card card-md border-danger">
						<div class="card-body text-center py-5"><i class="ti ti-alert-triangle text-danger" style="font-size: 2rem"></i><h3 class="mt-2">{{ t("Tender dashboard could not be loaded.") }}</h3><p class="text-secondary mb-3">{{ tenderError }}</p><button type="button" class="btn btn-primary" @click="loadTender"><i class="ti ti-refresh me-1"></i>{{ t("Try again") }}</button></div>
					</div>

					<EmptyState
						v-else-if="tenderEmpty"
						icon="ti-gavel"
						accentIcon="ti-circle-check"
						tone="primary"
						:title='t("Tender activity is empty for this period")'
						:subtitle='t("Choose another period or start a tender intake to see lifecycle and execution work here.")'
					/>

					<div v-else class="row row-cards">
						<div class="col-12 col-lg-8">
							<div class="card h-100">
								<div class="card-header"><h3 class="card-title"><i class="ti ti-route-2 me-1"></i>{{ t("Tender acquisition") }}</h3></div>
								<div class="card-body">
									<div v-if="tenderData.role_scope.acquisition_scope === 'none'" class="text-secondary">
										{{ t("Acquisition portfolio is not in your role scope.") }}
									</div>
									<div v-else-if="canOpenAcquisition && acquisitionDestination" class="row g-2">
										<div class="col-6 col-md-4"><button type="button" class="tender-metric-card" @click="navigate(acquisitionDestination, { stage: 'identified' })"><span>{{ t("Aniqlangan") }}</span><strong>{{ acquisition.identified || 0 }}</strong></button></div>
										<div class="col-6 col-md-4"><button type="button" class="tender-metric-card" @click="navigate(acquisitionDestination, { stage: 'decided' })"><span>{{ t("Qaror qilingan") }}</span><strong>{{ (acquisition.go || 0) + (acquisition.no_go || 0) }}</strong></button></div>
										<div class="col-6 col-md-4"><button type="button" class="tender-metric-card" @click="navigate(acquisitionDestination, { stage: 'ready' })"><span>{{ t("Tayyor") }}</span><strong>{{ acquisition.ready || 0 }}</strong></button></div>
										<div class="col-6 col-md-4"><button type="button" class="tender-metric-card" @click="navigate(acquisitionDestination, { stage: 'submitted' })"><span>{{ t("Yuborilgan") }}</span><strong>{{ acquisition.submitted || 0 }}</strong></button></div>
										<div class="col-6 col-md-4"><button type="button" class="tender-metric-card" @click="navigate(acquisitionDestination, { status: 'won' })"><span>{{ t("Yutilgan") }}</span><strong>{{ acquisition.won || 0 }}</strong></button></div>
										<div class="col-6 col-md-4"><button type="button" class="tender-metric-card" @click="navigate(acquisitionDestination, { status: 'lost' })"><span>{{ t("Yo'qotilgan") }}</span><strong>{{ acquisition.lost || 0 }}</strong></button></div>
									</div>
									<div v-else class="text-secondary">{{ t("No acquisition board is available for your role.") }}</div>
									<div v-if="acquisition.unverified_history" class="alert alert-warning mt-3 mb-0 py-2">
										<i class="ti ti-shield-exclamation me-1"></i>{{ t("Tekshirilmagan tarix") }}: {{ acquisition.unverified_history }}
									</div>
								</div>
							</div>
						</div>

						<div class="col-12 col-lg-4">
							<div class="card h-100">
								<div class="card-header"><h3 class="card-title"><i class="ti ti-bell-ringing me-1"></i>{{ t("E'tibor talab qiladi") }}</h3><span class="badge bg-red-lt text-red ms-auto">{{ tenderData.attention.count || 0 }}</span></div>
								<div v-if="!attention.length" class="card-body text-secondary"><i class="ti ti-circle-check text-green me-1"></i>{{ t("No priority checks right now.") }}</div>
								<div v-else class="list-group list-group-flush">
									<button v-for="item in attention" :key="`${item.deal}-${item.kind}`" type="button" class="list-group-item list-group-item-action text-start" @click="openAttention(item)">
										<div class="fw-semibold">{{ item.label }}</div><div class="small" :class="item.severity === 'risk' ? 'text-red' : 'text-yellow'">{{ attentionLabel(item) }}</div><div v-if="attentionDetail(item)" class="small text-secondary">{{ attentionDetail(item) }}</div>
									</button>
								</div>
							</div>
						</div>

						<div class="col-12 col-lg-8">
							<div class="card h-100">
								<div class="card-header"><h3 class="card-title"><i class="ti ti-truck-loading me-1"></i>{{ t("Ijro oqimi") }}</h3></div>
								<div class="card-body"><div class="row g-2">
									<div class="col-6 col-md-3"><button v-if="hasTenderView('logist')" type="button" class="tender-metric-card" @click="navigate('tender-logistics', { status: 'all' })"><span>{{ t("Purchase orders") }}</span><strong>{{ execution.purchase_orders || 0 }}</strong><small>{{ t("Qabul qilingan PO") }}: {{ execution.received || 0 }}</small></button><div v-else class="tender-metric-card tender-metric-card--disabled"><span>{{ t("Purchase orders") }}</span><strong>{{ execution.purchase_orders || 0 }}</strong><small>{{ t("Qabul qilingan PO") }}: {{ execution.received || 0 }}</small></div></div>
									<div class="col-6 col-md-3"><button v-if="hasTenderView('declarant')" type="button" class="tender-metric-card" @click="navigate('tender-customs', { status: 'in_progress' })"><span>{{ t("Customs workload") }}</span><strong>{{ execution.customs_workload_open || 0 }}</strong></button><div v-else class="tender-metric-card tender-metric-card--disabled"><span>{{ t("Customs workload") }}</span><strong>{{ execution.customs_workload_open || 0 }}</strong></div></div>
									<div class="col-6 col-md-3"><button v-if="canOpenSalesExecution" type="button" class="tender-metric-card" @click="navigate('tender-board', { tender: '1', status: 'all' })"><span>{{ t("Sales orders") }}</span><strong>{{ execution.sales_orders || 0 }}</strong></button><div v-else class="tender-metric-card tender-metric-card--disabled"><span>{{ t("Sales orders") }}</span><strong>{{ execution.sales_orders || 0 }}</strong></div></div>
									<div class="col-6 col-md-3"><button v-if="canOpenSalesExecution" type="button" class="tender-metric-card" @click="navigate('tender-board', { tender: '1', status: 'delivery_pending' })"><span>{{ t("Awaiting delivery") }}</span><strong>{{ execution.delivery_pending || 0 }}</strong></button><div v-else class="tender-metric-card tender-metric-card--disabled"><span>{{ t("Awaiting delivery") }}</span><strong>{{ execution.delivery_pending || 0 }}</strong></div></div>
								</div></div>
							</div>
						</div>

						<div class="col-12 col-lg-4">
							<div class="card h-100"><div class="card-header"><h3 class="card-title"><i class="ti ti-user-check me-1"></i>{{ t("Mening ishlarim") }}</h3></div><div class="list-group list-group-flush">
								<button v-if="acquisitionDestination" type="button" class="list-group-item list-group-item-action d-flex justify-content-between" @click="navigate(acquisitionDestination, { stage: 'assigned' })"><span>{{ t("Assigned tenders") }}</span><strong>{{ myWork.assigned || 0 }}</strong></button>
								<div v-else class="list-group-item d-flex justify-content-between"><span>{{ t("Assigned tenders") }}</span><strong>{{ myWork.assigned || 0 }}</strong></div>
								<button v-if="myWork.customs_workload_open && hasTenderView('declarant')" type="button" class="list-group-item list-group-item-action d-flex justify-content-between" @click="navigate('tender-customs', { status: 'in_progress' })"><span>{{ t("Open customs work") }}</span><strong>{{ myWork.customs_workload_open }}</strong></button>
								<button v-if="myWork.delivery_pending && canOpenSalesExecution" type="button" class="list-group-item list-group-item-action d-flex justify-content-between" @click="navigate('tender-board', { tender: '1', status: 'delivery_pending' })"><span>{{ t("Pending deliveries") }}</span><strong>{{ myWork.delivery_pending }}</strong></button>
							</div></div>
						</div>

						<div v-if="tenderFinance" class="col-12">
							<div class="card"><div class="card-header"><h3 class="card-title"><i class="ti ti-report-money me-1"></i>{{ t("Finance") }}</h3></div><div class="card-body"><div class="row g-2"><div class="col-md-4"><div class="text-secondary small">{{ t("Procurement total") }}</div><div class="font-monospace fw-semibold">{{ money(tenderFinance.procurement_total, tenderFinance.currency) }}</div></div><div class="col-md-4"><div class="text-secondary small">{{ t("Contract total") }}</div><div class="font-monospace fw-semibold">{{ money(tenderFinance.contract_total, tenderFinance.currency) }}</div></div><div class="col-md-4"><div class="text-secondary small">{{ t("Execution spread") }}</div><div class="font-monospace fw-semibold">{{ money(tenderFinance.execution_spread, tenderFinance.currency) }}</div></div></div></div></div>
						</div>
					</div>
				</template>

				<template v-else>
				<div v-if="isFirstRun" class="card card-md mb-3 border-start border-3 border-primary">
					<div class="card-body">
						<div class="row align-items-center">
							<div class="col-auto">
								<span class="avatar avatar-lg bg-primary-lt">
									<i class="ti ti-rocket" style="font-size: 1.75rem"></i>
								</span>
							</div>
							<div class="col">
								<h3 class="mb-1">{{ t("Welcome to Stabler") }}</h3>
								<p class="text-secondary mb-2">
									{{ t("Your books are empty. Get started by adding a customer, recording your first sale, or logging an opening balance.") }}
								</p>
								<div class="d-flex flex-wrap gap-2">
									<RouterLink :to="{ name: 'sales-customers' }" class="btn btn-sm btn-primary">
										<i class="ti ti-user-plus me-1"></i>{{ t("Add a customer") }}
									</RouterLink>
									<RouterLink :to="{ name: 'sales-invoices' }" class="btn btn-sm btn-outline-primary">
										<i class="ti ti-file-invoice me-1"></i>{{ t("Record a sale") }}
									</RouterLink>
									<RouterLink :to="{ name: 'money-journals' }" class="btn btn-sm btn-outline-secondary">
										<i class="ti ti-book me-1"></i>{{ t("Opening balances") }}
									</RouterLink>
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="row row-deck row-cards">
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							:label='t("Cash on hand")'
							:lines="lines(summary.cash)"
							icon="ti-coin"
							tone="primary"
							:loading="loading"
						/>
					</div>
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							:label='t("Receivable (AR)")'
							:lines="lines(summary.ar)"
							icon="ti-arrow-down-right"
							tone="success"
							:loading="loading"
						/>
					</div>
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							:label='t("Payable (AP)")'
							:lines="lines(summary.ap)"
							icon="ti-arrow-up-right"
							tone="warning"
							:loading="loading"
						/>
					</div>
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							:label='t("Revenue MTD")'
							:lines="lines(summary.revenue_mtd)"
							icon="ti-trending-up"
							tone="info"
							:trend="summary.revenue_trend_pct"
							:hint='t("vs. last month")'
							:loading="loading"
						/>
					</div>

					<div class="col-lg-8">
						<div class="card">
							<div class="card-header">
								<h3 class="card-title">{{ t("Revenue vs. Expense (12 months)") }}</h3>
							</div>
							<div class="card-body">
								<div v-if="loading" class="placeholder-glow">
									<div class="placeholder col-12" style="height: 240px"></div>
								</div>
								<ApexChart
									v-else
									type="area"
									:height="280"
									:options="revenueChartOptions"
									:series="revenueSeries"
								/>
							</div>
						</div>
					</div>

					<div class="col-lg-4">
						<div class="card h-100">
							<div class="card-header">
								<h3 class="card-title">{{ t("Cash flow") }}</h3>
							</div>
							<div class="card-body">
								<div v-if="loading" class="placeholder-glow">
									<div class="placeholder col-12" style="height: 240px"></div>
								</div>
								<ApexChart
									v-else
									type="bar"
									:height="280"
									:options="cashFlowOptions"
									:series="cashFlowSeries"
								/>
							</div>
						</div>
					</div>

					<div class="col-lg-8">
						<div class="card h-100">
							<div class="card-header">
								<h3 class="card-title">{{ t("Recent activity") }}</h3>
							</div>
							<div class="list-group list-group-flush">
								<div v-if="loading" class="list-group-item placeholder-glow">
									<div class="placeholder col-8"></div>
								</div>
								<div
									v-else-if="!activity.length"
									class="list-group-item text-secondary text-center py-4"
								>
									{{ t("No recent transactions.") }}
								</div>
								<div
									v-else
									v-for="item in activity"
									:key="item.doctype + ':' + item.name"
									class="list-group-item"
								>
									<div class="row align-items-center">
										<div class="col-auto">
											<span class="avatar avatar-sm bg-primary-lt">
												<i class="ti" :class="activityIcon(item.doctype)"></i>
											</span>
										</div>
										<div class="col text-truncate">
											<div class="text-body d-block">{{ item.title }}</div>
											<div class="d-block text-secondary text-truncate mt-n1">
												{{ item.doctype }} · {{ item.party || "—" }} ·
												{{ formatDateTime(item.date) }}
											</div>
										</div>
										<div class="col-auto text-end">
											<div class="fw-bold">{{ money(item.amount, item.currency) }}</div>
											<span
												class="badge"
												:class="
													item.status === 'Paid'
														? 'bg-success-lt'
														: item.status === 'Overdue'
															? 'bg-danger-lt'
															: 'bg-secondary-lt'
												"
												>{{ item.status || "—" }}</span
											>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>

					<div class="col-lg-4">
						<div class="card h-100">
							<div class="card-header">
								<h3 class="card-title">
									<i class="ti ti-alert-triangle text-warning me-1"></i>{{ t("Low stock") }}
								</h3>
								<div class="ms-auto">
									<RouterLink
										:to="{ name: 'inventory-alerts' }"
										class="btn btn-sm btn-outline-secondary"
									>
										{{ t("View all") }}
									</RouterLink>
								</div>
							</div>
							<div class="list-group list-group-flush">
								<div v-if="loading" class="list-group-item placeholder-glow">
									<div class="placeholder col-8"></div>
								</div>
								<div
									v-else-if="!lowStock.length"
									class="list-group-item text-secondary text-center py-4"
								>
									<i class="ti ti-circle-check text-success me-1"></i>
									{{ t("All items above reorder level.") }}
								</div>
								<div
									v-else
									v-for="row in lowStock"
									:key="row.item_code + ':' + row.warehouse"
									class="list-group-item"
								>
									<div class="row align-items-center">
										<div class="col text-truncate">
											<div class="text-body d-block text-truncate">
												{{ row.item_name || row.item_code }}
											</div>
											<div class="d-block text-secondary small text-truncate mt-n1">
												<i class="ti ti-building-warehouse me-1"></i>{{ row.warehouse }}
											</div>
										</div>
										<div class="col-auto text-end">
											<div
												class="fw-bold font-monospace"
												:class="
													Number(row.projected_qty) <= 0
														? 'text-red'
														: 'text-yellow-dark'
												"
											>
												{{ Number(row.projected_qty).toLocaleString() }}
												<span class="text-secondary fw-normal small"
													>/ {{ row.reorder_level }}</span
												>
											</div>
											<div class="small text-secondary">{{ row.stock_uom || "" }}</div>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
				</template>
			</template>
		</div>
	</div>
</template>

<style scoped>
.tender-metric-card {
	align-items: flex-start;
	background: var(--tblr-bg-surface, #fff);
	border: 1px solid var(--tblr-border-color, #e6e7e9);
	border-radius: var(--tblr-border-radius, 4px);
	color: inherit;
	display: flex;
	flex-direction: column;
	gap: 0.35rem;
	min-height: 7.25rem;
	padding: 0.9rem;
	text-align: left;
	transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
	width: 100%;
}

.tender-metric-card:hover {
	border-color: var(--tblr-primary, #206bc4);
}

.tender-metric-card:focus-visible {
	box-shadow: 0 0 0 0.2rem rgba(32, 107, 196, 0.25);
	outline: 0;
}

.tender-metric-card:active {
	transform: translateY(1px);
}

.tender-metric-card span,
.tender-metric-card small {
	color: var(--tblr-secondary, #6c7a87);
}

.tender-metric-card strong {
	font-family: var(--tblr-font-monospace, monospace);
	font-size: 1.2rem;
}

.tender-metric-card--disabled {
	background: var(--tblr-bg-surface-secondary, #f6f8fb);
	cursor: not-allowed;
	opacity: 0.72;
}

@media (max-width: 991.98px) {
	.tender-metric-card {
		min-height: 6.5rem;
	}
}
</style>
