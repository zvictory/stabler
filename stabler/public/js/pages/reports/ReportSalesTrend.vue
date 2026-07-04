<script setup>
// Report Center: Sales Trend — invoiced totals over time, by day or month.
// Not a DrillReport leaf: the granularity toggle doesn't fit summaryApi's fixed
// (company, from_date, to_date) signature, so this gets its own small page.
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ReportFilters from "../../components/ReportFilters.vue";
import ReportTable from "../../components/ReportTable.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const granularity = ref("month");
const range = ref(null);
const loading = ref(false);
const error = ref("");
const report = ref(null);
const lang = () => user.value?.language || "en";
const filterDescriptors = [
	{
		key: "customers",
		label: t("Customers"),
		searchApi: "stabler.api.sales.list_customers",
		idKey: "name",
		display: (r) => r.customer_name || r.name,
		placeholder: t("All customers"),
	},
];
const sortBy = ref("period");
const sortDir = ref("asc");

const exportFilters = computed(() => ({
	company: activeCompany.value,
	from_date: range.value?.from_date,
	to_date: range.value?.to_date,
	granularity: granularity.value,
	customers: range.value?.customers || [],
	sort_by: sortBy.value,
	sort_dir: sortDir.value,
}));

async function load(r) {
	if (r) range.value = r;
	if (!activeCompany.value || !range.value) return;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.sales_trend", {
			company: activeCompany.value,
			from_date: range.value.from_date,
			to_date: range.value.to_date,
			granularity: granularity.value,
			customers: range.value.customers || [],
			sort_by: sortBy.value,
			sort_dir: sortDir.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

function setGranularity(g) {
	granularity.value = g;
	load();
}

function onSort({ sort_by, sort_dir }) {
	sortBy.value = sort_by;
	sortDir.value = sort_dir;
	load();
}
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Reports") }}</div>
		<h2 class="page-title">{{ t("Sales Trend") }}</h2>
	</div>

	<ReportFilters :filters="filterDescriptors" :company="activeCompany" @apply="load">
		<div class="btn-group btn-group-sm" role="group">
			<button
				type="button"
				class="btn"
				:class="granularity === 'day' ? 'btn-primary' : 'btn-outline-secondary'"
				@click="setGranularity('day')"
			>
				{{ t("Daily") }}
			</button>
			<button
				type="button"
				class="btn"
				:class="granularity === 'month' ? 'btn-primary' : 'btn-outline-secondary'"
				@click="setGranularity('month')"
			>
				{{ t("Monthly") }}
			</button>
		</div>
	</ReportFilters>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="report" class="card">
		<div class="card-body">
			<div v-if="report.meta?.note" class="text-secondary small mb-2">{{ report.meta.note }}</div>
			<ReportTable
				:columns="report.columns"
				:rows="report.rows"
				:totals="report.totals"
				:currency="report.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="loading"
				export-name="sales_trend"
				report-key="sales_trend"
				:export-filters="exportFilters"
				server-sort
				:sort-by="sortBy"
				:sort-dir="sortDir"
				@sort="onSort"
			/>
		</div>
	</div>
</template>
