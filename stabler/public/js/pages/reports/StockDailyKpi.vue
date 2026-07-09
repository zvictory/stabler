<script setup>
// Ombor — kunlik kirim-chiqim KPI. Aggregates Stock Ledger movements by
// direction (Kirim / Chiqim / Qaytish) over a posting-date window. The four
// KPI cards are derived CLIENT-SIDE from the report rows (backend returns
// per-direction {cnt, jami} buckets); the same rows also feed the table.
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { todayIso, daysAgoIso } from "../../composables/date.js";
import ReportTable from "../../components/ReportTable.vue";
import KpiCard from "../../components/KpiCard.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const fromDate = ref(daysAgoIso(30));
const toDate = ref(todayIso());
const warehouse = ref("");
const warehouses = ref([]);

const report = ref(null);
const loading = ref(false);
const error = ref("");

const lang = () => user.value?.language || "en";

const whOptions = computed(() => [
	{ value: "", label: t("All warehouses") },
	...warehouses.value.map((w) => ({ value: w.name, label: w.warehouse_name || w.name })),
]);

const exportFilters = computed(() => ({
	company: activeCompany.value,
	from_date: fromDate.value,
	to_date: toDate.value,
	warehouse: warehouse.value,
}));

// qty formatting mirrors ReportTable: grouped with a space thousands separator.
function fmtQty(value) {
	return Number(value || 0)
		.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
		.replace(/,/g, " ");
}

// Sum the `jami` (quantity) column for one direction across the report rows.
function sumFor(direction) {
	const rows = report.value?.rows || [];
	return rows.filter((r) => r.yonalish === direction).reduce((acc, r) => acc + Number(r.jami || 0), 0);
}

const kpiIn = computed(() => sumFor("Kirim"));
const kpiOut = computed(() => sumFor("Chiqim"));
const kpiReturn = computed(() => sumFor("Qaytish"));
const kpiNet = computed(() => kpiIn.value + kpiReturn.value - kpiOut.value);

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", { company: activeCompany.value });
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.stock_daily_kpi", exportFilters.value);
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

onMounted(() => {
	load();
	loadWarehouses();
});
watch(activeCompany, () => {
	load();
	loadWarehouses();
});
</script>

<template>
	<div>
		<div class="page-header mb-3">
			<div class="page-pretitle">{{ t("Ombor") }}</div>
			<h2 class="page-title">{{ t("Daily in/out KPI") }}</h2>
		</div>

		<div class="d-flex align-items-end gap-2 flex-wrap mb-3">
			<div>
				<label class="form-label small mb-1">{{ t("From") }}</label>
				<DateInput v-model="fromDate" size="sm" />
			</div>
			<div>
				<label class="form-label small mb-1">{{ t("To") }}</label>
				<DateInput v-model="toDate" size="sm" />
			</div>
			<div style="min-width: 200px">
				<label class="form-label small mb-1">{{ t("Warehouse") }}</label>
				<Select v-model="warehouse" :options="whOptions" size="sm" />
			</div>
			<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="loading" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
			</button>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<div class="row row-deck row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<KpiCard :label="t('In')" :value="fmtQty(kpiIn)" icon="ti-arrow-down-left" tone="success" :loading="loading" />
			</div>
			<div class="col-sm-6 col-lg-3">
				<KpiCard :label="t('Out')" :value="fmtQty(kpiOut)" icon="ti-arrow-up-right" tone="danger" :loading="loading" />
			</div>
			<div class="col-sm-6 col-lg-3">
				<KpiCard :label="t('Returns')" :value="fmtQty(kpiReturn)" icon="ti-arrow-back-up" tone="warning" :loading="loading" />
			</div>
			<div class="col-sm-6 col-lg-3">
				<KpiCard :label="t('Net')" :value="fmtQty(kpiNet)" icon="ti-scale" tone="primary" :loading="loading" />
			</div>
		</div>

		<div v-if="report" class="card">
			<div class="card-body">
				<ReportTable
					:columns="report.columns"
					:rows="report.rows"
					:totals="report.totals"
					:currency="report.meta?.currency || 'UZS'"
					:language="lang()"
					:loading="loading"
					export-name="stock_daily_kpi"
					report-key="stock_daily_kpi"
					:export-filters="exportFilters"
				/>
			</div>
		</div>
	</div>
</template>
