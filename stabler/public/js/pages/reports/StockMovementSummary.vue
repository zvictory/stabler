<script setup>
// Ombor — stok harakat xulosasi. Per-item opening / in / out / closing over a
// posting-date window, optionally scoped to one warehouse. Renders the generic
// {columns, rows, totals, meta} payload from stabler.api.reports.stock_movement_summary.
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { todayIso, daysAgoIso } from "../../composables/date.js";
import ReportTable from "../../components/ReportTable.vue";
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

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", { company: activeCompany.value });
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.stock_movement_summary", exportFilters.value);
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
			<h2 class="page-title">{{ t("Stock movement summary") }}</h2>
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

		<div v-if="report" class="card">
			<div class="card-body">
				<ReportTable
					:columns="report.columns"
					:rows="report.rows"
					:totals="report.totals"
					:currency="report.meta?.currency || 'UZS'"
					:language="lang()"
					:loading="loading"
					export-name="stock_movement_summary"
					report-key="stock_movement_summary"
					:export-filters="exportFilters"
				/>
			</div>
		</div>
	</div>
</template>
