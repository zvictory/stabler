<script setup>
// Reference Report Center report: Sales by Customer.
// Summary (one row per customer) → Detail (that customer's invoices) → Document
// (the Sales Invoice page). Built entirely on the reusable ReportFilters +
// ReportTable engine; adding another report is mostly columns + an endpoint.
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
const detailCustomer = ref("");

const lang = () => user.value?.language || "en";

const exportFilters = computed(() => ({
	company: activeCompany.value,
	from_date: range.value?.from_date,
	to_date: range.value?.to_date,
}));
const detailExportFilters = computed(() => ({
	...exportFilters.value,
	customer: detailCustomer.value,
}));

async function loadSummary(r) {
	range.value = r;
	detailOpen.value = false;
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		summary.value = await call("stabler.api.reports.sales_by_customer", {
			company: activeCompany.value,
			from_date: r.from_date,
			to_date: r.to_date,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

async function onSummaryDrill({ row }) {
	detailCustomer.value = row.customer;
	detailOpen.value = true;
	detailLoading.value = true;
	try {
		// Ledger drill — every voucher behind the Balance, reconciles 1:1.
		detail.value = await call("stabler.api.reports.customer_balance_detail", {
			company: activeCompany.value,
			customer: row.customer,
		});
	} catch (err) {
		detail.value = null;
		error.value = err?.message || t("Failed to load detail.");
	} finally {
		detailLoading.value = false;
	}
}

function onDetailDrill() {}
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Reports") }}</div>
		<h2 class="page-title">{{ t("Sales by Customer") }}</h2>
	</div>

	<ReportFilters @apply="loadSummary" />

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="summary" class="card mb-3">
		<div class="card-body">
			<div v-if="summary.meta" class="text-secondary small mb-2">
				{{ summary.meta.basis }} · {{ summary.meta.note }}
			</div>
			<ReportTable
				:columns="summary.columns"
				:rows="summary.rows"
				:totals="summary.totals"
				:currency="summary.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="loading"
				export-name="sales_by_customer"
				report-key="sales_by_customer"
				:export-filters="exportFilters"
				@drill="onSummaryDrill"
			/>
		</div>
	</div>

	<!-- Detail drill -->
	<div v-if="detailOpen" class="card">
		<div class="card-header">
			<div class="card-title">
				<i class="ti ti-list me-1"></i>{{ t("Ledger") }} · {{ detail?.meta?.title || detailCustomer }}
			</div>
			<button type="button" class="btn btn-sm btn-ghost-secondary ms-auto" @click="detailOpen = false">
				<i class="ti ti-x"></i>
			</button>
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
				export-name="customer_ledger"
				report-key="customer_balance_detail"
				:export-filters="detailExportFilters"
				@drill="onDetailDrill"
			/>
			<div v-else-if="detailLoading" class="text-center py-3"><span class="spinner-border spinner-border-sm"></span></div>
		</div>
	</div>
</template>
