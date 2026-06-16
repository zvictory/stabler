<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { todayIso, startOfYearIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, language } = storeToRefs(session);
const route = useRoute();

const lang = computed(() => language.value || "en");

// Filters — seeded from query params when opened from the Budgets list
const fiscalYear = ref(String(route.query.fiscal_year || ""));
const costCenter = ref(String(route.query.cost_center || ""));
const fromDate = ref(startOfYearIso());
const toDate = ref(todayIso());

const loading = ref(false);
const error = ref("");
const search = ref("");

// Report data
const rows = ref([]);
const totals = ref({});
const meta = ref({});

const currency = computed(() => meta.value.currency || "UZS");

// Summary chip counts
const favorableCount = computed(() => meta.value.favorable_count || 0);
const unfavorableCount = computed(() => meta.value.unfavorable_count || 0);
const onBudgetCount = computed(() => meta.value.on_budget_count || 0);

// Client-side search on top of loaded results
const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.account, r.cost_center, r.period, r.status]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

function money(val) {
	return formatMoney(val ?? 0, currency.value, lang.value);
}

function varianceCellClass(r) {
	if (r.status === "favorable") return "text-success font-monospace text-end";
	if (r.status === "unfavorable") return "text-danger font-monospace text-end";
	return "font-monospace text-end";
}

function varPct(r) {
	if (r.variance_pct === null || r.variance_pct === undefined) return "—";
	return Number(r.variance_pct).toFixed(1) + "%";
}

async function load() {
	if (!activeCompany.value || !fromDate.value || !toDate.value) return;
	loading.value = true;
	error.value = "";
	rows.value = [];
	totals.value = {};
	meta.value = {};
	try {
		const res = await call("stabler.api.budget.budget_vs_actual", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			fiscal_year: fiscalYear.value || undefined,
			cost_center: costCenter.value || undefined,
		});
		rows.value = res.rows || [];
		totals.value = res.totals || {};
		meta.value = res.meta || {};
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

// Auto-apply — any filter change triggers a reload immediately
watch([activeCompany, fromDate, toDate, fiscalYear, costCenter], load);
onMounted(load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Account or cost centre…') + '  ⌘K'"
			:count="filteredRows.length"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-1">
					<label class="form-label mb-0 text-secondary small">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div class="d-flex align-items-center gap-1">
					<label class="form-label mb-0 text-secondary small">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<input
					v-model="fiscalYear"
					type="text"
					class="form-control form-control-sm"
					style="max-width: 140px"
					:placeholder="t('Fiscal year')"
				/>
				<input
					v-model="costCenter"
					type="text"
					class="form-control form-control-sm"
					style="max-width: 180px"
					:placeholder="t('Cost centre')"
				/>
			</template>

			<!-- Summary chips in the toolbar right slot -->
			<template #summary>
				<div v-if="rows.length" class="d-flex gap-2 align-items-center flex-wrap small">
					<span class="badge bg-green-lt">
						{{ favorableCount }}&nbsp;{{ t("favorable") }}
					</span>
					<span class="badge bg-red-lt">
						{{ unfavorableCount }}&nbsp;{{ t("unfavorable") }}
					</span>
					<span class="badge bg-secondary-lt">
						{{ onBudgetCount }}&nbsp;{{ t("on budget") }}
					</span>
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Account") }}</th>
						<th>{{ t("Cost Centre") }}</th>
						<th class="text-end">{{ t("Budget") }}</th>
						<th class="text-end">{{ t("Actual") }}</th>
						<th class="text-end">{{ t("Variance") }}</th>
						<th class="text-end">{{ t("Var %") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="7" :cols="7" />
				<tbody v-else>
					<tr v-for="(r, i) in filteredRows" :key="i">
						<td>
							<div class="fw-medium">{{ r.account || "—" }}</div>
							<div v-if="r.period" class="text-secondary small">{{ r.period }}</div>
						</td>
						<td class="text-secondary">{{ r.cost_center || "—" }}</td>
						<td class="text-end font-monospace">{{ money(r.budget) }}</td>
						<td class="text-end font-monospace">{{ money(r.actual) }}</td>
						<td :class="varianceCellClass(r)">{{ money(r.variance) }}</td>
						<td class="text-end font-monospace">{{ varPct(r) }}</td>
						<td>
							<span
								class="badge"
								:class="getStatusBadgeClass('Budget Variance', r.status)"
							>
								{{ t(r.status || "—") }}
							</span>
						</td>
					</tr>
				</tbody>
				<!-- Totals footer row -->
				<tfoot v-if="!loading && rows.length && Object.keys(totals).length">
					<tr class="fw-bold">
						<td colspan="2">{{ t("Total") }}</td>
						<td class="text-end font-monospace">{{ money(totals.budget) }}</td>
						<td class="text-end font-monospace">{{ money(totals.actual) }}</td>
						<td class="text-end font-monospace">{{ money(totals.variance) }}</td>
						<td></td>
						<td></td>
					</tr>
				</tfoot>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0 && !error"
			icon="ti-chart-bar"
			:title="t('No budget data for this period')"
			:subtitle="t('Submit a Budget document covering this date range and cost centre.')"
		/>

		<div v-if="!loading && meta.note" class="px-3 pb-3">
			<p class="text-secondary small mb-0">{{ meta.note }}</p>
		</div>
	</div>
</template>
