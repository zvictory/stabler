<script setup>
// Report Center: Customer Balance Summary — every customer's CURRENT receivable
// (all-time, all vouchers), period-independent. Same source as the Customer
// Center, so the numbers tie 1:1. QuickBooks-style A/R snapshot.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ReportTable from "../../components/ReportTable.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const onlyWithBalance = ref(1);
const loading = ref(false);
const error = ref("");
const report = ref(null);
const lang = () => user.value?.language || "en";

const exportFilters = computed(() => ({
	company: activeCompany.value,
	only_with_balance: onlyWithBalance.value,
}));

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.customer_balance_summary", {
			company: activeCompany.value,
			only_with_balance: onlyWithBalance.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Reports") }}</div>
		<h2 class="page-title">{{ t("Customer Balance Summary") }}</h2>
	</div>

	<div class="d-flex align-items-center gap-2 flex-wrap mb-3">
		<label class="form-check form-switch m-0">
			<input
				class="form-check-input"
				type="checkbox"
				:checked="onlyWithBalance === 1"
				@change="onlyWithBalance = $event.target.checked ? 1 : 0; load()"
			/>
			<span class="form-check-label">{{ t("Only with balance") }}</span>
		</label>
		<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="loading" @click="load">
			<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
		</button>
	</div>

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
				export-name="customer_balance_summary"
				report-key="customer_balance_summary"
				:export-filters="exportFilters"
			/>
		</div>
	</div>
</template>
