<script setup>
// Report Center: Sales by Item. Summary (item) → Detail (invoice lines) → Document.
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
const loading = ref(false);
const error = ref("");
const summary = ref(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const detailItem = ref("");
const lang = () => user.value?.language || "en";

const sortBy = ref("revenue");
const sortDir = ref("desc");

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

const exportFilters = computed(() => ({
	company: activeCompany.value,
	from_date: range.value?.from_date,
	to_date: range.value?.to_date,
	customers: range.value?.customers || [],
	items: range.value?.items || [],
	sort_by: sortBy.value,
	sort_dir: sortDir.value,
}));
const detailExportFilters = computed(() => ({
	...exportFilters.value,
	item_code: detailItem.value,
}));

async function loadSummary(r) {
	range.value = r;
	detailOpen.value = false;
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		summary.value = await call("stabler.api.reports.sales_by_item", {
			company: activeCompany.value,
			from_date: r.from_date,
			to_date: r.to_date,
			customers: r.customers || [],
			items: r.items || [],
			sort_by: sortBy.value,
			sort_dir: sortDir.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

function onSort({ sort_by, sort_dir }) {
	sortBy.value = sort_by;
	sortDir.value = sort_dir;
	if (range.value) loadSummary(range.value);
}

async function onSummaryDrill({ row }) {
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
		<h2 class="page-title">{{ t("Sales by Item") }}</h2>
	</div>

	<ReportFilters :filters="filterDescriptors" :company="activeCompany" @apply="loadSummary" />
	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="summary" class="card mb-3">
		<div class="card-body">
			<div v-if="summary.meta" class="text-secondary small mb-2">{{ summary.meta.basis }} · {{ summary.meta.note }}</div>
			<ReportTable
				:columns="summary.columns"
				:rows="summary.rows"
				:totals="summary.totals"
				:currency="summary.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="loading"
				export-name="sales_by_item"
				report-key="sales_by_item"
				:export-filters="exportFilters"
				server-sort
				:sort-by="sortBy"
				:sort-dir="sortDir"
				@sort="onSort"
				@drill="onSummaryDrill"
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
			<div v-else-if="detailLoading" class="text-center py-3"><span class="spinner-border spinner-border-sm"></span></div>
		</div>
	</div>
</template>
