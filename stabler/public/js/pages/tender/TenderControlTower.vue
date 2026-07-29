<script setup>
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import TenderExecutiveKpis from "./TenderExecutiveKpis.vue";
import TenderExecutionFlow from "./TenderExecutionFlow.vue";
import TenderTrendChart from "./TenderTrendChart.vue";

const props = defineProps({
	data: { type: Object, default: () => ({}) },
	currency: { type: String, default: "" },
	language: { type: String, default: "en" },
	days: { type: Number, default: 90 },
});

const router = useRouter();
const showAllAttention = ref(false);
const acquisition = computed(() => props.data.acquisition || {});
const execution = computed(() => props.data.execution || {});
const attention = computed(() => props.data.attention?.items || []);
const visibleAttention = computed(() =>
	showAllAttention.value ? attention.value : attention.value.slice(0, 3)
);
const remainingAttentionCount = computed(() => Math.max(0, attention.value.length - 3));
const myWork = computed(() => props.data.my_work || {});
const finance = computed(() => props.data.finance || null);
const views = computed(() => props.data.role_scope?.views || []);
const hasView = (view) => views.value.includes(view);
const acquisitionRoute = computed(() => (hasView("sourcing") ? "tender-my-tenders" : ""));
const periodQuery = computed(() => ({
	from_date: props.data.period?.from_date,
	to_date: props.data.period?.to_date,
}));

const roleKpis = computed(() => [
	{
		label: t("Identified"),
		value: acquisition.value.identified || 0,
		route: acquisitionRoute.value,
		query: { stage: "identified" },
	},
	{
		label: t("Submitted"),
		value: acquisition.value.submitted || 0,
		route: acquisitionRoute.value,
		query: { stage: "submitted" },
	},
	{
		label: t("Won"),
		value: acquisition.value.won || 0,
		route: acquisitionRoute.value,
		query: { status: "won" },
	},
	{
		label: t("Purchase orders"),
		value: execution.value.purchase_orders || 0,
		route: hasView("logist") ? "tender-logistics" : "",
		query: { status: "all" },
	},
	{
		label: t("Customs workload"),
		value: execution.value.customs_workload_open || 0,
		route: hasView("declarant") ? "tender-customs" : "",
		query: { status: "in_progress" },
	},
	{
		label: t("Awaiting delivery"),
		value: execution.value.delivery_pending || 0,
		route: hasView("logist") ? "tender-logistics" : "",
		query: { status: "delivery_pending" },
	},
]);

function navigate(name, query = {}) {
	if (!name) return;
	router.push({ name, query: { days: props.days, ...periodQuery.value, ...query } });
}

function openExecutiveKpi(key) {
	const filters = key === "risk" ? { risk: "risk" } : key === "win" ? { status: "won" } : {};
	navigate("tender-portfolio", filters);
}

function openAttention(item) {
	if (!item.deal) return;
	router.push({
		name: "tender-po-control",
		query: { days: props.days, deal: item.deal, tab: item.tab || "overview" },
	});
}

function attentionLabel(item) {
	if (item.kind === "bid_deadline") {
		const days = Math.abs(Number(item.days_left) || 0);
		return `${t("Bid deadline")}: ${days} ${Number(item.days_left) < 0 ? t("days late") : t("days left")}`;
	}
	return item.evidence || item.kind || "";
}

const financeMoney = (value) =>
	formatMoney(value || 0, finance.value?.currency || props.currency, props.language);
</script>

<template>
	<section class="tender-control-tower" :aria-label="t('Tender operations')">
		<TenderExecutiveKpis
			v-if="data.executive_kpi"
			:kpi="data.executive_kpi"
			:currency="data.executive_currency || currency"
			:language="language"
			@select="openExecutiveKpi"
		/>
		<ul v-else class="role-kpis" :aria-label="t('Tender operations')">
			<li v-for="item in roleKpis" :key="item.label" class="card card-sm role-kpi">
				<button
					v-if="item.route"
					type="button"
					class="card-body role-kpi-action"
					@click="navigate(item.route, item.query)"
				>
					<span class="text-secondary small">{{ item.label }}</span>
					<strong class="h2 mb-0 font-monospace">{{ item.value }}</strong>
				</button>
				<div v-else class="card-body">
					<span class="text-secondary small">{{ item.label }}</span>
					<strong class="h2 mb-0 font-monospace">{{ item.value }}</strong>
				</div>
			</li>
		</ul>

		<div class="row row-cards mt-1">
			<div class="col-12 col-lg-8">
				<div class="card h-100">
					<div class="card-header">
						<h3 class="card-title">
							<i class="ti ti-chart-line me-1"></i>{{ t("Tender acquisition") }}
						</h3>
					</div>
					<div class="card-body"><TenderTrendChart :points="data.trend || []" /></div>
				</div>
			</div>
			<div class="col-12 col-lg-4">
				<div class="card h-100">
					<div class="card-header">
						<h3 class="card-title">
							<i class="ti ti-bell-ringing me-1"></i>{{ t("Needs attention") }}
						</h3>
						<span class="badge bg-red-lt text-red ms-auto">{{ data.attention?.count || 0 }}</span>
					</div>
					<div v-if="!attention.length" class="card-body text-secondary">
						<i class="ti ti-circle-check text-green me-1"></i
						>{{ t("No priority checks right now.") }}
					</div>
					<div v-else class="list-group list-group-flush">
						<button
							v-for="item in visibleAttention"
							:key="`${item.deal}-${item.kind}`"
							type="button"
							class="list-group-item list-group-item-action text-start"
							@click="openAttention(item)"
						>
							<div class="fw-semibold">{{ item.label }}</div>
							<div class="small" :class="item.severity === 'risk' ? 'text-red' : 'text-yellow'">
								{{ attentionLabel(item) }}
							</div>
						</button>
						<button
							v-if="attention.length > 3"
							type="button"
							class="list-group-item list-group-item-action text-center text-primary"
							:aria-expanded="showAllAttention"
							@click="showAllAttention = !showAllAttention"
						>
							{{
								showAllAttention ? t("Show less") : `${t("Show more")} (${remainingAttentionCount})`
							}}
						</button>
					</div>
				</div>
			</div>

			<div class="col-12">
				<div class="card">
					<div class="card-header">
						<h3 class="card-title"><i class="ti ti-route me-1"></i>{{ t("Execution flow") }}</h3>
					</div>
					<div class="card-body">
						<TenderExecutionFlow
							:acquisition="acquisition"
							:execution="execution"
							:period="data.period"
						/>
					</div>
				</div>
			</div>

			<div class="col-12" :class="finance ? 'col-lg-8' : ''">
				<div class="card h-100">
					<div class="card-header">
						<h3 class="card-title"><i class="ti ti-user-check me-1"></i>{{ t("My work") }}</h3>
					</div>
					<div class="list-group list-group-flush">
						<button
							v-if="acquisitionRoute"
							type="button"
							class="list-group-item list-group-item-action d-flex justify-content-between"
							@click="navigate(acquisitionRoute, { stage: 'assigned' })"
						>
							<span>{{ t("Assigned tenders") }}</span
							><strong class="font-monospace">{{ myWork.assigned || 0 }}</strong>
						</button>
						<button
							v-if="hasView('declarant')"
							type="button"
							class="list-group-item list-group-item-action d-flex justify-content-between"
							@click="navigate('tender-customs', { status: 'in_progress' })"
						>
							<span>{{ t("Open customs work") }}</span
							><strong class="font-monospace">{{ myWork.customs_workload_open || 0 }}</strong>
						</button>
						<button
							v-if="hasView('logist')"
							type="button"
							class="list-group-item list-group-item-action d-flex justify-content-between"
							@click="navigate('tender-logistics', { status: 'delivery_pending' })"
						>
							<span>{{ t("Pending deliveries") }}</span
							><strong class="font-monospace">{{ myWork.delivery_pending || 0 }}</strong>
						</button>
					</div>
				</div>
			</div>
			<div v-if="finance" class="col-12 col-lg-4">
				<div class="card h-100">
					<div class="card-header">
						<h3 class="card-title"><i class="ti ti-cash me-1"></i>{{ t("Finance") }}</h3>
					</div>
					<div class="card-body finance-summary">
						<button type="button" @click="navigate('tender-portfolio')">
							<span>{{ t("Contract total") }}</span
							><strong>{{ financeMoney(finance.contract_total) }}</strong>
						</button>
						<button type="button" @click="navigate('tender-portfolio')">
							<span>{{ t("Procurement total") }}</span
							><strong>{{ financeMoney(finance.procurement_total) }}</strong>
						</button>
						<button type="button" @click="navigate('tender-portfolio')">
							<span>{{ t("Execution spread") }}</span
							><strong>{{ financeMoney(finance.execution_spread) }}</strong>
						</button>
					</div>
				</div>
			</div>
		</div>
	</section>
</template>

<style scoped>
.role-kpis {
	display: grid;
	grid-template-columns: repeat(6, minmax(0, 1fr));
	gap: 0.5rem;
	margin: 0 0 0.75rem;
	padding: 0;
	list-style: none;
}
.role-kpi {
	min-width: 0;
}
.role-kpi-action {
	width: 100%;
	border: 0;
	background: transparent;
	color: inherit;
	text-align: start;
}
.role-kpi-action:hover {
	background: var(--tblr-bg-surface-secondary);
}
.role-kpi strong,
.role-kpi span {
	display: block;
}
.finance-summary {
	display: grid;
	gap: 0.75rem;
}
.finance-summary button {
	background: transparent;
	border: 0;
	color: inherit;
	display: flex;
	justify-content: space-between;
	gap: 1rem;
	padding: 0;
	text-align: start;
	width: 100%;
}
.finance-summary span {
	color: var(--tblr-secondary);
}
.finance-summary strong {
	font-family: var(--tblr-font-monospace);
	text-align: end;
}
@media (max-width: 991.98px) {
	.role-kpis {
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}
}
@media (max-width: 575.98px) {
	.role-kpis {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
}
</style>
