<script setup>
// Report Center: Item ABC analysis (Pareto by value concentration).
// Ranks items, shows A/B/C class + cumulative %, drills into item invoice lines.
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ReportFilters from "../../components/ReportFilters.vue";
import ReportTable from "../../components/ReportTable.vue";

const session = useSession();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);

const range = ref(null);
const metric = ref("revenue");
const loading = ref(false);
const filterDescriptors = [
	{
		key: "customers",
		label: t("Customers"),
		searchApi: "stabler.api.sales.list_customers",
		idKey: "name",
		display: (r) => r.customer_name || r.name,
		placeholder: t("All customers"),
	},
	{
		key: "items",
		label: t("Items"),
		searchApi: "stabler.api.inventory.list_items",
		idKey: "name",
		display: (r) => r.item_name || r.name,
		placeholder: t("All items"),
	},
];
const error = ref("");
const report = ref(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const detailItem = ref("");
const lang = () => user.value?.language || "en";

const exportFilters = computed(() => ({
	company: activeCompany.value,
	from_date: range.value?.from_date,
	to_date: range.value?.to_date,
	metric: metric.value,
	customers: range.value?.customers || [],
	items: range.value?.items || [],
}));
const detailExportFilters = computed(() => ({
	...exportFilters.value,
	item_code: detailItem.value,
}));

async function load(r) {
	if (r) range.value = r;
	if (!activeCompany.value || !range.value) return;
	detailOpen.value = false;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.item_abc", {
			company: activeCompany.value,
			from_date: range.value.from_date,
			to_date: range.value.to_date,
			metric: metric.value,
			customers: range.value.customers || [],
			items: range.value.items || [],
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

async function onDrill({ row }) {
	detailItem.value = row.item_code;
	detailOpen.value = true;
	detailLoading.value = true;
	try {
		detail.value = await call("stabler.api.reports.sales_by_item_detail", {
			company: activeCompany.value,
			from_date: range.value.from_date,
			to_date: range.value.to_date,
			item_code: row.item_code,
		});
	} catch (err) {
		detail.value = null;
		error.value = err?.message || t("Failed to load detail.");
	} finally {
		detailLoading.value = false;
	}
}

function onDetailDrill({ row, col }) {
	if (col.doctype === "Sales Invoice") router.push(`/sales/invoices/${row.name}`);
}
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Reports") }}</div>
		<h2 class="page-title">{{ t("Item ABC analysis") }}</h2>
	</div>

	<ReportFilters :filters="filterDescriptors" :company="activeCompany" @apply="load">
		<div>
			<label class="form-label small mb-1">{{ t("Rank by") }}</label>
			<select v-model="metric" class="form-select form-select-sm" style="max-width: 160px" @change="load()">
				<option value="revenue">{{ t("Sales") }}</option>
				<option value="qty">{{ t("Quantity") }}</option>
			</select>
		</div>
	</ReportFilters>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="report" class="card mb-3">
		<div class="card-body">
			<div class="d-flex gap-2 flex-wrap mb-2">
				<span class="badge bg-green-lt">{{ t("Class") }} A: {{ report.meta?.counts?.A || 0 }}</span>
				<span class="badge bg-yellow-lt">{{ t("Class") }} B: {{ report.meta?.counts?.B || 0 }}</span>
				<span class="badge bg-secondary-lt">{{ t("Class") }} C: {{ report.meta?.counts?.C || 0 }}</span>
				<span class="text-secondary small ms-auto align-self-center">{{ report.meta?.note }}</span>
			</div>
			<ReportTable
				:columns="report.columns"
				:rows="report.rows"
				:totals="report.totals"
				:currency="report.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="loading"
				export-name="item_abc"
				report-key="item_abc"
				:export-filters="exportFilters"
				@drill="onDrill"
			/>
		</div>
	</div>

	<div v-if="detailOpen" class="card">
		<div class="card-header">
			<div class="card-title"><i class="ti ti-receipt me-1"></i>{{ t("Invoices") }} · {{ detail?.meta?.title }}</div>
			<button type="button" class="btn btn-sm btn-ghost-secondary ms-auto" @click="detailOpen = false"><i class="ti ti-x"></i></button>
		</div>
		<div class="card-body">
			<ReportTable
				v-if="detail"
				:columns="detail.columns"
				:rows="detail.rows"
				:totals="detail.totals"
				:currency="detail.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="detailLoading"
				export-name="item_invoices"
				report-key="sales_by_item_detail"
				:export-filters="detailExportFilters"
				@drill="onDetailDrill"
			/>
		</div>
	</div>
</template>
