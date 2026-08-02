<script setup>
import { ref, computed, watch, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { dashboardApi } from "../api/dashboard.js";
import { call } from "../api/client.js";
import { formatMoney, formatCompactMoney } from "../composables/money.js";
import { formatDateTime } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import KpiCard from "../components/KpiCard.vue";
import ApexChart from "../components/ApexChart.vue";
import EmptyState from "../components/EmptyState.vue";
import OperationsDesk from "./tender/OperationsDesk.vue";
import ImportsDashboard from "./imports/ImportsDashboard.vue";

const session = useSession();
const { activeCompany, user, currency } = storeToRefs(session);

const importsEnabled = computed(() => session.canAccessModule("imports"));

const loading = ref(true);
const summary = ref({
	cash: [],
	ar: [],
	ap: [],
	revenue_mtd: [],
	revenue_trend_pct: null,
	dominant_currency: "",
});
const trend = ref({ months: [], revenue: [], expense: [] });
const activity = ref([]);
const lowStock = ref([]);
const error = ref(null);

const tenderEnabled = computed(() => session.canAccessModule("tender"));
// Şirket seçilmemişken masa hiçbir şey çekmiyor (OperationsDesk.vue:270), boş bir
// kabuk çizerdi — o durumda aşağıdaki "şirket seçin" ekranına düşüyoruz.
const showDesk = computed(() => tenderEnabled.value && !!activeCompany.value);

const money = (v, ccy) => formatMoney(v, ccy || currency.value, user.value.language);
// Chart currency: dominant transaction currency once trend data loads, base currency until then.
const chartCurrency = computed(() => trend.value.currency || currency.value);
const compact = (v) => formatCompactMoney(v, chartCurrency.value, user.value.language);

// Render a per-currency breakdown as pre-formatted strings (dominant first).
// Falls back to a zero row in the dominant currency when the rows array is empty.
const sumRows = (rows) => (rows || []).reduce((s, r) => s + Math.abs(r.amount), 0);
const lines = (rows) => {
	const effective = rows?.length
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

/* Tender şirketinde bu sayfa `OperationsDesk`'in kendisi — finans panosu hiç
 * çizilmiyor, dolayısıyla onun dört isteğini de atmıyoruz. Masa kendi verisini
 * kendi çekiyor ve şirket değişiminde kendisi yeniliyor
 * (OperationsDesk.vue:510, :526), bu yüzden buradan sürülmesi gerekmiyor. */
async function load() {
	if (tenderEnabled.value) return;
	return loadFinancial();
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
		!activity.value.length
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
	<!-- Tender şirketinde pano = masanın kendisi. Bootstrap `page-header` +
	     `container-xl` kabuğu buraya giremez: `OperationsDesk` zaten tam bir
	     `TenderPage` kabuğu taşıyor (çubuk + başlık + eylemler), üstüne bir
	     kabuk daha sarmak iki başlık, iki Refresh ve `container-xl` yüzünden
	     içeri kaçmış bir modül çubuğu üretiyordu. Ölçüldü 2026-08-02, Mikas. -->
	<OperationsDesk v-if="showDesk" />

	<div v-if="!showDesk" class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">
						{{ importsEnabled ? t("Commerce & imports") : t("Overview") }}
					</div>
					<h2 class="page-title">
						{{ importsEnabled ? t("Imports control center") : t("Dashboard") }}
					</h2>
				</div>
				<div class="col-auto d-flex align-items-end gap-2">
					<button class="btn btn-outline-primary btn-sm" @click="load" :disabled="loading">
						<i class="ti ti-refresh"></i>
						{{ t("Refresh") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="!showDesk" class="page-body">
		<div class="container-xl">
			<div
				v-if="!tenderEnabled && !importsEnabled && error"
				class="alert alert-danger"
				role="alert"
			>
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
				:title="t('No company selected')"
				:subtitle="
					t('Pick a company from the switcher in the header to see your financial overview.')
				"
			/>

			<template v-else>
				<template v-if="importsEnabled">
					<ImportsDashboard />
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
										{{
											t(
												"Your books are empty. Get started by adding a customer, recording your first sale, or logging an opening balance."
											)
										}}
									</p>
									<div class="d-flex flex-wrap gap-2">
										<RouterLink :to="{ name: 'sales-customers' }" class="btn btn-sm btn-primary">
											<i class="ti ti-user-plus me-1"></i>{{ t("Add a customer") }}
										</RouterLink>
										<RouterLink
											:to="{ name: 'sales-invoices' }"
											class="btn btn-sm btn-outline-primary"
										>
											<i class="ti ti-file-invoice me-1"></i>{{ t("Record a sale") }}
										</RouterLink>
										<RouterLink
											:to="{ name: 'money-journals' }"
											class="btn btn-sm btn-outline-secondary"
										>
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
								:label="t('Cash on hand')"
								:lines="lines(summary.cash)"
								icon="ti-coin"
								tone="primary"
								:loading="loading"
							/>
						</div>
						<div class="col-sm-6 col-lg-3">
							<KpiCard
								:label="t('Receivable (AR)')"
								:lines="lines(summary.ar)"
								icon="ti-arrow-down-right"
								tone="success"
								:loading="loading"
							/>
						</div>
						<div class="col-sm-6 col-lg-3">
							<KpiCard
								:label="t('Payable (AP)')"
								:lines="lines(summary.ap)"
								icon="ti-arrow-up-right"
								tone="warning"
								:loading="loading"
							/>
						</div>
						<div class="col-sm-6 col-lg-3">
							<KpiCard
								:label="t('Revenue MTD')"
								:lines="lines(summary.revenue_mtd)"
								icon="ti-trending-up"
								tone="info"
								:trend="summary.revenue_trend_pct"
								:hint="t('vs. last month')"
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
													:class="Number(row.projected_qty) <= 0 ? 'text-red' : 'text-yellow-dark'"
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
