<script setup>
// Ombor — stok defteri detali. Raw Stock Ledger Entry rows over a posting-date
// window, filterable by warehouse and voucher type. Always LIMIT-capped by the
// backend. The voucher_no column drills IN-SPA: Sales Invoice -> /sales/invoices,
// Purchase Invoice -> /purchasing/invoices. Any other voucher type has no in-SPA
// detail route, so it stays plain text — NEVER a Frappe Desk (/app/) link.
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { todayIso, daysAgoIso } from "../../composables/date.js";
import ReportTable from "../../components/ReportTable.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const fromDate = ref(daysAgoIso(30));
const toDate = ref(todayIso());
const warehouse = ref("");
const warehouses = ref([]);
const voucherType = ref("");

const report = ref(null);
const loading = ref(false);
const error = ref("");

const lang = () => user.value?.language || "en";

const whOptions = computed(() => [
	{ value: "", label: t("All warehouses") },
	...warehouses.value.map((w) => ({ value: w.name, label: w.warehouse_name || w.name })),
]);

// Values are literal ERPNext voucher_type strings (backend WHERE match); only labels are translated.
const vtOptions = computed(() => [
	{ value: "", label: t("All types") },
	{ value: "Stock Entry", label: t("Stock Entry") },
	{ value: "Sales Invoice", label: t("Sales Invoice") },
	{ value: "Purchase Invoice", label: t("Purchase Invoice") },
	{ value: "Stock Reconciliation", label: t("Stock Reconciliation") },
	{ value: "Delivery Note", label: t("Delivery Note") },
	{ value: "Purchase Receipt", label: t("Purchase Receipt") },
]);

const exportFilters = computed(() => ({
	company: activeCompany.value,
	from_date: fromDate.value,
	to_date: toDate.value,
	warehouse: warehouse.value,
	voucher_type: voucherType.value,
}));

// voucher_type -> in-SPA route. Only Sales/Purchase Invoice have SPA detail
// forms; everything else has no route, so we leave it as plain text.
function onDrill({ row }) {
	if (!row?.voucher_no) return;
	if (row.voucher_type === "Sales Invoice") {
		router.push(`/sales/invoices/${row.voucher_no}`);
	} else if (row.voucher_type === "Purchase Invoice") {
		router.push(`/purchasing/invoices/${row.voucher_no}`);
	}
	// no in-SPA form for other voucher types -> intentionally no-op (plain text)
}

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", { company: activeCompany.value });
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.stock_ledger_detail", exportFilters.value);
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
			<h2 class="page-title">{{ t("Stock ledger detail") }}</h2>
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
			<div style="min-width: 180px">
				<label class="form-label small mb-1">{{ t("Document type") }}</label>
				<Select v-model="voucherType" :options="vtOptions" size="sm" />
			</div>
			<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="loading" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
			</button>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<div
			v-if="report && report.meta && report.rows && report.rows.length >= report.meta.limit"
			class="alert alert-info py-2 small"
		>
			{{ t("Showing first {n} rows. Narrow the filters to see more.").replace("{n}", report.meta.limit) }}
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
					export-name="stock_ledger_detail"
					report-key="stock_ledger_detail"
					:export-filters="exportFilters"
					@drill="onDrill"
				/>
			</div>
		</div>
	</div>
</template>
