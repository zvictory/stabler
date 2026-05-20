<script setup>
import { ref, computed, watch, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { dashboardApi } from "../api/dashboard.js";
import { call } from "../api/client.js";
import { formatMoney, formatCompactMoney } from "../composables/money.js";
import { t } from "../composables/i18n.js";
import KpiCard from "../components/KpiCard.vue";
import ApexChart from "../components/ApexChart.vue";
import EmptyState from "../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user, currency } = storeToRefs(session);

const loading = ref(true);
const summary = ref({ cash: 0, ar: 0, ap: 0, revenue_mtd: 0, revenue_trend_pct: null });
const trend = ref({ months: [], revenue: [], expense: [] });
const activity = ref([]);
const lowStock = ref([]);
const error = ref(null);

const money = (v, ccy) => formatMoney(v, ccy || currency.value, user.value.language);
const compact = (v) => formatCompactMoney(v, currency.value, user.value.language);

async function load() {
	if (!activeCompany.value) {
		loading.value = false;
		return;
	}
	loading.value = true;
	error.value = null;
	try {
		const [s, t, a, ls] = await Promise.all([
			dashboardApi.summary(activeCompany.value),
			dashboardApi.revenueTrend(activeCompany.value, 12),
			dashboardApi.recentActivity(activeCompany.value, 8),
			call("stabler.api.inventory.low_stock_alerts", {
				company: activeCompany.value,
				limit: 6,
			}).catch(() => []),
		]);
		summary.value = s || summary.value;
		trend.value = t || trend.value;
		activity.value = a || [];
		lowStock.value = Array.isArray(ls) ? ls : [];
	} catch (e) {
		error.value = e?.response?.data?.exception || e.message || "Failed to load dashboard.";
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

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
	tooltip: { y: { formatter: (v) => money(v) } },
	legend: { position: "top", horizontalAlign: "right" },
	grid: { strokeDashArray: 4 },
}));

const revenueSeries = computed(() => [
	{ name: "Revenue", data: trend.value.revenue || [] },
	{ name: "Expense", data: trend.value.expense || [] },
]);

const cashFlowOptions = computed(() => ({
	chart: { stacked: true },
	colors: ["#2fb344", "#d63939"],
	plotOptions: { bar: { borderRadius: 4, columnWidth: "60%" } },
	dataLabels: { enabled: false },
	xaxis: { categories: trend.value.months },
	yaxis: { labels: { formatter: (v) => compact(v) } },
	tooltip: { y: { formatter: (v) => money(v) } },
	legend: { position: "top", horizontalAlign: "right" },
	grid: { strokeDashArray: 4 },
}));

const cashFlowSeries = computed(() => [
	{ name: "Inflow", data: trend.value.revenue || [] },
	{ name: "Outflow", data: (trend.value.expense || []).map((v) => -Math.abs(v)) },
]);

const isFirstRun = computed(
	() =>
		!loading.value &&
		!error.value &&
		Number(summary.value.cash || 0) === 0 &&
		Number(summary.value.ar || 0) === 0 &&
		Number(summary.value.ap || 0) === 0 &&
		Number(summary.value.revenue_mtd || 0) === 0 &&
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
					<div class="page-pretitle">Overview</div>
					<h2 class="page-title">Dashboard</h2>
				</div>
				<div class="col-auto">
					<button class="btn btn-outline-primary btn-sm" @click="load" :disabled="loading">
						<i class="ti ti-refresh"></i>
						Refresh
					</button>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<div v-if="error" class="alert alert-danger" role="alert">
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
				title="No company selected"
				subtitle="Pick a company from the switcher in the header to see your financial overview."
			/>

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
								<h3 class="mb-1">Welcome to Stabler</h3>
								<p class="text-secondary mb-2">
									Your books are empty. Get started by adding a customer, recording your
									first sale, or logging an opening balance.
								</p>
								<div class="d-flex flex-wrap gap-2">
									<RouterLink :to="{ name: 'sales-customers' }" class="btn btn-sm btn-primary">
										<i class="ti ti-user-plus me-1"></i>Add a customer
									</RouterLink>
									<RouterLink :to="{ name: 'sales-invoices' }" class="btn btn-sm btn-outline-primary">
										<i class="ti ti-file-invoice me-1"></i>Record a sale
									</RouterLink>
									<RouterLink :to="{ name: 'money-journals' }" class="btn btn-sm btn-outline-secondary">
										<i class="ti ti-book me-1"></i>Opening balances
									</RouterLink>
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="row row-deck row-cards">
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							label="Cash on hand"
							:value="money(summary.cash)"
							icon="ti-coin"
							tone="primary"
							:loading="loading"
						/>
					</div>
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							label="Receivable (AR)"
							:value="money(summary.ar)"
							icon="ti-arrow-down-right"
							tone="success"
							:loading="loading"
						/>
					</div>
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							label="Payable (AP)"
							:value="money(summary.ap)"
							icon="ti-arrow-up-right"
							tone="warning"
							:loading="loading"
						/>
					</div>
					<div class="col-sm-6 col-lg-3">
						<KpiCard
							label="Revenue MTD"
							:value="money(summary.revenue_mtd)"
							icon="ti-trending-up"
							tone="info"
							:trend="summary.revenue_trend_pct"
							hint="vs. last month"
							:loading="loading"
						/>
					</div>

					<div class="col-lg-8">
						<div class="card">
							<div class="card-header">
								<h3 class="card-title">Revenue vs. Expense (12 months)</h3>
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
								<h3 class="card-title">Cash flow</h3>
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
								<h3 class="card-title">Recent activity</h3>
							</div>
							<div class="list-group list-group-flush">
								<div v-if="loading" class="list-group-item placeholder-glow">
									<div class="placeholder col-8"></div>
								</div>
								<div
									v-else-if="!activity.length"
									class="list-group-item text-secondary text-center py-4"
								>
									No recent transactions.
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
												{{ item.date }}
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
		</div>
	</div>
</template>
